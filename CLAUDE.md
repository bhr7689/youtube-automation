# CLAUDE.md — 프로젝트 기억 파일

# 🎬 이 저장소 = "유튜브 음악 채널 자동화" 도구 (youtube-automation)

> **세션 시작 규칙:** 사용자에게 첫 응답에서 "🎬 유튜브 음악 채널 자동화 프로젝트입니다"
> 라고 한 줄로 먼저 알려라. 사용자가 여러 자동화 도구(저장소)를 운영하므로, 지금 어느
> 프로젝트인지 명확히 해 혼동을 막기 위함이다.

> 새 세션의 Claude가 시작할 때 가장 먼저 읽는 파일입니다. 웹 세션은 매번 새 컨테이너로
> 시작해 이전 대화를 기억하지 못하므로, **여기에 적힌 내용이 유일한 인수인계**입니다.
> 작업을 끝낼 때마다 이 파일의 "현재 상태"와 "다음 할 일"을 갱신하세요.

## ⚠️ 가장 중요한 규칙 (세션 연속성)

1. **브랜치는 항상 `claude/practical-mendel-8xXP7` 하나만 쓴다.**
   과거에 세션마다 새 브랜치를 파서 작업이 7개 브랜치로 흩어진 적이 있다.
   새 브랜치를 만들지 말고, 반드시 이 브랜치에서 이어서 작업하고 푸시한다.
2. **작업 단위마다 커밋·푸시한다.** 커밋하지 않은 파일은 컨테이너 회수 시 사라진다.
   푸시: `git push -u origin claude/practical-mendel-8xXP7`
3. **세션을 끝내기 전에 이 파일의 "현재 상태 / 다음 할 일"을 갱신**하고 함께 푸시한다.
4. **사용자 PC 배포 흐름(중요!).** 사용자는 바탕화면 `유튜브실행.bat` → `git pull` 로
   **default 브랜치 `claude/youtube-discovery-dashboard-eqO5N`** 를 받아 실행한다.
   따라서 **변경을 사용자 화면에 반영하려면 반드시 그 브랜치까지 도달해야 한다**:
   `practical-mendel` 에 커밋·푸시 → **`eqO5N`(default)로 머지**(PR 또는 직접 머지).
   `eqO5N` 에 안 올라가면 사용자는 영원히 못 본다(과거에 이걸로 며칠 헤맴).

## 프로젝트 한 줄 요약

K-Trot(트로트 등 음악) 유튜브 채널 자동화 공장. **collect(정량55) + score(정성45)** 가
매일 SQLite(`store`)에 후보를 쌓고 → 사람이 **검수 큐**에서 승인 → **역설계(analyzer)**
로 Suno 스타일을 추출해 **레시피/스튜디오**에서 프롬프트를 만들고 → Suno mp3를 inbox에
넣으면 **pipeline**이 MP4로 자동 합성한다. 사람 개입은 검수 한 번뿐.

## 아키텍처 (데이터 흐름)

```
🗓️ orchestrator.py  ── 매일 자동 (--once=cron / --watch=데몬)
    ├─ collect.py   YouTube Data API v3 → store 적재 + 정량점수(0~55)
    └─ score.py     미채점 영상 댓글 → Gemini 정성점수(0~45) + 합산 랭킹
         ▼
    store.py  SQLite(ktrot.db) 자산 조인 체인 (video_id/prompt_id/song_id)
         ▼
🙋 검수 큐 탭(app.py) ── 사람: 승인/반려 → review_log     ← 유일한 개입점
         ▼
🔎 analyzer.py(역설계) → 📒 recipes.py(레시피) → 🎚️ suno_studio.py(조합·변주·블렌딩)
         ▼  (모두 vocab.json 통제어휘 공유)
🎵 Suno (사람 또는 API가 mp3를 pipeline inbox 에 투입)
         ▼
🤖 pipeline.py  ── inbox 폴더 감시 → mp3 → MP4 자동 합성 (media_core 공유)
```

## 파일 지도

