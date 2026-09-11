"""작업 중지 신호 — 입구의 '중지' 버튼이 돌고 있는 워커를 세운다.

워커 스레드가 시작할 때 자기 Event 를 bind() 해 두면, 느린 지점(LLM 스트림·근거 검색·
카드 렌더)이 check() 로 확인하다가 Cancelled 를 던진다. 인자로 줄줄이 넘기지 않는 건
make_cards → _self_fix → regen_slide → generate_json 처럼 경로가 깊어서다.

Cancelled 가 BaseException 인 이유: generate._self_fix 등이 재생성 실패를
`except Exception: continue` 로 삼키는데, 여기 걸리면 중지가 무시되고 다음 장을 계속 쓴다.
(asyncio.CancelledError 가 BaseException 인 것과 같은 이유)
"""
from __future__ import annotations
import threading


class Cancelled(BaseException):
    pass


_local = threading.local()


def bind(event: threading.Event | None) -> None:
    _local.event = event


def check() -> None:
    ev = getattr(_local, "event", None)
    if ev is not None and ev.is_set():
        raise Cancelled()
