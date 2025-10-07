import json
import sys
import urllib.request

URL = "http://localhost:8001/summarize"

EXAMPLE_TEXT = (
    "Bro, this guy is in a scary spot. He's only 46, came in gasping for air, skin cold and "
    "clammy, barely able to speak. His BP is crashing at 70/40, heart rate's shooting up past "
    "150, and his oxygen is sitting at 75% even with a mask on. He's confused, eyes rolling a bit, "
    "honestly looks like he could go out any second. Whole room's tense right now, everyone's scrambling."
)

def main():
    payload = json.dumps({"description": EXAMPLE_TEXT}).encode()
    req = urllib.request.Request(URL, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode()
            data = json.loads(raw)
    except Exception as e:
        print(f"Request failed: {e}")
        sys.exit(1)

    # Basic shape assertions
    missing = [k for k in ("severity_score", "summary", "category", "reasons") if k not in data]
    if missing:
        print(f"Missing expected keys: {missing}\nFull response: {json.dumps(data, indent=2)}")
        sys.exit(2)

    print("Severity Score:", data["severity_score"])
    print("Category:", data["category"])
    print("Reasons:")
    for r in data.get("reasons", []):
        print(" -", r)
    print("\nSummary excerpt keys:", list(data.get("summary", {}).keys())[:12])
    print("\nFull JSON (pretty):")
    print(json.dumps(data, indent=2))

if __name__ == "__main__":
    main()
