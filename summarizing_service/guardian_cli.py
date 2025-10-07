#!/usr/bin/env python
"""GuardianAI NLP Severity CLI (legacy rule system removed)

Usage examples:
    python guardian_cli.py --text "Severe chest pain radiating left arm for 10 minutes hr 118"
    python guardian_cli.py --file input.txt
    python guardian_cli.py --train --data dataset.csv --text-col text --score-col severity_score

If model artifacts are missing, predictions will fail with a message advising training.
"""
from __future__ import annotations
import argparse, json, sys, os, traceback
from typing import Any, Dict

from modeling import get_model_wrapper, ModelNotTrained, MODEL_PATH, FEATURE_META_PATH, THRESHOLDS_PATH
import joblib  # type: ignore
import numpy as np
import csv


def _read_text_file(path: str) -> str:
    with open(path, 'r', encoding='utf-8') as f:
        return f.read().strip()

def _train(args) -> None:
    data_path = args.data
    if not data_path or not os.path.exists(data_path):
        print("--data dataset.csv required for training", file=sys.stderr)
        sys.exit(2)
    text_col = args.text_col
    score_col = args.score_col
    rows: list[dict] = []
    with open(data_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            if r.get(text_col) and r.get(score_col):
                rows.append(r)
    if not rows:
        print("No valid rows found in dataset.", file=sys.stderr)
        sys.exit(3)
    from modeling import SeverityModelWrapper, MODEL_DIR, FEATURE_META_PATH, THRESHOLDS_PATH
    import json as _json
    import sklearn.linear_model  # type: ignore
    wrapper = SeverityModelWrapper()
    # load spaCy pipeline lazily via ensure_loaded error path
    try:
        wrapper.ensure_loaded()
    except ModelNotTrained:
        # force spaCy load by accessing predict path on dummy
        if wrapper._nlp is None:
            from modeling import spacy
            if spacy is None:
                print("spaCy not installed", file=sys.stderr)
                sys.exit(4)
            try:
                wrapper._nlp = spacy.load("en_core_web_sm")
            except Exception:
                wrapper._nlp = spacy.blank("en")
    X_list = []
    y_list = []
    feat_names = None
    for r in rows:
        text = r[text_col].strip()
        vals, names, _summary = wrapper.build_feature_vector(text)
        X_list.append(vals)
        y_list.append(float(r[score_col]))
        if feat_names is None:
            feat_names = names
    if feat_names is None:
        print("Failed to derive feature names.", file=sys.stderr)
        sys.exit(5)
    X = np.array(X_list)
    y = np.array(y_list)
    model = sklearn.linear_model.Ridge(alpha=1.0)
    model.fit(X, y)
    MODEL_DIR.mkdir(exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    with open(FEATURE_META_PATH, 'w', encoding='utf-8') as f:
        json.dump({"feature_names": feat_names}, f)
    # derive thresholds from label distribution (quantiles) if not provided
    urgent_q = float(np.quantile(y, 0.4))
    critical_q = float(np.quantile(y, 0.75))
    with open(THRESHOLDS_PATH, 'w', encoding='utf-8') as f:
        json.dump({"urgent": urgent_q, "critical": critical_q}, f)
    print(f"Trained model saved. urgent={urgent_q:.2f} critical={critical_q:.2f}")


def main():
    parser = argparse.ArgumentParser(description="GuardianAI Summarizer + Triage CLI")
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument('--text', type=str, help='Raw narrative text input')
    group.add_argument('--file', type=str, help='Path to a text file with narrative')
    parser.add_argument('--train', action='store_true', help='Train severity model')
    parser.add_argument('--data', type=str, help='Path to CSV dataset for training')
    parser.add_argument('--text-col', type=str, default='text', help='Dataset text column name')
    parser.add_argument('--score-col', type=str, default='severity_score', help='Dataset severity score column name')
    parser.add_argument('--pretty', action='store_true', help='Pretty-print output JSON')

    args = parser.parse_args()

    if args.train:
        _train(args)
        return

    # Predict path
    raw_text = ''
    if args.file:
        try:
            raw_text = _read_text_file(args.file)
        except OSError as e:
            print(f"Error reading file: {e}", file=sys.stderr)
            sys.exit(2)
    else:
        raw_text = (args.text or '').strip()
    if not raw_text:
        print("No input text provided.", file=sys.stderr)
        sys.exit(3)
    wrapper = get_model_wrapper()
    try:
        res = wrapper.predict(raw_text)
    except ModelNotTrained:
        print("Model not trained. Use --train --data dataset.csv first.", file=sys.stderr)
        sys.exit(10)
    output = {
        "severity_score": res["severity_score"],
        "category": res["category"],
        "reasons": res["reasons"],
        "summary": res["summary"] | {"raw_description": raw_text},
    }

    if args.pretty:
        print(json.dumps(output, indent=2))
    else:
        print(json.dumps(output, separators=(',', ':')))

if __name__ == '__main__':  # pragma: no cover
    try:
        main()
    except Exception as exc:
        print("Unhandled error:", exc, file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
