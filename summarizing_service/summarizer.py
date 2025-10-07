"""GuardianAI Summarizer Agent implementation.

Extract clinically important details from free-text emergency messages.

Core function: summarize_event(text: str, vitals: dict|None=None, history: list[str]|None=None) -> dict

Design Goals:
- Deterministic, lightweight rule-based pipeline with optional spaCy / scispaCy if installed.
- Robust regex extraction for symptoms, modifiers, onset durations.
- Map key symptoms to SNOMED codes using a local dictionary.
- Always produce a JSON-serializable dict following the required schema.

If spaCy model not present, proceed without NER gracefully.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import List, Dict, Optional, Tuple, Iterable

# SNOMED mapping dictionary (extendable)
SNOMED_MAP: Dict[str, str] = {
    "chest pain": "SNOMED:29857009",
    "shortness of breath": "SNOMED:267036007",
    "can't breathe": "SNOMED:267036007",  # alias to SOB
    "cannot breathe": "SNOMED:267036007",
    "difficulty breathing": "SNOMED:267036007",
    "seizure": "SNOMED:91175000",
    "unconscious": "SNOMED:3006004",
    "not responding": "SNOMED:3006004",
    "bleeding": "SNOMED:131148009",
    "headache": "SNOMED:25064002",  # added common term
    "severe headache": "SNOMED:25064002",
    "fainting": "SNOMED:271594007",
    "fainted": "SNOMED:271594007",
}

# Add simple anatomical locations list
ANATOMY_TERMS = [
    "left arm", "right arm", "left leg", "right leg", "left chest", "right chest", "chest",
    "abdomen", "stomach", "head", "neck", "back", "lower back", "upper back", "arm", "leg"
]
ANATOMY_REGEX = re.compile(r"\b(" + "|".join(re.escape(t) for t in sorted(ANATOMY_TERMS, key=len, reverse=True)) + r")\b", re.IGNORECASE)

SEX_REGEX = re.compile(r"\b(male|female|woman|man|girl|boy|lady|gentleman|m\/f)\b", re.IGNORECASE)
AGE_REGEX = re.compile(r"\b(\d{1,3})\s*(years? old|y/o|yo|yr old|yrs? old)\b", re.IGNORECASE)
AGE_COMPACT_REGEX = re.compile(r"\b(\d{1,2})\s*(m|months?) old\b", re.IGNORECASE)
AGE_SIMPLE_PREFIX = re.compile(r"\b(\d{1,3})\s*(y/o|yo)\b", re.IGNORECASE)

# Symptom synonym normalization mapping
SYMPTOM_SYNONYMS = {
    "sob": "shortness of breath",
    "can't breathe": "shortness of breath",
    "cannot breathe": "shortness of breath",
    "difficulty breathing": "shortness of breath",
    "passed out": "fainted",
    "loss of consciousness": "unconscious",
}

# Canonical symptom phrases (ordered by descending length to avoid partial shadowing)
SYMPTOM_PATTERNS: List[str] = [
    "shortness of breath",
    "can't breathe",
    "cannot breathe",
    "difficulty breathing",
    "chest pain",
    "severe headache",
    "headache",
    "not responding",
    "unconscious",
    "seizure",
    "bleeding",
    "fainting",
    "fainted",
]

# Severity / modifier terms
MODIFIER_TERMS = [
    "severe", "sudden", "radiating", "crushing", "persistent", "profuse", "heavy", "uncontrolled",
    "faint", "sweating", "diaphoretic", "unresponsive", "unconscious", "not responding",
]
# Add new informal modifiers
MODIFIER_TERMS.extend([
    "clammy", "cold", "confused", "gasping", "struggling", "crashing"
])
# Rebuild modifier regex after extension
MODIFIER_REGEX = re.compile(r"\b(" + "|".join(re.escape(m) for m in sorted(set(MODIFIER_TERMS))) + r")\b", re.IGNORECASE)

# Additional symptom concepts for informal text
INFORMAL_SYMPTOMS = {
    "gasping for air": ("shortness of breath", "SNOMED:267036007"),
    "gasping": ("shortness of breath", "SNOMED:267036007"),
    "struggling to breathe": ("shortness of breath", "SNOMED:267036007"),
    "confused": ("altered mental status", "SNOMED:419284004"),
    "eyes rolling": ("seizure", "SNOMED:91175000"),
}

# Expand INFORMAL_SYMPTOMS with additional mental status / syncope phrases
INFORMAL_SYMPTOMS.update({
    "disoriented": ("altered mental status", "SNOMED:419284004"),
    "lethargic": ("altered mental status", "SNOMED:419284004"),
    "dazed": ("altered mental status", "SNOMED:419284004"),
    "about to pass out": ("fainting", "SNOMED:271594007"),
    "could go out": ("fainting", "SNOMED:271594007"),
})

# Inline vitals regex patterns
BP_REGEX = re.compile(r"\b(\d{2,3})\s*/\s*(\d{2,3})\b")
HR_REGEX = re.compile(r"(heart\s*rate[^\d]{0,10}|hr[^\d]{0,3}|pulse[^\d]{0,10})?(\b\d{2,3}\b)(?=\D|$)", re.IGNORECASE)
SPO2_REGEX = re.compile(r"(?:spo2|oxygen|o2)[^\d]{0,6}(\d{2,3})%|\b(\d{2,3})%\b", re.IGNORECASE)

# Informal age heuristic: number near pronoun he/she/guy/girl/man/woman
AGE_INFORMAL_REGEX = re.compile(r"\b(?:he|she|guy|man|woman|dude|person)\W{0,10}(\d{2})\b", re.IGNORECASE)
# Additional informal age pattern: "he's only 46" / normalized apostrophes later
AGE_ONLY_PATTERN = re.compile(r"\b(?:he|she|they|person|guy|man|woman)[^\d]{0,6}(?:only\s+)?(\d{2})\b", re.IGNORECASE)

# Ensure onset regex definitions exist (reassert in case of patch side-effects)
if 'ONSET_REGEXES' not in globals():
    ONSET_REGEXES = [
        re.compile(r"\bfor\s+(\d{1,4})\s*(minutes?|mins?|min)\b", re.IGNORECASE),
        re.compile(r"\bfor\s+(\d{1,4})\s*(hours?|hrs?|hr)\b", re.IGNORECASE),
        re.compile(r"\bsince\s+(\d{1,4})\s*(minutes?|mins?|min)\b", re.IGNORECASE),
        re.compile(r"\bsince\s+(\d{1,4})\s*(hours?|hrs?|hr)\b", re.IGNORECASE),
    ]
if 'GENERIC_DURATION_REGEX' not in globals():
    GENERIC_DURATION_REGEX = re.compile(r"\b(\d{1,4})\s*(minutes?|mins?|hours?|hrs?|hr)\b", re.IGNORECASE)

# Attempt optional spaCy / scispaCy load
def _load_spacy_model():
    try:
        import spacy  # type: ignore
        # Prefer a scientific small model if available
        for model_name in ("en_core_sci_sm", "en_core_web_sm"):
            try:
                return spacy.load(model_name)
            except Exception:
                continue
    except ImportError:
        return None
    return None

_SPACY_NLP = _load_spacy_model()

@dataclass
class SymptomCandidate:
    term: str
    start: int
    end: int
    severity: Optional[str] = None

    def canonical(self) -> str:
        return self.term.lower()


def _truncate(text: str, limit: int = 320) -> str:
    return text[:limit]


def _normalize(text: str) -> str:
    # Normalize smart apostrophes and fancy quotes
    text = text.replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text.strip())


def _find_symptoms(text: str) -> List[SymptomCandidate]:
    lower = text.lower()
    found: List[SymptomCandidate] = []
    for pattern in SYMPTOM_PATTERNS:
        idx = 0
        pl = pattern.lower()
        while True:
            pos = lower.find(pl, idx)
            if pos == -1:
                break
            # Word boundary check
            before_ok = pos == 0 or not lower[pos - 1].isalnum()
            after_pos = pos + len(pl)
            after_ok = after_pos >= len(lower) or not lower[after_pos].isalnum()
            if before_ok and after_ok:
                found.append(SymptomCandidate(term=pattern, start=pos, end=after_pos))
            idx = pos + len(pl)
    # Deduplicate overlapping by keeping longest span
    found.sort(key=lambda c: (c.start, -len(c.term)))
    filtered: List[SymptomCandidate] = []
    last_end = -1
    for c in found:
        if c.start < last_end:
            # overlapping; skip shorter one (since sorted by -len)
            continue
        filtered.append(c)
        last_end = c.end
    return filtered


def _assign_severity_and_modifiers(symptoms: List[SymptomCandidate], text: str) -> Tuple[List[SymptomCandidate], List[str]]:
    modifiers_found = set(m.group(0).lower() for m in MODIFIER_REGEX.finditer(text))
    # severity per symptom: choose first severity adjective within window before term
    for s in symptoms:
        window_start = max(0, s.start - 30)
        window_text = text[window_start:s.start].lower()
        for sev in ["severe", "sudden", "crushing", "persistent"]:
            if re.search(r"\b" + re.escape(sev) + r"\b", window_text):
                s.severity = sev
                break
    return symptoms, sorted(modifiers_found)


def _parse_onset_minutes(text: str) -> Optional[int]:
    # Return earliest (first mention) converted to minutes
    for rx in ONSET_REGEXES:
        m = rx.search(text)
        if m:
            num = int(m.group(1))
            unit_part = m.group(2).lower()
            if unit_part.startswith("hour") or unit_part.startswith("hr"):
                return num * 60
            return num
    # fallback generic (avoid capturing blood pressure like 120/80)
    # We'll require a nearby time unit explicitly.
    m2 = GENERIC_DURATION_REGEX.search(text)
    if m2:
        num = int(m2.group(1))
        unit = m2.group(2).lower()
        if unit.startswith("hour") or unit.startswith("hr"):
            return num * 60
        return num
    return None


def _map_code(term: str) -> Optional[str]:
    key = term.lower()
    return SNOMED_MAP.get(key)


def _maybe_spacy_terms(text: str) -> Iterable[str]:
    if not _SPACY_NLP:
        return []
    try:
        doc = _SPACY_NLP(text)
        for ent in doc.ents:
            label = ent.label_.lower()
            if label in {"symptom", "disease", "problem", "sign_or_symptom"}:
                yield ent.text.lower()
    except Exception:
        return []


def _extract_age(text: str) -> Optional[int]:
    for rx in (AGE_REGEX, AGE_SIMPLE_PREFIX):
        m = rx.search(text)
        if m:
            try:
                age = int(m.group(1))
                if 0 < age < 125:
                    return age
            except ValueError:
                pass
    # Months old -> convert to years rounding down if >=12 months
    m2 = AGE_COMPACT_REGEX.search(text)
    if m2:
        try:
            months = int(m2.group(1))
            if 0 < months < 24:
                # represent infants <2 years as 0 (schema uses int years) else floor division
                return 0 if months < 12 else 1
        except ValueError:
            pass
    return None


def _extract_sex(text: str) -> Optional[str]:
    m = SEX_REGEX.search(text)
    if not m:
        return None
    token = m.group(1).lower()
    if token in {"male", "man", "boy", "gentleman"}:
        return "male"
    if token in {"female", "woman", "girl", "lady"}:
        return "female"
    return None


def _extract_location(text: str) -> Optional[str]:
    m = ANATOMY_REGEX.search(text)
    if m:
        return m.group(0).lower()
    return None


def _normalize_symptom(term: str) -> str:
    t = term.lower()
    return SYMPTOM_SYNONYMS.get(t, t)


def _parse_inline_vitals(text: str) -> Dict[str, int]:
    vitals = {}
    bp_match = BP_REGEX.search(text)
    if bp_match:
        try:
            syst, diast = int(bp_match.group(1)), int(bp_match.group(2))
            vitals["bp_systolic"] = syst
            vitals["bp_diastolic"] = diast
        except ValueError:
            pass
    hr_values = []
    for m in HR_REGEX.finditer(text):
        try:
            val = int(m.group(2))
            if 30 <= val <= 250:
                hr_values.append(val)
        except ValueError:
            continue
    if hr_values:
        vitals["hr"] = max(hr_values)
    spo2_values = []
    for m in SPO2_REGEX.finditer(text):
        groups = m.groups()
        raw = next((g for g in groups if g), None)
        if raw:
            try:
                val = int(raw)
                if 40 <= val <= 100:
                    spo2_values.append(val)
            except ValueError:
                continue
    if spo2_values:
        vitals["spo2"] = min(spo2_values)
    return vitals


def _informal_age(text: str) -> Optional[int]:
    # Try new pattern first
    m = AGE_ONLY_PATTERN.search(text)
    if m:
        try:
            age = int(m.group(1))
            if 1 < age < 120:
                return age
        except ValueError:
            pass
    # fallback to legacy heuristic
    m2 = AGE_INFORMAL_REGEX.search(text)
    if m2:
        try:
            age = int(m2.group(1))
            if 1 < age < 120:
                return age
        except ValueError:
            pass
    return None


# Simple negation detection: remove symptoms preceded by negation cues within window.
NEGATION_CUES = ["no", "denies", "without", "not", "absence of"]
NEGATION_REGEX = re.compile(r"\b(" + "|".join(re.escape(n) for n in NEGATION_CUES) + r")\b", re.IGNORECASE)

def _apply_negation_filter(symptoms: List[SymptomCandidate], text: str) -> List[SymptomCandidate]:
    lower = text.lower()
    filtered = []
    for s in symptoms:
        window_start = max(0, s.start - 25)
        window = lower[window_start:s.start]
        if NEGATION_REGEX.search(window):
            # skip negated symptom
            continue
        filtered.append(s)
    return filtered


def summarize_event(text: str, vitals: Optional[Dict] = None, history: Optional[List[str]] = None) -> Dict:
    """Summarize emergency event into structured clinical JSON dict.

    Parameters
    ----------
    text : str
        Free form input message.
    vitals : dict | None
        Optional vitals dictionary.
    history : list[str] | None
        Optional past medical history.
    """
    if not text:
        text = ""
    raw = _truncate(text)
    norm = _normalize(raw)

    symptoms = _find_symptoms(norm)
    # Add synonym-driven detection for tokens not explicitly in pattern list
    for syn, canon in SYMPTOM_SYNONYMS.items():
        if syn in norm.lower() and not any(s.canonical() == canon for s in symptoms):
            pos = norm.lower().find(syn)
            if pos != -1:
                symptoms.append(SymptomCandidate(term=canon, start=pos, end=pos + len(syn)))

    inline_vitals = _parse_inline_vitals(norm)

    # Extract informal age if not found by formal patterns
    formal_age = _extract_age(norm)
    informal_age = formal_age if formal_age is not None else _informal_age(norm)

    # Add informal symptom detections
    lower_norm = norm.lower()
    for phrase, (canonical, code) in INFORMAL_SYMPTOMS.items():
        if phrase in lower_norm and not any(s.canonical() == canonical for s in symptoms):
            pos = lower_norm.find(phrase)
            symptoms.append(SymptomCandidate(term=canonical, start=pos, end=pos + len(phrase)))
            # Ensure SNOMED mapping exists dynamically if not present
            if canonical not in SNOMED_MAP:
                SNOMED_MAP[canonical] = code

    # Apply negation filtering before severity assignment
    symptoms = _apply_negation_filter(symptoms, norm)

    symptoms, modifiers = _assign_severity_and_modifiers(symptoms, norm)

    # Severity inference: critical if severe hypotension or very low SpO2
    inferred_severity = None
    if inline_vitals.get("bp_systolic", 200) < 80 or inline_vitals.get("spo2", 101) < 85:
        inferred_severity = "critical"
    if inferred_severity:
        for s in symptoms:
            if not s.severity:
                s.severity = inferred_severity

    onset_minutes = _parse_onset_minutes(norm)

    symptom_entries = []
    for s in symptoms:
        canonical_term = _normalize_symptom(s.term)
        entry = {
            "term": canonical_term,
            "code": _map_code(canonical_term) or None,
            "severity": s.severity,
            "onset_minutes": onset_minutes,
        }
        symptom_entries.append(entry)

    # Remove duplicate identical symptom entries (same term)
    dedup = {}
    for e in symptom_entries:
        key = e["term"]
        if key not in dedup:
            dedup[key] = e
        else:
            # merge severity if missing
            if not dedup[key]["severity"] and e["severity"]:
                dedup[key]["severity"] = e["severity"]
            # keep earliest onset (they are same) -> already same
    symptom_entries = list(dedup.values())

    # Build output schema
    out = {
        "symptoms": symptom_entries,
        "vitals": None,
        "modifiers": modifiers,
        "history": history if history else [],
        "location": _extract_location(norm),
        "age": informal_age,
        "sex": _extract_sex(norm),
    }
    # Merge explicit vitals with inline parsed; inline takes precedence if more clinically suspicious
    combined_vitals = {}
    if vitals:
        allowed = {"hr", "bp_systolic", "bp_diastolic", "spo2"}
        combined_vitals.update({k: v for k, v in vitals.items() if k in allowed})
    # Overwrite with inline
    combined_vitals.update(inline_vitals)
    out["vitals"] = combined_vitals or None

    return out


if __name__ == "__main__":
    examples = [
        ("Severe chest pain and shortness of breath for 5 minutes.", {"hr": 120}, ["Hypertension"]),
        ("Patient fainted and is not responding", None, None),
        ("Headache since 2 hours", None, None),
        ("Profuse bleeding from arm for 10 min", {"bp_systolic": 110, "bp_diastolic": 70}, []),
    ]
    import json
    for txt, v, h in examples:
        print(json.dumps(summarize_event(txt, v, h), indent=2))
