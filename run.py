"""주제 한 줄 → 카드뉴스 PNG 완성. 엔트리.

    python run.py "직장인 점심 10분 스트레칭"
    python run.py "월 100만원 부수입 만드는 법" --n 8 --brand @mypage
"""
from __future__ import annotations
import argparse
import sys
import time
from pathlib import Path

# Windows 콘솔 cp949 → 한글/이모지 깨짐·크래시 방지
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from generate import make_cards
from render import render
from llm import pick_model


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("topic", help="카드뉴스 주제 한 줄")
    ap.add_argument("--n", type=int, default=8, help="슬라이드 장수 (기본 8)")
    ap.add_argument("--tone", default="20-30대, 정보형, 단정하고 신뢰감 있게")
    ap.add_argument("--brand", default="@contentforge")
    ap.add_argument("--out", default=None, help="출력 폴더 (기본 out/<주제>)")
    args = ap.parse_args()

    model = pick_model()
    if not model:
        print("⚠️  Ollama 모델을 못 찾음. `ollama serve` 떠있는지, `ollama list` 확인.")
        sys.exit(1)

    slug = "".join(c if c.isalnum() else "_" for c in args.topic)[:30]
    out_dir = args.out or f"out/{slug}"

    print(f"[model]  {model}")
    print(f"[topic]  {args.topic}")
    print(f"[기획] 슬라이드 카피 생성 중...")
    t0 = time.time()
    cards = make_cards(args.topic, n=args.n, tone=args.tone)
    print(f"       {len(cards['slides'])}장 기획 완료 ({time.time()-t0:.1f}s)")

    print(f"[렌더] 카드 PNG 굽는 중 → {out_dir}/")
    pngs = render(cards, out_dir, brand=args.brand)
    print(f"\n✅ {len(pngs)}장 완성 → {Path(out_dir).resolve()}")


if __name__ == "__main__":
    main()
