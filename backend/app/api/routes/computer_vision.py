from pathlib import Path
import hashlib
import json
import os
import random
import re
import time
import traceback

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from google import genai
from google.genai import types, errors

router = APIRouter()

# --------------------------------------------------
# Configuration
# --------------------------------------------------

DATASET_ROOT = Path(__file__).resolve().parents[3] / "datasets"
RESULTS_ROOT = Path(__file__).resolve().parents[3] / "analysis_results"
CACHE_ROOT = RESULTS_ROOT / "cache"

SCENARIOS = {"cyclone", "earthquake", "flood"}

MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

PRIORITY_LABELS = {
    1: "low",
    2: "moderate",
    3: "high",
    4: "critical",
    5: "life_threatening",
}

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
PROMPT_VERSION = "visual-evidence-v2"

MAX_ATTEMPTS = 3
RETRYABLE_STATUS_CODES = {500, 502, 503, 504}


# --------------------------------------------------
# Validation helpers
# --------------------------------------------------

def validate_scenario(scenario: str) -> None:
    if scenario not in SCENARIOS:
        raise HTTPException(
            status_code=404,
            detail="Unknown scenario. Use cyclone, earthquake, or flood.",
        )


def validate_filename(filename: str) -> None:
    pattern = r"D[1-9]\d*_T[1-9]\d*\.(png|jpg|jpeg|webp)"

    if not re.fullmatch(pattern, filename, re.IGNORECASE):
        raise HTTPException(
            status_code=400,
            detail="Invalid image filename. Example: D1_T1.png",
        )


def get_image_path(scenario: str, filename: str) -> Path:
    validate_scenario(scenario)
    validate_filename(filename)

    image_path = DATASET_ROOT / scenario / filename

    if not image_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Image not found. Check the dataset folder and filename.",
        )

    return image_path


def discover_images(scenario: str) -> list[Path]:
    validate_scenario(scenario)

    folder = DATASET_ROOT / scenario

    if not folder.is_dir():
        raise HTTPException(
            status_code=404,
            detail="Dataset folder not found.",
        )

    return sorted(
        path
        for path in folder.iterdir()
        if path.is_file()
        and path.suffix.lower() in MIME_TYPES
        and re.fullmatch(
            r"D[1-9]\d*_T[1-9]\d*",
            path.stem,
            re.IGNORECASE,
        )
    )


# --------------------------------------------------
# Persistent cache helpers
# --------------------------------------------------

def get_cache_path(scenario: str, filename: str) -> Path:
    return CACHE_ROOT / scenario / f"{filename}.json"


def load_cached_result(
    scenario: str,
    filename: str,
    image_hash: str,
) -> dict | None:
    cache_file = get_cache_path(scenario, filename)

    if not cache_file.is_file():
        return None

    try:
        cached_data = json.loads(
            cache_file.read_text(encoding="utf-8")
        )

        if cached_data.get("image_hash") != image_hash:
            return None

        if cached_data.get("model") != GEMINI_MODEL:
            return None

        if cached_data.get("prompt_version") != PROMPT_VERSION:
            return None

        result = cached_data.get("result")

        if not isinstance(result, dict):
            return None

        print(
            f"[Computer Vision] Cache hit: "
            f"{scenario}/{filename}"
        )

        return result

    except (OSError, json.JSONDecodeError):
        print(
            f"[Computer Vision] Invalid cache entry: "
            f"{scenario}/{filename}"
        )
        return None


def save_cached_result(
    scenario: str,
    filename: str,
    image_hash: str,
    result: dict,
) -> None:
    cache_file = get_cache_path(scenario, filename)
    cache_file.parent.mkdir(parents=True, exist_ok=True)

    cached_data = {
        "image_hash": image_hash,
        "model": GEMINI_MODEL,
        "prompt_version": PROMPT_VERSION,
        "result": result,
    }

    temporary_file = cache_file.with_suffix(".tmp")

    try:
        temporary_file.write_text(
            json.dumps(cached_data, indent=2),
            encoding="utf-8",
        )

        temporary_file.replace(cache_file)

    except OSError:
        temporary_file.unlink(missing_ok=True)

        print(
            f"[Computer Vision] Could not save cache for "
            f"{scenario}/{filename}"
        )
        traceback.print_exc()


