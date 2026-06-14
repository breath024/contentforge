"""페르소나 = 계정 컨셉. ContentForge를 '운영대행 공장'으로 만드는 축.

페르소나 1개(니치/타겟/톤/브랜드/기본테마)를 정의하면 → 그 채널이 올릴
주제를 AI가 자동으로 뽑고 → 일괄 제작. 오파독의 '운영대행' 구조 그대로.
저장은 단일 JSON(personas.json). 외부 의존 없음.
"""
from __future__ import annotations
import json
import uuid
from pathlib import Path

import themes
import tones
from llm import generate_json, pick_model

ROOT = Path(__file__).parent
FILE = ROOT / "personas.json"


def load_all() -> list[dict]:
    if not FILE.exists():
        return []
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_all(items: list[dict]) -> None:
    FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def get(pid: str) -> dict | None:
    return next((p for p in load_all() if p.get("id") == pid), None)


def create(name: str, niche: str, target: str = "", tone: str = "",
           brand: str = "", theme: str = "", tone_preset: str = "") -> dict:
    p = {
        "id": "p_" + uuid.uuid4().hex[:8],
        "name": name.strip() or "이름없는 채널",
        "niche": niche.strip(),
        "target": target.strip() or "일반 대중",
        "tone": tone.strip() or "신뢰감 있고 친근하게, 어려운 말 안 씀",
        "brand": brand.strip() or "@my.page",
        "theme": theme if theme in themes.THEMES else themes.DEFAULT,
        "tone_preset": tone_preset if tone_preset in tones.TONES else tones.DEFAULT,
    }
    items = load_all()
    items.append(p)
    _save_all(items)
    return p


def update(pid: str, **fields) -> dict | None:
    items = load_all()
    for p in items:
        if p.get("id") == pid:
            for k in ("name", "niche", "target", "tone", "brand", "theme", "tone_preset"):
                if k in fields and fields[k] is not None:
                    p[k] = fields[k]
            _save_all(items)
            return p
    return None


def delete(pid: str) -> bool:
    items = load_all()
    new = [p for p in items if p.get("id") != pid]
    if len(new) == len(items):
        return False
    _save_all(new)
    return True


_TOPIC_PROMPT = """채널 컨셉: {niche}
타겟 독자: {target}
{trend}
이 채널이 올릴 인스타 카드뉴스 '주제' {n}개를 제안하라.
규칙: 저장을 부르는 구체적·실용적 주제. 서로 다른 각도로 다양하게(노하우/실수/비교/체크리스트/입문 등 섞어서).
각 주제는 그 자체로 카드뉴스 제목이 될 한 줄. 추상적 키워드 말고 완성된 주제문.
JSON으로만: {{"topics": ["주제1", "주제2", ...]}}"""


def suggest_topics(persona: dict, n: int = 10, references: list[str] | None = None,
                   model: str | None = None) -> list[str]:
    trend = ""
    if references:
        lines = "\n".join(f"  · {t}" for t in references[:8] if t)
        trend = ("\n[참고] 같은 분야 인기 콘텐츠 제목(각도만 참고, 베끼지 말 것):\n"
                 f"{lines}\n")
    prompt = _TOPIC_PROMPT.format(niche=persona.get("niche", ""),
                                  target=persona.get("target", ""), n=n, trend=trend)
    data = generate_json(prompt, model=model or pick_model(), temperature=0.9)
    topics = data.get("topics", [])
    # 문자열만, 중복 제거, 트림
    seen, out = set(), []
    for t in topics:
        if isinstance(t, str):
            t = t.strip()
            if t and t not in seen:
                seen.add(t)
                out.append(t)
    return out[:n]


if __name__ == "__main__":
    p = {"niche": "20-30대 재테크/투자 입문", "target": "사회초년생"}
    for t in suggest_topics(p, 8):
        print(" ·", t)
