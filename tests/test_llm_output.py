import requests

from src.utils.dual_explainer import STATIC_REASONING_INSTRUCTIONS


def test_model():

    prompt = f"{STATIC_REASONING_INSTRUCTIONS}\n\nCONTEXT:\nEvent: overload\nDuration: 15 sec\nPersistence: 3 cycles"

    print("--- Sending Request to Ollama ---")
    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": "qwen2.5:3b", "prompt": prompt, "stream": False, "format": "json"},
            timeout=60,
        )
        print(f"Status: {response.status_code}")
        response_data = response.json()
        print(f"Response: {response_data.get('response')}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    test_model()
