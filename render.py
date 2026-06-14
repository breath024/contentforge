"""슬라이드 JSON → 1080x1350 카드 HTML → Chrome 헤드리스 PNG.

테마 엔진(themes.py): 공통 레이아웃 CSS가 CSS 변수(--cover-bg, --font ...)를
참조하고, 테마는 변수 세트만 주입한다. 사진 on/off는 body 클래스로 분기.
  cover/cta = 풀블리드 (사진 위 오버레이 or 단색/그라데이션) + 하단정렬 타이포
  point     = 사진 테마면 상단밴드+패널, 무사진이면 풀컬러 중앙 타이포
"""
from __future__ import annotations
import html
import json
import shutil
import subprocess
from pathlib import Path

from images import fetch_images
import themes

W, H = 1080, 1350

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]


def find_chrome() -> str:
    for c in CHROME_CANDIDATES:
        if Path(c).exists():
            return c
    found = shutil.which("chrome") or shutil.which("msedge")
    if found:
        return found
    raise RuntimeError("Chrome/Edge를 못 찾음. PNG 추출 불가.")


def _file_uri(p: Path) -> str:
    return "file:///" + str(Path(p).resolve()).replace("\\", "/")


# 공통 레이아웃 — 모든 색/폰트/크기는 var()로 테마에서 주입
LAYOUT_CSS = """
*{margin:0;padding:0;box-sizing:border-box;}
html,body{width:1080px;height:1350px;overflow:hidden;}
.card{position:relative;width:1080px;height:1350px;overflow:hidden;
  font-family:var(--body-font);}
.bg{position:absolute;inset:0;background-size:cover;background-position:center;}
.num{position:absolute;top:62px;right:74px;font-size:30px;font-weight:800;z-index:6;opacity:.8;}
.badge{position:absolute;top:70px;left:78px;font-size:26px;font-weight:800;
  letter-spacing:3px;z-index:6;color:var(--accent);}
.content{position:absolute;left:0;right:0;z-index:3;padding:0 78px;
  display:flex;flex-direction:column;}
.bar{width:104px;height:13px;background:var(--accent);border-radius:7px;margin-bottom:34px;}
.headline{font-family:var(--font);font-weight:800;line-height:1.16;letter-spacing:-1px;}
.body{font-family:var(--body-font);font-weight:500;line-height:1.55;margin-top:30px;}
.foot{position:absolute;bottom:54px;font-size:26px;font-weight:600;opacity:.62;z-index:6;}

/* ===== COVER / CTA : 풀블리드, 텍스트 하단정렬 ===== */
.cover{background:var(--cover-bg);color:var(--cover-fg);}
.cta{background:var(--cta-bg);color:var(--cta-fg);}
.cover .content,.cta .content{bottom:140px;}
.cover .headline{font-size:var(--cover-size);}
.cta .headline{font-size:var(--cta-size);}
.cover .body,.cta .body{font-size:42px;opacity:.9;}
.cover .foot{right:78px;color:var(--cover-fg);}
.cta .foot{right:78px;color:var(--cta-fg);}
.cta .badge{color:var(--cta-fg);opacity:.75;}
.has-photo .bg::after{content:'';position:absolute;inset:0;
  background:linear-gradient(180deg,rgba(0,0,0,.28) 0%,rgba(0,0,0,.82) 82%);}

/* ===== POINT ===== */
.point{background:var(--point-bg);color:var(--point-fg);}
.point .headline{font-size:var(--point-size);}
.point .body{font-size:44px;color:var(--point-sub);}
.point .foot{left:78px;color:var(--point-sub);}
/* 사진 테마: 상단 밴드 + 하단 패널 */
.point.has-photo .bg{height:44%;}
.point.has-photo .bg::after{background:linear-gradient(180deg,
  rgba(0,0,0,.2) 0%,rgba(0,0,0,0) 55%,var(--point-bg) 100%);}
.point.has-photo .content{top:44%;bottom:0;justify-content:center;padding-bottom:70px;}
.point.has-photo .badge{color:#fff;text-shadow:0 2px 14px rgba(0,0,0,.6);}
/* 무사진 테마: 풀컬러 중앙 타이포 */
.point.no-photo .content{top:0;bottom:0;justify-content:center;}
"""

PAGE = ("<!doctype html><html lang=ko><head><meta charset=utf-8>{fonts}"
        "<style>{layout}</style></head><body>"
        "<div class=\"card {cls}\" style=\"{vars}\">{inner}</div></body></html>")


