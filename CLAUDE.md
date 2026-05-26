# CLAUDE.md — 프로젝트 기억 파일

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

### app.py 탭 (`main()` @ app.py)
🔍 레퍼런스 발굴 · ✍️ AI 스토리텔링&가사 · 🎬 영상 합성(인코딩) · 🎤 가사 자동 동기화(SRT) ·
🎚️ Suno 프롬프트 스튜디오 · 🔎 곡 역설계 · 🙋 검수 큐

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

## 다음 할 일 / 미확인
- [ ] 모듈 실제 구동 검증(import·DB 초기화·orchestrator 1사이클·pipeline inbox→output)
- [ ] 실제 API 키로 end-to-end 점검(collect→score→검수→역설계→pipeline)
- [ ] `automation.py`(laughing-hawking) cron 레이어를 통합할지 결정
- (작업하며 갱신할 것)
