# GuardianAI Summarizer & Triage

Hybrid rule + ML pipeline for transforming informal emergency narratives into structured clinical summaries and triage urgency scores.

## Modules

- `summarizer.py` – Extracts clinically relevant fields from raw text.
- `triage.py` – Assigns an urgency score (0–10) and category (Critical / Urgent / Non-Urgent).

## 1. Summarizer
`from summarizer import summarize_event`

Input: free-form text + optional vitals/history.
Output JSON keys:
```
{
  "symptoms": [{"term": str, "code": str|None, "severity": str|None, "onset_minutes": int|None}],
  "vitals": {"hr": int, "bp_systolic": int, "bp_diastolic": int, "spo2": int} | None,
  "modifiers": [str],
  "history": [str],
  "location": str|None,
  "age": int|None,
  "sex": str|None
}
```

Features:
- Informal phrase handling (e.g., "gasping for air", "could go out").
- Inline vital parsing (BP, HR, SpO₂) from narrative.
- Age, sex, anatomical location heuristics.
- Severity inference for critical physiology.

## 2. Triage
`from triage import triage_case`

Input: summarizer output.
Output:
```
{
  "urgency_score": float,    # 0.0–10.0
  "category": "Critical"|"Urgent"|"Non-Urgent",
  "reasons": [str],          # top rationale factors
  "model_confidence": float|None
}
```

### Deterministic Critical Overrides
Triggered if any:
- Systolic BP < 80
- SpO₂ < 85
- Unresponsive / unconscious / not responding / not breathing
- Seizure with severe/critical severity or multiple seizure indications
- Profuse or uncontrolled bleeding

Override assigns a score (default 9.5) and category `Critical`.

### ML & Heuristic Blend
If no critical override:
1. Attempt ML model (Ridge regressor) – trained on synthetic pseudo-labeled cases.
2. If unavailable or `SKIP_ML=True`, use heuristic scoring.
3. Post-calibration ensures chest pain + tachycardia (HR>100) is at least `Urgent` (>=4.0).

### Category Thresholds (configurable)
```
Critical: score >= 8.5
Urgent:   4.0 <= score < 8.5
Non-Urgent: score < 4.0
```

### Weight Configuration
`CONFIG['WEIGHTS']` controls contributions (e.g., chest pain weight, HR scaling, recalibration floor).

### Training
Invoke (optional):
```bash
python -c "import triage; triage.train_model()"
```
Artifacts:
- `triage_model.joblib`
- `triage_model_meta.json`

### Example
```python
from summarizer import summarize_event
from triage import triage_case

case = summarize_event("65 year old male severe chest pain radiating left arm for 10 minutes hr 118 spo2 95%")
triage = triage_case(case)
print(triage)
```

## Example Scenarios
| Scenario | Key Factors | Expected |
|----------|-------------|----------|
| Critical multi-system | BP 70/40, SpO₂ 82%, SOB | Critical (~9.5) |
| Chest pain + tachycardia | HR 110, stable vitals otherwise | Urgent (~4.3+) |
| Mild headache only | Normal vitals | Non-Urgent (~1.0) |

## Explainability
- Deterministic rules list direct reason strings.
- ML path returns approximate top contributors (coef * feature or feature importance).

## Extensibility Ideas
- Add SHAP for model explanation.
- Calibrate score to real outcome labels.
- Negative evidence parsing (e.g., "no chest pain").
- Confidence calibration using isotonic regression.

## Safety Notes
This system is a prototype. All outputs must be reviewed by licensed clinicians before operational use. Deterministic rules favor sensitivity over specificity for high-risk presentations.

## License
Add a license of your choice before distribution.
