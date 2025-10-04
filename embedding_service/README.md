# GuardianAI DeepFace Embedding Service

This FastAPI service wraps the [DeepFace](https://github.com/serengil/deepface) library to provide embeddings for the Flutter client. By default it loads the `Facenet512` model with the OpenCV detector, but both can be customized via environment variables.

## Setup

```powershell
cd embedding_service
python -m venv .venv
.\.venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Run the service

```powershell
uvicorn main:app --host 0.0.0.0 --port 8000
```

Environment overrides:

- `DEEPFACE_MODEL` (default `Facenet512`)
- `DEEPFACE_DETECTOR` (default `opencv`)
- `CORS_ALLOW_ORIGINS` (comma-separated list, default `*`)

The service exposes:

- `GET /health` – basic readiness probe
- `POST /generate_embedding` – generates the primary face embedding
- `POST /generate_embeddings` – plural alias for compatibility

### Request body

```json
{
  "image_base64": "<base64-encoded image bytes>"
}
```

### Response body

```json
{
  "embedding": [0.1, 0.2, ...],
  "faces_detected": 1
}
```

Set the Flutter app's `EMBEDDING_SERVICE_URL` to the deployed endpoint (default `http://localhost:8000/generate_embedding`).