# --------------------------------------------------
# Gemini analysis helper
# --------------------------------------------------

def analyze_image(
    scenario: str,
    filename: str,
    force: bool = False,
) -> dict:
    image_path = get_image_path(scenario, filename)

    try:
        image_bytes = image_path.read_bytes()
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not read the selected image.",
        ) from exc

    image_hash = hashlib.sha256(image_bytes).hexdigest()

    if not force:
        cached_result = load_cached_result(
            scenario,
            filename,
            image_hash,
        )

        if cached_result is not None:
            return cached_result

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "Gemini API key is not configured. "
                "Set GEMINI_API_KEY in your backend environment."
            ),
        )

    prompt = """
You are a careful computer-vision analyst supporting RESQNET,
a simulated drone-based disaster-response system.

Analyze the supplied image directly. Accuracy is more important
than producing a detailed description.

STRICT VISUAL EVIDENCE RULES:
1. Describe only objects, structures, and hazards visibly supported
   by the supplied image.
2. Never invent trains, railway tracks, bridges, vehicles, people,
   firefighters, snow, ice, or other objects that are not clearly visible.
3. Do not infer an object's identity from ambiguous shapes.
4. Do not assume that a person-shaped figure is a real person.
5. Do not invent injuries, deaths, trapped survivors, or casualties.
6. If an object or hazard is unclear, explicitly state the uncertainty.
7. Treat the scenario name as metadata, not proof of what the image
   contains.
8. If the image content appears inconsistent with the assigned scenario,
   describe the visible evidence and mention the possible mismatch.
9. Do not force the image description to fit the scenario label.
10. Keep descriptions concise and factual.

PRIORITY LEVELS:
1 = low
2 = moderate
3 = high
4 = critical
5 = life_threatening

Assign priority based on visible hazard severity.
Use level 5 only when visible evidence strongly supports an immediate,
potentially life-threatening emergency.
Do not infer actual casualties from an image alone.

CONFIDENCE:
Return a number between 0 and 1 representing your confidence in
the visual assessment. Do not treat confidence as a probability
that the assessment is correct.

Return exactly one JSON object:
{
  "visible_hazards": ["hazard supported by visible evidence"],
  "priority_level": 1,
  "explanation": "Concise explanation grounded in the image",
  "confidence": 0.0,
  "limitations": "Uncertainties and details that cannot be established"
}

Requirements:
- priority_level must be an integer from 1 to 5.
- confidence must be a number between 0 and 1.
- visible_hazards must be a list of strings.
- explanation and limitations must be strings.
- Return valid JSON only, without Markdown fences.
"""

    try:
        client = genai.Client(api_key=api_key)

        contents = [
            prompt,
            types.Part.from_bytes(
                data=image_bytes,
                mime_type=MIME_TYPES[image_path.suffix.lower()],
            ),
        ]

        response = None

        for attempt in range(MAX_ATTEMPTS):
            try:
                response = client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.2,
                    ),
                )
                break

            except errors.ServerError as exc:
                status_code = getattr(exc, "code", None)

                if (
                    status_code not in RETRYABLE_STATUS_CODES
                    or attempt == MAX_ATTEMPTS - 1
                ):
                    raise

                wait_seconds = 2 ** (attempt + 1)

                print(
                    f"[Computer Vision] Gemini returned {status_code}. "
                    f"Retrying in {wait_seconds} seconds "
                    f"(attempt {attempt + 2}/{MAX_ATTEMPTS})."
                )

                time.sleep(wait_seconds)

        if response is None:
            raise RuntimeError("Gemini did not return a response.")

        if not response.text:
            raise ValueError("Gemini returned an empty response.")

        result = json.loads(response.text)

        if not isinstance(result, dict):
            raise ValueError("Gemini did not return a JSON object.")

        priority = result.get("priority_level")

        if (
            isinstance(priority, bool)
            or not isinstance(priority, int)
            or priority not in PRIORITY_LABELS
        ):
            raise ValueError("Invalid priority_level returned by Gemini.")

        confidence = result.get("confidence")

        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 1
        ):
            raise ValueError("Invalid confidence returned by Gemini.")

        hazards = result.get("visible_hazards")

        if (
            not isinstance(hazards, list)
            or not all(isinstance(item, str) for item in hazards)
        ):
            raise ValueError("Invalid visible_hazards returned by Gemini.")

        explanation = result.get("explanation")

        if (
            not isinstance(explanation, str)
            or not explanation.strip()
        ):
            raise ValueError("Invalid explanation returned by Gemini.")

        limitations = result.get("limitations")

        if not isinstance(limitations, str):
            raise ValueError("Invalid limitations returned by Gemini.")

    except HTTPException:
        raise

    except Exception as exc:
        print("\n========== GEMINI ANALYSIS ERROR ==========")
        print(f"Error type: {type(exc).__name__}")
        print(f"Error message: {str(exc)[:2000]}")
        print(f"Configured model: {GEMINI_MODEL}")
        traceback.print_exc()
        print("============================================\n")

        if isinstance(exc, errors.ServerError):
            status_code = getattr(exc, "code", 502)

            if status_code in RETRYABLE_STATUS_CODES:
                raise HTTPException(
                    status_code=status_code,
                    detail=(
                        "Gemini is temporarily unavailable after retries. "
                        "Please try again later."
                    ),
                ) from None

        raise HTTPException(
            status_code=502,
            detail=(
                f"Gemini image analysis failed: {type(exc).__name__}. "
                "Check the backend terminal for details."
            ),
        ) from None

    simulated_risk_score = round(
        0.15
        + 0.175 * (priority - 1)
        + random.uniform(-0.08, 0.08),
        4,
    )

    drone_id, timeframe = image_path.stem.split("_", maxsplit=1)

    result_data = {
        "scenario": scenario,
        "filename": filename,
        "drone_id": drone_id,
        "timeframe": timeframe,
        "visible_hazards": hazards,
        "priority_level": priority,
        "priority_label": PRIORITY_LABELS[priority],
        "simulated_risk_score": simulated_risk_score,
        "explanation": explanation,
        "confidence": round(float(confidence), 2),
        "limitations": limitations,
        "analysis_source": "gemini",
    }

    save_cached_result(
        scenario,
        filename,
        image_hash,
        result_data,
    )

    return result_data


