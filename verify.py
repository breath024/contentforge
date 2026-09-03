"""근거 대조 게이트 — 지어낸 수치를 웹검색으로 잡는다.

quality.py 는 형식만 본다(글자수·빈칸·클리셰). 그래서 "35% 자영업자가 사업자등록일을
잘못 입력했다" 같은 **그럴듯한 거짓말**이 그대로 통과했다. 로컬 LLM은 자기가 지어낸
수치를 근거 있다고 우기므로 자기검증은 못 믿는다 → 바깥 근거로 대조한다.

원칙: 사실을 증명하는 게 아니라 **바깥 어디에도 같은 수치가 없음**을 잡는다.
슬라이드에서 수치를 뽑아 검색 스니펫 + 결과 원문에 같은 수치가 실제로 있는지 본다.
없으면 '근거 없음' = 재생성 대상. 찾으면 출처 URL을 슬라이드에 남긴다.

2026-09-03 실측 기록(다시 밟지 말 것):
  · DuckDuckGo html → 약 20질의 만에 캡차. 검증 도구로는 못 씀.
  · Bing 로케일 없이 → 한국어 매칭 붕괴("자영업자"를 "자영(진왕)"으로). mkt=ko-KR 필수.
  · 네이버 → 검색 페이지가 **검색어를 그대로 되뱉는다**. 페이지 전체로 대조하면 내 질문이
    스스로의 근거가 되는 자기확인 함정. 그래서 결과 블록/원문 안에서만 대조한다.
  · 스니펫만 보면 "…"로 잘려 참인 수치도 떨어진다(부가가치세 10% 등) → 원문도 같이 본다.
  · Bing 결과 링크는 ck/a 리다이렉트이고 직접 열면 막힌다 → u=a1<base64> 를 풀어야 한다.
"""
from __future__ import annotations
import base64
import html
import re
import time
import urllib.parse
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept-Language": "ko-KR,ko;q=0.9"}
SEARCH_URL = "https://www.bing.com/search?mkt=ko-KR&setlang=ko&cc=KR&q="

TOP_K = 5          # 원문까지 열어볼 상위 결과 수
PAGE_CAP = 300_000  # 원문 읽기 상한(바이트)

# 검증 대상 수치 패턴. '3단계', '3가지' 같은 구조 표현은 사실주장이 아니라 제외.
CLAIM_PATTERNS = [
    r"\d[\d,.]*\s*%",                                        # 35%, 12.5%
    r"\d[\d,.]*\s*(?:억|만|천)?\s*원",                        # 2000만 원, 50만원
    r"\d{4}\s*년(?:\s*\d{1,2}\s*월)?(?:\s*\d{1,2}\s*일)?",     # 2026년 10월 15일
    r"\d{1,2}\s*월\s*\d{1,2}\s*일",                           # 10월 15일
    r"\d[\d,.]*\s*(?:배|명|건|곳|개월|주일|시간)",              # 3배, 60명, 2개월
]
_CLAIM_RE = re.compile("|".join(CLAIM_PATTERNS))
_SAFE_CONTEXT = re.compile(r"\d\s*(?:단계|가지|번째|줄|장)")

# 결과 블록 머리의 도메인·URL·게시일("2025년 9월 18일 ·", "1일 전 ·")은 본문이 아니다.
# 여길 같이 대조하면 게시일이 주장의 근거로 둔갑한다 → 잘라내고 본문만 본다.
_DATELINE = re.compile(r"^.*?(?:\d{4}년\s*\d{1,2}월\s*\d{1,2}일|\d+\s*(?:일|시간|분)\s*전)\s*·\s*")
_URLHEAD = re.compile(r"^\S*\s*https?://\S+\s*")


def find_claims(text: str | None) -> list[str]:
    """문장에서 검증이 필요한 수치 주장들을 뽑는다."""
    t = (text or "").strip()
    if not t:
        return []
    out: list[str] = []
    for m in _CLAIM_RE.finditer(t):
        s = m.group(0).strip()
        tail = t[m.end():m.end() + 4]
        if _SAFE_CONTEXT.match(s + tail) or _SAFE_CONTEXT.search(s):
            continue
        if s not in out:
            out.append(s)
    return out


def _norm(s: str) -> str:
    """'2,000 만 원' → '2000만원'. 대조용 정규화."""
    return re.sub(r"[\s,]", "", s)


def _strip_tags(s: str) -> str:
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<link[^>]*>", " ", s, flags=re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def _decode_bing_link(blk: str) -> str | None:
    """Bing ck/a 리다이렉트에서 실제 URL 복원(u=a1<base64url>)."""
    m = re.search(r'href="(https://www\.bing\.com/ck/a\?[^"]+)"', blk)
    if not m:
        return None
    raw = urllib.parse.parse_qs(
        urllib.parse.urlparse(html.unescape(m.group(1))).query).get("u", [""])[0]
    if not raw.startswith("a1"):
        return None
    s = raw[2:]
    s += "=" * (-len(s) % 4)
    try:
        return base64.urlsafe_b64decode(s).decode("utf-8", "ignore") or None
    except Exception:
        return None


def search_results(query: str, timeout: int = 15) -> list[dict]:
    """검색 결과 [{url, snippet}]. 실패해도 예외 대신 빈 리스트."""
    try:
        req = urllib.request.Request(SEARCH_URL + urllib.parse.quote(query), headers=UA)
        body = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")
    except Exception as e:
        print(f"[verify] 검색 실패({query[:30]}): {e}")
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for blk in re.findall(r'<li class="b_algo".*?</li>', body, re.S):
        url = _decode_bing_link(blk)
        if not url or url in seen:
            continue
        seen.add(url)
        txt = _DATELINE.sub("", _URLHEAD.sub("", _strip_tags(blk)))
        out.append({"url": url, "snippet": txt.strip()})
    return out