| 파일 | 역할 | 의존 |
|---|---|---|
| `store.py` | SQLite 토대. videos/video_stats/comments/video_features/prompts/songs/publications/performance/review_log. append-only 이력 + upsert 스냅샷, 자연키 멱등성. stdlib `sqlite3`만. | 없음 |
| `collect.py` | 1단계 수집. YouTube 검색→통계/댓글→store. 정량점수=구독자대비조회수(≤30)+시간당조회수(≤25). | `store`, `isodate`, google-api |
| `score.py` | 2단계 정성. 미채점 영상 댓글→Gemini. 정성=댓글반응(≤20)+5070정서(≤15)+무대에너지(≤10). 해시 캐시(`score_cache.json`). `ranked_candidates()`=정량+정성 합산. | `store`, `suno_studio`, Gemini |
| `orchestrator.py` | 지휘자. collect→score→랭킹. 스테이지 격리, 키 없으면 스킵. `--once`/`--watch`. 로그 `orchestrator_log.jsonl`. | `collect`,`score`,`store` |
| `analyzer.py` | 역설계. 영상 메타데이터→Gemini→vocab 안에서 Suno picks. **오디오 다운로드 안 함(ToS 안전)**. `llm_call` 주입 가능(테스트용). | `vocab.json` |
| `recipes.py` | picks 조합 저장/불러오기/블렌딩(`recipes.json`). SINGLE_DIMS 충돌 방지. | 없음 |
| `suno_studio.py` | Suno 프롬프트 엔진. vocab→compose/auto_select/generate_variations. | `vocab.json` |
| `pipeline.py` | 무인 mp3→MP4. inbox/<job_id>/(job.json+오디오+배경)→output→processed/failed. SRT 생성, 자막 굽기 옵션, 배경 없으면 단색 자동생성. | `media_core` |
| `media_core.py` | 공유 ffmpeg/SRT 순수함수: find_ffmpeg/ffprobe_duration/concat_audio_files/generate_srt/encode_music_video. **Streamlit 비의존** → app.py와 pipeline.py 공용. | ffmpeg |
| `app.py` | Streamlit 대시보드(사람 UI). 탭 7개(아래). | 위 모듈 다수 |
| `vocab.json` | 통제 어휘 사전(차원별 Suno 용어). analyzer/score/studio 정렬 기준. | — |
| `recipes.json` | 저장된 레시피 자산. | — |

### app.py 탭 (`main()` @ app.py) — 총 9탭
🔍 레퍼런스 발굴 · ✍️ AI 스토리텔링&가사 · 🧪 제목 공식 Lab · 🎬 영상 합성(인코딩) ·
📦 인코딩 잡(백그라운드 작업 큐) · 🎤 가사 자동 동기화(SRT, 인터랙티브 편집기+플레이어) ·
🎚️ Suno 프롬프트 스튜디오 · 🔎 곡 역설계 · 🙋 검수 큐
- 주의: app.py 는 기능 풍부한 eGtMR 계열을 base 로, 자동화 3탭(스튜디오/역설계/검수)을
  이식한 합본. 영상 합성·자막은 app.py 자체 inline ffmpeg 사용, pipeline.py 는 media_core 사용.

## 실행 방법

```bash
pip install -r requirements.txt
cp .env.example .env   # YOUTUBE_API_KEY (필수), GEMINI_API_KEY/OPENAI_API_KEY (선택) 입력

streamlit run app.py                                   # 대시보드(사람)
python orchestrator.py --once --keywords "트로트 발라드,효도 트로트" --comments   # 매일 자동 1회 (cron용)
python pipeline.py --init                              # 파이프라인 폴더 생성 후 inbox 감시
```
환경변수: `YOUTUBE_API_KEY`(필수), `GEMINI_API_KEY`(정성점수·역설계·가사), `OPENAI_API_KEY`(선택).
런타임 데이터(`*.db`, `pipeline_data/`, `*_log.jsonl`, `score_cache.json`)는 `.gitignore` 처리됨.

## 점수 체계 (합계 100)
- **정량 55** (collect, 무료·결정론적): 구독자 대비 조회수 비율(≤30) + 시간당 조회수=바이럴 속도(≤25)
- **정성 45** (score, Gemini): 댓글 반응(≤20) + 5070 정서 환기력(≤15) + 무대/연주 에너지(≤10)

## 현재 상태 (2026-05-26 기준)
- 다이어그램의 전 모듈이 `practical-mendel-8xXP7`에 통합 완료(과거 `gracious-feynman-Wmw2f`의
  자동화 커밋 10개를 fast-forward로 흡수). 모든 모듈 존재 + Streamlit 7탭 동작.
- 참고: 별도 브랜치 `laughing-hawking-gNIsO`에 또 다른 cron 레이어 `automation.py`가 있음(미통합).
  cron 구현 보강이 필요하면 거기서 가져올 수 있음.

## 환경 셋업 (자동)
- **SessionStart 훅**(`.claude/hooks/session-start.sh`)이 매 웹 세션 시작 시 자동 실행:
  ffmpeg 설치 + `pip install -r requirements.txt` + (필요 시)cffi 보정. 멱등·동기 모드.
- 즉 새 세션에서 별도 셋업 없이 `streamlit run app.py`·검증·인코딩이 바로 가능.
  (이 훅은 default 브랜치에 머지돼야 모든 세션에 적용됨.)

## 다음 할 일 / 미확인
- [x] 🔬 **제목 알고리즘 분석 앱 + 글로벌 시드 발굴**(2026-06-25, awesome-ride-86mmn8):
  `title_analyzer_app.py` 신규 — 모바일 세로 우선. 4모드: 🪄 시드 자동 발굴 / 🔥 트렌드 /
  📂 카테고리 / ✍️ 직접 붙여넣기. 히든 젬(viral_ratio=조회수/구독자) 발굴, 15개국
  멀티셀렉트(KR/US/JP/IN/MX/ES/BR/DE/FR/ID/VN/TH/PH…) 다국가 비교 → 🌍 공통 시드 vs
  🏳️ 국가별 고유 시드. 토큰 추출은 유니코드 \w 기반(일본어/스페인어/힌디 등 호환).
  쇼츠/롱폼 사용자 라디오 선택.
