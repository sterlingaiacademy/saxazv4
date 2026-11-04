FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    libsndfile1 \
    espeak-ng \
    wget \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt gunicorn uvicorn

# Download the Kokoro ONNX model and voices into the Docker image (cached layer before code copy)
RUN mkdir -p models && \
    wget --tries=10 --retry-connrefused --timeout=60 --waitretry=5 \
         --header="User-Agent: Mozilla/5.0 (X11; Linux x86_64)" \
         -O models/kokoro-v0_19.onnx \
         "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/kokoro-v0_19.onnx" && \
    wget --tries=10 --retry-connrefused --timeout=60 --waitretry=5 \
         --header="User-Agent: Mozilla/5.0 (X11; Linux x86_64)" \
         -O models/voices.bin \
         "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/voices.bin"

COPY . .

ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
