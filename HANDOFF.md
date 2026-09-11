# ContentForge — 작업 핸드오프

> 주제 한 줄 → AI 카드뉴스(이미지+카피) 자동 생성 + 인스타식 리더기.
> 숏폼 자동화 에이전시들이 파는 결과물을 직접 만들어보려고 시작했다.

> 작업 전에 **`작업 유의사항.md`** 를 먼저 읽을 것(또 밟을 지뢰 모음).

## 다음에 해야 할 것

1. **팀 베타테스터 모집 카드뉴스 마무리** — 덱은 `out/` 에 있고(리더기에서 편집), 납품 폴더·zip 은
   루트에 있다(`.git/info/exclude` 로 제외, 커밋 금지). **모집 인원·기간·혜택·신청 방법**을 팀원에게 받아
   6~7장에 넣고 다시 zip. 지어내지 말 것.
2. **■중지 버튼 브라우저 실물 확인** — API 로만 검증했다. 입구에서 단발·배치 각각 눌러보기.
3. **`verify.py` 실물 검증** — 만들어만 놓고 한 번도 안 돌렸다. 입구에서 `🔎 수치 근거 대조`
   토글 켜고 한 편 뽑아, ①근거 없는 수치를 실제로 잡는지 ②생성이 몇 초 더 걸리는지 잰다.
4. **PEXELS_API_KEY 연결**(무료 1분) — Openverse 는 주제 안 맞거나 960px 이라 흐리다.
   겸사겸사 `images.py` 가 CC BY 사진의 출처를 안 남기는 것도 고칠 것(slides.json 에 credits).
5. **모델 재선정 확인** — `llm.py` PREFERRED 맨 앞이 `huihui_ai/qwen3-abliterated:14b-v2`.
   카피 품질이 qwen2.5:14b 보다 나은지 같은 주제로 대조. (가끔 `{}` 빈 응답 → 재시도로 막아둠)
6. CTA 뱃지 `SAVE · FOLLOW` 고정 — 모집·공지형 글엔 어색하다. 슬라이드별로 바꿀 수 있게.

## ⚡ 즉시 실행
**바탕화면 `ContentForge` 바로가기** → 런처 창(`launcher.pyw`)에서 켜기/끄기. 켜지면 브라우저 자동으로 열림.
창 닫으면 거기서 켠 서버도 꺼짐. `.pyw` 연결이 없는 PC라 바로가기가 `pythonw.exe`를 직접 가리킨다.
```powershell
cd C:\Users\USER\Desktop\ContentForge
$env:PYTHONUTF8=1; python app.py    # → http://127.0.0.1:8770
# CLI만:  python run.py "직장인 점심시간 10분 스트레칭"
```
※ Ollama 떠 있어야 함(`ollama serve`). 모델 자동선택 `llm.PREFERRED` 순(qwen3-abliterated > qwen2.5:14b > gemma3).
※ Chrome 필수(헤드리스로 카드 PNG 굽기). Edge 폴백.

## 📁 파일 맵
| 파일 | 역할 |
|---|---|
| `run.py` | CLI 엔트리. 주제 → 기획 → 렌더 한 방 |
| `app.py` | 로컬 서버(ThreadingHTTPServer). `/api/generate`(백그라운드 워커)·`/api/job`·`/api/projects`·`/api/project`·`/out/*` 정적 |
| `generate.py` | 주제 → 슬라이드 JSON. **후킹 프롬프트**(숫자/손해회피/반전 강제) + 슬라이드별 `image_query`(영문 검색어) |
| `images.py` | 배경사진 조달. `PEXELS_API_KEY` 있으면 실사검색 / 없으면 picsum 폴백. out/<slug>/img/ 다운로드 |
| `render.py` | 슬라이드 → 1080×1350 카드 HTML → Chrome 헤드리스 PNG. cover/cta=풀배경+오버레이, point=상단 이미지밴드+밝은 패널 |
| `verify.py` | **근거 대조 게이트**(2026-09-03). 슬라이드의 %·금액·날짜를 뽑아 Bing 검색 결과 원문과 대조 → 어디에도 없으면 그 장을 숫자 없이 재생성. 검색엔진 함정은 이 파일 docstring 이 원본 |
| `launcher.pyw` | 서버 켜기/끄기 창(tkinter). 끄기는 8770 포트 주인을 자식(Chrome)까지 taskkill → 터미널에서 켠 서버도 끔 |
| `cancel.py` | 생성 중지 신호. 워커가 Event 를 bind, LLM 스트림 조각·근거 검색·카드 1장마다 check(). `Cancelled`는 BaseException(재생성 `except Exception` 에 삼켜지지 않게) |
| `index.html` | 입구. 주제입력 + 진행률 폴링 + ■중지 버튼(단발·배치, `/api/cancel`) + "내 작업" 갤러리 |
| `reader.html` | 리더기. `?slug=` 캐러셀(←→/키보드/점), 개별·전체 저장 |
| `out/<slug>/` | 산출물: card_NN.png, card_NN.html, img/, slides.json |