def page_text(url: str, timeout: int = 8) -> str:
    """결과 원문의 본문 텍스트. 못 열면 빈 문자열(검증 실패로 취급하지 않음)."""
    try:
        b = urllib.request.urlopen(
            urllib.request.Request(url, headers=UA), timeout=timeout).read(PAGE_CAP)
    except Exception:
        return ""
    for enc in ("utf-8", "cp949", "euc-kr"):
        try:
            s = b.decode(enc)
            break
        except Exception:
            continue
    else:
        s = b.decode("utf-8", "ignore")
    return _strip_tags(s)


_PARTICLE = re.compile(r"(?:은|는|이|가|을|를|의|에|에서|으로|로|와|과|도|만|까지|부터|다|한다|이다)$")
_STOP = {"경우", "때문", "위해", "그리고", "하지만", "있다", "없다", "된다", "한다"}


def keywords(text: str, k: int = 4) -> list[str]:
    """문장에서 내용어(2자 이상 한글 명사류)를 뽑는다. 조사 떼고 긴 것 우선."""
    words: list[str] = []
    for w in re.findall(r"[가-힣]{2,}", text or ""):
        w = _PARTICLE.sub("", w)
        if len(w) >= 2 and w not in _STOP and w not in words:
            words.append(w)
    return sorted(words, key=len, reverse=True)[:k]


def _supported(evidence: str, want: str, keys: list[str], window: int = 150) -> bool:
    """수치가 '핵심어 근처'에 있을 때만 근거로 인정.

    이게 없으면 긴 문서 아무 데나 있는 '1개월' 한 조각이 근거로 둔갑한다
    (실제로 나무위키 '자영(진왕)' 문서가 지방세 주장의 근거로 잡혔다).
    """
    ev = _norm(evidence)
    if not want or want not in ev:
        return False
    if not keys:
        return False
    nkeys = [_norm(x) for x in keys]
    for m in re.finditer(re.escape(want), ev):
        lo = max(0, m.start() - window)
        near = ev[lo:m.end() + window]
        if any(k in near for k in nkeys):
            return True
    return False


def check_claim(claim: str, query: str, keys: list[str], top_k: int = TOP_K) -> dict:
    """수치 하나가 바깥 근거에 있는지. 스니펫 먼저(싸다) → 없으면 원문까지."""
    want = _norm(claim)
    if not want:
        return {"ok": True, "claim": claim, "source": None, "match": None}
    results = search_results(query)[:top_k]
    for r in results:                                   # 1차: 스니펫(추가 요청 0)
        if _supported(r["snippet"], want, keys):
            return {"ok": True, "claim": claim, "source": r["url"], "match": "snippet"}
    for r in results:                                   # 2차: 원문(느리지만 정확)
        if _supported(page_text(r["url"]), want, keys):
            return {"ok": True, "claim": claim, "source": r["url"], "match": "page"}
    return {"ok": False, "claim": claim, "source": None, "match": None}


def check_slide(slide: dict, topic: str, pause: float = 0.5) -> dict:
    """슬라이드 1장의 수치 주장 검증 → {ok, claims, unverified, sources}."""
    text = f"{slide.get('headline') or ''} {slide.get('body') or ''}"
    claims = find_claims(text)
    if not claims:
        return {"ok": True, "claims": [], "unverified": [], "sources": []}
    # 검색어·근접판정 모두 이 문장의 내용어를 쓴다. 주제만 넣으면 엉뚱한 문서가 걸린다.
    keys = keywords(text)
    ctx = " ".join(dict.fromkeys((topic or "").split() + keys))
    unver: list[str] = []
    srcs: list[dict] = []
    for c in claims:
        r = check_claim(c, f"{ctx} {c}".strip(), keys)
        if r["ok"]:
            srcs.append({"claim": c, "url": r["source"], "match": r["match"]})
        else:
            unver.append(c)
        time.sleep(pause)  # 검색 매너 — 연속 호출 간격
    return {"ok": not unver, "claims": claims, "unverified": unver, "sources": srcs}


def check_cards(cards: dict, topic: str | None = None, pause: float = 0.5) -> dict:
    """덱 전체 근거 대조 → {ok, slides:{idx:{...}}} (quality.check_cards 와 같은 모양)."""
    topic = topic or cards.get("topic") or ""
    per: dict[int, dict] = {}
    for i, s in enumerate(cards.get("slides", [])):
        r = check_slide(s, topic, pause=pause)
        if r["sources"]:
            s["sources"] = r["sources"]   # 사람이 나중에 확인할 수 있게 남긴다
        if not r["ok"]:
            per[i] = r
    return {"ok": not per, "slides": per}


if __name__ == "__main__":
    import json
    import sys
    demo = {"topic": "자영업자가 지원금 못 받는 이유", "slides": [
        {"role": "point", "headline": "사업자등록일이 잘못 되어 있다",
         "body": "35% 자영업자가 사업자등록일을 잘못 입력했다"},
        {"role": "cta", "headline": "지금 확인하세요", "body": "팔로우하고 오늘 바로 확인"},
    ]}
    if len(sys.argv) > 1:
        demo = json.load(open(sys.argv[1], encoding="utf-8"))
    print(json.dumps(check_cards(demo), ensure_ascii=False, indent=2))
