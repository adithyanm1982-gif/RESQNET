import hashlib
import json
import os
from pathlib import Path

SCENARIO = "cyclone"
FILENAME = "D1_T1.png"

cache_file = Path("analysis_results/cache") / SCENARIO / f"{FILENAME}.json"
image_file = Path("datasets") / SCENARIO / FILENAME

print("Cache file exists:", cache_file.exists())
print("Image file exists:", image_file.exists())

if cache_file.exists() and image_file.exists():
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    current_hash = hashlib.sha256(image_file.read_bytes()).hexdigest()

    print("Hash matches current image:", data.get("image_hash") == current_hash)
    print("Cached model:", data.get("model"))
    print("Configured model:", os.getenv("GEMINI_MODEL", "gemini-3.8-flash"))
    print("Cached prompt version:", data.get("prompt_version"))
    print("Result is a dict:", isinstance(data.get("result"), dict))