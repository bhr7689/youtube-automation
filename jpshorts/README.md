# 🎌 jpshorts — 일본쇼츠 자동 프로그램 백엔드

일본 시니어 타깃 쇼츠 채널 공장의 실작동 서버.
정적 시안(`japan_shorts_app/`)을 **같은 포트에서 UI로 서빙**하고, API로 생명을 불어넣는다.

## 실행 (사용자 PC)

바탕화면 `일본쇼츠실행.bat` 더블클릭 → 브라우저가 `http://localhost:8787/` 자동 오픈.

수동 실행:
```bash
pip install -r jpshorts/backend/requirements.txt
uvicorn main:app --port 8787 --app-dir jpshorts/backend
```

## 키 설정

저장소 루트 `.env` (기존 K-Trot 과 공유):
```
YOUTUBE_API_KEY=AIza...   # 없으면 데모 데이터 모드 (UI 개발·시연용)
```

## 구조

```
jpshorts/backend/
├── main.py           FastAPI — API + 정적 UI(japan_shorts_app) 마운트, 포트 8787
├── taxonomy.py       3축(장르×상황×감정) 칩 조합 → 검색어 자동 생성 (템플릿 5종)
├── taxonomies.json   어휘 사전 시드 — 장르17·상황10·감정8, 한/영/일 어휘
├── youtube_client.py YouTube Data API + 키 없으면 데모 폴백
│                     배수 = 영상조회수 / 채널평균조회수(총조회/영상수)
│                     채널나이 = 개설일 기준 개월수 (🌱 신생 필터 근거)
└── store.py          SQLite(data/jpshorts.db, gitignore)
                      bookmarks / ref_channels / recent_searches / channel_cache(24h)
```

## API 요약

| 엔드포인트 | 역할 |
|---|---|
| `GET /api/health` | 상태 + demo 모드 여부 |
| `GET /api/taxonomy` | 3축 어휘 사전 |
| `POST /api/discover/queries` | 칩 선택 → 검색어 자동 생성 |
| `POST /api/discover/search` | 검색어 여러 개 → 병합·중복제거·배수 정렬 |
| `GET /api/search` | 키워드 검색 (기간·형식·개수·언어) |
| `GET /api/trend` | 🔥 트렌드 피드 — 등록 채널 최근 업로드 → 배수 급등 정렬 |
| `GET /api/global-surge` | 🌍 전 세계 24h 급등 채널 (숏폼100·롱폼50, VPH 랭킹, 3h 캐시) |
| `GET /api/surge-analysis` | 📊 급등 채널 키워드·제목 규칙 집계 |
| `GET/POST/PATCH/DELETE /api/collections` | 📁 컬렉션(채널 폴더) CRUD |
| `POST/DELETE /api/collections/{id}/channels` | 폴더에 채널 담기/빼기 |
| `GET/POST/DELETE /api/bookmarks` | ⭐ 북마크 (크로스 화면 공유) |
| `GET/POST/DELETE /api/channels` | ➕ 레퍼런스 채널 |
| `GET/DELETE /api/recent` | 최근 검색어 |
| `POST /api/translate` | 🌸 번역봇 — shorts/literal/japanese/auto/check (Gemini, 데모폴백) |
| `GET /api/translate/status` | Gemini·VOICEVOX 감지 + 화자 목록 |
| `POST /api/tts` | 문장별 TTS(VOICEVOX/무음폴백) → narration job(manifest·SRT·ZIP) |
| `GET /api/tts/{job_id}/download` | narration job ZIP 다운로드 |
| `POST /api/cut/plan` | ✂️ 컷 플래너 — narration job → 3~5초 세그먼트 타임라인(줌·미러·속도) |
| `GET /api/cut/{plan_id}/capcut` | CapCut 초안(A안) JSON 다운로드 |
| `GET /api/cut/{plan_id}/ffmpeg` | ffmpeg 렌더 스크립트(B안) 다운로드 |

## 작동 화면 (japan_shorts_app/*.html)

- ✅ `search.html` — 키워드 검색 + 옵션(기간/기준/형식/개수/언어) + 결과 내 필터(정렬/배수/조회수/🌱채널나이)
- ✅ `youtube_discover.html` — 3축 칩 조합 → 검색어 생성 → 발굴 (신생 채널 필터)
- ✅ `trend.html` — 🔥 트렌드 피드: 등록 레퍼런스 채널 최근 업로드 → 평균 대비 배수 급등 정렬
  (기간/배수/조회수/형식/정렬[배수·조회·최신·좋아요·댓글·시간당]/개수 필터 + CSV)
