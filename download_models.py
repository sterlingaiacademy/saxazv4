import os
import time

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': '*/*',
}

def download_file(url, filepath, max_retries=5):
    """Download a file with retries and exponential backoff."""
    # Use requests if available (already in requirements.txt via google-cloud-storage)
    try:
        import requests
        for attempt in range(1, max_retries + 1):
            try:
                print(f"  Attempt {attempt}/{max_retries}...")
                with requests.get(url, headers=HEADERS, stream=True, timeout=120) as r:
                    r.raise_for_status()
                    with open(filepath, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=32768):
                            if chunk:
                                f.write(chunk)
                return  # success
            except Exception as e:
                print(f"  Attempt {attempt} failed: {e}")
                if os.path.exists(filepath):
                    os.remove(filepath)
                if attempt < max_retries:
                    wait = 2 ** attempt  # 2, 4, 8, 16 seconds
                    print(f"  Retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    raise RuntimeError(f"Failed to download {url} after {max_retries} attempts") from e
    except ImportError:
        # Fallback to urllib
        import urllib.request
        for attempt in range(1, max_retries + 1):
            try:
                print(f"  Attempt {attempt}/{max_retries} (urllib)...")
                req = urllib.request.Request(url, headers=HEADERS)
                with urllib.request.urlopen(req, timeout=120) as response, open(filepath, 'wb') as out_file:
                    while True:
                        chunk = response.read(32768)
                        if not chunk:
                            break
                        out_file.write(chunk)
                return  # success
            except Exception as e:
                print(f"  Attempt {attempt} failed: {e}")
                if os.path.exists(filepath):
                    os.remove(filepath)
                if attempt < max_retries:
                    wait = 2 ** attempt
                    print(f"  Retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    raise RuntimeError(f"Failed to download {url} after {max_retries} attempts") from e

def download_models():
    os.makedirs('models', exist_ok=True)
    onnx_path = 'models/kokoro-v0_19.onnx'
    voices_path = 'models/voices.bin'

    if not os.path.exists(onnx_path):
        print("Downloading Kokoro ONNX model (~300MB, may take a while)...")
        download_file('https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/kokoro-v0_19.onnx', onnx_path)
        print("Successfully downloaded ONNX model.")
    else:
        print("Kokoro ONNX model already exists, skipping.")

    if not os.path.exists(voices_path):
        print("Downloading Kokoro voices mapping...")
        download_file('https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/voices.bin', voices_path)
        print("Successfully downloaded voices mapping.")
    else:
        print("Kokoro voices mapping already exists, skipping.")

if __name__ == '__main__':
    download_models()
