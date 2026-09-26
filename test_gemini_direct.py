import os
import sys
import traceback
from google import genai

key = os.environ.get("GEMINI_API_KEY", "").strip()

print("=" * 60)
print("GEMINI API DIRECT DIAGNOSTIC - GEMINI 3")
print("=" * 60)

if not key:
    print("[ERROR] GEMINI_API_KEY is NOT set in this environment!")
    sys.exit(1)

client = genai.Client(api_key=key)

models_to_test = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
]

for model_name in models_to_test:
    print(f"\n--- Testing model: {model_name} ---")
    try:
        response = client.models.generate_content(
            model=model_name,
            contents="Reply with the single word: OK",
        )
        print(f"[SUCCESS] Response received from {model_name}:")
        print(f"Output text: {response.text.strip()}")
        break
    except Exception as e:
        print(f"[FAILED] {type(e).__name__}: {str(e)}")

print("\n" + "=" * 60)