## ⚠️ 하드런 함정 (이미 잡은 것)
- **Chrome `--screenshot`은 절대경로만** 받음(상대경로=조용히 실패). `png_path.resolve()`.
- **한글 경로 file:// 는 `as_uri()`(%인코딩) 말고 raw** `file:///` + `/` 치환. 헤드리스가 %인코딩 못 엶.
- **`render.py`의 POINT_CSS는 `PAGE.format()`에 값으로 삽입** → 단일 중괄호(완성형 CSS)여야 함. `{{` 쓰면 literal로 새어나가 CSS 통째 무효(텍스트 사라짐). FULL_CSS는 `.format()` 호출하므로 `{{` 유지.
- **검색 기반 검증의 함정**(캡차·로케일·자기확인·리다이렉트)은 `verify.py` 상단 docstring 에 실측으로 적혀 있다. 거기를 먼저 읽을 것.
- 콘솔 cp949 → 엔트리에서 stdout/stderr `reconfigure(utf-8)`. 실행은 `PYTHONUTF8=1` 권장.
- **`llm.generate_json` 은 스트리밍**(2026-09-11) — 중지 신호를 조각마다 보려고. `stream:false` 로 되돌리면
  ■중지가 LLM 한 번(최대 180초)이 끝날 때까지 안 먹는다.
- 한글 줄바꿈(`keep-all`)·사진 위 글자색·공개 저장소 제품명 등 새로 밟은 것은 `작업 유의사항.md`.

## 🎯 현재 상태 (2026-06-12) — "휘어잡는 완성품" 빌드 중
**목표: 진짜 사람을 붙잡는 완성품.** 4축: ①디자인 다중테마 ✅ ②카피 톤 프리셋 ✅ ③생성중 실시간 미리보기+UX ✅ ④이미지 고급화(Pexels) ⬜(키 필요)
- ✅ **실시간 미리보기+UX**: `_worker` on_progress가 카드 1장 구워질 때마다 `job["cards"]`에 url 추가 → 입구 poll이 `.preview` 그리드에 pop 애니메이션으로 한 장씩 표시. 완성 시 "편집하러 가기" 버튼(자동이동 폐지, 사용자 통제). 버튼/카드 마이크로인터랙션 + 반응형 미디어쿼리(index/reader).
- ✅ **카피 톤**(`tones.py`): hook/info/story/empathy 4프리셋(표지·본문 화법 가이드). `make_cards(tone_preset=, avoid=)` + temperature 0.9. **DEFAULT_AVOID 클리셰 금지어**("이거 모르면 손해" 등)로 반복 박멸. 배치는 `used_covers` 누적→표지 서로 안 겹침. 단발패널 톤칩 + 페르소나 tone_preset 필드. API `/api/tones`.
- ✅ **페르소나 공장**(`personas.py`): 계정 컨셉(니치/타겟/톤/브랜드/기본테마)=페르소나. `personas.json` 저장. **주제 자동추천**(`suggest_topics`, 트렌드 결합옵션) → **배치 일괄생성**(여러 주제를 페르소나 톤·테마·브랜드로 순차 제작). 오파독 '운영대행' 구조. API: `/api/personas`·`/api/persona_create`·`/api/persona_delete`·`/api/suggest_topics`·`/api/batch_generate`·`/api/batch`. 입구 하단 "🏭 페르소나로 한 번에" 영역. `make_cards(tone=)` 연결, `_worker`/`_batch_worker`가 톤 전달.
- ✅ **테마 엔진**(`themes.py` + `render.py`): CSS변수 주입식. 4테마(editorial/impact/vivid/minimal). 무사진 테마(impact/vivid)는 사진 없이 타이포만으로 강함 → 이미지 0바이트. 입구에서 선택, slides.json에 theme 저장→편집 재렌더도 유지. 무사진 테마는 편집기 '사진' 버튼 자동 숨김. 폰트=Google Fonts(Black Han Sans/Nanum Myeongjo/Jua)+Pretendard, `--virtual-time-budget`로 웹폰트 로딩 대기.
- ✅ **편집기**(reader.html): 카드별 카피수정(`/api/update_card`)·AI재생성(`/api/regen_card`)·사진교체(`/api/reroll_image`). 단일 카드만 재렌더.
- ✅ **트렌드 수집**(`research.py`): yt-dlp로 유튜브 인기 콘텐츠 메타만(미디어 0) → 기획 벤치마킹. SOURCES에 함수 추가로 플랫폼 확장.
- ✅ **용량 관리**(`storage.py`): out/ 상한 500MB(CONTENTFORGE_CAP_MB) LRU 자동정리, temp_download 무조건삭제, 생성마다 중간 HTML 청소, 홈에 용량 표시.
- ⚠️ **카피 반복 경향**: qwen이 표지를 "이거 모르면 손해"로 자주 냄 → ②톤 프리셋에서 다양화 필요.

