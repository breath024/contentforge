"""ContentForge 전용 앱 — 로컬 서버.

  python app.py        → http://127.0.0.1:8770

라우트:
  GET  /                 입구(index.html)
  GET  /reader.html      리더기(카드뉴스 캐러셀 뷰어)
  POST /api/generate     {topic,n,brand} → job_id (백그라운드 생성)
  GET  /api/job?id=      진행상태
  GET  /api/projects     생성된 카드뉴스 목록(최근순)
  GET  /api/project?slug= 슬라이드 + 카드 PNG 경로
  GET  /out/...          생성물 정적 서빙
ThreadingHTTPServer + 백그라운드 워커 패턴.
"""
from __future__ import annotations
import json
import sys
import threading
import time
import traceback
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from generate import make_cards, regen_slide
from render import render, render_card, img_path_for
from images import fetch_one
from llm import pick_model
import research
import storage
import themes
import personas

ROOT = Path(__file__).parent
OUT = ROOT / "out"
JOBS: dict[str, dict] = {}
BATCHES: dict[str, dict] = {}
_seq = {"n": 0}


def _slugify(topic: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in topic).strip("_")[:40] or "untitled"


def _worker(job_id: str, topic: str, n: int, brand: str, model: str | None,
            use_research: bool = False, theme: str | None = None,
            tone: str | None = None, tone_preset: str | None = None,
            verify_claims: bool = False):
    job = JOBS[job_id]
    try:
        slug = _slugify(topic)
        out_dir = OUT / slug
        references = None
        if use_research:
            job.update(stage="트렌드", message="인기 콘텐츠 분석 중...", slug=slug)
            r = research.collect(topic, n=10)
            references = research.reference_titles(r, k=8)
            job["references"] = references
        job.update(stage="기획", message="카피 생성 중...", slug=slug)

        def on_verify(phase, *a):
            # 근거 대조는 검색을 타서 느리다 → 뭘 하는 중인지 계속 보여준다
            if phase == "checking":
                job.update(stage="근거 대조", message="수치 근거 확인 중...")
            else:
                bad = ", ".join(a[1]) if len(a) > 1 and a[1] else ""
                job.update(stage="근거 대조",
                           message=f"근거 없는 수치({bad}) → {a[0] + 1}번 카드 다시 씀")

        cards = make_cards(topic, n=n, model=model, references=references,
                           tone=tone, tone_preset=tone_preset,
                           verify_claims=verify_claims, on_verify=on_verify)
        cards["brand"] = brand  # 재렌더(편집) 때 다시 쓰려고 저장
        if references:
            cards["references"] = references
        job.update(stage="렌더", message="카드 이미지 굽는 중...", cards=[])

        def on_progress(phase, i, total):
            if phase == "images":
                job["message"] = "배경 이미지 받는 중..."
            else:
                job.update(message=f"카드 렌더 {i}/{total}", progress=i / total)
                # 카드 1장 완성될 때마다 실시간으로 노출
                job["cards"].append(f"/out/{slug}/card_{i:02d}.png?t={job_id}")

        pngs = render(cards, out_dir, brand=brand, on_progress=on_progress, theme=theme)
        # 용량 관리: 중간 HTML 청소 + 총량 상한 적용(현재 작업물은 보호)
        storage.cleanup_artifacts(out_dir)
        removed = storage.enforce_cap(keep={slug})
        if removed:
            print(f"[storage] 상한 초과 → {len(removed)}개 정리: {removed}")
        job.update(stage="완료", status="done", message=f"{len(pngs)}장 완성",
                   progress=1.0, count=len(pngs))
    except Exception as e:
        traceback.print_exc()
        job.update(stage="에러", status="error", message=str(e))


def _batch_worker(bid: str, persona: dict, topics: list[str], n: int,
                  model: str | None, use_research: bool):
    """페르소나 톤·테마·브랜드로 주제들을 순차 일괄 제작."""
    b = BATCHES[bid]
    brand = persona.get("brand", "@my.page")
    theme = persona.get("theme") or themes.DEFAULT
    tone = persona.get("tone")
    tone_preset = persona.get("tone_preset")
    used_covers: list[str] = []  # 배치 내 표지 누적 → 서로 안 겹치게
    for item in b["items"]:
        topic = item["topic"]
        b["current"] = topic
        item["status"] = "running"
        try:
            slug = _slugify(topic)
            out_dir = OUT / slug
            refs = None
            if use_research:
                refs = research.reference_titles(research.collect(topic, n=10), k=8)
            cards = make_cards(topic, n=n, model=model, references=refs, tone=tone,
                               tone_preset=tone_preset, avoid=used_covers)
            cov = (cards["slides"][0].get("headline") or "").strip()
            if cov:
                used_covers.append(cov)
            cards["brand"] = brand
            cards["theme"] = theme
            render(cards, out_dir, brand=brand, theme=theme)
            storage.cleanup_artifacts(out_dir)
            item.update(status="done", slug=slug)
        except Exception as e:
            traceback.print_exc()
            item.update(status="error", error=str(e))
        b["done"] += 1
    removed = storage.enforce_cap()
    if removed:
        print(f"[storage] 배치 후 정리: {removed}")
    b["status"] = "done"
    b["current"] = None


