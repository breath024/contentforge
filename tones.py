"""카피 톤 프리셋 — 같은 주제도 완전히 다른 화법으로.

톤 = 표지/본문 화법 가이드. 다중 테마(디자인)와 직교 → 디자인×톤 조합 폭발.
DEFAULT_AVOID(진부 클리셰)는 매 생성에 금지어로 투입해 "이거 모르면 손해" 류 반복 차단.
"""
from __future__ import annotations

DEFAULT = "hook"

TONES: dict[str, dict] = {
    "hook": {
        "label": "후킹·자극", "desc": "충격·반전·호기심으로 손 멈추게",
        "guide": ("표지는 충격/반전/호기심 자극. 단 매번 다른 방식으로 — 숫자·질문·반전·"
                  "금기·비교를 번갈아 쓰고 같은 후킹 패턴을 반복하지 말 것. 본문은 짧고 세게."),
    },
    "info": {
        "label": "정보·깔끔", "desc": "담백하게 핵심만, 신뢰감",
        "guide": ("표지는 과장 없이 명확한 가치 제시('~하는 법', '~ 총정리', '~ 체크리스트'). "
                  "본문은 바로 써먹는 정보 위주로 차분하고 정확하게."),
    },
    "story": {
        "label": "경험·스토리", "desc": "직접 해본 듯한 1인칭 내러티브",
        "guide": ("표지·본문을 1인칭 경험담 톤으로('내가 ~해보니', '3개월 만에', '퇴사하고 깨달은'). "
                  "솔직하고 생생하게, 구체적 숫자·디테일을 넣어라."),
    },
    "empathy": {
        "label": "공감·위로", "desc": "독자 속마음을 콕 집어 공감",
        "guide": ("표지는 독자의 속마음·상황을 콕 집어 공감('나만 그런 거 아니지?', "
                  "'퇴근하면 아무것도 하기 싫은 너에게'). 본문은 따뜻하고 부드럽게, 다그치지 말 것."),
    },
}

# 어떤 톤이든 항상 피할 진부 클리셰 (반복의 주범)
DEFAULT_AVOID = [
    "이거 모르면 손해", "이것만 알면", "90%가 모르는", "당신이 몰랐던",
    "지금 당장", "충격", "반드시 알아야 할", "절대 하지 마세요",
]


def get(preset: str | None) -> dict:
    return TONES.get(preset or DEFAULT, TONES[DEFAULT])


def guide(preset: str | None) -> str:
    return get(preset)["guide"]


def options() -> list[dict]:
    return [{"key": k, "label": t["label"], "desc": t["desc"]} for k, t in TONES.items()]
