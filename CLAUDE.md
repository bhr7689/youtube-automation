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
- [x] ☀️ **오늘의 시그니처(채널 사운드 정체성)**(2026-06-27, lyrics-auto-generator-9pf34x):
  `daily_signature.py` 신규 + `daily_signature.json` 로컬 저장. 첫 시드 시리즈 =
  사용자가 명시한 **"Parisian Chanson Café"** (스텔라장식, soft acoustic piano +
  romantic accordion + upright bass + warm string pad, 보컬 whispering airy female,
  분위기 charming/cozy/dreamy, **strictly no drums, no guitars**).
  - 곡마다 액센트 1개만 자동 변주(glockenspiel/vibraphone/muted trumpet/flute/cello/celeste)
  - day_count 자동 증가 — 같은 시그니처 50곡 쌓아 채널 정체성 확립
  - 사이드바에서 시그니처 편집(악기·보컬·분위기·액센트 팔레트 수정 가능)
  - Suno Style of Music = 시리즈명(Day N) + 금지 악기 + 핵심 악기 + 보컬 + 분위기 +
    레퍼런스 아티스트 + 언어 명시 + [today's accent: …]
  - `lyrics_generator.build_prompt` 에 `signature_brief` 주입 → LLM 이 섹션마다
    sound_direction(괄호) + stage_direction(대괄호) 자동 작성
  - 결과 가사 = 사용자 예시 동일 형식: `[Intro]\n(사운드)\n[Stage]\n가사`
- [x] 🎤 **가사 자동 생성기 단독 앱**(2026-06-27, lyrics-auto-generator-9pf34x):
  `lyrics_app.py` 신규 — 모바일 세로 우선 단일 페이지 Streamlit. 장르(트로트5070/
  트로트흥/발라드/K-POP/포크7080) + 길이(2:30~6:00) + **언어 멀티셀렉트(12개국)** +
  주제 선택 + 변주개수(1~3) → Gemini → 언어별 N개 가사 변주.
  **결과 카드를 3블록(제목/스타일/가사)으로 분리**해 **수노(Suno) Custom 모드에
  그대로 붙여넣기** 가능. 섹션 태그는 Suno 표준 `[Verse 1]/[Chorus]/[Bridge]/[Outro]`
  로 자동 변환. **다국어 지원**: 한국어/영어/일본어/대만식 중국어/멕시코·스페인
  스페인어/프랑스어/힌디/베트남어/인도네시아어/태국어/브라질 포르투갈어. 각 언어
  선택 시 Suno 스타일도 그 지역 음악(샹송/랜체라/볼리우드/만도팝/볼레로/MPB 등)으로
  자동 변환 + "sung in {언어}" 명시. 전체 백업 TXT 다운로드.
  - 엔진: `lyrics_generator.py` 에 `language` 파라미터 추가(언어별 가요 운율 지시)
  - 실행: `streamlit run lyrics_app.py` 또는 `가사생성기실행.bat` (포트 8503)
  - import + Suno 섹션/스타일 변환 + 다국어 프롬프트 + stub generate_lyrics 검증.
    HTTP 200 페이지 렌더 확인.
- [ ] 실제 API 키로 end-to-end 점검(collect→score→검수→역설계→pipeline) — 키 필요해 미수행
- [ ] `automation.py`(laughing-hawking) cron 레이어를 통합할지 결정
- [ ] sleepy-fermat-76R13 의 reverse_app.py 를 default 브랜치(eqO5N)로 머지해야 사용자 화면에 반영됨
- [x] 🌍 **나라별 작사 도서관**(2026-06-27, lyrics-auto-generator-9pf34x):
  `nation_prompts.py` + `nation_prompts.json` (gitignore — 사용자 편집 로컬 보존,
  시드는 코드 안 SEED_NATION_PROMPTS). **12개국 작사 DNA 시드**:
  한국어/영어/일본어/대만식 중국어/멕시코식·스페인 스페인어/프랑스어/힌디어/
  베트남어/인도네시아어/태국어/브라질 포르투갈어. 각 나라마다 6필드 — 작사가
  페르소나·자주 쓰는 모티프(9개 내외)·운율 형식 규칙·대표 작사가·피해야 할 것·
  한 줄 샘플(톤 참고). 가사 생성 시 `build_combined_persona()` 가 자동으로
  장르 페르소나 + 그 나라 작사 DNA 를 합쳐 generate_lyrics 에 주입.
  사이드바에서 나라별 편집·저장 UI(드롭다운 + expander). 결과 카드에 적용된
  작사 DNA(대표 작사가) 표시. 새 언어 시드 추가 시 기존 사용자 편집 보존하며
  자동 보충.
- [x] 🏆 **자동 셀프 평가 + 재생성**(2026-06-28, lyrics-auto-generator-9pf34x):
  `lyrics_evaluator.py` 신규. 가사 생성 후 같은 Gemini 호출로 4기준 채점 →
  임계값 미만이면 곡당 1회 자동 재생성, 점수 더 높은 쪽 채택.
  - 기준 4개 (각 0-10, 합 40): rhyme(운율) / nativeness(나라스러움) /
    emotion(정서 전달) / signature_fit(시그니처 일치)
  - 기본 임계값 28 (70%). 사용자가 사이드바 슬라이더로 20~36 조정.
  - 기본 OFF — 사용자가 사이드바 토글 켜야 작동(API 호출 약 1.5~2배).
  - 결과 카드에 🏆 점수 배지(30↑녹/24↑주/그 아래 빨), 4기준 세부 점수,
    💬 한국어 코멘트 1줄, 🔄 재시도됨 표식 표시.
  - 채점 프롬프트에 그 나라 작사 DNA + 오늘의 시그니처 요약 주입 →
    "그 나라스러움"·"시그니처 일치" 항목이 의미 있게 작동.
  - stub LLM 으로 채점/임계값 검출 흐름 검증 완료.
- [x] 🎭 **시리즈 전환 (시즌 운영)**(2026-06-27, lyrics-auto-generator-9pf34x):
  여러 시그니처를 보관·전환해 시즌처럼 운영. 시드 4개 추가:
  · Parisian Chanson Café (스텔라장식 샹송, 사용자 명시)
  · Hometown Memory Café (5070 트로트, 시골 봄날·어머니)
  · Midnight City Lounge (발라드, 도시 야경·Rhodes)
  · Saturday Morning Café (7080 포크, 통기타·하모니카)
  - `daily_signature.py` 헬퍼 추가: `list_series` / `create_series`
    (현재 복제 옵션 + slug ID 자동 + 중복 시 _N 접미) / `delete_series`
    (마지막 1개 보호) / `_slugify` (한글/영문 안전)
  - lyrics_app.py 사이드바 🎭 시리즈 셀렉트박스 + 시리즈 추가/삭제 expander
  - 새 시리즈 만들면 자동 current 전환. 삭제 시 현재 삭제하면 다른 것으로 자동 전환.
- [x] **lyrics-auto-generator-9pf34x → default 브랜치(eqO5N) 머지 완료**
  (2026-06-27, rebase + no-ff merge). 사용자 PC `유튜브실행.bat` 로 받으면
  가사 생성기 자동 포함.
- [x] 🎬 **채널 설명·해시태그 자동 생성기**(2026-06-28, youtube-description-generator-lssj9c):
  유튜브 링크(채널/영상) → YouTube Data API 로 채널 정체성 + 최근 영상 설명 N개
  수집 → 키워드/태그 빈도 분석 → Gemini 가 채널 브리프 + **의식의 흐름 4단**
  (감정 호명 → 그림 한 컷 → 약속 → 강요 없는 초대) 으로 채널 설명 + 해시태그 +
  채널 설정 키워드 생성. 결과 카드 3블록 모두 `st.code()` 로 복붙 가능.
  - 신규 모듈:
    · `channel_brief.py` — **모든 앱이 공유하는 채널 브랜드 브리프** JSON 메모리
      (정체성/타깃/약속/감정·음악 키워드/톤/금지어/시그니처/CTA/발행 리듬).
      시드 2개(파리지앵 샹송 카페·고향의 봄 트로트). `as_prompt_block()` 으로
      LLM 프롬프트에 그대로 주입. 사이드바에서 브리프 추가·편집·삭제·전환.
    · `channel_desc_generator.py` — URL 파싱(channel/video/handle/user 전부) +
      YouTube Data API 수집 + 키워드 빈도(스톱워드 필터) + Gemini 호출 + 파싱.
      `llm_call` 주입으로 헤드리스 테스트 가능.
    · `channel_desc_app.py` — 모바일 세로 우선 Streamlit. 변주 1~3개 / 길이
      짧게·중간·길게 / 분석 영상 수 5~50개 슬라이더. 전체 결과 JSON 백업.
  - 실행: `streamlit run channel_desc_app.py` 또는 `채널설명생성기실행.bat`
    (포트 8504). `channel_brief.json` 은 gitignore — 로컬 보존.
  - 검증: URL 파싱 5종 + 키워드 추출 + stub generate + Streamlit HTTP 200.
- 💡 **(아이디어 보관)** 일본 시니어 타깃 — 해외 감동/인생교훈 채널 자동화
  (영상 짜집기 + TTS + CapCut 편집). 30개 소스 채널·전략·기술스택·MVP 로드맵 전문:
  `ideas/japan_senior_heartwarming.md`. 기존 youtube-automation(K-Trot)과 **별개**
  의 독립 프로젝트로 구상 — MVP 진입 시 별도 repo 분리 권장.
- 🎌 **(설계 완료)** **일본쇼츠 자동 프로그램** (2026-07-01, new-session-rhtlol):
  사장님이 시안 15장+ 로 그린 3-도구 통합 대시보드 설계 완결.
  전문: `ideas/japan_shorts_architecture.md` (~900줄).
  - **3 도구**: 📺 RefTracker(발굴) · 🌸 일본어 번역봇(대본·TTS) · ✂️ 자동 컷편집
  - **핵심 자산**: 통합대본 4섹션(의미확인/자막/영어확인/TTS용) · 파이프(`|`) 3역할
    · 매칭 신뢰도 % · MediaPipe 얼굴추적 9:16 크롭 · 캡컷 프로젝트 직접 쓰기
  - **파이프라인 6단계**: yt-dlp → Whisper STT → 쇼츠처리 → 한국어번역 →
    의미매칭 → 시각매칭보강
  - **스택 결정**: Next.js 14 + FastAPI + SQLite(MVP) + Redis/RQ + VOICEVOX
  - **로드맵**: Phase 0~5 총 11주 (2.5개월)
  - **저장소 전략**: `japan_shorts/` 서브폴더 시작 → 안정화 후 별도 repo
  - 다음 단계: 사장님 GO 사인 → Phase 0 착수
- [x] 🎌 **일본쇼츠 Phase 1 — RefTracker 실작동**(2026-07-02, new-session-rhtlol):
  정적 시안(`japan_shorts_app/`)에 FastAPI 백엔드(`jpshorts/backend/`)를 붙여
  **4개 화면 실작동**: 🔍 검색 / 🌐 YouTube 발굴(3축 칩 조합) / ⭐ 북마크 / 📺 레퍼런스 채널.
  - 실행: **`일본쇼츠실행.bat`** → uvicorn 포트 8787 이 UI+API 통합 서빙 (서버 1개).
  - 백엔드: `taxonomies.json`(장르17·상황10·감정8, 한/영/일 어휘) + `taxonomy.py`
    (칩 조합→검색어 5템플릿) + `youtube_client.py`(키 없으면 **데모 폴백**,
    배수=조회수/채널평균, 채널나이 개월) + `store.py`(SQLite: 북마크/채널/최근검색/캐시24h).
  - 프론트: `assets/api.js` 공용(카드 렌더러·북마크/채널 토글·정렬필터·토스트·데모배너).
    카드 액션 5개 작동(자막=downsub/원본/유사=재검색/댓글/링크복사). 🌱 채널나이 필터.
  - 검증: Playwright 전 화면 통과 — 검색 24카드·북마크 크로스 화면·채널 등록·
    3축 조합(트로트×슬픔) 5검색어→75카드·JS 오류 0. 스크린샷 `japan_shorts_app/screenshots/`.
  - ⚠️ `.env` 에 YOUTUBE_API_KEY 넣으면 실검색, 없으면 데모 데이터 (UI에 배너 표시).
  - **다음(Phase 2 후보)**: trend.html(레시피 자동 재실행 피드) · collections.html(컬렉션+내보내기)
    · translator.html(Gemini 번역+VOICEVOX 문장별 TTS→manifest 패키지) · editor.html(컷 플래너
    →CapCut draft). 설계 전문: `ideas/japan_shorts_architecture.md` + `ideas/japan_senior_heartwarming.md`.
- [x] 🕵️ **원본 소스 찾기 — 5플랫폼 역추적**(2026-07-04, new-session-rhtlol):
  사용자가 Codex(로컬 PC PowerShell)에서 쓰던 source-finder 를 Python 으로 이식+확장.
  조사 범위: YouTube·Instagram·TikTok·**샤오홍슈·더우인** 기본 포함.
  - `jpshorts/backend/source_finder.py`: meta(yt-dlp→oEmbed 폴백)→다운로드(480p)→
    프레임24+contact_sheet.jpg+**워터마크 스트립**(하단 28% 2배 확대)→@핸들 추출
    (정규식+pytesseract OCR 옵션)→5플랫폼 후보(프로필 probe+검색 루트+DDG 자동검색)
    →판정+report.md/json. **전 단계 실패 허용** — 막혀도 한계 명시하고 완주.
  - 판정 체계(Codex 방식 답습): "가장 이른 공개 후보" vs "원본 촬영 후보" 분리,
    근거 우선순위 워터마크 @핸들 > 메타 날짜 > 자막 일치. 업로더 자신 핸들과 외부 핸들 구분.
  - 수동 단서(hints: 제목/@핸들) 지원 — 프록시로 메타 수집 막혀도 후보 생성 가능.
  - API: POST/GET `/api/source-finder` (백그라운드 스레드 잡+1.5s 폴링+산출물 서빙+기록).
  - UI: `source_finder.html` (URL 입력→6단계 진행 표시→판정 패널+이미지+확인 루트 버튼
    +report.md+과거 기록). 전 페이지 사이드바 🕵️ 메뉴 + 카드 액션 "🕵️ 원본찾기".
  - 검증: 로컬 워터마크 시뮬레이션(@kimdy804 drawtext 영상)으로 전 단계 통과 —
    Codex 실사례와 동일 판정(@kimdy804 유력·TikTok/Instagram 1순위) 재현. Playwright UI 통과.
  - ⚠️ 웹 컨테이너는 프록시가 유튜브 차단 → 메타·다운로드 실패(정상 동작으로 한계 기록).
    **사용자 PC(일본쇼츠실행.bat)에서 풀가동** (yt-dlp/ffmpeg 로컬 설치 확인됨).
  - ⚠️ 이 컨테이너는 2회 리셋됨 — **커밋·푸시를 검증보다 먼저** 하는 원칙 재확인.
- [x] 🔑 **설정 화면에서 API 키 직접 저장**(2026-07-06, new-session-rhtlol):
  비개발자 사장님이 메모장으로 `.env` 편집하는 대신 **설정 → 🔑 연결키 저장**
  패널에서 YouTube/Gemini/OpenAI 키를 붙여넣고 💾 저장 → 이 PC의 `.env` 에
  영구 저장 + **서버 재시작 없이 즉시 적용**.
  - 백엔드(`jpshorts/backend/main.py`): `POST /api/keys/save`(.env upsert — 다른
    줄 보존, 빈칸은 기존 키 유지해 실수 삭제 방지, 최소 1개 없으면 400) +
    `os.environ` & `yc.YOUTUBE_API_KEY` 즉시 반영. `GET /api/keys/status` 는
    마스킹(••••last4)만 반환 — 평문 노출 없음. `ENV_PATH`=저장소 루트 `.env`.
  - 프론트(`settings.html`): 3개 비밀번호 입력 + 현재 상태 배지(저장됨/미설정) +
    "입력한 키 보기" 토글. 저장 후 상태·연결배지 자동 새로고침.
  - 🔒 보안: `.env` 는 `.gitignore` — **절대 커밋/업로드 안 됨**. 키는 사장님
    PC 에만. 검증: TestClient 8케이스(저장/부분업데이트/빈칸보존/즉시반영/마스킹)
    + 라이브 HTTP + Playwright 렌더 통과. **default(eqO5N) 머지·푸시 완료**.
- [x] 🎨 **플리 컨셉 제조기 결과 화면 카드형 개편**(2026-07-06, new-session-rhtlol):
  사장님이 "결과가 너무 보기 불편" + GPT 예시 출력을 붙여줌 → 장점(9섹션 구조·
  85/15 컨셉·복붙 자산)은 살리고 단점(마크다운 한 덩어리 = 긴 스크롤 벽)을 보완.
  - 백엔드(`concept_maker.py`): 출력 방식을 마크다운 → **구조화 JSON** 으로 전환.
    `JSON_OUTPUT` 스키마 지침(입력가정/채널분석/브랜딩점수/컨셉/세팅/미리보기/
    대표썸네일/제목10/Suno/체크리스트) + `_parse_json`(코드펜스 제거·첫{~마지막}
    방어 파싱). 파싱 실패 시 원문 마크다운 폴백, 키 없으면 `_demo_result`(전
    컴포넌트 채운 구조화 데모). 반환 `{result, markdown, channels, engine}`.
  - 프론트(`concept_maker.html`): `renderReport` 카드 렌더러. 상단 **섹션 네비
    pill**(탭 점프) + 전체복사 · 브랜딩점수 **색상 막대+총점배지(/50)** · 컨셉
    **그라디언트 카드**(유지85%/비틀15% 2열+색상 스와치) · **채널 세팅 복붙 존**
    (설명문·키워드·태그·해시태그·템플릿 각각 📋 복사 버튼, 이름·핸들·곡제목은
    클릭복사 칩) · 대표썸네일 **이미지 프롬프트**·Suno **스타일/가사** 강조 복사
    블록 · 제목10 번호리스트(개별+전체복사) · Suno 구조 타임라인 · 체크박스
    체크리스트. 모바일 대응(네비 가로스크롤·2열→1열), 마크다운 폴백 유지.
  - 검증: Playwright 렌더 — 네비8·점수막대5·총점배지·컨셉카드·복사블록9·클릭칩11·
    제목행10·타임라인6·체크5·스와치8, JS오류 0. **default(eqO5N) 머지·푸시 완료**.
- (작업하며 갱신할 것)
