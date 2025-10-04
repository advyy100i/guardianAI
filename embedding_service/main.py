import base64
import binascii
import logging
import os
from typing import List

import cv2
import numpy as np

logger = logging.getLogger("embedding_service")
logging.basicConfig(level=logging.INFO)

try:
    from deepface import DeepFace  # type: ignore[import]
except Exception as error:  # pragma: no cover - import-time failure should surface clearly
    logger.critical("Failed to import DeepFace: %s", error)
    raise RuntimeError(
        "DeepFace must be installed correctly. Run `pip install -r requirements.txt`."
    ) from error
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

MODEL_NAME = os.getenv("DEEPFACE_MODEL", "Facenet512")
DETECTOR_BACKEND = os.getenv("DEEPFACE_DETECTOR", "opencv")

try:
    logger.info(
        "Loading DeepFace model '%s' with detector '%s'", MODEL_NAME, DETECTOR_BACKEND
    )
    _MODEL = DeepFace.build_model(MODEL_NAME)
except Exception as error:  # pragma: no cover - import-time failure should surface clearly
    logger.critical("Failed to load DeepFace model: %s", error)
    raise RuntimeError(
        "DeepFace must be installed correctly. Run `pip install -r requirements.txt`."
    ) from error


class EmbeddingRequest(BaseModel):
    image_base64: str = Field(..., description="Base64-encoded JPEG/PNG image bytes")


class EmbeddingResponse(BaseModel):
    embedding: List[float]
    faces_detected: int


def _decode_image(image_base64: str) -> np.ndarray:
    try:
        image_bytes = base64.b64decode(image_base64)
    except (ValueError, binascii.Error) as error:
        raise HTTPException(status_code=400, detail=f"Invalid base64 payload: {error}")

    array = np.frombuffer(image_bytes, dtype=np.uint8)
    if array.size == 0:
        raise HTTPException(status_code=400, detail="Empty image payload")

    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=400, detail="Unable to decode image bytes")

    return image


def _generate_embedding(image: np.ndarray) -> EmbeddingResponse:
    try:
        representations = DeepFace.represent(
            img_path=image,
            model_name=MODEL_NAME,
            detector_backend=DETECTOR_BACKEND,
            enforce_detection=True,
            align=True,
        )
    except ValueError as error:
        # DeepFace raises ValueError when no face is detected or image invalid
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:  # pragma: no cover - inference unexpected failure
        logger.exception("DeepFace inference failed")
        raise HTTPException(  # noqa: B904
            status_code=500,
            detail=f"DeepFace inference failed: {error}",
        )

    if not representations:
        raise HTTPException(status_code=422, detail="No face detected in the image")

    primary_face = representations[0]
    embedding_vector = [float(value) for value in primary_face["embedding"]]

    return EmbeddingResponse(
        embedding=embedding_vector,
        faces_detected=len(representations),
    )


app = FastAPI(title="GuardianAI DeepFace Embedding Service")

allowed_origins = os.getenv("CORS_ALLOW_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in allowed_origins if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/generate_embedding", response_model=EmbeddingResponse)
@app.post("/generate_embeddings", response_model=EmbeddingResponse)
async def generate_embedding(payload: EmbeddingRequest) -> EmbeddingResponse:
    image = _decode_image(payload.image_base64)
    return _generate_embedding(image)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=True,
    )