def _fit_px(base: int, text: str, max_lines: int = 3, avail: int = 912) -> int:
    """글자 수로 줄 수를 추정해 max_lines를 넘으면 폰트를 줄인다(넘침/답답함 방지)."""
    n = len(text.strip())
    if n == 0:
        return base
    per_line = max(1.0, avail / base)          # 기본 폰트로 한 줄 글자수(한글 기준)
    if n / per_line <= max_lines:
        return base
    return max(int(base * 0.5), min(base, int(avail * max_lines / n)))


def _card_html(slide: dict, idx: int, total: int, brand: str,
               img: Path | None, theme: str) -> str:
    role = slide.get("role", "point")
    photo = themes.uses_photo(theme) and img is not None
    cls = f"{role} {'has-photo' if photo else 'no-photo'}"
    headline_raw = slide.get("headline", "")
    headline = html.escape(headline_raw).replace("\n", "<br>")
    tvars = themes.get(theme)["vars"]
    skey = {"cover": "--cover-size", "cta": "--cta-size"}.get(role, "--point-size")
    base_h = int(str(tvars.get(skey, "70px")).replace("px", "").strip())
    fit_h = _fit_px(base_h, headline_raw, 3)
    body = slide.get("body", "").strip()
    body_html = f'<div class="body">{html.escape(body)}</div>' if body else ""
    badge = {"cover": "CONTENTFORGE", "cta": "SAVE · FOLLOW"}.get(role, "POINT")
    foot = "← 넘겨서 보기" if role == "cover" else brand
    bg = (f'<div class="bg" style="background-image:url(\'{_file_uri(img)}\')"></div>'
          if photo else "")
    inner = (
        f'{bg}<div class="num">{idx}/{total}</div>'
        f'<div class="badge">{badge}</div>'
        f'<div class="content"><div class="bar"></div>'
        f'<div class="headline" style="font-size:{fit_h}px">{headline}</div>{body_html}</div>'
        f'<div class="foot">{foot}</div>'
    )
    return PAGE.format(fonts=themes.FONT_LINKS, layout=LAYOUT_CSS,
                       cls=cls, vars=themes.css_vars(theme), inner=inner)


def _shoot(chrome: str, html_path: Path, png_path: Path) -> bool:
    cmd = [
        chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--no-sandbox", f"--screenshot={png_path.resolve()}",
        f"--window-size={W},{H}", "--default-background-color=00000000",
        # 폰트(Google Fonts) 로딩 대기 — 웹폰트 깨짐 방지
        "--virtual-time-budget=2500", "--run-all-compositor-stages-before-draw",
        _file_uri(html_path),
    ]
    subprocess.run(cmd, capture_output=True, timeout=60)
    return png_path.exists()


def img_path_for(out_dir: str | Path, i: int) -> Path | None:
    p = Path(out_dir) / "img" / f"img_{i:02d}.jpg"
    return p if p.exists() else None


def render_card(slide: dict, i: int, total: int, out_dir: str | Path,
                brand: str = "@contentforge", img: Path | None = None,
                chrome: str | None = None, theme: str = themes.DEFAULT) -> Path | None:
    out = Path(out_dir)
    chrome = chrome or find_chrome()
    html_path = out / f"card_{i:02d}.html"
    png_path = out / f"card_{i:02d}.png"
    html_path.write_text(_card_html(slide, i, total, brand, img, theme), encoding="utf-8")
    return png_path if _shoot(chrome, html_path, png_path) else None


def render(cards: dict, out_dir: str | Path, brand: str = "@contentforge",
           with_images: bool = True, on_progress=None,
           theme: str | None = None) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    theme = theme or cards.get("theme") or themes.DEFAULT
    cards["theme"] = theme
    slides = cards["slides"]
    total = len(slides)
    if on_progress:
        on_progress("images", 0, total)
    # 무사진 테마는 이미지 안 받음 → 다운로드/용량 0
    imgs: dict[int, Path] = ({} if not themes.uses_photo(theme)
                             else fetch_images(slides, out) if with_images else {})
    chrome = find_chrome()
    pngs: list[Path] = []
    for i, slide in enumerate(slides, 1):
        png = render_card(slide, i, total, out, brand, imgs.get(i), chrome, theme)
        if on_progress:
            on_progress("render", i, total)
        if png:
            pngs.append(png)
            print(f"  [{i}/{total}] {slide.get('role'):5} → {png.name}")
        else:
            print(f"  [{i}/{total}] PNG 실패: {slide.get('headline')}")
    (out / "slides.json").write_text(
        json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return pngs


if __name__ == "__main__":
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else "out/slides.json"
    th = sys.argv[2] if len(sys.argv) > 2 else None
    data = json.loads(Path(src).read_text(encoding="utf-8"))
    pngs = render(data, "out", theme=th)
    print(f"\n{len(pngs)}장 생성 완료 → out/")
