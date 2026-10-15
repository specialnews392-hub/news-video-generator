import sys
from pathlib import Path
import config
from google import genai
from google.genai import types

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

key = config.get_random_gemini_key()
http_opts = types.HttpOptions(base_url=config.GEMINI_BASE_URL) if config.GEMINI_BASE_URL else None
client = genai.Client(api_key=key, http_options=http_opts)

test_text = "Guten Tag! Willkommen zu unserem Kanal. Heute analysieren wir die Lage an den deutschen Grenzen."

# Let's inspect model info or test generation
for model_name in ["gemini-3.8-flash-tts", "gemini-2.5-flash-preview-tts"]:
    print(f"\n--- Testing model: {model_name} ---")
    try:
        # Check standard speech config or prompt
        response = client.models.generate_content(
            model=model_name,
            contents=test_text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
            )
        )
        print("Success! Response candidates:", len(response.candidates))
        for cand in response.candidates:
            for part in cand.content.parts:
                if hasattr(part, "inline_data") and part.inline_data:
                    mime = getattr(part.inline_data, "mime_type", "unknown")
                    data_len = len(part.inline_data.data) if part.inline_data.data else 0
                    print(f"Audio received! MIME: {mime}, Bytes: {data_len}")
                    # Save test audio
                    out_file = Path(f"test_gemini_{model_name.replace('/', '_')}.wav")
                    import base64
                    raw_bytes = part.inline_data.data if isinstance(part.inline_data.data, bytes) else base64.b64decode(part.inline_data.data)
                    with open(out_file, "wb") as f:
                        f.write(raw_bytes)
                    print(f"Saved audio to {out_file} (size: {len(raw_bytes)} bytes)")
                    break
        break
    except Exception as e:
        print(f"Error on {model_name}: {e}")
