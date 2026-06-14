"""품질 게이트 — 사람 검수 없이 도구가 스스로 거른다.

호윤 원칙: 컴퓨터의 강점 = 정확·빠른 반복 검증. 그래서 규칙으로 잡히는 건
LLM 없이 즉시 잡는다(글자수·슬라이드수·빈칸·클리셰). 미달 슬라이드는 재생성.
주관 품질(후킹·구체성)은 별도 LLM 평가 층(다음 단계)에서.
"""
from __future__ import annotations
import tones

# 공백 제외 글자수 기준 (한글 카드뉴스 가독 범위)
LIMITS = {
    "cover": {"head_max": 16, "body_max": 40},
    "cta":   {"head_max": 16, "body_max": 40},
    "point": {"head_max": 14, "body_max": 45},
}


def clen(s: str | None) -> int:
    return len((s or "").replace(" ", ""))


def check_slide(slide: dict) -> list[str]:
    """슬라이드 1장의 규칙 위반 목록(비었으면 통과)."""
    role = slide.get("role", "point")
    lim = LIMITS.get(role, LIMITS["point"])
    issues: list[str] = []
    h = (slide.get("headline") or "").strip()
    b = (slide.get("body") or "").strip()
    if not h:
        issues.append("headline 비었음")
    elif clen(h) > lim["head_max"]:
        issues.append(f"headline 너무 김 ({clen(h)}>{lim['head_max']}자)")
    if role != "cover" and not b:
        issues.append("body 비었음")           # cover 부제는 선택
    if b and clen(b) > lim["body_max"]:
        issues.append(f"body 너무 김 ({clen(b)}>{lim['body_max']}자)")
    for c in tones.DEFAULT_AVOID:
        if c in h:
            issues.append(f"클리셰 '{c}'")
    return issues


def check_cards(cards: dict, want_n: int | None = None) -> dict:
    """덱 전체 검증 → {ok, slides:{idx:[issues]}, deck:[issues]}."""
    slides = cards.get("slides", [])
    deck: list[str] = []
    if want_n and len(slides) != want_n:
        deck.append(f"슬라이드 수 {len(slides)} (요청 {want_n})")
    if not slides:
        deck.append("슬라이드 없음")
    # 표지 중복(배치/단발 모두 표지 똑같으면 티남)
    heads = [(s.get("headline") or "").strip() for s in slides]
    if len(heads) != len(set(heads)):
        deck.append("중복 헤드라인 존재")
    per: dict[int, list[str]] = {}
    for i, s in enumerate(slides):
        iss = check_slide(s)
        if iss:
            per[i] = iss
    return {"ok": not per and not deck, "slides": per, "deck": deck}


if __name__ == "__main__":
    sample = {"slides": [
        {"role": "cover", "headline": "이거 모르면 손해 보는 재테크의 모든 것 총정리", "body": ""},
        {"role": "point", "headline": "복리", "body": ""},
        {"role": "cta", "headline": "저장하세요", "body": "팔로우도"},
    ]}
    import json
    print(json.dumps(check_cards(sample, want_n=4), ensure_ascii=False, indent=2))
