import json
import os
import re
from pathlib import Path
from typing import Dict, Any, List, Tuple

import joblib  # type: ignore
import numpy as np

try:
    import spacy  # type: ignore
except ImportError:  # pragma: no cover
    spacy = None

MODEL_DIR = Path(__file__).parent / "artifacts"
MODEL_DIR.mkdir(exist_ok=True)
CONFIG_DIR = Path(__file__).parent / "config"
PATTERNS_PATH = CONFIG_DIR / "patterns.json"

MODEL_PATH = MODEL_DIR / "severity_model.joblib"
VECTORIZER_PATH = MODEL_DIR / "vectorizer.joblib"
FEATURE_META_PATH = MODEL_DIR / "feature_meta.json"
THRESHOLDS_PATH = MODEL_DIR / "thresholds.json"


class ModelNotTrained(Exception):
    pass


def load_patterns() -> Dict[str, Any]:
    if not PATTERNS_PATH.exists():
        return {"vitals_patterns": {}}
    with open(PATTERNS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


class SeverityModelWrapper:
    def __init__(self):
        self._nlp = None
        self._model = None
        self._vectorizer = None
        self._feature_names: List[str] = []
        self._thresholds: Dict[str, float] = {}
        self._patterns = load_patterns()

    # Lightweight status inspection that does NOT require model load unless needed
    def get_status(self) -> Dict[str, Any]:
        """Return status about training/artifacts without forcing full model load.

        Structure:
            {
              "trained": bool,
              "artifacts": {"model": bool, "feature_meta": bool, "thresholds": bool, "vectorizer": bool},
              "feature_names": [...],   # empty if unavailable
              "thresholds": {...}       # empty if unavailable
            }
        """
        artifacts = {
            "model": MODEL_PATH.exists(),
            "feature_meta": FEATURE_META_PATH.exists(),
            "thresholds": THRESHOLDS_PATH.exists(),
            "vectorizer": VECTORIZER_PATH.exists(),
        }
        trained = all([artifacts["model"], artifacts["feature_meta"], artifacts["thresholds"]])
        feature_names: List[str] = []
        thresholds: Dict[str, float] = {}
        # If already loaded, reuse in-memory data
        if self._feature_names:
            feature_names = list(self._feature_names)
        elif artifacts["feature_meta"]:
            try:
                with open(FEATURE_META_PATH, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                feature_names = meta.get("feature_names", [])
            except Exception:
                pass
        if self._thresholds:
            thresholds = dict(self._thresholds)
        elif artifacts["thresholds"]:
            try:
                with open(THRESHOLDS_PATH, "r", encoding="utf-8") as f:
                    thresholds = json.load(f)
            except Exception:
                pass
        return {
            "trained": trained,
            "artifacts": artifacts,
            "feature_count": len(feature_names),
            "feature_names": feature_names,
            "thresholds": thresholds,
        }

    def ensure_loaded(self):
        if self._model is not None:
            return
        if not MODEL_PATH.exists() or not FEATURE_META_PATH.exists() or not THRESHOLDS_PATH.exists():
            raise ModelNotTrained("Severity model artifacts missing. Train before use.")
        # lazy load spaCy
        if spacy is None:
            raise RuntimeError("spaCy not installed")
        try:
            self._nlp = spacy.load("en_core_web_sm")
        except Exception:
            # fallback blank pipeline
            self._nlp = spacy.blank("en")
        self._model = joblib.load(MODEL_PATH)
        if VECTORIZER_PATH.exists():
            self._vectorizer = joblib.load(VECTORIZER_PATH)
        with open(FEATURE_META_PATH, "r", encoding="utf-8") as f:
            meta = json.load(f)
        self._feature_names = meta.get("feature_names", [])
        with open(THRESHOLDS_PATH, "r", encoding="utf-8") as f:
            self._thresholds = json.load(f)

    # ---------------- FEATURE EXTRACTION -----------------
    def _extract_vitals(self, text: str) -> Dict[str, float]:
        vitals: Dict[str, float] = {}
        vp = self._patterns.get("vitals_patterns", {})
        bp_pat = vp.get("blood_pressure")
        if bp_pat:
            m = re.search(bp_pat, text)
            if m:
                try:
                    vitals["bp_systolic"] = float(m.group(1))
                    vitals["bp_diastolic"] = float(m.group(2))
                except Exception:
                    pass
        hr_pat = vp.get("heart_rate")
        if hr_pat:
            m = re.search(hr_pat, text)
            if m:
                try:
                    vitals["hr"] = float(m.group(1))
                except Exception:
                    pass
        spo2_pat = vp.get("spo2")
        if spo2_pat:
            m = re.search(spo2_pat, text)
            if m:
                # pattern may capture in group1
                for g in m.groups():
                    if g:
                        try:
                            vitals["spo2"] = float(g)
                            break
                        except Exception:
                            pass
        return vitals

    def _basic_doc_features(self, doc) -> Dict[str, float]:
        tokens = [t for t in doc if not t.is_space]
        n = len(tokens)
        feats: Dict[str, float] = {
            "tok_count": float(n),
            "avg_tok_len": float(np.mean([len(t.text) for t in tokens])) if n else 0.0,
            "ent_count": float(len(doc.ents)),
            "num_ratio": float(sum(1 for t in tokens if t.like_num) / n) if n else 0.0,
            "upper_ratio": float(sum(1 for t in tokens if t.text.isupper()) / n) if n else 0.0,
            "exclaim_count": float(sum(1 for t in tokens if "!" in t.text)),
        }
        return feats

    def _embedding_features(self, doc, dims: int = 25) -> Dict[str, float]:
        if not doc.vector.any():  # spaCy small may have zero vectors
            return {f"emb_{i}": 0.0 for i in range(dims)}
        vec = doc.vector
        if vec.shape[0] < dims:
            # pad
            padded = np.zeros(dims, dtype=float)
            padded[: vec.shape[0]] = vec
            vec = padded
        else:
            vec = vec[:dims]
        return {f"emb_{i}": float(v) for i, v in enumerate(vec)}

    def build_feature_vector(self, text: str) -> Tuple[List[float], List[str], Dict[str, Any]]:
        if self._nlp is None:
            raise ModelNotTrained("NLP pipeline not loaded")
        doc = self._nlp(text)
        vitals = self._extract_vitals(text)
        basic = self._basic_doc_features(doc)
        emb = self._embedding_features(doc)
        feature_map: Dict[str, float] = {}
        # deterministic ordering: vitals then basic then emb (makes meta stable)
        for group in (vitals, basic, emb):
            for k, v in group.items():
                feature_map[k] = float(v)
        names = list(feature_map.keys())
        values = [feature_map[k] for k in names]
        summary_payload = {
            "vitals": vitals,
            "entities": [
                {"text": ent.text, "label": ent.label_} for ent in doc.ents
            ],
            "token_stats": basic,
        }
        return values, names, summary_payload

    def predict(self, text: str) -> Dict[str, Any]:
        self.ensure_loaded()
        vec, names, summary = self.build_feature_vector(text)
        # align to training feature order
        if self._feature_names:
            aligned = []
            name_to_val = dict(zip(names, vec))
            for fname in self._feature_names:
                aligned.append(name_to_val.get(fname, 0.0))
        else:
            aligned = vec
        X = np.array(aligned).reshape(1, -1)
        sev = float(self._model.predict(X)[0])
        # clamp 0-10
        sev = max(0.0, min(10.0, sev))
        # thresholds
        cat = "Unknown"
        if self._thresholds:
            crit = self._thresholds.get("critical")
            urgent = self._thresholds.get("urgent")
            if crit is not None and sev >= crit:
                cat = "Critical"
            elif urgent is not None and sev >= urgent:
                cat = "Urgent"
            else:
                cat = "Non-Urgent"
        # reasons: top coefficients * value (if linear)
        reasons: List[str] = []
        if hasattr(self._model, "coef_"):
            coefs = self._model.coef_.ravel() if hasattr(self._model.coef_, "ravel") else self._model.coef_
            pairs = []
            for fname, val in zip(self._feature_names, aligned):
                idx = self._feature_names.index(fname)
                if idx < len(coefs):
                    contrib = coefs[idx] * (val or 0.0)
                    pairs.append((abs(contrib), contrib, fname, val))
            pairs.sort(reverse=True, key=lambda x: x[0])
            for p in pairs[:3]:
                reasons.append(f"{p[2]} contrib={p[1]:.2f}")
        return {
            "severity_score": sev,
            "category": cat,
            "reasons": reasons,
            "summary": summary,
        }


# Singleton accessor
_MODEL_WRAPPER: SeverityModelWrapper | None = None

def get_model_wrapper() -> SeverityModelWrapper:
    global _MODEL_WRAPPER
    if _MODEL_WRAPPER is None:
        _MODEL_WRAPPER = SeverityModelWrapper()
    return _MODEL_WRAPPER
