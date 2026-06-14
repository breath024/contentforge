"""용량 엄격 관리 — '받는 건 임시로, 끝나면 삭제, 총량은 상한'.

호윤 지시: 플랫폼 데이터/다운로드가 디스크에 쌓이지 않게.
  · temp_download(): with 블록 끝나면 무조건 삭제 (예외 나도)
  · enforce_cap(): out/ 총량이 상한 넘으면 오래된 프로젝트부터 통째 삭제(LRU)
  · cleanup_artifacts(): 카드 PNG/slides.json만 남기고 중간 HTML 제거
"""
from __future__ import annotations
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "out"
CAP_MB = float(os.environ.get("CONTENTFORGE_CAP_MB", "500"))  # out/ 총 상한


def dir_size(path) -> int:
    total = 0
    for p in Path(path).rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def size_mb(path) -> float:
    return dir_size(path) / 1024 / 1024


def cleanup_artifacts(slug_dir) -> None:
    """카드 HTML(디버그용 중간물)은 삭제 — 편집 시 render_card가 재생성한다."""
    for h in Path(slug_dir).glob("card_*.html"):
        try:
            h.unlink()
        except OSError:
            pass


def enforce_cap(cap_mb: float | None = None, keep: set[str] = frozenset()) -> list[str]:
    """out/ 총량이 상한 초과면 오래된 프로젝트부터 삭제. keep는 보호(작업 중)."""
    cap = cap_mb if cap_mb is not None else CAP_MB
    if not OUT.exists():
        return []
    # 언더스코어 폴더(_research 캐시 등 시스템)는 정리 대상에서 제외
    projects = [d for d in OUT.iterdir() if d.is_dir() and not d.name.startswith("_")]
    projects.sort(key=lambda d: d.stat().st_mtime)  # 오래된 것 먼저
    removed: list[str] = []
    for victim in projects:
        if size_mb(OUT) <= cap:
            break
        if victim.name in keep:
            continue
        shutil.rmtree(victim, ignore_errors=True)
        removed.append(victim.name)
    return removed


@contextmanager
def temp_download():
    """임시 다운로드 폴더. with 블록을 벗어나면 예외 여부와 무관하게 삭제."""
    d = Path(tempfile.mkdtemp(prefix="cf_dl_"))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def usage() -> dict:
    return {"used_mb": round(size_mb(OUT), 1), "cap_mb": CAP_MB,
            "projects": len([d for d in OUT.iterdir() if d.is_dir()]) if OUT.exists() else 0}


if __name__ == "__main__":
    print(usage())
