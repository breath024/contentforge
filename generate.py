"""주제 한 줄 → 인스타 카드뉴스 슬라이드 기획(JSON).

오파독식 '조회수 나올 수밖에 없는 구조' = 표지 훅 강하게 → 정보 포인트 →
저장/팔로우 CTA. LLM이 카피를 쓰고, 우리는 구조를 강제한다.
각 슬라이드에 배경 사진 검색용 영문 키워드(image_query)도 함께 뽑는다.
"""
from __future__ import annotations
import json
import re
from llm import generate_json, pick_model
import tones
import quality
import verify

PROMPT_TMPL = """당신은 인스타에서 수십만 저장을 받는 카드뉴스 카피라이터다.
주제: "{topic}"
타겟/말투: {tone}
콘텐츠 톤: {tone_guide}
{facts}{benchmark}{avoid}
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


def _facts_block(facts: str | None) -> str:
    """사용자가 준 제품 사실. 모델은 제품을 모르니 이걸 안 주면 지어낸다(2026-09-11).

    tone 칸에 욱여넣어도 대개 무시됐다 → 프롬프트의 독립 블록으로 올리고,
    '여기 없는 수치는 쓰지 마라'를 같이 못 박는다.
    """
    facts = (facts or "").strip()
    if not facts:
        return ""
    nl = chr(10)
    return (nl + "[제품 사실 — 여기 적힌 것만 사실로 쓸 것]" + nl + facts + nl
            + "[중요] 위에 없는 수치(퍼센트·금액·기간·인원·날짜·순위)는 절대 지어내지 마라. "
            "모르면 수치 없이 장면과 행동으로 써라. 설명 문장을 그대로 옮겨 적지 말고 "
            "사장님/사용자가 겪는 말로 바꿔 써라." + nl)


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
    facts: str | None = None,
    self_fix: bool = True,
    verify_claims: bool = False,
    on_verify=None,
) -> dict:
    prompt = PROMPT_TMPL.format(
        topic=topic, tone=tone or DEFAULT_TONE, tone_guide=tones.guide(tone_preset),
        n=n, last=n - 1, facts=_facts_block(facts),
        benchmark=_benchmark_block(references), avoid=_avoid_block(avoid))
    # qwen3 가 가끔 생성 없이 곧바로 "{}" 를 낸다(2026-09-11 실측, 0.4초 만에 빈 응답).
    # 다시 물으면 대개 제대로 나온다 → 빈 응답이면 두 번까지 재시도.
    for _ in range(3):
        data = generate_json(prompt, model=model, temperature=0.9)
        slides = data.get("slides", [])
        if slides:
            break
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
    if facts:
        data["facts"] = facts          # 편집기의 '카피 다시'도 같은 사실을 보게 저장
    if self_fix:
        _self_fix(data, topic, model, facts=facts)
    if facts:
        _facts_fix(data, topic, model, facts)
    if verify_claims:
        _verify_fix(data, topic, model, on_verify=on_verify)
    return data


def _verify_fix(cards: dict, topic: str, model: str | None, rounds: int = 2,
                on_verify=None) -> dict:
    """근거 없는 수치를 웹검색으로 잡아 그 슬라이드만 다시 쓴다.

    규칙 게이트(_self_fix)는 형식만 본다 → "35%가 잘못 입력했다" 같은 지어낸 수치가
    통과했다. 여긴 바깥 근거로 대조해서(verify.py) 근거 못 찾은 수치를 걷어낸다.
    재생성은 수치를 새로 지어내지 못하게 막은 프롬프트를 쓴다.
    """
    for rd in range(rounds):
        if on_verify:
            on_verify("checking", rd)
        rep = verify.check_cards(cards, topic)
        bad = rep["slides"]
        if not bad:
            break
        slides = cards["slides"]
        used = [(s.get("headline") or "").strip() for s in slides]
        for idx, info in bad.items():
            if on_verify:
                on_verify("regen", idx, info.get("unverified", []))
            role = slides[idx].get("role", "point")
            try:
                fresh = regen_slide(topic, role, used, model=model, no_numbers=True)
            except Exception:
                continue
            slides[idx]["headline"] = fresh.get("headline", slides[idx].get("headline"))
            slides[idx]["body"] = fresh.get("body", slides[idx].get("body"))
            if fresh.get("image_query"):
                slides[idx]["image_query"] = fresh["image_query"]
            slides[idx].pop("sources", None)
            used.append((fresh.get("headline") or "").strip())

    # 마지막 빗질(검색 없음, 결정적).
    # 웹검색은 호출마다 결과가 달라서 같은 문장이 통과했다 걸렸다 한다 → 라운드만으로는
    # '근거 없는 수치가 안 남는다'를 보장 못 한다. 여기서 불변식을 강제한다:
    #   수치가 남아 있으면 반드시 근거(sources)가 붙어 있다.
    slides = cards["slides"]
    used = [(s.get("headline") or "").strip() for s in slides]
    for idx, s in enumerate(slides):
        claims = verify.find_claims(f"{s.get('headline') or ''} {s.get('body') or ''}")
        if not claims:
            continue
        backed = {c["claim"] for c in s.get("sources") or []}
        if all(c in backed for c in claims):
            continue
        if on_verify:
            on_verify("regen", idx, [c for c in claims if c not in backed])
        try:
            fresh = regen_slide(topic, s.get("role", "point"), used,
                                model=model, no_numbers=True)
        except Exception:
            continue
        s["headline"] = fresh.get("headline", s.get("headline"))
        s["body"] = fresh.get("body", s.get("body"))
        if fresh.get("image_query"):
            s["image_query"] = fresh["image_query"]
        s.pop("sources", None)
        used.append((fresh.get("headline") or "").strip())
    return cards


_NUM_RE = re.compile(r"\d[\d,.]*")


def _stray_numbers(text: str, facts: str) -> list[str]:
    """사실 목록에 없는 숫자. '3단계'·'2장' 같은 구조 표현은 뺀다."""
    allowed = {n.replace(",", "") for n in _NUM_RE.findall(facts or "")}
    out = []
    for m in _NUM_RE.finditer(text or ""):
        if verify._SAFE_CONTEXT.match(text[m.start():m.end() + 4]):
            continue
        n = m.group(0).rstrip(".,").replace(",", "")
        if n and n not in allowed and n not in out:
            out.append(n)
    return out


def _facts_fix(cards: dict, topic: str, model: str | None, facts: str,
               tries: int = 3) -> dict:
    """사실을 줬는데 그 안에 없는 숫자('지원금 놓친 가게 300만 개')를 쓴 장을 다시 쓴다.

    find_claims는 %·원·명 같은 단위만 봐서 '300만 개'를 놓쳤다 → 사실 대조는 숫자 전체로 한다.
    """
    slides = cards["slides"]
    used = [(s.get("headline") or "").strip() for s in slides]
    for s in slides:
        for _ in range(tries):
            if not _stray_numbers(f"{s.get('headline') or ''} {s.get('body') or ''}", facts):
                break
            try:
                fresh = regen_slide(topic, s.get("role", "point"), used, model=model,
                                    no_numbers=True, facts=facts)
            except Exception:
                break
            s["headline"] = fresh.get("headline", s.get("headline"))
            s["body"] = fresh.get("body", s.get("body"))
            if fresh.get("image_query"):
                s["image_query"] = fresh["image_query"]
            used.append((fresh.get("headline") or "").strip())
    return cards


def _self_fix(cards: dict, topic: str, model: str | None, rounds: int = 2,
              facts: str | None = None) -> dict:
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
                fresh = regen_slide(topic, role, used, model=model, facts=facts)
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


# 근거 대조에서 걸린 장을 다시 쓸 때. 여기서 또 수치를 지어내면 검증이 무의미해진다.
_NO_NUMBERS = (
    "\n[중요] 통계·비율·금액·날짜·기한 같은 구체적 수치는 절대 쓰지 마라. "
    "확인되지 않은 숫자를 지어내는 것보다 수치 없이 행동을 구체적으로 지시하는 편이 낫다. "
    "'무엇을 어떻게 하라'로 써라.")


def regen_slide(topic: str, role: str, used_headlines: list[str],
                model: str | None = None, no_numbers: bool = False,
                facts: str | None = None) -> dict:
    """카드 1장의 카피만 새로 뽑는다(편집기 '다시 생성')."""
    hsize = "12자 내외" if role == "cover" else "6~10자 소제목"
    prompt = REGEN_TMPL.format(
        topic=topic, role_desc=_ROLE_DESC.get(role, _ROLE_DESC["point"]),
        used=", ".join(h for h in used_headlines if h) or "(없음)", hsize=hsize,
    )
    prompt += _facts_block(facts)
    if no_numbers:
        prompt += _NO_NUMBERS
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
