import json
import urllib.request

BASE_URL = "http://localhost:8001"

EXAMPLE = (
    "Male 72 with crushing chest pain for 30 minutes, diaphoretic, BP 88/52, oxygen 89%."
)

def post_json(path: str, payload: dict, timeout: int = 10):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def test_basic_summary_shape():
    resp = post_json("/summarize", {"description": EXAMPLE})
    assert isinstance(resp.get("severity_score"), (int, float))
    assert 0 <= resp["severity_score"] <= 10
    assert isinstance(resp.get("summary"), dict)
    assert isinstance(resp.get("category"), str)
    assert resp["category"] in {"Critical", "Urgent", "Non-Urgent"}
    assert isinstance(resp.get("reasons"), list)
    assert resp["reasons"], "Expected at least one rationale"


def test_includes_raw_description():
    resp = post_json("/summarize", {"description": EXAMPLE})
    assert resp["summary"].get("raw_description"), "raw_description not echoed"
