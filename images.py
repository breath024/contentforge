"""카드 배경 사진 조달.

우선순위:
1) PEXELS_API_KEY 있으면 → 주제 영문 키워드로 실사 검색 (무료, 한국어/영문 OK)
2) 키 없으면 → picsum.photos 시드 기반 (무키, 즉시. 주제무관이지만 '이미지 들어감' 증명)
다운로드해서 로컬 파일로 두고 render가 file://로 합성한다 (재현성 + 오프라인 렌더).
"""
from __future__ import annotations
import hashlib
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

PEXELS_KEY = os.environ.get("PEXELS_API_KEY", "").strip()
W, H = 1080, 1350


def _pexels_search(query: str) -> str | None:
    """검색어로 세로형 사진 1장 URL."""
    if not PEXELS_KEY:
        return None
    url = (
        "https://api.pexels.com/v1/search?"
        + urllib.parse.urlencode(
            {"query": query, "orientation": "portrait", "per_page": 5, "size": "large"}
        )
    )
    try:
        req = urllib.request.Request(url, headers={"Authorization": PEXELS_KEY})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
        photos = data.get("photos", [])
        if not photos:
            return None
        # 시드로 안정적 선택(같은 쿼리 = 같은 사진)
        idx = int(hashlib.md5(query.encode()).hexdigest(), 16) % len(photos)
        return photos[idx]["src"].get("large") or photos[idx]["src"].get("original")
    except Exception:
        return None


def _pexels_pick(query: str, variant: int) -> str | None:
    """variant만큼 다른 사진을 고른다(사진 교체용)."""
    if not PEXELS_KEY:
        return None
    url = (
        "https://api.pexels.com/v1/search?"
        + urllib.parse.urlencode(
            {"query": query, "orientation": "portrait", "per_page": 15, "size": "large"}
        )
    )
    try:
        req = urllib.request.Request(url, headers={"Authorization": PEXELS_KEY})
        with urllib.request.urlopen(req, timeout=15) as r:
            photos = json.loads(r.read().decode("utf-8")).get("photos", [])
        if not photos:
            return None
        base = int(hashlib.md5(query.encode()).hexdigest(), 16)
        p = photos[(base + variant) % len(photos)]
        return p["src"].get("large") or p["src"].get("original")
    except Exception:
        return None


def _openverse_pick(query: str, variant: int = 0) -> str | None:
    """Openverse(CC 이미지, 키 불필요, 상업적 사용 가능) — 주제 맞는 실사."""
    try:
        u = ("https://api.openverse.org/v1/images/?"
             + urllib.parse.urlencode({"q": query, "page_size": 12,
                                       "license_type": "commercial"}))
        req = urllib.request.Request(u, headers={"User-Agent": "ContentForge/1.0 (cardnews)"})
        with urllib.request.urlopen(req, timeout=15) as r:
            res = json.loads(r.read().decode("utf-8")).get("results", [])
        if not res:
            return None
        base = int(hashlib.md5(query.encode()).hexdigest(), 16)
        return res[(base + variant) % len(res)].get("url")
    except Exception:
        return None


def _picsum_url(seed: str) -> str:
    s = hashlib.md5(seed.encode()).hexdigest()[:12]
    return f"https://picsum.photos/seed/{s}/{W}/{H}"


def _resolve_url(query: str, variant: int = 0) -> tuple[str, str]:
    """소스 우선순위: Pexels(키 있으면) → Openverse(키X, 주제맞춤) → picsum(랜덤).
    (url, source) 반환."""
    if PEXELS_KEY:
        u = _pexels_pick(query, variant) if variant else _pexels_search(query)
        if u:
            return u, "pexels"
    u = _openverse_pick(query, variant)
    if u:
        return u, "openverse"
    return _picsum_url(f"{query}{variant}"), "picsum"


def fetch_one(query: str, out_dir, i: int, variant: int = 0) -> Path | None:
    """카드 1장의 배경 이미지만 받아 img_NN.jpg로 저장(사진 교체)."""
    img_dir = Path(out_dir) / "img"
    img_dir.mkdir(parents=True, exist_ok=True)
    query = (query or "").strip() or "minimal background"
    url, _ = _resolve_url(query, variant or i)
    dest = img_dir / f"img_{i:02d}.jpg"
    return dest if _download(url, dest) else None


def _download(url: str, dest: Path) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            dest.write_bytes(r.read())
        return dest.stat().st_size > 1000
    except Exception:
        return False


def fetch_images(slides: list[dict], out_dir: Path) -> dict[int, Path]:
    """슬라이드별 배경 이미지를 받아 out_dir/img_NN.jpg 로 저장. {index: path}."""
    out_dir = Path(out_dir)
    img_dir = out_dir / "img"
    img_dir.mkdir(parents=True, exist_ok=True)
    result: dict[int, Path] = {}
    sources: set[str] = set()
    for i, s in enumerate(slides, 1):
        query = (s.get("image_query") or "").strip() or "minimal background"
        url, src = _resolve_url(query, i)
        dest = img_dir / f"img_{i:02d}.jpg"
        if _download(url, dest):
            result[i] = dest
            sources.add(src)
    print(f"  [이미지] {'/'.join(sorted(sources)) or '-'}: {len(result)}/{len(slides)}장 받음")
    return result


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "office stretching"
    test = [{"image_query": q}]
    print("KEY:", "있음" if PEXELS_KEY else "없음(picsum 폴백)")
    print(fetch_images(test, Path("out/_imgtest")))