# --------------------------------------------------
# 1. List images for a scenario and timeframe
#
# GET /api/computer-vision/images/cyclone/T1
# --------------------------------------------------

@router.get("/images/{scenario}/{timeframe}")
def list_images(scenario: str, timeframe: str):
    validate_scenario(scenario)

    if not re.fullmatch(r"T[1-9]\d*", timeframe, re.IGNORECASE):
        raise HTTPException(
            status_code=400,
            detail="Invalid timeframe. Example: T1",
        )

    images = [
        path.name
        for path in discover_images(scenario)
        if re.fullmatch(
            rf"D[1-9]\d*_{re.escape(timeframe)}",
            path.stem,
            re.IGNORECASE,
        )
    ]

    return {
        "scenario": scenario,
        "timeframe": timeframe,
        "count": len(images),
        "images": [
            {
                "filename": filename,
                "url": (
                    f"/api/computer-vision/image/"
                    f"{scenario}/{filename}"
                ),
            }
            for filename in images
        ],
    }


# --------------------------------------------------
# 2. Serve an individual image
#
# GET /api/computer-vision/image/cyclone/D1_T1.png
# --------------------------------------------------

@router.get("/image/{scenario}/{filename}")
def get_image(scenario: str, filename: str):
    image_path = get_image_path(scenario, filename)

    return FileResponse(
        path=image_path,
        media_type=MIME_TYPES[image_path.suffix.lower()],
    )


