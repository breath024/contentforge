"""카드뉴스 디자인 테마 — '사람이 만든 것'처럼 보이게 하는 핵심.

각 테마 = CSS 변수 세트(색/폰트/타이포 스케일) + 사진 사용 여부.
사진 없이 타이포만으로 강한 테마(impact/vivid)를 둬서 무키 환경에서도 휘어잡는다.
새 테마는 여기에 dict 하나 추가하면 끝(렌더 코드 안 건드림).
"""
from __future__ import annotations

DEFAULT = "editorial"

# Google Fonts 한글 디스플레이/세리프 + Pretendard
FONT_LINKS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css">'
    '<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/webfontworld/gmarket/GmarketSans.css">'
    '<link href="https://fonts.googleapis.com/css2?'
    'family=Black+Han+Sans&family=Hahmlet:wght@700;800;900&'
    'family=Gowun+Dodum&display=swap" rel="stylesheet">'
)

THEMES: dict[str, dict] = {
    "editorial": {
        "label": "매거진", "desc": "또렷한 세리프 + 사진, 세련된 여백", "photo": True,
        "vars": {
            "--font": "'Hahmlet','Nanum Myeongjo',serif",
            "--body-font": "'Pretendard',sans-serif",
            "--accent": "#b91c1c",
            "--cover-bg": "#161616", "--cover-fg": "#ffffff",
            "--point-bg": "#faf8f4", "--point-fg": "#1a1a1a", "--point-sub": "#6b6357",
            "--cta-bg": "linear-gradient(135deg,#1a1a1a,#2d2424)", "--cta-fg": "#ffffff",
            "--cover-size": "90px", "--point-size": "70px", "--cta-size": "82px",
        },
    },
    "impact": {
        "label": "임팩트", "desc": "초굵은 타이포, 검정+형광 (사진 없음)", "photo": False,
        "vars": {
            "--font": "'Black Han Sans',sans-serif",
            "--body-font": "'Pretendard',sans-serif",
            "--accent": "#facc15",
            "--cover-bg": "#0a0a0a", "--cover-fg": "#ffffff",
            "--point-bg": "#0a0a0a", "--point-fg": "#ffffff", "--point-sub": "#a3a3a3",
            "--cta-bg": "linear-gradient(135deg,#facc15,#eab308)", "--cta-fg": "#0a0a0a",
            "--cover-size": "112px", "--point-size": "86px", "--cta-size": "100px",
        },
    },
    "vivid": {
        "label": "비비드", "desc": "또렷한 고딕, 비비드 그라데이션 (사진 없음)", "photo": False,
        "vars": {
            "--font": "'GmarketSans','Pretendard',sans-serif",
            "--body-font": "'Pretendard',sans-serif",
            "--accent": "#fde047",
            "--cover-bg": "linear-gradient(135deg,#7c3aed,#db2777)", "--cover-fg": "#ffffff",
            "--point-bg": "linear-gradient(160deg,#6d28d9,#9333ea)", "--point-fg": "#ffffff",
            "--point-sub": "#e9d5ff",
            "--cta-bg": "linear-gradient(135deg,#f43f5e,#ec4899)", "--cta-fg": "#ffffff",
            "--cover-size": "100px", "--point-size": "78px", "--cta-size": "90px",
        },
    },
    "minimal": {
        "label": "미니멀", "desc": "절제된 여백 + 사진, 고급감", "photo": True,
        "vars": {
            "--font": "'Pretendard',sans-serif",
            "--body-font": "'Pretendard',sans-serif",
            "--accent": "#4f46e5",
            "--cover-bg": "#0f172a", "--cover-fg": "#ffffff",
            "--point-bg": "#ffffff", "--point-fg": "#0f172a", "--point-sub": "#64748b",
            "--cta-bg": "#4f46e5", "--cta-fg": "#ffffff",
            "--cover-size": "86px", "--point-size": "66px", "--cta-size": "78px",
        },
    },
}


def get(theme: str | None) -> dict:
    return THEMES.get(theme or DEFAULT, THEMES[DEFAULT])


def css_vars(theme: str | None) -> str:
    return ";".join(f"{k}:{v}" for k, v in get(theme)["vars"].items())


def uses_photo(theme: str | None) -> bool:
    return get(theme)["photo"]


def options() -> list[dict]:
    return [{"key": k, "label": t["label"], "desc": t["desc"], "photo": t["photo"]}
            for k, t in THEMES.items()]
