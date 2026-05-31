# CLAUDE.md — 썸네일 자동화 시스템

> **세션 시작 규칙:** 첫 응답에서 "🎨 썸네일 자동화 시스템입니다" 라고 한 줄로 먼저 알려라.

## 프로젝트 한 줄 요약

YouTube/Pinterest에서 클릭율 높은 썸네일을 수집·분석해 "나만의 한 끗"을 더한
새 썸네일을 자동 생성하고, 사람이 검수·컨펌하는 독립 자동화 툴.

## 핵심 철학

- **1초 안에 손가락을 멈추게 하라** — 논리가 아닌 감정 트리거
- **레트로 리마스터링** — 과거 히트 패턴 + 현대 감각
- **한 끗 차별화** — 남들 안 쓴 요소 하나가 CTR을 바꾼다

## 아키텍처 (건물 구조)

```
기초  core/           store.py + config.py + utils.py
1층   collect/        YouTube + Pinterest 크롤러
2층   analyze/        12레이어 Vision 분석 엔진
3층   generate/       한 끗 엔진 + 프롬프트 조립
4층   render/         이미지 생성 API (Imagen3 / DALL-E3 / SD)
5층   review/         Streamlit 검수 UI (app.py) — 9탭
옥상  operate/        스케줄러 + 급상승감시 + 리포트
```

## 데이터 흐름

```
YouTube/Pinterest → collect → thumbnail.db
                 → analyze → analysis (12레이어)
                 → generate → hook(6소스) + prompt
                 → render → 후보 이미지 (멀티엔진)
                 → review → 사람 컨펌 → approved
                 → operate → 패턴학습 → 다음 생성 반영
```

## 파일 지도

| 층 | 파일 | 역할 |
|---|---|---|
| 기초 | core/store.py | SQLite 4테이블 + CRUD |
| 기초 | core/config.py | 환경변수 + 카테고리 + 상수 |
| 기초 | core/utils.py | 로깅/다운로드/재시도 |
| 1층 | collect/youtube_collector.py | 키워드 채널검색 + 썸네일수집 |
| 1층 | collect/channel_registry.py | URL/핸들 직접등록 |
| 1층 | collect/pinterest_collector.py | Pinterest 트렌드 수집 |
| 2층 | analyze/vision_analyzer.py | 12레이어 Gemini Vision 분석 |
| 2층 | analyze/color_extractor.py | HEX 팔레트 로컬 추출 |
| 3층 | generate/hook_generator.py | 한 끗 6소스 통합 엔진 |
| 3층 | generate/prompt_builder.py | DALL-E/SD 프롬프트 조립 |
| 3층 | generate/ctr_predictor.py | CTR 예측 100점 만점 |
| 3층 | generate/pattern_miner.py | 고조회수 DB 패턴 추출 |
| 3층 | generate/custom_hooks.py | 나만의 공식 등록/관리 |
| 3층 | generate/feedback_learner.py | 승인 이력 학습 |
| 4층 | render/imagen_client.py | Imagen 3 (GEMINI_API_KEY) |
| 4층 | render/dalle_client.py | DALL-E 3 (OPENAI_API_KEY) |
| 4층 | render/sd_client.py | Stable Diffusion (REPLICATE_API_KEY) |
| 4층 | render/image_generator.py | 멀티엔진 병렬 실행 |
| 5층 | review/app.py | Streamlit 9탭 UI |
| 옥상 | operate/scheduler.py | 자동 스케줄러 (6태스크) |
| 옥상 | operate/youtube_trend_watcher.py | 급상승/경쟁채널 감시 |
| 옥상 | operate/reporter.py | 일일 리포트 + 전략조언 |

## UI 탭 (9탭)

```
📡 채널수집 → 🖼️ 썸네일수집 → 🌸 Pinterest → 🔎 분석
→ 💡 한끗생성 → 🧠 한끗관리 → 🎨 이미지생성 → ✅ 검수 → 🚀 운영·전략
```

## 한 끗 아이디어 6가지 소스

1. **규칙 기반** — 고정 공식 (API 없이 동작)
2. **Gemini AI** — 분석 결과 기반 창의적 생성
3. **Pinterest 트렌드** — 수집된 핀 색상/구도 참고
4. **DB 패턴 마이닝** — 고조회수 썸네일 공통 요소
5. **나만의 공식** — 사용자가 직접 등록한 공식
6. **피드백 학습** — 승인된 썸네일 패턴 우선 반영

## 알고리즘 상위노출 스케줄 (KST)

```
06:00  경쟁채널 새 업로드 감지 + 즉시분석
08:00  Pinterest 트렌드 수집
10:00  유튜브 급상승 수집·분석
14:00  DB 패턴마이닝 + 피드백학습
19:00  피크타임 알림 + 트렌드 키워드 리포트
23:00  일일 리포트 저장
```

## 환경변수 (.env)

```
YOUTUBE_API_KEY   필수 — 채널/영상 수집
GEMINI_API_KEY    Imagen 3 이미지생성 + Vision 분석 + 한끗 AI
OPENAI_API_KEY    DALL-E 3 이미지생성
REPLICATE_API_KEY Stable Diffusion XL
PINTEREST_TOKEN   Pinterest API (없으면 스크래핑)
```

## 실행

```bash
pip install -r requirements.txt
cp .env.example .env  # API 키 입력

streamlit run review/app.py              # UI 실행
python operate/scheduler.py --run-now    # 전체 1회 실행
python operate/scheduler.py --watch      # 24시간 데몬
python operate/scheduler.py --task trend # 특정 태스크만
```

## 현재 상태 (2026-05-31) — 전체 완공

- [x] 기초: core/ 완성
- [x] 1층: collect/ — YouTube + Pinterest
- [x] 2층: analyze/ — 12레이어 Gemini Vision
- [x] 3층: generate/ — 한끗 6소스 + CTR예측 + 패턴마이닝
- [x] 4층: render/ — Imagen3 + DALL-E3 + SD 멀티엔진
- [x] 5층: review/app.py — Streamlit 9탭
- [x] 옥상: operate/ — 스케줄러 + 급상승감시 + 리포트
- [x] GitHub: bhr7689/youtube-automation / thumbnail-automation/

## 브랜치 규칙

- 개발 브랜치: `claude/inspiring-meitner-C7Nvv`
- 작업 단위마다 커밋·푸시
- 세션 종료 전 이 파일 "현재 상태" 갱신
