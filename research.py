"""멀티플랫폼 레퍼런스/트렌드 수집 — 오파독식 '데이터 기반 기획'.

수단 자유, 단 **메타데이터(제목·조회수·채널)만** 뽑는다 → 미디어 0바이트.
잘나가는 콘텐츠의 제목/훅을 모아 카드뉴스 기획에 벤치마킹 자료로 투입.

yt-dlp는 검색+메타 추출에 강력(유튜브 외 다수 사이트). extract_flat로
영상 자체는 절대 안 받는다. 플랫폼은 함수로 분리 → 확장 가능.
"""
from __future__ import annotations
import json
import re

from storage import OUT

CACHE = OUT / "_research"


def _cache_path(topic: str) -> "Path":
    safe = re.sub(r"[^0-9A-Za-z가-힣]+", "_", topic)[:50] or "q"
    return CACHE / f"{safe}.json"


def youtube_search(query: str, n: int = 10) -> list[dict]:
    """유튜브 검색 결과 메타만(다운로드 0). 제목/채널/조회수."""
    import yt_dlp
    opts = {
        "quiet": True, "no_warnings": True, "skip_download": True,
        "extract_flat": True, "noplaylist": True, "ignoreerrors": True,
    }
    out: list[dict] = []
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{n}:{query}", download=False)
        for e in (info or {}).get("entries", []) or []:
            if not e:
                continue
            out.append({
                "platform": "youtube",
                "title": e.get("title"),
                "channel": e.get("channel") or e.get("uploader"),
                "views": e.get("view_count"),
                "url": e.get("url") or e.get("id"),
                "duration": e.get("duration"),
            })
    except Exception as ex:
        print(f"[research] youtube 실패: {ex}")
    return out


# 플랫폼 레지스트리 — 새 소스는 여기에 함수 추가하면 collect가 자동 포함.
SOURCES = {
    "youtube": youtube_search,
    # "tiktok": tiktok_search,  # yt-dlp가 tiktok도 지원(로그인 필요할 수 있음) — 확장 지점
}


def collect(topic: str, n: int = 10, platforms: list[str] | None = None,
            use_cache: bool = True) -> dict:
    """주제로 여러 플랫폼에서 인기 콘텐츠 메타 수집. 결과는 작은 JSON 캐시."""
    cp = _cache_path(topic)
    if use_cache and cp.exists():
        try:
            return json.loads(cp.read_text(encoding="utf-8"))
        except Exception:
            pass
    platforms = platforms or list(SOURCES)
    items: list[dict] = []
    for name in platforms:
        fn = SOURCES.get(name)
        if fn:
            items.extend(fn(topic, n))
    # 조회수 내림차순(있는 것 우선)
    items.sort(key=lambda r: (r.get("views") or 0), reverse=True)
    result = {"topic": topic, "count": len(items), "items": items}
    CACHE.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def reference_titles(research: dict, k: int = 8) -> list[str]:
    """기획 프롬프트에 넣을 상위 제목들."""
    return [it["title"] for it in research.get("items", [])[:k] if it.get("title")]


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "주식 초보 투자"
    r = collect(q, n=8, use_cache=False)
    print(f"[{q}] {r['count']}건")
    for it in r["items"][:8]:
        v = it.get("views")
        print(f"  · {(it.get('title') or '')[:40]:40} | {it.get('channel')} | {v}")
