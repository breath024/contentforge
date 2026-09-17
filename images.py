"""카드 배경 사진 조달.

우선순위:
1) PEXELS_API_KEY 있으면 → 주제 영문 키워드로 실사 검색 (무료, 한국어/영문 OK)
2) 키 없으면 → picsum.photos 시드 기반 (무키, 즉시. 주제무관이지만 '이미지 들어감' 증명)
다운로드해서 로컬 파일로 두고 render가 file://로 합성한다 (재현성 + 오프라인 렌더).
"""
from __future__ import annotations
import hashlib
import re
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


# ── 후보 고르기 ────────────────────────────────────────────────────────────────
# 자동 조달은 한 장을 찍어 오지만, 남에게 내보낼 결과물은 사람이 보고 골라야 한다.
# 여기서는 CC0/PDM(출처 표기 의무 없음)만 긁어 후보로 돌려준다.
#
# ⚠️ Openverse 익명 요청은 page_size 20 이 상한이다. 21 이상을 넘기면 검색어·필터와
#    무관하게 401 Unauthorized 가 떨어진다(2026-09-17 실측). 키 없이 쓰는 한 여기를 넘기지 말 것.
OPENVERSE_MAX_PAGE = 20
CC0_LICENSES = "cc0,pdm"


def _clean_title(t: str) -> str:
    """Openverse 의 title 에 HTML 조각이 통째로 들어오는 소스가 있다(wikimedia 계열).
    그대로 두면 출처 파일에 태그가 박힌다."""
    t = re.sub(r"<[^>]+>", " ", t or "")
    t = re.sub(r"\s+", " ", t).strip()
    return t[:120] or "(제목없음)"


def _query_variants(query: str) -> list[str]:
    """LLM 이 뽑는 image_query 는 "AI automation, video editing" 처럼 쉼표 나열이 잦은데
    Openverse 는 이런 긴 나열에 0건을 낸다(2026-09-17 실측). 쉼표를 털고, 그래도 안 나오면
    뒤쪽 두 단어 → 앞쪽 두 단어 → 마지막 한 단어로 좁혀 가며 다시 묻는다."""
    q = (query or "").replace(",", " ").replace("·", " ")
    words = [w for w in q.split() if w]
    if not words:
        return ["minimal background"]
    out = [" ".join(words)]
    for cand in (" ".join(words[-2:]), " ".join(words[:2]), words[-1]):
        if cand and cand not in out:
            out.append(cand)
    return out


def _search_page(query: str, page: int) -> list[dict]:
    u = ("https://api.openverse.org/v1/images/?" + urllib.parse.urlencode(
        {"q": query, "page_size": OPENVERSE_MAX_PAGE, "page": page,
         "license": CC0_LICENSES, "mature": "false"}))
    try:
        req = urllib.request.Request(u, headers={"User-Agent": "ContentForge/1.0 (cardnews)"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8")).get("results", [])
    except Exception:
        return []


def search_candidates_ex(query: str, want_tall: bool = False,
                         limit: int = 12) -> tuple[list[dict], str]:
    """CC0/PDM 후보 목록과 '실제로 먹힌 검색어'를 함께 돌려준다.

    한 페이지(20건)만 긁으면 해상도 하한에 걸려 후보가 한두 장만 남는 검색어가 많다
    (2026-09-17 'coffee shop' → 1장). 원하는 수가 찰 때까지 다음 페이지를 더 본다.
    """
    for q in _query_variants(query):
        out: list[dict] = []
        seen: set[str] = set()
        for page in range(1, 4):
            results = _search_page(q, page)
            if not results:
                break
            for c in results:
                w, h = c.get("width") or 0, c.get("height") or 0
                url = c.get("url")
                if not url or url in seen:
                    continue
                if min(w, h) < 800:      # 960px 짜리를 풀블리드로 깔면 흐리다
                    continue
                seen.add(url)
                out.append({
                    "url": url, "thumb": c.get("thumbnail"),
                    "title": _clean_title(c.get("title")),
                    "creator": c.get("creator") or "(작자미상)",
                    "license": (c.get("license") or "").upper(),
                    "landing": c.get("foreign_landing_url") or url,
                    "w": w, "h": h,
                })
            if len(out) >= limit * 2:
                break
        if len(out) >= 4:                # 고를 만큼 나왔으면 이 검색어로 확정
            # 원하는 방향(세로/가로)을 먼저, 그 다음 해상도 큰 순
            out.sort(key=lambda c: ((c["h"] >= c["w"]) == want_tall, min(c["w"], c["h"])),
                     reverse=True)
            return out[:limit], q
        last = (out, q)
    out, q = last
    out.sort(key=lambda c: ((c["h"] >= c["w"]) == want_tall, min(c["w"], c["h"])), reverse=True)
    return out[:limit], q


def search_candidates(query: str, want_tall: bool = False, limit: int = 12) -> list[dict]:
    return search_candidates_ex(query, want_tall, limit)[0]


def fetch_chosen(url: str, out_dir, i: int) -> Path | None:
    """고른 후보 1장을 카드 배경으로 받는다."""
    img_dir = Path(out_dir) / "img"
    img_dir.mkdir(parents=True, exist_ok=True)
    dest = img_dir / f"img_{i:02d}.jpg"
    return dest if _download(url, dest) else None


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


def save_uploaded(data: bytes, out_dir, i: int) -> Path | None:
    """사용자가 올린 사진을 카드 배경으로 저장한다.

    스톡에 없는 것(내 매장·내 제품 화면)은 본인 사진이 제일 낫다.
    렌더러는 img_NN.jpg 를 file:// 로 읽으므로 JPEG 로 눕혀 둔다.
    """
    if not data or len(data) < 1000:
        return None
    img_dir = Path(out_dir) / "img"
    img_dir.mkdir(parents=True, exist_ok=True)
    dest = img_dir / f"img_{i:02d}.jpg"
    try:
        from PIL import Image
        import io as _io
        im = Image.open(_io.BytesIO(data))
        im.load()
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        # 너무 큰 원본은 카드(1080x1350)보다 훨씬 커도 의미가 없다 → 긴 변 2600 으로
        if max(im.size) > 2600:
            im.thumbnail((2600, 2600), Image.LANCZOS)
        im.convert("RGB").save(dest, "JPEG", quality=92)
        return dest
    except Exception:
        # Pillow 가 없거나 못 여는 포맷 → 헤더만 확인하고 그대로 둔다(Chrome 이 읽는다)
        sig_jpeg = bytes([0xFF, 0xD8, 0xFF])
        sig_png = bytes([0x89, 0x50, 0x4E, 0x47])
        if data[:3] == sig_jpeg or data[:4] == sig_png or data[:4] == b"RIFF":
            dest.write_bytes(data)
            return dest
        return None
