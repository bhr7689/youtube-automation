# 🧬 SRE-OS — Shorts Reverse Engineering Operating System (기존 프로젝트 정합 버전 v1.0)

> 원본: 사장님이 준 "SRE-OS MASTER BUILD SPECIFICATION v1.0".
> 이 문서 = **원본을 일본쇼츠 자동화 프로젝트(기존 자산)에 맞춰 큐레이션한 버전.**
> 원칙: 중복은 삭제, 스택은 기존에 맞춰 수정, 없는 것만 신규 추가.

---

## 0. 경험자 결론 — 스택은 갈아엎지 않는다 (핵심 수정)

원본 스펙은 **Next.js + TypeScript + PostgreSQL + Redis 모노레포**를 지시하지만 채택하지 않는다.
이유: 그러면 **기존 일본쇼츠 앱(FastAPI + 정적 HTML) + 방금 만든 파이썬 자산 전체**를 폐기하게 됨.

**대신**: SRE-OS를 **기존 `jpshorts` 백엔드(FastAPI/Python) 위의 모듈**로 얹는다.
그리고 SRE-OS의 심장인 **멀티 에이전트 런타임 = 이미 만든 `metadata_team`의 오케스트레이터를 확장**한다.
(원본의 Provider Adapter·Mock Mode·구조화 JSON·재시도·Idempotency 개념은 그대로 채택 — 스택만 파이썬)

| 원본 스펙 | 정합 버전(채택) |
|---|---|
| Next.js/React/TS | 기존 정적 HTML + FastAPI(Python) |
| PostgreSQL/ORM/Redis/Job Queue | 기존 SQLite(`store.py`) + JSON 자산 + 백그라운드 스레드 잡(이미 있음) |
| Provider Adapter(Anthropic) | 채택 — `concept_maker._llm`(OpenAI/Gemini) 패턴 재사용, Anthropic 추가 |
| Multi-Agent Runtime(DAG) | **`metadata_team`(ChiefEditor+전문가) 확장** |
| Mock Mode | 채택 — 우리 규칙기반이 곧 Mock(키 없이 동작) |
| 구조화 JSON 출력 | 채택 — 이미 전부 JSON |

---

## 1. SRE-OS 19 에이전트 ↔ 기존 자산 매핑 (중복 삭제 근거)

| # | 에이전트 | 기존 자산 | 판정 |
|---|---|---|---|
| A01 | Input Normalizer | `source.py`/`source_finder`(메타 정규화) | 🟨 일부·보강 |
| A02 | Evidence Extractor | `transcript_probe`/`script_corpus`(자막·근거) | 🟨 일부·보강 |
| A03 | Content Structure(Hook~Loop) | `script_corpus`(대본 구조) | 🟥 **신규**(쇼츠 구조 분해) |
| A04 | Viral DNA | `viral_lab`/`tier_lab`(배수·승리공식) | 🟨 일부→쇼츠 구조로 확장 |
| A05 | Viewer Psychology | `concept_maker.CLICK_PSYCH`(클릭 심리) | 🟨 일부·확장 |
| A06 | Emotion DNA | — | 🟥 **신규** |
| A07 | Language DNA | `lyrics_analyzer`/`nation_prompts` | 🟨 일부·확장 |
| A08 | Voice DNA | `tts.py`(속도·간격 관련) | 🟥 **신규**(분석축) |
| A09 | Market KR | `metadata_engine`(KR)+`nation_prompts` | 🟩 **있음** |
| A10 | Market JP | `metadata_engine`(JP)+`translator` | 🟩 **있음** |
| A11 | Thumbnail | `concept_maker`+`thumb_overlay`(Vision·무드이식) | 🟩 **있음(강)** |
| A12 | Strategy A/B/C/D | `concept_maker`(컨셉 생성) | 🟨 A/B/C/D 골격 신규 |
| A13 | Script KR | `scriptwriter.py` | 🟩 **있음** |
| A14 | Script JP | `scriptwriter`+`translator` | 🟩 **있음·정합** |
| A15 | Editing Director(초단위) | `cutplanner.py` | 🟩 **있음** |
| A16 | SEO/Distribution | **`metadata_team`(전문가10+편집장 전체)** | 🟩 **있음(강)** |
| A17 | Growth Intelligence | `asset_ledger`(실험·자산)+`viral_folders` | 🟨 일부·확장 |
| A18 | Critic/Safety | `metadata_team.PolicyReviewer`+`QAEvaluator` | 🟨 일부·유사성검사 신규 |
| A19 | Final Synthesizer | **`metadata_team.ChiefEditor`** | 🟩 **있음(패턴)** |

