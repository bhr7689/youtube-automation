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
| `GET/POST/DELETE /api/bookmarks` | ⭐ 북마크 (크로스 화면 공유) |
| `GET/POST/DELETE /api/channels` | ➕ 레퍼런스 채널 |
| `GET/DELETE /api/recent` | 최근 검색어 |

## 작동 화면 (japan_shorts_app/*.html)

- ✅ `search.html` — 키워드 검색 + 옵션(기간/기준/형식/개수/언어) + 결과 내 필터(정렬/배수/조회수/🌱채널나이)
- ✅ `youtube_discover.html` — 3축 칩 조합 → 검색어 생성 → 발굴 (신생 채널 필터)
- ✅ `trend.html` — 🔥 트렌드 피드: 등록 레퍼런스 채널 최근 업로드 → 평균 대비 배수 급등 정렬
  (기간/배수/조회수/형식/정렬[배수·조회·최신·좋아요·댓글·시간당]/개수 필터 + CSV)
- ✅ `bookmarks.html` — 크로스 화면 북마크 모아보기
- ✅ `channels.html` — 레퍼런스 채널 관리 + CSV 내보내기
- ⏳ `collections.html` `translator.html` `editor.html` — 다음 단계 (아직 정적 시안)

## 검증

Playwright 헤드리스 브라우저로 전 화면 자동 테스트 통과 (2026-07-02):
검색 24카드 · 북마크 토글·크로스 화면 · 채널 등록 · 3축 조합 5검색어→75카드 · JS 오류 0
