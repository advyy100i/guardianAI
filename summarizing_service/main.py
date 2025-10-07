import logging
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from modeling import get_model_wrapper, ModelNotTrained
import os

logger = logging.getLogger("summarizing_service")

app = FastAPI(title="GuardianAI Summarizing Service")

class SummarizeRequest(BaseModel):
    description: str = Field(..., min_length=5, description="Free-text emergency description")
    vitals: Optional[dict] = Field(None, description="Optional vitals dictionary")
    history: Optional[list[str]] = Field(None, description="Optional history list")

class SummarizeResponse(BaseModel):
    severity_score: float = Field(..., description="Urgency score 0.0-10.0")
    summary: dict = Field(..., description="Structured summary JSON: vitals/entities/token_stats/raw_description")
    category: str = Field(..., description="Critical|Urgent|Non-Urgent|Unknown classification")
    reasons: list[str] = Field(..., description="Feature contribution rationale strings")

@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}

@app.get("/model_info")
async def model_info() -> dict:
    """Return model training status / metadata.

    Indicates whether a trained model is available and exposes
    feature names & thresholds if present. Does not force a full
    model load beyond reading artifact JSON files.
    """
    wrapper = get_model_wrapper()
    status = wrapper.get_status()
    return status | {"fallback_active": not status.get("trained", False)}

@app.post("/summarize", response_model=SummarizeResponse)
async def summarize(payload: SummarizeRequest) -> SummarizeResponse:
    text = payload.description.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Description required")
    wrapper = get_model_wrapper()
    try:
        result = wrapper.predict(text)
    except ModelNotTrained:
        use_pretrained = os.getenv("USE_PRETRAINED_SEVERITY", "0").lower() in {"1","true","yes"}
        if use_pretrained:
            # Pretrained sentiment-based fallback using VADER
            try:
                from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer  # type: ignore
                analyzer = SentimentIntensityAnalyzer()
                vs = analyzer.polarity_scores(text)
                # Map compound (-1..1) to 0..10 severity (inverse: more negative = higher severity)
                compound = vs.get('compound', 0.0)
                sev = (1 - (compound + 1)/2) * 10  # compound -1 -> 10, +1 -> 0
                sev = max(0.0, min(10.0, sev))
                # Simple categorical cutoffs inspired by original thresholds
                if sev >= 7.5: cat = 'Critical'
                elif sev >= 4.0: cat = 'Urgent'
                else: cat = 'Non-Urgent'
                reasons = [f"Sentiment compound={compound:.3f}"]
                result = {
                    'severity_score': sev,
                    'category': cat,
                    'reasons': reasons,
                    'summary': {
                        'vitals': {},
                        'token_stats': {
                            'length': len(text),
                            'word_count': len(text.split()),
                        },
                        'entities': [],
                    }
                }
            except Exception as sentiment_exc:  # fallback to old heuristic if sentiment fails
                logger.warning("Pretrained sentiment fallback failed: %s", sentiment_exc)
                use_pretrained = False
        if not use_pretrained:
            # Original heuristic fallback (generic, not medical advice)
            vitals_patterns = {
                'bp': r"(?i)\b(\d{2,3})\s*/\s*(\d{2,3})\b",
                'hr': r"(?i)(?:heart rate|hr|pulse)[^\d]{0,6}(\d{2,3})",
                'spo2': r"(?i)(?:spo2|oxygen|o2)[^\d]{0,6}(\d{2,3})%",
            }
            import re
            systolic = diastolic = hr = spo2 = None
            if m:=re.search(vitals_patterns['bp'], text):
                try:
                    systolic = float(m.group(1))
                    diastolic = float(m.group(2))
                except: pass
            if m:=re.search(vitals_patterns['hr'], text):
                try: hr = float(m.group(1))
                except: pass
            if m:=re.search(vitals_patterns['spo2'], text):
                for g in m.groups():
                    if g:
                        try: spo2 = float(g); break
                        except: pass
            score = 0.0
            reasons = []
            if systolic is not None:
                if systolic < 80: score += 4; reasons.append(f"Low systolic {systolic}")
                elif systolic < 90: score += 2; reasons.append(f"Borderline systolic {systolic}")
            if spo2 is not None:
                if spo2 < 85: score += 4; reasons.append(f"Low SpO2 {spo2}%")
                elif spo2 < 92: score += 2; reasons.append(f"Moderate SpO2 {spo2}%")
            if hr is not None and hr >= 130:
                score += 2; reasons.append(f"Tachycardia HR {hr}")
            exclaims = text.count('!')
            score += min(1.0, exclaims * 0.3)
            import re as _re
            urgent_terms = _re.findall(r"(?i)\b(unconscious|not? ?breathing|gasping|confused|collapse|seizing|shock)\b", text)
            if urgent_terms:
                score += min(3.0, 1.5 + 0.3*len(set(urgent_terms)))
                reasons.append("Urgency terms: " + ",".join(sorted(set([u.lower() for u in urgent_terms]))))
            score = max(0.0, min(10.0, score))
            if score >= 7.5: category = 'Critical'
            elif score >= 4.0: category = 'Urgent'
            else: category = 'Non-Urgent'
            summary = {
                'vitals': {
                    **({ 'bp_systolic': systolic, 'bp_diastolic': diastolic } if systolic is not None and diastolic is not None else {}),
                    **({ 'hr': hr } if hr is not None else {}),
                    **({ 'spo2': spo2 } if spo2 is not None else {}),
                },
                'token_stats': {
                    'length': len(text),
                    'exclaim_count': exclaims,
                    'word_count': len(text.split()),
                },
                'entities': [],
            }
            result = {
                'severity_score': score,
                'category': category,
                'reasons': reasons or ["Heuristic fallback (no model)"],
                'summary': summary,
            }
    except Exception as e:  # pragma: no cover
        logger.exception("Summarization failed")
        raise HTTPException(status_code=500, detail=str(e))
    # augment with raw description
    result["summary"]["raw_description"] = text
    return SummarizeResponse(
        severity_score=result["severity_score"],
        summary=result["summary"],
        category=result["category"],
        reasons=result["reasons"],
    )

if __name__ == "__main__":
    import uvicorn, os
    # Allow overriding port via ENV (SUMMARIZING_SERVICE_PORT) with fallback to 8001
    port = int(os.getenv("SUMMARIZING_SERVICE_PORT", "8001"))
    # Disable reload to avoid duplicate file watchers / socket reuse issues on Windows (can trigger WinError 10013)
    print(f"[summarizing_service] Starting on port {port} (reload disabled)")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