→ **19개 중 8개 이미 있음(🟩), 8개 일부 있음(🟨), 3개 신규(🟥: 콘텐츠구조·감정DNA·보이스DNA).**
즉 **처음부터 다 만들 게 아니라, 기존 런타임에 분석 에이전트 3~5개만 추가 + A/B/C/D 골격.**

---

## 2. 채택하는 원본 원칙 (그대로 유지 — 매우 좋음)

- **Reverse Engineering First**: Evidence→Pattern→Hypothesis→Strategy→Generation→Experiment
- **Multi-Source Pattern**: 공통 패턴 vs 개별 특성 vs 시장 일반 vs 검증필요 vs 데이터부족 분리
- **Human Psychology First**: 알고리즘이 아니라 시청 심리 중심
- **Ethical Transformation**: 특정 크리에이터 고유표현 복제 금지 → 일반화 패턴만 추출·변환
- **Experiment-Driven**: 모든 전략 = 가설(가설·지표·실패가능성·기간·성공기준·다음행동)
- **A/B/C/D**: Experience / Story / Fact / Curiosity — 심리 작동방식 자체가 다름
- **구조화 JSON 출력** + **Critic/Safety 유사성 검사** + **verificationRequired 표시**
- **Prompt를 코드에 하드코딩 금지** → Prompt Registry(우리 `nation_prompts`/`vocab.json` 방식 확장)

---

## 3. MVP 범위 (기존에 맞춰 큐레이션)

### 유지(원본 그대로)
- 입력: 대본/자막/키워드/아이디어 + URL(메타·자막) — 자동추출 실패 시 사용자 transcript 입력 폴백
- 출력: Reverse Engineering Report + A/B/C/D + KR/JP 대본 + 편집표 + SEO + Growth + JSON Export
- 시장: KR / JP / KR+JP (Locale Registry로 확장 가능 — 우리 `metadata_engine` 국가축과 통합)
- Runtime 진행상태 화면(SSE 또는 폴링 — 기존 source_finder 잡 폴링 방식 재사용)
- Mock Mode(키 없이 전체 흐름) — 우리 규칙기반이 곧 Mock

### 삭제/보류(기존 프로젝트엔 과함 — Adapter만)
- ❌ PostgreSQL/Redis/ORM → SQLite + JSON (기존)
- ❌ Auth/Workspace/Billing/Team/Admin(Phase 5) → 단일 사용자(사장님) 로컬/PC 우선, 후속
- ❌ 컴퓨터비전 프레임분석/음성합성/영상렌더링 자동화 → Adapter 자리만(기존 방침과 동일)
- ❌ 모노레포 apps/web·apps/worker 분리 → 기존 단일 FastAPI + 정적 HTML

### 신규 추가(진짜 만들 것)
- 🟥 A03 콘텐츠 구조 분해(Hook/Setup/Escalation/Reveal/Payoff/CTA/Loop)
- 🟥 A06 감정 DNA(시간축 감정곡선) · 🟥 A08 보이스 DNA(속도·쉼·강조 분석축)
- 🟥 A/B/C/D 전략 4종 골격 + Viral Potential Score(100점, 근거·confidence 포함)
- 🟨 A18 Critic 유사성 검사(원본 과유사 위험 LOW~BLOCKED)
- 🟨 Runtime 진행 상태 화면 + Result Workspace 탭 UI

---

## 4. 아키텍처 (정합 버전)

```
정적 HTML (기존 japan_shorts_app 스타일)
   ↓  /api/sre/*
FastAPI (jpshorts/backend/main.py 확장)
   ├── sre_runtime.py     ← metadata_team.ChiefEditor 확장(DAG 오케스트레이터)
   ├── sre_agents/        ← A01~A19 (기존 모듈 재사용 + 신규 3~5)
   ├── sre_schemas.py     ← 구조화 JSON 스키마 + 검증(§17 스키마)
   ├── prompts/           ← Prompt Registry(버전 고정)
   └── store.py (기존 SQLite) + JSON 자산(asset_ledger 등)
   ↓
Provider Adapter (concept_maker._llm 확장: OpenAI/Gemini/Anthropic) + Mock
```

