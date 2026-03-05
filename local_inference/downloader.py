import os, argparse
from huggingface_hub import snapshot_download

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--revision", default=None)
    args = ap.parse_args()

    token = os.environ.get("HF_TOKEN") or None
    cache_dir = os.environ.get("HF_HOME", "/data/hf")

    snapshot_download(repo_id=args.model, revision=args.revision, token=token, cache_dir=cache_dir)
    print("download_ok")

if __name__ == "__main__":
    main()
