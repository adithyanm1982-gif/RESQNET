import os


def main() -> None:
    from google import genai

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is not set in this window.")

    client = genai.Client(api_key=api_key)
    candidates = [
        "gemini-3.7-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-flash-latest",
        "gemini-flash-lite-latest",
    ]

    for model in candidates:
        try:
            client.models.generate_content(
                model=model,
                contents="Reply with the word OK.",
            )
            print(f"{model}: WORKS")
        except Exception as exc:
            text = str(exc)
            print(f"{model}: FAILED ({type(exc).__name__}) {text[:110]}")


if __name__ == "__main__":
    main()