- **런타임 = `metadata_team` 확장**: 전문가(Specialist)=Agent, ChiefEditor=Orchestrator/Synthesizer.
  이미 있는 것: Brief(공유컨텍스트)·순차/병렬 실행·구조화 산출·리포트·Mock(규칙기반).
  추가할 것: DAG 의존성 선언, 재시도 정책(§10.3), Idempotency Key(§10.4), Run/Result 버전 저장.
- **재시도/Idempotency/버전관리**: 원본 §10 그대로 채택(SQLite에 AgentRun/ResultVersion 저장).
- **Prompt Injection 방어**(§16.4): Source transcript는 신뢰불가 데이터로 취급 — 기존 방침과 일치.

---

## 5. 데이터 모델 (기존 store.py SQLite 확장)

원본 §15 Entity를 SQLite 테이블로: Project·Source·AnalysisRun·AgentRun·Evidence·
ResultVersion·UserEdit·Experiment·ExperimentMetric·PromptTemplate·Export.
(User/Workspace는 단일 사용자라 후속. 나머지는 그대로.)

## 6. 핵심 출력 JSON (원본 §17 그대로 채택)
`reverseEngineering / scores.viralPotential / strategies.A~D / localizations.KR·JP / experiments / critic / metadata`
— 우리 `metadata_team` 출력이 이미 이 구조에 근접(제목/설명/태그/썸네일/QA/serp/team_report).

---

## 7. Phase 계획 (정합)

- **Phase 0**: 이 문서 + 스키마(`sre_schemas.py`) + Mock Provider(있음) + SQLite 테이블
- **Phase 1(MVP)**: New Project→Source 입력→Run(Mock)→Runtime 진행→Result 탭(A/B/C/D·KR/JP대본·편집·SEO·Growth·JSON)→Copy/Download. **기존 metadata_team 재사용으로 빠르게.**
- **Phase 2**: 실제 Provider(Anthropic 추가) + 신규 분석 에이전트(A03/A06/A08) + Critic + 버전관리
- **Phase 3**: URL 메타/자막 수집(기존 youtube_client·transcript_probe 재사용) + 다중 소스 비교
- **Phase 4**: 실험 성과 입력 + A/B/C/D 승자판정 + **asset_ledger 채널 학습 메모리로 통합**
- **Phase 5(보류)**: Auth/Workspace/Billing — 필요 시

## 8. MVP Definition of Done (원본 §29 채택, 스택만 정합)
로컬 1명령 실행 / 프로젝트 생성 / 입력 / KR·JP 선택 / Run / 진행표시(새로고침 복원) /
A/B/C/D 독립 표시 / KR·JP 대본 / 편집·SEO·Growth / JSON 복사·다운로드 / **Mock 키없이 동작** /
실패 에이전트 재실행 / DB 저장 / 최소 테스트 / .env.example / README / 미구현 기록 /
**크리에이터 고유표현 복제 방지 검사 단계.**

---

## 9. 첫 실행 산출물(원본 요구 §첫 실행) — 정합 버전

1. **기술 스택**: Python 3 / FastAPI / SQLite / 정적 HTML(+JS) / Provider Adapter(OpenAI·Gemini·Anthropic·Mock). (Next.js 아님 — 기존 재사용)
2. **폴더**: `jpshorts/backend/sre/`(runtime·agents·schemas·prompts) + `japan_shorts_app/sre_*.html`
3. **핵심 데이터 모델**: Project/Source/AnalysisRun/AgentRun/ResultVersion/Experiment (SQLite)
4. **구현 순서**: 스키마 → Mock 런타임(metadata_team 확장) → Result JSON → 화면(New/Runtime/Result) → 신규 분석 에이전트
5. **아키텍처 결정**: 런타임=metadata_team 확장 / 저장=SQLite+JSON / Prompt Registry / Mock=규칙기반 / 재시도·Idempotency 채택
6. **위험**: (a) 스택 이원화 방지 위해 기존 위에만 얹기 (b) 유사성/저작권 검사 필수 (c) 웹 컨테이너 유튜브 차단 → 수집·실검증은 PC
7. **Phase 1 완료조건**: 위 §8 MVP DoD

---

## 다음 결정 필요
- **(A) 이 정합 방향(기존 파이썬 위에 얹기, metadata_team 확장)으로 Phase 0~1 착수** ← 권장
- (B) 원본대로 별도 Next.js/Postgres 모노레포 신규(기존 자산 미사용)
- (C) 문서만 보존, 구현은 나중