- ✅ `global_surge.html` — 🌍 전 세계 24h 급등 채널: 숏폼 TOP 100 · 롱폼 TOP 50 (VPH 랭킹,
  국가 플래그, 대표영상·키워드, + 레퍼런스 등록, CSV)
- ✅ `surge_analysis.html` — 📊 급등 규칙 분석: 급등 채널의 검색 키워드 빈도·제목 규칙
  (숫자/이모지/괄호/물음표 사용률·평균 길이)·지역별 키워드 → 내 영상 레퍼런스
- ✅ 카드 공통: 실제 키워드(태그)·구독자·VPH 노출 (api.js 전 화면 반영)
- ✅ `bookmarks.html` — 크로스 화면 북마크 모아보기
- ✅ `channels.html` — 레퍼런스 채널 관리 + CSV 내보내기
- ✅ `collections.html` + `collection_detail.html` — 📁 채널 폴더(플랫 v1): 폴더 생성/이름변경/삭제,
  등록 채널을 폴더에 담기/빼기. (2단계 중첩 폴더는 다음 단계)
- ✅ `translator.html` — 🌸 번역봇(도구②): 4컬럼(원본→한국어직역→한국어쇼츠→일본어) 실작동.
  ⚡쇼츠만들기·↻직역·✨자동완성·번역·🔍점검. Gemini(없으면 데모). 🔊 TTS 모달 →
  문장별 음성(VOICEVOX/무음폴백) + 자막(SRT) + manifest.json → ZIP 다운로드/컷편집 핸드오프.
  · 신규 모듈: `translator.py`(번역·문장분해·품질점검) `tts.py`(VOICEVOX+narration job 패키지)
- ✅ `editor.html` — ✂️ 자동 컷편집(도구③ v1): narration job → 컷 플랜(문장별 3~5초 세그먼트,
  줌 1.1~1.3·좌우반전·속도 0.95~1.05, 동일 원본 5초+ 연속 금지) → 색상 타임라인 +
  세그먼트 상세 + 내보내기(CapCut 초안 JSON·ffmpeg 렌더 스크립트·narration ZIP).
  · 신규 모듈: `cutplanner.py` (플랜·CapCut draft 스켈레톤·ffmpeg 스크립트 생성)
  · 실제 렌더는 사용자 PC(CapCut 또는 ffmpeg). yt-dlp 원본 다운로드는 다음 단계.

### 🖥️ 보조 화면 (2026-07-06 실작동 전환)
- ✅ `index.html` 포털 — 3도구 카드 + 대본 공장 6단계 스트립 + 실시간 상태 칩
- ✅ `settings.html` — 연결 상태(키·VOICEVOX·ffmpeg) + 카테고리별 [수집+재학습] UI + 데이터 보관 안내
- ✅ `notifications.html` — 시스템 알림 + 내레이션/컷플랜/제목성과 작업 기록
- API: /api/system/status · /api/cut/plans · /api/title/logs

### 🧠 대본 공장 (2026-07-05~06 확정 워크플로)
- ✅ `scriptwriter.html` — ✍️ 대본 작성 UI: 터진 숏폼+원본 롱폼 → 카테고리 규칙 →
  훅 7종(구조 미리보기·🎲분포 가중 자동) → 게이트(유사도·훅-구조·앵커) →
  제목 후보(채점)+해시태그 → 🌸 내레이션 패키지 원클릭 → ✂️ 컷편집.
  모든 영상 카드에 ✍️ 대본 액션.
- 백엔드: script_corpus(카테고리별 수집→자동 재학습, by_hook 통계),
  scriptwriter(STRUCTURES 훅→구조 7종, 시선비틀기 4앵글, 앵커, 게이트),
  title_engine(3층 키워드·채점·성과로그), keyword_radar(상승·히트·계절),
  cutplanner(⚓앵커 매칭·🔁루프 컷·🔊SFX 플랜), renderer(실렌더 검증됨).
- 학습 데이터는 실행 PC의 data/ 에 카테고리별로 누적(hook_rules/{genre}.json).

## 🔗 전체 파이프라인 (3도구 연결 완료)
발굴(RefTracker) → 자막/대본 → 🌸 번역봇(일본어+TTS 패키지) → ✂️ 컷편집(컷 플랜+내보내기)
→ CapCut/ffmpeg 렌더 → 업로드

## 검증

Playwright 헤드리스 브라우저로 전 화면 자동 테스트 통과 (2026-07-02):
검색 24카드 · 북마크 토글·크로스 화면 · 채널 등록 · 3축 조합 5검색어→75카드 · JS 오류 0