- [x] 🤖 **자동 시드 발굴 → Notion 적재**(2026-06-25, awesome-ride-86mmn8):
  `daily_seed_report.py` + `.github/workflows/daily_seed_report.yml`. GitHub Actions cron
  매일 08:00 KST 트리거. 환경변수로 모드(hidden_gems/trending)·국가·기간·임계값 제어.
  Notion DB 스키마 자동 감지(컬럼명 한/영 매칭) — 사용자가 어떤 컬럼을 만들었든 매칭되는
  것만 채움. 본문엔 국가별 시드 + 영상 리스트(⚡배수·구독자·조회수). Secrets 3개 필요:
  YOUTUBE_API_KEY / NOTION_TOKEN / NOTION_DATABASE_ID.
- [x] 모듈 실제 구동 검증 완료(2026-05-26): 전 모듈 헤드리스 검증 35/35 통과 +
  셀프테스트 + CLI + 실제 ffmpeg 인코딩(inbox→MP4) + app.py import. **코드 버그 없음.**
- [x] 사라졌던 UI 기능 전체 복원(2026-05-26): eGtMR 기반 9탭 합본. 제목 Lab·인코딩 잡·
  인터랙티브 자막 편집기·영상합성 고급모드·보컬분리·키 영속저장 복원 + 자동화 3탭 유지.
- [x] 🔎 곡 역설계를 **단독 Streamlit 툴**로 분리(2026-06-01, sleepy-fermat-76R13):
  `reverse_app.py`. URL 한 줄 → YouTube API 메타 + 자막(가사) 자동 수집 →
  Gemini 가 **곡 picks(Suno) + 작사 패턴(writer_prompt)** 동시 추출 → 두 도서관에
  장르별로 누적. 탭 3개: 🔎 분석 / 🎚️ 곡 도서관 / ✍️ 작사가 도서관.
  - 신규 모듈: `transcript_probe.py` (youtube-transcript-api + Whisper API fallback),
    `lyrics_analyzer.py` (가사→작사 패턴 Gemini), `lyrics_library.py` (장르별 가사 저장소
    `lyrics_library.json`; 같은 장르 곡들 종합한 **통합 페르소나** 생성 기능).
  - 의존성 추가: `youtube-transcript-api`, `yt-dlp`.
  - 실행: `streamlit run reverse_app.py`. 곡 제작은 Suno 에서 사용자가 직접.
- [x] 🎧 **오디오 실측 분석** 통합(2026-06-01, sleepy-fermat-76R13):
  `audio_probe.py` 신규 모듈 — yt-dlp 로 오디오 추출 + librosa 로
  BPM/키(Krumhansl-Schmuckler)/길이/RMS 에너지/스펙트럴센트로이드/어택밀도 실측.
  옵트인 토글(사이드바 "🎧 오디오 실측 분석 활성화"). 본인 권리·CC 영상 한정.
  `analyzer.build_prompt` 가 `meta["audio_features"]` 와 `meta["lyrics_excerpt"]` 를
  받아 Gemini 프롬프트에 실측 단서로 주입 — 추정 정확도 격상.
  의존성 추가: `librosa>=0.10.1`.
- [x] ✨ **생성 단계 통합**(2026-06-01, sleepy-fermat-76R13): 데이터 수집→생성으로
  최종 흐름 연결. reverse_app.py 가 5탭 구조로 확장.
  - 🎚️→✨ **곡 프롬프트 변주 탭**: 도서관 베이스(단일/다중 블렌딩) +
    변주 강도(약/중/강 — lock dim 차등) → `suno_studio.generate_variations`
    재사용으로 N개 변주. 마음에 드는 변주는 도서관에 저장.
  - ✍️→✨ **가사 생성 탭**: 신규 모듈 `lyrics_generator.py`. 페르소나(단일/장르
    통합/직접 입력) + 곡 길이(2분30초~6분, 7개 프리셋) → 절·후렴·브릿지 구조
    자동 매핑 → Gemini 가 N개 가사 변주. 각 카드에 📋 복사 블록 + .txt 다운로드.
  - 모든 결과 출력은 `st.code()` 블록으로 통일(우상단 📋 아이콘 복사). 통합
    페르소나·가사 본문도 텍스트 영역에서 코드 블록으로 교체. 각 탭 상단에
    복사 안내 캡션 1회 노출.
- [ ] 실제 API 키로 end-to-end 점검(collect→score→검수→역설계→pipeline) — 키 필요해 미수행
- [ ] `automation.py`(laughing-hawking) cron 레이어를 통합할지 결정
- [ ] sleepy-fermat-76R13 의 reverse_app.py 를 default 브랜치(eqO5N)로 머지해야 사용자 화면에 반영됨
- (작업하며 갱신할 것)