# --------------------------------------------------
# 3. Analyze an individual image
#
# POST /api/computer-vision/analyze/cyclone/D1_T1.png
# Optional: ?force=true
# --------------------------------------------------

@router.post("/analyze/{scenario}/{filename}")
def analyze_single_image(
    scenario: str,
    filename: str,
    force: bool = Query(default=False),
):
    return analyze_image(
        scenario,
        filename,
        force=force,
    )


# --------------------------------------------------
# 4. Retrieve saved analyses for a timeframe
#
# GET /api/computer-vision/results/cyclone/T1
# --------------------------------------------------

@router.get("/results/{scenario}/{timeframe}")
def get_saved_results(scenario: str, timeframe: str):
    validate_scenario(scenario)

    if not re.fullmatch(r"T[1-9]\d*", timeframe, re.IGNORECASE):
        raise HTTPException(
            status_code=400,
            detail="Invalid timeframe. Example: T1",
        )

    results_file = RESULTS_ROOT / f"{scenario}_batch_results.json"

    if not results_file.is_file():
        raise HTTPException(
            status_code=404,
            detail=(
                f"No saved batch results found for {scenario}. "
                "Run batch analysis first."
            ),
        )

    try:
        batch_data = json.loads(
            results_file.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not read the saved analysis results.",
        ) from exc

    saved_results = batch_data.get("successful_results", [])

    if not isinstance(saved_results, list):
        raise HTTPException(
            status_code=500,
            detail="Saved analysis results have an invalid format.",
        )

    timeframe_results = []

    for result in saved_results:
        if not isinstance(result, dict):
            continue

        if result.get("timeframe", "").upper() != timeframe.upper():
            continue

        filename = result.get("filename")

        if not isinstance(filename, str):
            continue

        try:
            validate_filename(filename)
        except HTTPException:
            continue

        timeframe_results.append({
            **result,
            "image_url": (
                f"/api/computer-vision/image/"
                f"{scenario}/{filename}"
            ),
        })

    return {
        "scenario": scenario,
        "timeframe": timeframe.upper(),
        "count": len(timeframe_results),
        "results": timeframe_results,
    }

# --------------------------------------------------
# 4. Batch image analysis
#
# POST /api/computer-vision/analyze-batch/cyclone
# Optional: ?max_images=5&force=true
# --------------------------------------------------

@router.post("/analyze-batch/{scenario}")
def analyze_batch(
    scenario: str,
    max_images: int = Query(default=5, ge=1, le=50),
    force: bool = Query(default=False),
):
    image_paths = discover_images(scenario)

    if not image_paths:
        raise HTTPException(
            status_code=404,
            detail=f"No valid images found for scenario: {scenario}",
        )

    selected_images = image_paths[:max_images]

    successful_results = []
    failed_results = []

    for image_path in selected_images:
        try:
            result = analyze_image(
                scenario,
                image_path.name,
                force=force,
            )

            successful_results.append(result)

        except HTTPException as exc:
            failed_results.append({
                "filename": image_path.name,
                "status_code": exc.status_code,
                "error": exc.detail,
            })

        except Exception as exc:
            failed_results.append({
                "filename": image_path.name,
                "error": type(exc).__name__,
            })

    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)

    output_file = RESULTS_ROOT / f"{scenario}_batch_results.json"
    temporary_file = output_file.with_suffix(".tmp")

    batch_output = {
        "scenario": scenario,
        "images_discovered": len(image_paths),
        "images_selected": len(selected_images),
        "successful_count": len(successful_results),
        "failed_count": len(failed_results),
        "successful_results": successful_results,
        "failed_results": failed_results,
    }

    try:
        temporary_file.write_text(
            json.dumps(batch_output, indent=2),
            encoding="utf-8",
        )

        temporary_file.replace(output_file)

    except OSError as exc:
        temporary_file.unlink(missing_ok=True)

        raise HTTPException(
            status_code=500,
            detail="Could not save the batch results.",
        ) from exc

    return {
        "message": "Batch analysis completed.",
        **batch_output,
        "results_file": str(output_file),
    }