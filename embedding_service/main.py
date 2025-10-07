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
    relaxed: bool = Field(
        False,
        description=(
            "If true, retry with alternative detectors and a final pass with "
            "enforce_detection disabled to salvage an embedding when no face is detected."
        ),
    )
    detectors: list[str] | None = Field(
        None,
        description=(
            "Optional ordered list of detector backends to try when relaxed is true. "
            "Defaults: retinaface, mtcnn, mediapipe, opencv."
        ),
    )


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


def _generate_embedding(
    image: np.ndarray, *, relaxed: bool = False, detectors: list[str] | None = None
) -> EmbeddingResponse:
    """Generate embedding with optional relaxed fallback.

    When relaxed is True, multiple detector backends are attempted. If all fail, a
    final attempt with enforce_detection=False is made to salvage an embedding.
    """
    primary_error: Exception | None = None
    backends = [DETECTOR_BACKEND]
    # Always allow at least one alternative detector before giving up; when relaxed add the full list.
    base_alternatives = ["retinaface"]  # strong general detector
    full_relaxed = detectors or [
        "retinaface",
        "mtcnn",
        "mediapipe",
        "opencv",
    ]
    chosen = full_relaxed if relaxed else base_alternatives
    for d in chosen:
        if d not in backends:
            backends.append(d)

    for idx, backend in enumerate(backends):
        try:
            representations = DeepFace.represent(
                img_path=image,
                model_name=MODEL_NAME,
                detector_backend=backend,
                enforce_detection=True,
                align=True,
            )
            if not representations:
                raise ValueError("Empty representations list returned")
            primary_face = representations[0]
            embedding_vector = [float(v) for v in primary_face["embedding"]]
            return EmbeddingResponse(
                embedding=embedding_vector, faces_detected=len(representations)
            )
        except ValueError as error:  # likely no face detected
            primary_error = error
            logger.info(
                "Detector '%s' failed to detect face (attempt %d/%d): %s",
                backend,
                idx + 1,
                len(backends),
                error,
            )
            continue
        except Exception as error:  # unexpected inference failure
            primary_error = error
            logger.warning(
                "Detector '%s' unexpected failure (attempt %d/%d): %s",
                backend,
                idx + 1,
                len(backends),
                error,
            )
            continue

    # If relaxed, attempt a final raw forward pass without detection.
    if relaxed:
        try:
            logger.info(
                "All detectors failed; attempting relaxed enforce_detection=False fallback"
            )
            representations = DeepFace.represent(
                img_path=image,
                model_name=MODEL_NAME,
                detector_backend=backends[0],  # original backend
                enforce_detection=False,
                align=False,
            )
            if representations:
                primary_face = representations[0]
                embedding_vector = [float(v) for v in primary_face["embedding"]]
                return EmbeddingResponse(embedding=embedding_vector, faces_detected=0)
        except Exception as error:  # pragma: no cover
            logger.info("Relaxed fallback also failed: %s", error)
            # fall through to error raise below

    detail_msg = (
        f"No face detected after trying detectors: {', '.join(backends)}"
        if primary_error
        else "No face detected"
    )
    raise HTTPException(status_code=422, detail=detail_msg)


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
    return _generate_embedding(
        image,
        relaxed=payload.relaxed,
        detectors=payload.detectors,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=True,
    )