### 품질 하한선 빌드 (2026-06-13~) — "믿고 돌리는" 도구
방향: 컴퓨터 강점=정확·빠른 반복검증 → 사람 검수 없이 도구가 스스로 거름.
- ✅ **auto-fit**(`render._fit_px`): 헤드라인 글자수로 줄 수 추정→3줄 초과 시 폰트 축소(인라인 font-size). 넘침/답답함 방지. (근본은 카피 길이라 ②에서도 잡음)
- ✅ **규칙 게이트**(`quality.py`): `check_cards`=슬라이드수/글자수(cover16·point14·body40~45)/빈칸/클리셰(tones.DEFAULT_AVOID)/중복헤드라인. `generate._self_fix`가 위반 슬라이드만 `regen_slide`로 재생성(rounds=2). **make_cards self_fix=True 기본** → 단발·배치 자동 적용. 검증: 망친 카드4개(클리셰·19/23자·빈body)→전부 통과로 교정.
- ⬜ **LLM 자기평가 층**(다음): 규칙은 형식만 봄. 내용 품질(후킹 약함·헛소리·구체성)은 LLM이 채점→미달 재생성. 폰트(editorial=Hahmlet, vivid=GmarketSans) 교체됨. 이미지=Openverse(키X, 복불복)+SD폴백은 보류(셋업 무거움).


## 다음 후보
1. **PEXELS_API_KEY 연결** — 주제 맞는 실사로 즉시 퀄 점프(무료, 1분).
2. **영상 파이프라인 결합** — 앱에 "숏폼" 탭을 같은 입구로. 오파독이 못 하는 진짜 차별점.
3. **AI 이미지 생성** — picsum/스톡 대신 내 GPU(RTX 5070Ti)로 주제 맞춤 생성(SD/ComfyUI). 무거움, 2단계.
4. 카피 품질 A/B — qwen2.5:32b 옵션, 톤 프리셋(정보형/후킹형/스토리형).
5. 카드 템플릿 다양화(현재 1테마) + 폰트/색 브랜드 프리셋.

## 기록
- `logs/2026-09-11-log.md` — 생성 중지 버튼, 서버 런처, 팀 모집 카드뉴스 제작 중 렌더러 가독성 수정, qwen3 `{}` 재시도
- `logs/2026-09-04-log.md` — 근거 대조 게이트 커밋(9/3 작업분), 잔디 소급
- `logs/2026-06-10-log.md` — 초기 파이프라인 E2E (HANDOFF 에서 옮김)
