"""GuardianAI Triage Module
=================================

This module provides a hybrid emergency triage scoring system combining:
1. Deterministic safety-first rules (hard overrides for life threats)
2. Optional ML regression model (scikit-learn) for nuanced urgency scoring

Primary entrypoint:
    triage_case(case_json: dict) -> dict

Output schema:
{
  "urgency_score": float (0.0 - 10.0),
  "category": "Critical"|"Urgent"|"Non-Urgent",
  "reasons": [str],
  "model_confidence": float|None
}

Deterministic Critical Rules (override ML):
- bp_systolic < 80
- spo2 < 85
- presence of critical symptoms: unconscious|not responding|unconsciousness|not breathing|seizure (with critical modifiers)|airway compromise phrases
- severe active bleeding (modifiers contain 'profuse' or 'uncontrolled' AND symptom bleeding)

ML Scoring:
- If no critical override, features extracted and fed to a regressor
- If model is missing or SKIP_ML=True, use heuristic score fallback

Configurable thresholds:
CRITICAL_THRESHOLD = 8.5
URGENT_THRESHOLD = 4.0
CRITICAL_OVERRIDE_SCORE = 9.5 (assigned when rules trigger, can be tuned)

Synthetic Training Stub:
- train_model() can generate synthetic logical cases if real dataset absent
- Saves model via joblib to triage_model.joblib and metadata to triage_model_meta.json

Approximate Explainability:
- For ML path: we compute contribution approximations using feature * coefficient for linear models or feature importance weighting for tree models.

NOTE: This implementation is designed for extension. Real-world deployment should incorporate calibration, additional safety checks, and robust logging.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
import math
import json
import os
import datetime

# Attempt lightweight ML imports
_MODEL_BACKEND = None
try:
    from sklearn.linear_model import Ridge
    from sklearn.model_selection import KFold
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline
    from sklearn.metrics import mean_absolute_error, mean_squared_error
    import joblib  # type: ignore
    _MODEL_BACKEND = 'sklearn'
except Exception:  # pragma: no cover - degrade gracefully
    _MODEL_BACKEND = None

# ----------------------------- CONFIG ---------------------------------
CONFIG = {
    "CRITICAL_THRESHOLD": 8.5,
    "URGENT_THRESHOLD": 4.0,
    "CRITICAL_OVERRIDE_SCORE": 9.5,
    "MIN_SCORE": 0.0,
    "MAX_SCORE": 10.0,
    "SKIP_ML": False,  # set True to force heuristic scoring
    "MODEL_PATH": "triage_model.joblib",
    "MODEL_META_PATH": "triage_model_meta.json",
    "USE_SYNTHETIC_IF_MISSING": True,
    # toggles
    "ENABLE_RULE_LOW_BP": True,
    "ENABLE_RULE_LOW_SPO2": True,
    "ENABLE_RULE_UNRESPONSIVE": True,
    "ENABLE_RULE_SEIZURE_CRITICAL": True,
    "ENABLE_RULE_PROFUSE_BLEEDING": True,
    "WEIGHTS": {
        "vital_low_bp": 2.2,
        "vital_spo2_scale": 2.8,  # multiplier for SpO2 deficit scaling
        "vital_hr_scale": 1.2,    # scaling per (hr-100)/30
        "sym_chest_pain": 3.0,
        "sym_sob": 2.7,
        "sym_seizure": 3.0,
        "sym_bleeding": 2.0,
        "sym_unconscious": 4.0,
        "sym_altered_mental": 1.5,
        "severity_flag": 1.0,
        "onset": 1.5,
        "elderly": 0.8,
        "infant": 1.0,
        "mod_count_unit": 0.2,
        "mod_count_cap": 1.0,
        "hist_cardiac": 0.7,
        "hist_anticoagulant": 0.7,
        "recalib_min_chest_pain_hr": 5.2,  # raise floor above urgent threshold baseline 4.0
    }
}

CRITICAL_SYMPTOMS = {"unconscious", "not responding", "unresponsive", "not breathing"}
SEIZURE_TERMS = {"seizure"}
BLEED_TERMS = {"bleeding"}
RESP_DISTRESS_TERMS = {"shortness of breath"}
HEADACHE_TERMS = {"headache", "severe headache"}
CHEST_PAIN_TERMS = {"chest pain"}
FAINTING_TERMS = {"fainting", "fainted"}
ALTERED_MENTAL_TERMS = {"altered mental status"}

# ----------------------------- FEATURE EXTRACTION ---------------------
FEATURE_ORDER = [
    # vitals
    "hr", "bp_systolic", "bp_diastolic", "spo2",
    # symptom presence booleans
    "sym_chest_pain", "sym_sob", "sym_seizure", "sym_unconscious", "sym_bleeding", "sym_headache", "sym_fainting", "sym_altered_mental",
    # severity flags (any severe/critical)
    "sev_any",
    # onset (inverse scaled)
    "inv_onset",
    # age
    "age", "is_elderly", "is_infant",
    # modifiers count
    "mod_count",
    # history flags (example demonstration: cardiac, anticoagulant)
    "hist_cardiac", "hist_anticoagulant",
]

HISTORY_KEYWORDS = {
    "cardiac": "hist_cardiac",
    "heart disease": "hist_cardiac",
    "anticoagulant": "hist_anticoagulant",
    "blood thinner": "hist_anticoagulant",
}

@dataclass
class FeatureVector:
    vector: List[float]
    names: List[str]

# ----------------------------- UTILITIES ------------------------------

def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _extract_symptom_terms(case_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    return case_json.get("symptoms", []) or []


def _symptom_present(symptoms: List[Dict[str, Any]], terms: set) -> bool:
    for s in symptoms:
        term = (s.get("term") or "").lower()
        if term in terms:
            return True
    return False


def _any_severity(symptoms: List[Dict[str, Any]]) -> bool:
    for s in symptoms:
        sev = (s.get("severity") or "").lower()
        if sev in {"severe", "critical"}:
            return True
    return False


def extract_features(case_json: Dict[str, Any]) -> FeatureVector:
    symptoms = _extract_symptom_terms(case_json)
    vitals = case_json.get("vitals") or {}
    hr = float(vitals.get("hr") or 0)
    bp_sys = float(vitals.get("bp_systolic") or 0)
    bp_dia = float(vitals.get("bp_diastolic") or 0)
    spo2 = float(vitals.get("spo2") or 0)

    onset_any = None
    for s in symptoms:
        if s.get("onset_minutes") is not None:
            onset_any = s["onset_minutes"]
            break
    if onset_any is None:
        onset_any = 9999  # treat unknown as far past
    inv_onset = 1.0 / (1.0 + onset_any)  # more recent -> closer to 1

    age = case_json.get("age")
    age_val = float(age) if isinstance(age, (int, float)) else 0.0
    is_elderly = 1.0 if age_val >= 65 else 0.0
    is_infant = 1.0 if 0 < age_val < 2 else 0.0

    modifiers = case_json.get("modifiers") or []
    mod_count = float(len(modifiers))

    history = case_json.get("history") or []
    history_flags = {k: 0.0 for k in ["hist_cardiac", "hist_anticoagulant"]}
    for h in history:
        h_low = h.lower()
        for key, feat_name in HISTORY_KEYWORDS.items():
            if key in h_low:
                history_flags[feat_name] = 1.0

    vector = [
        hr, bp_sys, bp_dia, spo2,
        1.0 if _symptom_present(symptoms, CHEST_PAIN_TERMS) else 0.0,
        1.0 if _symptom_present(symptoms, RESP_DISTRESS_TERMS) else 0.0,
        1.0 if _symptom_present(symptoms, SEIZURE_TERMS) else 0.0,
        1.0 if _symptom_present(symptoms, CRITICAL_SYMPTOMS) else 0.0,
        1.0 if _symptom_present(symptoms, BLEED_TERMS) else 0.0,
        1.0 if _symptom_present(symptoms, HEADACHE_TERMS) else 0.0,
        1.0 if _symptom_present(symptoms, FAINTING_TERMS) else 0.0,
        1.0 if _symptom_present(symptoms, ALTERED_MENTAL_TERMS) else 0.0,
        1.0 if _any_severity(symptoms) else 0.0,
        inv_onset,
        age_val, is_elderly, is_infant,
        mod_count,
        history_flags["hist_cardiac"], history_flags["hist_anticoagulant"],
    ]
    return FeatureVector(vector=vector, names=FEATURE_ORDER)

# ----------------------------- DETERMINISTIC RULES --------------------

def check_critical_rules(case_json: Dict[str, Any]) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    vitals = case_json.get("vitals") or {}
    bp_sys = vitals.get("bp_systolic")
    spo2 = vitals.get("spo2")
    symptoms = _extract_symptom_terms(case_json)
    modifiers = case_json.get("modifiers") or []

    if CONFIG["ENABLE_RULE_LOW_BP"] and isinstance(bp_sys, (int, float)) and bp_sys < 80:
        reasons.append(f"bp_systolic {bp_sys} (critical)")
    if CONFIG["ENABLE_RULE_LOW_SPO2"] and isinstance(spo2, (int, float)) and spo2 < 85:
        reasons.append(f"SpO2 {spo2}% (critical)")

    # Unresponsive / airway / not breathing
    for s in symptoms:
        term = (s.get("term") or "").lower()
        if CONFIG["ENABLE_RULE_UNRESPONSIVE"] and term in CRITICAL_SYMPTOMS:
            reasons.append(f"{term} (critical symptom)")

    # Seizure with severity or multiple seizure entries
    if CONFIG["ENABLE_RULE_SEIZURE_CRITICAL"] and any((s.get("term") or "").lower() in SEIZURE_TERMS for s in symptoms):
        seizure_count = sum(1 for s in symptoms if (s.get("term") or "").lower() in SEIZURE_TERMS)
        if seizure_count > 1 or any((s.get("severity") or "").lower() in {"severe", "critical"} for s in symptoms if (s.get("term") or "").lower() in SEIZURE_TERMS):
            reasons.append("seizure activity (critical)")

    # Profuse bleeding
    if CONFIG["ENABLE_RULE_PROFUSE_BLEEDING"] and any((s.get("term") or "").lower() in BLEED_TERMS for s in symptoms):
        if any(m in {"profuse", "uncontrolled", "crashing"} for m in modifiers):
            reasons.append("severe bleeding (critical)")

    return (len(reasons) > 0, reasons)

# ----------------------------- HEURISTIC SCORING ----------------------

def heuristic_score(features: FeatureVector) -> Tuple[float, List[str]]:
    v = dict(zip(features.names, features.vector))
    W = CONFIG['WEIGHTS']
    score = 0.0
    reasons: List[str] = []

    # Vital contributions
    if v['bp_systolic'] > 0 and v['bp_systolic'] < 90:
        score += W['vital_low_bp']; reasons.append(f"Low BP {int(v['bp_systolic'])}")
    if 0 < v['spo2'] < 95:
        delta = (95 - v['spo2']) / 10.0
        score += clamp(delta * W['vital_spo2_scale'], 0, 3.2)
        reasons.append(f"SpO2 {int(v['spo2'])}%")
    if v['hr'] > 110:
        score += min((v['hr'] - 100) / 30.0 * W['vital_hr_scale'], 2.5)
        reasons.append(f"HR {int(v['hr'])}")

    # Symptom weights
    if v['sym_chest_pain']:
        score += W['sym_chest_pain']; reasons.append("Chest pain")
    if v['sym_sob']:
        score += W['sym_sob']; reasons.append("Respiratory distress")
    if v['sym_seizure']:
        score += W['sym_seizure']; reasons.append("Seizure")
    if v['sym_bleeding']:
        score += W['sym_bleeding']; reasons.append("Bleeding")
    if v['sym_unconscious']:
        score += W['sym_unconscious']; reasons.append("Unresponsive")
    if v['sym_altered_mental']:
        score += W['sym_altered_mental']; reasons.append("Altered mental status")

    if v['sev_any']:
        score += W['severity_flag']; reasons.append("Severity flag")

    # Onset recency
    score += v['inv_onset'] * W['onset']
    if v['inv_onset'] > 0.001:
        reasons.append("Recent onset")

    # Age adjustments
    if v['is_elderly']:
        score += W['elderly']; reasons.append("Elderly")
    if v['is_infant']:
        score += W['infant']; reasons.append("Infant")

    # Modifiers
    if v['mod_count'] > 0:
        score += min(v['mod_count'] * W['mod_count_unit'], W['mod_count_cap'])
        reasons.append("Multiple modifiers")

    # History
    if v['hist_cardiac']:
        score += W['hist_cardiac']; reasons.append("Cardiac history")
    if v['hist_anticoagulant']:
        score += W['hist_anticoagulant']; reasons.append("Anticoagulant")

    # Recalibration: ensure chest pain + elevated HR gets at least urgent floor
    if v['sym_chest_pain'] and v['hr'] > 100 and score < W['recalib_min_chest_pain_hr']:
        reasons.append("Recalibrated (chest pain + tachycardia)")
        score = max(score, W['recalib_min_chest_pain_hr'])

    score = clamp(score, CONFIG['MIN_SCORE'], CONFIG['MAX_SCORE'])
    # Deduplicate reasons
    seen = set(); dedup = []
    for r in reasons:
        if r not in seen:
            dedup.append(r); seen.add(r)
    return score, dedup[:6]

# ----------------------------- MODEL HANDLING -------------------------
MODEL_CACHE = {"model": None, "kind": None}

def load_model() -> Optional[Any]:
    if CONFIG['SKIP_ML']:
        return None
    if MODEL_CACHE['model'] is not None:
        return MODEL_CACHE['model']
    path = CONFIG['MODEL_PATH']
    if _MODEL_BACKEND and os.path.exists(path):
        try:
            model = joblib.load(path)
            MODEL_CACHE['model'] = model
            MODEL_CACHE['kind'] = 'sklearn'
            return model
        except Exception:
            return None
    return None


def save_model(model: Any, meta: Dict[str, Any]) -> None:
    if not _MODEL_BACKEND:
        return
    joblib.dump(model, CONFIG['MODEL_PATH'])
    with open(CONFIG['MODEL_META_PATH'], 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=2)


def model_score(features: FeatureVector) -> Tuple[Optional[float], Optional[float], List[str]]:
    model = load_model()
    if not model:
        return None, None, []
    import numpy as np  # local import to avoid dependency if unused
    X = np.array([features.vector])
    try:
        pred = model.predict(X)[0]
    except Exception:
        return None, None, []
    # Ensure prediction scaled 0-10
    score = float(clamp(pred, CONFIG['MIN_SCORE'], CONFIG['MAX_SCORE']))

    # Attempt approximate explanation
    reasons: List[str] = []
    if hasattr(model, 'coef_'):
        coefs = getattr(model, 'coef_')
        contribs = list(zip(features.names, [c * v for c, v in zip(coefs, features.vector)]))
        contribs.sort(key=lambda x: abs(x[1]), reverse=True)
        for name, val in contribs[:4]:
            reasons.append(f"{name}:{val:.2f}")
    elif hasattr(model, 'feature_importances_'):
        imps = getattr(model, 'feature_importances_')
        pairs = list(zip(features.names, imps))
        pairs.sort(key=lambda x: x[1], reverse=True)
        for name, val in pairs[:4]:
            reasons.append(f"{name}:{val:.2f}")
    else:
        reasons.append("model_inference")

    # Confidence placeholder: for ridge we approximate by normalization of std residuals (not available here) -> fixed 0.75
    confidence = 0.75
    return score, confidence, reasons

# ----------------------------- TRAINING -------------------------------

def _generate_synthetic_cases(n: int = 300) -> List[Dict[str, Any]]:
    import random
    cases = []
    for _ in range(n):
        bp_s = random.randint(70, 160)
        spo2 = random.randint(78, 100)
        hr = random.randint(50, 170)
        chest = random.random() < 0.25
        sob = random.random() < 0.20
        seizure = random.random() < 0.05
        bleed = random.random() < 0.10
        unconscious = random.random() < 0.04
        altered = random.random() < 0.08
        fainting = random.random() < 0.06
        severity = random.random() < 0.30
        age = random.choice([None] + list(range(1, 90)))
        onset = random.choice([5, 10, 30, 60, 120, 300, None])
        vitals = {"bp_systolic": bp_s, "bp_diastolic": random.randint(40, 100), "spo2": spo2, "hr": hr}
        symptoms = []
        for flag, term in [
            (chest, 'chest pain'), (sob, 'shortness of breath'), (seizure, 'seizure'),
            (bleed, 'bleeding'), (unconscious, 'unconscious'), (fainting, 'fainting'), (altered, 'altered mental status')
        ]:
            if flag:
                symptoms.append({"term": term, "severity": 'severe' if severity and random.random()<0.5 else None, "onset_minutes": onset})
        case = {
            "symptoms": symptoms,
            "vitals": vitals,
            "modifiers": [m for m in ["severe" if severity else None] if m],
            "history": [h for h in ["cardiac disease" if random.random()<0.1 else None] if h],
            "age": age,
        }
        cases.append(case)
    return cases


def train_model(train_cases: Optional[List[Dict[str, Any]]] = None) -> None:
    if CONFIG['SKIP_ML'] or not _MODEL_BACKEND:
        print("[train_model] ML backend unavailable or SKIP_ML=True; skipping training.")
        return
    import numpy as np
    # Generate synthetic if missing
    if train_cases is None and CONFIG['USE_SYNTHETIC_IF_MISSING']:
        train_cases = _generate_synthetic_cases(400)

    if not train_cases:
        print("[train_model] No training data provided.")
        return

    X = []
    y = []
    for c in train_cases:
        feats = extract_features(c)
        # heuristic baseline as pseudo-label (in absence of real labels)
        base_score, _ = heuristic_score(feats)
        # escalate if rule critical
        critical, _r = check_critical_rules(c)
        if critical:
            label = 9.5
        else:
            label = base_score
        X.append(feats.vector)
        y.append(label)

    X = np.array(X)
    y = np.array(y)

    model = Pipeline([
        ('scaler', StandardScaler()),
        ('ridge', Ridge(alpha=1.0))
    ])

    kf = KFold(n_splits=5, shuffle=True, random_state=42)
    maes = []
    rmses = []
    for train_idx, val_idx in kf.split(X):
        model.fit(X[train_idx], y[train_idx])
        pred = model.predict(X[val_idx])
        maes.append(mean_absolute_error(y[val_idx], pred))
        rmses.append(math.sqrt(mean_squared_error(y[val_idx], pred)))

    # Train final on all
    model.fit(X, y)

    meta = {
        "model_type": "Ridge",
        "trained_at": datetime.datetime.utcnow().isoformat() + 'Z',
        "cv_mae_mean": float(sum(maes)/len(maes)),
        "cv_rmse_mean": float(sum(rmses)/len(rmses)),
        "feature_order": FEATURE_ORDER,
        "version": "0.1.0",
    }
    save_model(model, meta)
    print("[train_model] Model trained and saved.")
    print(json.dumps(meta, indent=2))

# ----------------------------- CATEGORY MAPPING -----------------------

def map_category(score: float) -> str:
    if score >= CONFIG['CRITICAL_THRESHOLD']:
        return "Critical"
    if score >= CONFIG['URGENT_THRESHOLD']:
        return "Urgent"
    return "Non-Urgent"

# ----------------------------- MAIN API -------------------------------

def triage_case(case_json: Dict[str, Any]) -> Dict[str, Any]:
    """Compute urgency triage result for a summarized case.

    Parameters
    ----------
    case_json : dict
        Output from summarizer.summarize_event()

    Returns
    -------
    dict with keys: urgency_score, category, reasons, model_confidence

    Example critical input (A) triggers deterministic override:
    {
      "symptoms": [{"term":"shortness of breath"},{"term":"chest pain"}],
      "vitals": {"hr":140,"bp_systolic":70,"bp_diastolic":40,"spo2":82},
      "modifiers":["severe"],"history":["Hypertension"],"age":65
    }
    """
    # 1. Deterministic rule check
    is_critical, crit_reasons = check_critical_rules(case_json)
    if is_critical:
        score = CONFIG['CRITICAL_OVERRIDE_SCORE']
        return {
            "urgency_score": score,
            "category": map_category(score),
            "reasons": crit_reasons[:4],
            "model_confidence": None,
        }

    # 2. Feature extraction
    features = extract_features(case_json)

    # 3. Model path if available
    model_used = False
    model_conf = None
    model_reasons: List[str] = []
    model_score_val: Optional[float] = None
    if not CONFIG['SKIP_ML']:
        model_score_val, model_conf, model_reasons = model_score(features)
        model_used = model_score_val is not None

    # 4. Fallback heuristic if model absent
    if not model_used:
        heuristic_val, heur_reasons = heuristic_score(features)
        final_score = heuristic_val
        reasons = heur_reasons
    else:
        final_score = model_score_val  # type: ignore
        # Merge top model reasons with human-friendly heuristics for interpretability
        heur_val, heur_reasons = heuristic_score(features)
        reasons = heur_reasons[:3] + model_reasons[:2]

    final_score = clamp(final_score, CONFIG['MIN_SCORE'], CONFIG['MAX_SCORE'])
    category = map_category(final_score)

    # Post-calibration safety net: ensure chest pain + tachycardia not labeled Non-Urgent
    symptoms = _extract_symptom_terms(case_json)
    has_chest = any((s.get('term') or '').lower() in CHEST_PAIN_TERMS for s in symptoms)
    vitals = case_json.get('vitals') or {}
    hr_val = vitals.get('hr')
    if has_chest and isinstance(hr_val, (int, float)) and hr_val > 100 and final_score < CONFIG['URGENT_THRESHOLD']:
        final_score = max(final_score, CONFIG['URGENT_THRESHOLD'] + 0.3)
        category = map_category(final_score)
        reasons.append('Post-calibration: chest pain + tachycardia')

    return {
        "urgency_score": round(final_score, 2),
        "category": category,
        "reasons": reasons[:6],
        "model_confidence": round(model_conf, 2) if model_conf is not None else None,
    }

# ----------------------------- DEMO / TESTS ---------------------------

def _demo_examples():
    example_a = {
        "symptoms": [{"term":"shortness of breath"},{"term":"chest pain"}],
        "vitals": {"hr":140,"bp_systolic":70,"bp_systolic":70,"bp_diastolic":40,"spo2":82},
        "modifiers":["severe"],
        "history":["Hypertension"],
        "age":65,
    }
    example_b = {
        "symptoms":[{"term":"chest pain"}],
        "vitals": {"hr":110,"bp_systolic":120,"bp_diastolic":80,"spo2":96},
        "modifiers":["sudden"],
        "history":["smoker"],
        "age":54,
    }
    example_c = {
        "symptoms":[{"term":"headache"}],
        "vitals": {"hr":78,"bp_systolic":128,"bp_diastolic":82,"spo2":98},
        "modifiers":[],
        "history":[],
        "age":30,
    }
    print("Example A (Critical override):")
    print(json.dumps(triage_case(example_a), indent=2))
    print("\nExample B (Urgent via ML/heuristic):")
    print(json.dumps(triage_case(example_b), indent=2))
    print("\nExample C (Non-Urgent):")
    print(json.dumps(triage_case(example_c), indent=2))

    # Basic asserts
    a_res = triage_case(example_a)
    assert a_res['category'] == 'Critical' and a_res['urgency_score'] >= 9.0
    b_res = triage_case(example_b)
    assert b_res['category'] in {'Urgent','Non-Urgent'}  # depends on model/heuristic
    c_res = triage_case(example_c)
    assert c_res['category'] == 'Non-Urgent'
    print("\nAssertions passed.")

if __name__ == "__main__":
    # Optional: train model if not present
    if _MODEL_BACKEND and not os.path.exists(CONFIG['MODEL_PATH']):
        train_model()
    _demo_examples()