def _load_cards(slug: str):
    d = OUT / slug
    sj = d / "slides.json"
    if not sj.exists():
        return None, None
    return d, json.loads(sj.read_text(encoding="utf-8"))


def _rerender_one(d: Path, cards: dict, index: int, img: Path | None):
    """slides.json 저장 + 카드 1장 재렌더. 캐시 회피용 ?t 쿼리 포함 url 반환."""
    slides = cards["slides"]
    brand = cards.get("brand", "@contentforge")
    (d / "slides.json").write_text(
        json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    png = render_card(slides[index - 1], index, len(slides), d, brand, img,
                      theme=cards.get("theme"))
    bust = int(d.stat().st_mtime * 1000) + index
    return f"/out/{d.name}/card_{index:02d}.png?t={bust}", png


def _project_info(slug_dir: Path) -> dict | None:
    sj = slug_dir / "slides.json"
    if not sj.exists():
        return None
    try:
        data = json.loads(sj.read_text(encoding="utf-8"))
    except Exception:
        return None
    cards = sorted(slug_dir.glob("card_*.png"))
    th = data.get("theme")
    return {
        "slug": slug_dir.name,
        "topic": data.get("topic", slug_dir.name),
        "count": len(cards),
        "cover": f"/out/{slug_dir.name}/{cards[0].name}" if cards else None,
        "mtime": sj.stat().st_mtime,
        "theme": th,
        "uses_photo": themes.uses_photo(th),
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT), **k)

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/":
            self.path = "/index.html"
            return super().do_GET()
        if u.path == "/api/job":
            jid = q.get("id", [""])[0]
            return self._json(JOBS.get(jid, {"status": "unknown"}))
        if u.path == "/api/research":
            topic = q.get("topic", [""])[0].strip()
            if not topic:
                return self._json({"error": "주제 필요"}, 400)
            try:
                return self._json(research.collect(topic, n=10))
            except Exception as e:
                traceback.print_exc()
                return self._json({"error": str(e)}, 500)
        if u.path == "/api/storage":
            return self._json(storage.usage())
        if u.path == "/api/themes":
            return self._json({"themes": themes.options(), "default": themes.DEFAULT})
        if u.path == "/api/tones":
            import tones
            return self._json({"tones": tones.options(), "default": tones.DEFAULT})
        if u.path == "/api/personas":
            return self._json({"personas": personas.load_all()})
        if u.path == "/api/suggest_topics":
            p = personas.get(q.get("pid", [""])[0])
            if not p:
                return self._json({"error": "페르소나 없음"}, 404)
            n = max(3, min(20, int(q.get("n", ["10"])[0])))
            trend = q.get("trend", ["0"])[0] in ("1", "true")
            try:
                refs = (research.reference_titles(research.collect(p["niche"], n=10), k=8)
                        if trend else None)
                topics = personas.suggest_topics(p, n=n, references=refs, model=pick_model())
                return self._json({"topics": topics, "persona": p})
            except Exception as e:
                traceback.print_exc()
                return self._json({"error": str(e)}, 500)
        if u.path == "/api/batch":
            return self._json(BATCHES.get(q.get("id", [""])[0], {"status": "unknown"}))
        if u.path == "/api/projects":
            items = [p for d in OUT.glob("*") if d.is_dir()
                     for p in [_project_info(d)] if p]
            items.sort(key=lambda x: x["mtime"], reverse=True)
            return self._json({"projects": items})
        if u.path == "/api/project":
            slug = q.get("slug", [""])[0]
            d = OUT / slug
            info = _project_info(d) if d.is_dir() else None
            if not info:
                return self._json({"error": "not found"}, 404)
            data = json.loads((d / "slides.json").read_text(encoding="utf-8"))
            cards = sorted(d.glob("card_*.png"))
            info["slides"] = data.get("slides", [])
            info["cards"] = [f"/out/{slug}/{c.name}" for c in cards]
            return self._json(info)
        return super().do_GET()

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/generate":
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8", "replace").strip()
            payload = json.loads(raw) if raw else {}
            topic = (payload.get("topic") or "").strip()
            if not topic:
                return self._json({"error": "주제를 입력하세요"}, 400)
            n = max(4, min(12, int(payload.get("n", 8))))
            brand = (payload.get("brand") or "@contentforge").strip()
            model = pick_model()
            if not model:
                return self._json({"error": "Ollama 모델 없음. ollama serve 확인"}, 503)
            use_research = bool(payload.get("use_research", False))
            theme = payload.get("theme") or themes.DEFAULT
            tone_preset = payload.get("tone_preset")
            verify_claims = bool(payload.get("verify_claims", False))
            _seq["n"] += 1
            jid = f"job{_seq['n']}"
            JOBS[jid] = {"status": "running", "stage": "대기", "message": "시작",
                         "progress": 0.0, "topic": topic}
            threading.Thread(target=_worker,
                             args=(jid, topic, n, brand, model, use_research, theme,
                                   None, tone_preset, verify_claims),
                             daemon=True).start()
            return self._json({"job_id": jid, "model": model})

        if u.path in ("/api/persona_create", "/api/persona_delete", "/api/batch_generate"):
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8", "replace").strip()
            p = json.loads(raw) if raw else {}
            if u.path == "/api/persona_create":
                if not (p.get("name") or "").strip() and not (p.get("niche") or "").strip():
                    return self._json({"error": "이름과 니치는 필요해요"}, 400)
                persona = personas.create(
                    name=p.get("name", ""), niche=p.get("niche", ""),
                    target=p.get("target", ""), tone=p.get("tone", ""),
                    brand=p.get("brand", ""), theme=p.get("theme", ""),
                    tone_preset=p.get("tone_preset", ""))
                return self._json({"ok": True, "persona": persona})
            if u.path == "/api/persona_delete":
                return self._json({"ok": personas.delete(p.get("id", ""))})
            # batch_generate
            persona = personas.get(p.get("pid", ""))
            if not persona:
                return self._json({"error": "페르소나 없음"}, 404)
            topics = [t.strip() for t in p.get("topics", []) if isinstance(t, str) and t.strip()]
            if not topics:
                return self._json({"error": "주제를 하나 이상 선택하세요"}, 400)
            model = pick_model()
            if not model:
                return self._json({"error": "Ollama 모델 없음"}, 503)
            n = max(4, min(12, int(p.get("n", 8))))
            use_research = bool(p.get("use_research", False))
            _seq["n"] += 1
            bid = f"batch{_seq['n']}"
            BATCHES[bid] = {"status": "running", "persona": persona["name"],
                            "items": [{"topic": t, "status": "queued"} for t in topics],
                            "done": 0, "total": len(topics), "current": None}
            threading.Thread(target=_batch_worker,
                             args=(bid, persona, topics, n, model, use_research),
                             daemon=True).start()
            return self._json({"batch_id": bid, "total": len(topics)})

        if u.path in ("/api/update_card", "/api/regen_card", "/api/reroll_image"):
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8", "replace").strip()
            p = json.loads(raw) if raw else {}
            slug = p.get("slug", "")
            d, cards = _load_cards(slug)
            if not cards:
                return self._json({"error": "프로젝트 없음"}, 404)
            slides = cards["slides"]
            idx = int(p.get("index", 0))
            if not (1 <= idx <= len(slides)):
                return self._json({"error": "잘못된 카드 번호"}, 400)
            slide = slides[idx - 1]
            try:
                if u.path == "/api/update_card":
                    # 사용자가 고친 카피 반영, 이미지는 그대로
                    if "headline" in p:
                        slide["headline"] = p["headline"]
                    if "body" in p:
                        slide["body"] = p["body"]
                    img = img_path_for(d, idx)
                elif u.path == "/api/regen_card":
                    used = [s.get("headline", "") for j, s in enumerate(slides) if j != idx - 1]
                    fresh = regen_slide(cards.get("topic", slug), slide.get("role", "point"),
                                        used, model=pick_model())
                    slide.update(headline=fresh.get("headline", slide.get("headline")),
                                 body=fresh.get("body", slide.get("body")),
                                 image_query=fresh.get("image_query", slide.get("image_query")))
                    img = img_path_for(d, idx)
                else:  # reroll_image
                    variant = int(p.get("variant", 1))
                    img = fetch_one(slide.get("image_query", cards.get("topic", "")),
                                    d, idx, variant=variant) or img_path_for(d, idx)
                url, png = _rerender_one(d, cards, idx, img)
                if not png:
                    return self._json({"error": "렌더 실패"}, 500)
                return self._json({"ok": True, "index": idx, "url": url, "slide": slide})
            except Exception as e:
                traceback.print_exc()
                return self._json({"error": str(e)}, 500)

        return self._json({"error": "not found"}, 404)


def main():
    OUT.mkdir(exist_ok=True)
    port = 8770
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"ContentForge → http://127.0.0.1:{port}")
    print(f"  모델: {pick_model() or '⚠️ Ollama 미연결'}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n종료")


if __name__ == "__main__":
    main()
