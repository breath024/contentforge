"""주제 한 줄 → 인스타 카드뉴스 슬라이드 기획(JSON).

오파독식 '조회수 나올 수밖에 없는 구조' = 표지 훅 강하게 → 정보 포인트 →
저장/팔로우 CTA. LLM이 카피를 쓰고, 우리는 구조를 강제한다.
각 슬라이드에 배경 사진 검색용 영문 키워드(image_query)도 함께 뽑는다.
"""
from __future__ import annotations
import json
from llm import generate_json, pick_model
import tones
import quality

PROMPT_TMPL = """당신은 인스타에서 수십만 저장을 받는 카드뉴스 카피라이터다.
주제: "{topic}"
타겟/말투: {tone}
콘텐츠 톤: {tone_guide}
{benchmark}{avoid}
이 주제로 '스크롤을 멈추고 저장하게 만드는' 카드뉴스 {n}장을 기획하라.

[규칙]
- 1장(cover): 위 '콘텐츠 톤'에 맞는 표지 헤드라인 12자 내외. 손이 멈추되 진부한
  클리셰·상투어는 절대 금지. 이 주제만의 구체적인 각도로.
- 2~{last}장(point): 한 장 = 핵심 1개. headline은 6~10자 소제목,
  body는 바로 써먹는 한 문장(35자 내외). 두루뭉술 금지, 행동/숫자 구체.
- 마지막 장(cta): 저장·팔로우를 콕 집어 유도.
- 각 슬라이드에 image_query: 배경사진 영문 검색어 1~2단어.

과장광고·이모지 금지. 한국어. 아래 JSON 스키마로만 답하라:
{{"topic": "...", "slides": [
  {{"role": "cover", "headline": "표지", "body": "한 줄 부제", "image_query": "english keywords"}},
  {{"role": "point", "headline": "소제목", "body": "한 문장", "image_query": "english keywords"}},
  {{"role": "cta", "headline": "마무리", "body": "행동 유도 한 줄", "image_query": "english keywords"}}
]}}"""


def _benchmark_block(references: list[str] | None) -> str:
    if not references:
        return ""
    lines = "\n".join(f"  · {t}" for t in references[:8] if t)
    return ("\n[벤치마킹] 같은 주제로 조회수 잘 나온 실제 콘텐츠 제목들이다. "
            "후킹 각도·표현을 참고하되 그대로 베끼지 말고 카드뉴스에 맞게 변형하라:\n"
            f"{lines}\n")


DEFAULT_TONE = "20-30대, 정보형, 단정하고 신뢰감 있게"


def _avoid_block(avoid: list[str] | None) -> str:
    items: list[str] = []
    for a in list(tones.DEFAULT_AVOID) + list(avoid or []):
        if a and a not in items:
            items.append(a)
    if not items:
        return ""
    return ("\n[회피] 다음 표현·패턴은 진부하거나 이미 썼으니 절대 쓰지 말고, "
            "특히 표지를 이것들과 확실히 다르게 하라:\n  " + ", ".join(items[:24]) + "\n")


def make_cards(
    topic: str,
    n: int = 8,
    tone: str | None = None,
    model: str | None = None,
    references: list[str] | None = None,
    tone_preset: str | None = None,
    avoid: list[str] | None = None,
    self_fix: bool = True,
) -> dict:
    prompt = PROMPT_TMPL.format(
        topic=topic, tone=tone or DEFAULT_TONE, tone_guide=tones.guide(tone_preset),
        n=n, last=n - 1, benchmark=_benchmark_block(references),
        avoid=_avoid_block(avoid))
    data = generate_json(prompt, model=model, temperature=0.9)
    slides = data.get("slides", [])
    if not slides:
        raise RuntimeError(f"슬라이드가 비었음. LLM 응답: {data}")
    # role 보정: 첫 장 cover, 끝 장 cta 강제
    slides[0]["role"] = "cover"
    slides[-1]["role"] = "cta"
    for s in slides[1:-1]:
        s["role"] = "point"
    for s in slides:
        s.setdefault("image_query", topic)
    data["slides"] = slides
    data.setdefault("topic", topic)
    if self_fix:
        _self_fix(data, topic, model)
    return data


def _self_fix(cards: dict, topic: str, model: str | None, rounds: int = 2) -> dict:
    """규칙 위반(글자수/빈칸/클리셰/중복) 슬라이드만 재생성으로 교정. 정확·빠른 게이트."""
    for _ in range(rounds):
        rep = quality.check_cards(cards)
        bad = rep["slides"]
        if not bad:
            break
        slides = cards["slides"]
        used = [(s.get("headline") or "").strip() for s in slides]
        for idx in bad:
            role = slides[idx].get("role", "point")
            try:
                fresh = regen_slide(topic, role, used, model=model)
            except Exception:
                continue
            slides[idx]["headline"] = fresh.get("headline", slides[idx].get("headline"))
            slides[idx]["body"] = fresh.get("body", slides[idx].get("body"))
            if fresh.get("image_query"):
                slides[idx]["image_query"] = fresh["image_query"]
            used.append((fresh.get("headline") or "").strip())
    return cards


REGEN_TMPL = """인스타 카드뉴스의 한 장을 새로 써라.
주제: "{topic}"
이 장의 역할: {role_desc}
이미 쓴 다른 장들(겹치지 말 것): {used}

규칙: headline은 {hsize}, body는 한 문장(35자 내외) 구체적으로. 과장·이모지 금지. 한국어.
JSON으로만: {{"headline":"...","body":"...","image_query":"english keywords"}}"""

_ROLE_DESC = {
    "cover": "표지 후킹 — 숫자/손해회피/반전 중 하나로 손이 멈추게",
    "point": "정보 포인트 한 개 — 바로 써먹는 한 가지",
    "cta": "마무리 — 저장·팔로우를 콕 집어 유도",
}


def regen_slide(topic: str, role: str, used_headlines: list[str],
                model: str | None = None) -> dict:
    """카드 1장의 카피만 새로 뽑는다(편집기 '다시 생성')."""
    hsize = "12자 내외" if role == "cover" else "6~10자 소제목"
    prompt = REGEN_TMPL.format(
        topic=topic, role_desc=_ROLE_DESC.get(role, _ROLE_DESC["point"]),
        used=", ".join(h for h in used_headlines if h) or "(없음)", hsize=hsize,
    )
    data = generate_json(prompt, model=model, temperature=0.9)
    data["role"] = role
    data.setdefault("image_query", topic)
    return data


if __name__ == "__main__":
    import sys
    topic = sys.argv[1] if len(sys.argv) > 1 else "직장인 점심 10분 스트레칭"
    print(f"[model] {pick_model()}")
    print(f"[topic] {topic}")
    cards = make_cards(topic)
    print(json.dumps(cards, ensure_ascii=False, indent=2))
