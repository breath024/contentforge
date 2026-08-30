"""LLM 백엔드 래퍼 — Ollama(로컬, 무료) 우선, 실패 시 명확히 에러.

LLM 판정 패턴. 카드뉴스/숏폼 카피 생성용.
"""
from __future__ import annotations
import json
import urllib.request
import urllib.error

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
# 카피 품질 순: qwen2.5:14b > gemma3:27b > gemma3:4b. 있는 걸 자동 선택.
PREFERRED = ["qwen2.5:14b", "gemma3:27b", "gemma3:12b", "gemma3:4b"]


def _available_models() -> list[str]:
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags")
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def pick_model() -> str | None:
    have = _available_models()
    if not have:
        return None
    for p in PREFERRED:
        for h in have:
            if h == p or h.startswith(p.split(":")[0] + ":"):
                # 정확 일치 우선
                if h == p:
                    return h
    # 선호 prefix 매칭
    for p in PREFERRED:
        base = p.split(":")[0]
        for h in have:
            if h.startswith(base):
                return h
    return have[0]


def generate_json(prompt: str, model: str | None = None, temperature: float = 0.7) -> dict:
    """Ollama로 JSON 강제 생성. 모델 없으면 RuntimeError."""
    model = model or pick_model()
    if not model:
        raise RuntimeError(
            "Ollama에 모델이 없거나 서버가 안 떠있음. `ollama serve` + `ollama pull gemma3:4b` 확인."
        )
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": temperature},
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        resp = json.loads(r.read().decode("utf-8"))
    text = resp.get("response", "").strip()
    return json.loads(text)


if __name__ == "__main__":
    print("models:", _available_models())
    print("picked:", pick_model())
