import os
import time
from huggingface_hub import InferenceClient

# Configuration from environment
RUN_DURATION_MINUTES = float(os.environ.get("RUN_DURATION_MINUTES", "30"))
MODEL = os.environ.get("MODEL", "meta-llama/Llama-3.1-8B-Instruct")
HF_TOKEN = os.environ.get("HF_TOKEN", "")

PROMPTS = [
    "What is machine learning?",
    "Explain neural networks.",
    "What are the applications of AI?",
    "Describe deep learning architectures.",
    "What is natural language processing?",
]

def main():
    print("=" * 60)
    print(f"Model: {MODEL}")
    print(f"Duration: {RUN_DURATION_MINUTES} minutes")
    print("=" * 60)

    # Initialize client
    if HF_TOKEN:
        client = InferenceClient(token=HF_TOKEN)
        print(f"✓ Using HF token (length: {len(HF_TOKEN)})")
    else:
        client = InferenceClient()
        print("⚠ No HF_TOKEN set")

    end = time.time() + RUN_DURATION_MINUTES * 60
    n = 0
    errors = 0

    print(f"Starting workload...")

    while time.time() < end:
        for prompt in PROMPTS:
            if time.time() >= end:
                break

            try:
                completion = client.chat.completions.create(
                    model=MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=50,
                    temperature=0.7
                )

                response_text = completion.choices[0].message.content
                print(f"✓ Request {n+1}: {response_text[:60]}...")
                n += 1

                if n % 10 == 0:
                    print(f"Progress: {n} requests completed")

                time.sleep(2)

            except Exception as e:
                print(f"❌ Request error: {e}")
                errors += 1
                time.sleep(5)

    print("=" * 60)
    print(f"Complete! Successful: {n}, Failed: {errors}")
    print("=" * 60)

if __name__ == "__main__":
    main()
