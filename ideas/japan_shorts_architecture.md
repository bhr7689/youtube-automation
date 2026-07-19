# 🎌 일본 시니어 쇼츠 자동화 — 아키텍처 설계 v1

> **최종 목표**: 해외 예능/리얼리티 롱폼 → **일본 시니어 타깃 쇼츠** 자동 생성
> **범위**: 소재 발굴 → 대본·TTS → 캡컷 자동 편집 (사용자 개입 최소화)
> **작성일**: 2026-07-01 / **작성자 메모**: whiteh2r@gmail.com (박남정)
> **상태**: 설계 완료. 구현 대기.

---

## 📋 목차

1. [프로젝트 개요](#1-프로젝트-개요)
2. [3-도구 시스템 개요](#2-3-도구-시스템-개요)
3. [기술 스택](#3-기술-스택-결정)
4. [Part 1. RefTracker (레퍼런스 트래커)](#part-1-reftracker)
5. [Part 2. 일본어 번역봇](#part-2-일본어-번역봇)
6. [Part 3. 자동 컷편집](#part-3-자동-컷편집)
7. [통합대본 스펙 (핵심 데이터 계약)](#4-통합대본-스펙)
8. [데이터 모델](#5-데이터-모델)
9. [배포 아키텍처](#6-배포-아키텍처)
10. [구현 로드맵](#7-구현-로드맵)
11. [리스크·대응](#8-리스크대응)
12. [부록: Q&A 결정 이력](#부록-qa-결정-이력)

---

## 1. 프로젝트 개요

### 목표
현재 유튜브에서 **터지는(급등)** 해외 예능/리얼리티 롱폼 영상을 자동으로 찾아,
**일본 시니어**가 좋아할 쇼츠(9:16 세로)로 컷편집까지 원스톱 자동 생산.

### 타깃 사용자
- 1차: 사장님(박남정 · whiteh2r@gmail.com) 본인
- 2차: 유료 수강생 (Google OAuth 로 개인별 데이터 분리)

### 최종 산출물
- **캡컷 프로젝트 폴더**(사용자 캡컷 실행하면 즉시 편집 가능한 상태)
  - 컷 15개 정도 배치된 비디오 트랙
  - 파이프 유지 일본어 자막 트랙
  - TTS 나레이션 오디오 트랙
  - 얼굴 추적 9:16 크롭 keyframe

### 성공 지표
- 소재 발굴 → 완성 캡컷 프로젝트: **60분 이내** (사용자 손 개입 5분 이하)
- 매칭 신뢰도 평균 **80% 이상**
- 캡컷에서 최종 마무리 (색보정·BGM·썸네일) **20분 이내**

---

## 2. 3-도구 시스템 개요

Google OAuth 한 번 로그인 → 3개 도구가 상태를 공유하며 순차 연결.

```
┌────────────────────────────────────────────────────────────────┐
│ 🏠 포털 메인 (앱 첫 화면)                                        │
│    📺 RefTracker  |  🌸 일본어 번역봇  |  ✂️ 자동 컷편집        │
└────────────────────────────────────────────────────────────────┘
        │                     │                     │
        ▼                     ▼                     ▼
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│ 소재 발굴     │ ───▶ │ 대본·TTS     │ ───▶ │ 롱폼 → 쇼츠  │
│ 트렌드·검색   │      │ 통합대본     │      │ 캡컷 프로젝트│
│ 컬렉션·북마크 │      │ 4섹션 자동   │      │ 파이프라인 6 │
└──────────────┘      └──────────────┘      └──────────────┘
        ▲                     ▲                     ▲
        └─────────────────────┼─────────────────────┘
                              │
                    ┌─────────────────┐
                    │ 공유 서비스     │
                    │ · OAuth 세션    │
                    │ · SQLite DB     │
                    │ · Job Queue     │
                    │ · 알림 (🔔)     │
                    └─────────────────┘
```

### 도구 간 흐름 (사용자 경험)
```
① RefTracker: 좋은 롱폼 발견 → "🌸 번역봇으로 보내기" 클릭
      ↓ (링크 + 자막 자동 전달)
② 일본어 번역봇: STEP 1·2·3 자동 진행 → 통합대본 완성
      → TTS 생성 → "✂️ 컷편집으로 보내기" 클릭
      ↓ (통합대본 + TTS + 링크 자동 전달)
③ 자동 컷편집: 6단계 파이프라인 → 검토/조정 → 캡컷 저장
      ↓
캡컷 실행 → 프로젝트가 이미 대시보드에 → 최종 마무리
```

---

## 3. 기술 스택 (결정)

| 층 | 선택 | 이유 |
|---|---|---|
| **프론트엔드** | **Next.js 14** (App Router) + Tailwind + shadcn/ui | 시안 디자인 정교도 대응 · SEO·SSR 필요 없어 CSR도 OK |
| **백엔드** | **FastAPI** (Python 3.11) | LLM·yt-dlp·Whisper·CapCut JSON 파이썬 생태계 |
| **인증** | **Google OAuth 2.0** (NextAuth.js) | 사용자별 데이터 분리 · YouTube 채널 액세스 대비 |
| **DB (MVP)** | **SQLite** | 단순 · 파일 백업 · 기존 store.py 재활용 가능 |
| **DB (프로덕션)** | **PostgreSQL** | 멀티 유저 확장 시 |
| **Job Queue** | **Redis + RQ** (Python) | 컷편집 파이프라인 백그라운드 실행 |
| **파일 저장 (MVP)** | 로컬 FS | 사용자 PC 실행이라 로컬로 충분 |
| **파일 저장 (SaaS)** | S3 (또는 R2) | 클라우드 전환 시 |
| **STT** | Whisper (openai-whisper 로컬) | 무료·정확 · GPU 있으면 빠름 |
| **번역** | Gemini 2.0 Flash | 저렴·빠름·품질 충분 |
| **TTS** | VOICEVOX (기본) / OpenAI / ElevenLabs | 시안 그대로 3엔진 지원 |
| **얼굴 감지** | MediaPipe Face Detection | 로컬·경량·정확 |
| **씬 감지** | PySceneDetect | 컷 경계 검출 |
| **비디오 처리** | ffmpeg + yt-dlp | 로컬 실행 |
| **캡컷 JSON** | `pyJianYingDraft` 커뮤니티 라이브러리 참고 | 리버스 엔지니어링된 오픈소스 활용 |

### 저장소 전략
- **MVP**: 기존 `youtube-automation` repo에 **`japan_shorts/` 서브폴더** 시작
- **안정화 후**: 별도 repo `youtube-japan-shorts` 로 분리

---

## Part 1. RefTracker

### 목적
유튜브에서 **터지는 롱폼 영상 자동 발굴** → 컬렉션·북마크·알림 관리 → 번역봇으로 전달.

### 사이드바 구조 (시안 확인)
```
🔴 쇼치 강사님 시리즈
RefTracker
레퍼런스 채널 추적
─────────────────
🔥 트렌드 피드          ← 등록 채널 신작 자동 감지
🌐 YouTube 발굴        ← 카테고리·인기 급상승 브라우징
🔍 검색                ← 키워드 검색 (핵심)
📺 레퍼런스 채널        ← 등록 채널 관리
📁 컬렉션              ← 큐레이션 폴더
⭐ 북마크               ← 즐겨찾기 영상
🔔 알림                ← 트렌드 피드 알림 센터
⚙️ 설정                 ← API 키·임계값·언어·크론
─────────────────
🏠 포털 메인
🌸 일본어 번역봇
✂️ 자동 컷편집
```

### 화면 1. 🔍 검색 (시안 확인 완료)

#### 상단
- 페이지 제목: **"키워드로 영상·채널 발굴"**
- 부제: "유튜브에서 키워드 검색 · 등록 채널 영상이면 배수도 함께 표시"
- 검색바: `키워드 입력 후 Enter — 예: shark tank, science, K-pop` + [검색] 버튼
- 최근 검색 chips: 최대 20개 · 각각 `× 삭제` · [전체 지우기]
  - Chip 뒤 뱃지 `3m` = 3개월 전 검색 (검색 히스토리 기간 표시)

#### 검색 옵션 (변경 시 새로 API 호출)
| 필드 | 값 |
|---|---|
| **범위** | 유튜브 전체 / 내 레퍼런스 채널만 |
| **기간** | 1일 / 3일 / 1주 / 1달 / 3달 / 6달 / 1년 / 전체 |
| **기준** | 인기 영상 / 최신 영상 |
| **형식** | Shorts / 롱폼 / 전체 |
| **개수** | 100 / 200 / 300 / 500 |
| **언어** | 12개국 (한/영/일/중/스/독/불/포/힌/아/인/베) 멀티체크 |

- 언어 뜻: **영상 언어** (YouTube API `relevanceLanguage`)
- 12개국 리스트는 기존 `lyrics_app.py` 것 재활용

#### 결과 내 필터 (즉시 적용 · 클라이언트 사이드)
| 필드 | 값 |
|---|---|
| **정렬** | 조회수 / 급등 배수 / 최신 / 원본 순서 |
| **배수** | 전체 / ×1↑(평균↑) / ×2↑ / ×3↑ / ×5↑ / ×10↑ / ×30↑ |
| **조회수** | 전체 / 10만↑ / 50만↑ / 100만↑ / 500만↑ / 1000만↑ |

#### 결과 그리드 (카드)
- 카드 요소:
  - 상단 뱃지: `SHORTS` or `LONG` + 재생시간 (`0:53`, `12:34`)
  - 좌상단 ⭐: 북마크 토글
  - 우상단 **배수 뱃지 `×38.1`** (등록 채널만) — 색상 규칙:
    - `×1-2`: 회색 / `×2-5`: 주황 / `×5-10`: 빨강 / `×10-50`: 진빨강 / `×50+`: 어두운빨강
  - 썸네일
  - 제목 (2줄)
  - 채널명 + [+ 추가] 버튼 / [✓ 등록] 뱃지
  - 조회수 · 며칠 전
  - 액션 5개:
    - **📜 자막**: 자막 팝업 → "번역봇으로 보내기" 버튼
    - **✏️ 원본**: 유튜브 원본 새 탭
    - **📰 유사**: YouTube "related" API + LLM 임베딩 유사도 상위 20개
    - **💬 댓글**: 최상위 댓글 20개 모달
    - **🔗 링크**: URL 클립보드 복사

#### 배수 계산법 (⭐ 핵심)
```python
def viral_multiplier(video, channel):
    """영상 조회수 ÷ 채널 평균 조회수 (같은 형식만 대상)"""
    same_format_videos = channel.recent_videos(
        n=20,
        format=video.format  # shorts vs long-form 분리
    )
    avg_views = mean([v.views for v in same_format_videos])
    return round(video.views / max(avg_views, 1), 1)
```

- 등록 채널 저장 시 최근 20개 영상 통계 캐시
- 매 시간 배경 크론으로 재계산
- Shorts와 롱폼은 별도로 평균 계산 (형식별 배수)

#### 상단 탭 (영상 / 채널)
- **영상 탭**: 위 카드 그리드
- **채널 탭**: 검색어 매칭 채널 리스트 → [+ 추가]로 레퍼런스 등록

#### 로딩·에러
- API 호출 중: "검색 중... (최초 호출은 2~3초 걸려요)"
- 실패: "다시 시도" 버튼

---

### 화면 2. 🔥 트렌드 피드 (설계 제안 — 미확인)

**핵심 로직**: 등록된 레퍼런스 채널의 신작 영상을 자동 감지 → 사용자 임계값 넘으면 알림.

#### 상단
- 페이지 제목: "🔥 트렌드 피드"
- 부제: "등록 채널의 새 영상 · 임계값 넘으면 자동 알림"
- 상단 우측: [⚙️ 임계값 설정] 버튼

#### 임계값 설정 모달
| 조건 | 기본값 |
|---|---|
| 최소 조회수 | 10만 |
| 최소 배수 | ×3 |
| 최대 게시일 | 7일 이내 |
| 형식 필터 | Shorts만 / 롱폼만 / 전체 |

#### 피드 리스트
- 카드 요소: 검색 화면과 동일
- 좌상단 🔴 NEW 뱃지 (조건 넘긴 것)
- 시간순 정렬 (최신 위)
- 각 카드에 [👁 봤음] [🌸 번역봇으로] [🗑 무시]

#### 백엔드 크론 (매 30분)
```python
def refresh_trend_feed(user_id):
    for channel in user.ref_channels:
        new_videos = channel.get_new_videos_since(last_check)
        for video in new_videos:
            multiplier = viral_multiplier(video, channel)
            if meets_threshold(video, user.thresholds):
                notify(user_id, video)  # 🔔 알림
                cache_in_feed(user_id, video)
```

---

### 화면 3. 🌐 YouTube 발굴 (설계 제안)

**핵심 로직**: 키워드 없이 브라우징 — YouTube 인기 급상승·카테고리 탐색.

- 국가 선택 (일본/미국/영국/한국/…)
- 카테고리 선택 (엔터테인먼트/뉴스/코미디/음악/…)
- 인기 급상승 vs 오늘의 추천

기본 뷰: YouTube API `videos.list?chart=mostPopular&regionCode=JP&videoCategoryId=24`

카드 UX는 검색 결과와 동일.

---

### 화면 4. 📺 레퍼런스 채널 (설계 제안)

등록된 채널을 표·그리드로 관리.

| 컬럼 | 예 |
|---|---|
| 로고 | 📺 |
| 채널명 | Pitch Reality |
| 구독자 | 245만 |
| 최근 20개 평균조회수 | 380만 |
| Shorts 평균 | 250만 |
| 롱폼 평균 | 720만 |
| 카테고리 | 사장님 태그 |
| 마지막 신작 | 3일 전 |
| 액션 | [수정] [비활성화] [삭제] |

레퍼런스 카테고리 (사장님 커스텀):
- 예: `가족`, `역경극복`, `친절`, `황혼열정`, `기타`
- 이전 30채널 아이디어(`japan_senior_heartwarming.md`)의 4카테고리 시드로 미리 채워둠

---

### 화면 5. 📁 컬렉션

큐레이션 폴더. 여러 영상을 주제별로 묶음.

- 컬렉션 생성 (이름·설명·커버)
- 영상 카드에서 [+ 컬렉션에 저장]
- 컬렉션 안에서 순서 조정 · 메모 추가
- **컬렉션 통째로 번역봇에 보내기** (여러 영상 순차 처리)

---

### 화면 6. ⭐ 북마크

- 별 눌린 영상들 timeline 뷰
- 필터: 등록 채널만 / 미등록만 / 전체
- 정렬: 별 누른 순 / 배수 높은 순 / 최신 순

---

### 화면 7. 🔔 알림 (📬 인박스)

- 트렌드 피드 알림 리스트
- 유형별 필터: 신규 영상 / 배수 급등 / 시스템
- 읽음 표시 / 전체 읽음 처리
- 클릭 시 해당 영상 카드로 딥링크

---

### 화면 8. ⚙️ 설정

| 섹션 | 항목 |
|---|---|
| **계정** | Google OAuth 정보 · 로그아웃 |
| **API 키** | YouTube · Gemini · ElevenLabs 개인키 (선택) |
| **알림** | 이메일 / 브라우저 푸시 / 조용 시간대 |
| **트렌드 피드 임계값** | 조회수 · 배수 · 게시일 · 형식 |
| **크론 실행 주기** | 30분 (기본) / 15분 / 1시간 |
| **UI 언어** | 한국어 / 영어 / 일본어 |
| **캡컷 프로젝트 경로** | 자동 감지 or 수동 지정 |

---

## Part 2. 일본어 번역봇

### 목적
영어/한국어 원본 → **4섹션 통합대본** 자동 생성 → TTS mp3 파일 세트 → 컷편집 전달.

### STEP 1. 원본 수집 (설계 제안 — 미확인)

#### 상단
- 페이지 제목: "**STEP 1. 원본 수집**"
- 진행률: `● ○ ○` (1/3 STEP)

#### 입력 방식 3가지
**방식 A. RefTracker에서 자동 전달** (가장 편함)
- RefTracker의 "🌸 번역봇으로 보내기" 클릭 시 유튜브 링크 + 자막 자동 채움

**방식 B. 유튜브 링크 직접 입력**
- URL 붙여넣기 → 자막 자동 다운로드 (youtube-transcript-api → 실패 시 Whisper API)

**방식 C. 대본 직접 붙여넣기**
- 텍스트에어리어 (영어 원문)
- 언어 자동 감지 (영어 / 한국어)

#### 원본 미리보기
- 유튜브: 썸네일 + 제목 + 길이 + 채널
- 자막: 시간 코드 있는 SRT 뷰 (인터랙티브 편집기, 기존 `app.py`의 자막 편집기 재활용)

#### 옵션
- **핵심 구간만 뽑기**: 24분 영상 중 감동/재미 30초~1분 자동 추출
  - LLM(Gemini)로 자막 분석 → 감정어 스코어 상위 3개 구간
- **전체 영상 사용**: 그대로

#### 하단
- [← 이전] [다음 STEP →]

---

### STEP 2. 번역·구성 (설계 제안 — 미확인)

#### 상단
- 페이지 제목: "**STEP 2. 번역·구성**"
- 진행률: `● ● ○` (2/3 STEP)

#### 좌측 (원문)
- 영어 원본 (STEP 1에서 넘어온 자막)
- 각 문장 앞 체크박스 (원음 유지 vs 나레이션 대체)

#### 우측 (일본어 초안)
- 사장님 톤(시니어 친화) Gemini 번역 결과
- 문장 단위로 편집 가능
- 파이프 자동 삽입 위치 미리보기

#### 상단 옵션
| 옵션 | 값 |
|---|---|
| **번역 톤** | 시니어 친화 (정중체/です·ます) / 캐주얼 (だ·である) / 자동 |
| **길이** | 원문 그대로 / 압축 (쇼츠용) / 확장 (스토리텔링) |
| **파이프 밀도** | 짧게 (2-3어절마다) / 보통 / 길게 |

#### 액션
- [자동 번역 실행] · [수동 수정]
- [← STEP 1로] [STEP 3 완성 →]

---

### STEP 3. 통합대본 완성 (시안 확인)

#### 상단
- 페이지 제목: "**STEP 3. 일본어 대본**"
- 진행률: `● ● ●` (3/3 STEP)

#### 통합대본 4섹션 자동 생성
- 사용자가 편집하는 곳: **[1. 의미 확인용]** 만
- [2] [2-1] [3]은 [1]에서 파생 → 사용자에게 표시만

#### 텍스트에어리어
- 초기값: 4섹션 통째 표시
- 파이프 정합성 실시간 검증 (한/일/발음 개수 일치?)
- 문자 수: 좌하단 `1,355자 / 4분 26초`

#### 하단 액션 (3개 버튼)
- ⚙️ **설정** (톤·모델·언어 재변경)
- 🎧 **TTS** (VOICEVOX 등)
- ✂️ **컷편집** (자동 컷편집으로 이동)

---

### TTS 생성 (시안 확인)

#### TTS 엔진 선택
| 엔진 | 특징 |
|---|---|
| **VOICEVOX** ⭐기본 | 일본어 네이티브 · 무료 · 자체 호스팅 |
| **OpenAI** | 표준 · 저렴 · 다국어 |
| **ElevenLabs** | 프리미엄 · 감정 표현 최고 |

#### 재생 속도
- 슬라이더 0.5x ~ 2.0x
- 프리셋 5개: 0.9x 차분 / 1.0x 기본 / 1.1x 가볍게 / **1.2x 빠르게 (쇼츠 권장)** / 1.3x 더 빠르게
- ffmpeg atempo 로 파일에 이미 적용

#### 음성 선택 모달
- 121개 캐릭터 (VOICEVOX)
- 즐겨찾기 (최대 3개 자동 웜업)
- 미리듣기 + 캐릭터 검색
- 첫 호출 시 5~15초 모델 로드 (자동 재시도)

#### 텍스트 미준비 처리
- STEP 3 안 왔으면 → "생성 버튼 누르면 인서(대본) 자동 생성됩니다 (10~20초 추가)"
- 즉, 사용자가 STEP 3 스킵해도 TTS 버튼이 원본에서 대본 자동 생성

#### 출력 파일 규격
```
[다운로드 폴더]/{제목_슬러그}_{엔진}_{spk_id}_{속도}x/
   ├─ 01.wav    ← 제목 (첫 파일)
   ├─ 02.wav    ← 나레이션 1
   ├─ 03.wav    ← 나레이션 2
   ├─ 04.wav
   └─ 05.wav
+ ZIP: {제목_슬러그}_{엔진}_{spk_id}_{속도}x.zip
```

- **WAV 포맷**: VOICEVOX 원본 (24kHz mono 16-bit)
- **파일명**: 2자리 숫자 (`01.wav` ~ `NN.wav`)
- **순번 규칙**: `01`=제목 / `02~N`=나레이션 순서 (연속, 스킵 없음)
- **ZIP 구조**: 프로젝트명 폴더로 감싸기 (Mac `__MACOSX/`, `.DS_Store` 자동 제외)
- **자동 압축해제**: 앱이 백엔드에서 자동 풀어서 즉시 사용 가능하게

#### 완료 UX
- 하단 토스트: `✓ TTS 생성 완료: 5개 mp3 [VOICEVOX · 1.20x]`
- 우상단 최근 다운로드 기록 dropdown에 추가

---

### 컷편집으로 전달
- ✂️ 컷편집 버튼 클릭 시:
  1. 세션에 통합대본 + 유튜브 링크 + TTS 파일 경로 저장
  2. 컷편집 화면으로 라우팅
  3. 컷편집 화면에서 자동 로드

---

## Part 3. 자동 컷편집

### 목적
롱폼 영상 + 통합대본 + TTS → 15개 쇼츠 컷 자동 매칭 → 캡컷 프로젝트 자동 생성.

### 화면 1. 진입 (통합대본 모드 — 시안 확인)

#### 상단 탭
- **✂️ 쇼츠 매칭** ← 여러 쇼츠 대본을 하나의 롱폼에 매칭
- **✨ 통합대본** ⭐기본 ← 하나의 통합대본으로 하나의 롱폼 편집

#### 좌측 (마케팅 소개)
- "일본어 나레이션으로 캡컷 컷편집까지 한 번에"
- "영어 구간=원음 · 일본어=무음+TTS+자막 · 9:16 세로 캡컷 드래프트 자동"
- 2단계 요약 카드

#### 우측 (입력 폼)
| 필드 | 소스 |
|---|---|
| ① 롱폼 원본 영상 | 유튜브 링크 (기본) · 파일 업로드 (탭 선택) |
| ② 통합대본 | 번역봇 자동 전달 (수정 가능) |
| ③ TTS 음성 파일 (여러 개) | 파일 피커 (Downloads 기본) · 파일 4개 뱃지 |
| ④ **제목도 음성으로 읽기 (TTS)** | 체크박스 (카테고리 따라 끄기 가능) |
| ⑤ 프로젝트 이름 | 비워두면 자동 생성 (`AutoCut_{hash}_{slug}`) |

#### 실시간 감지 표시
`감지: 원음 11 · 나레이션 5 (제목 낭독) → TTS 5개 필요 (현재 4개)`
- 매칭 안 되면 빨강, 매칭되면 녹색

#### 하단 버튼
- 보라색 **✂️ 컷편집 시작**

---

### 화면 2. ✂️ 쇼츠 매칭 모드 (설계 제안 — 미확인)

**차이점**: 통합대본은 1롱폼 → 1쇼츠, 쇼츠 매칭은 여러 쇼츠 대본 → 하나의 롱폼에서 각각 잘라냄.

#### 입력
- ① 롱폼 원본 영상
- ② **여러 쇼츠 대본** (한 대본당 1쇼츠 · 각각 3섹션 or 4섹션)
  - 텍스트에어리어 여러 개 or 파일 여러 개 업로드
- ③ 각 쇼츠별 TTS 파일

#### 처리
- 각 쇼츠 대본별로 통합대본 모드 파이프라인 실행
- 결과: N개의 캡컷 프로젝트

#### 사용 사례
- 24분 롱폼에서 3~5개 쇼츠를 한 번에 생산

---

### 화면 3. 파이프라인 진행 화면 (시안 확인)

#### 상단
- 🟣 배지: `컷편집 진행 중`
- 타이틀: **"AI가 매칭하고 있어요"**
- `Job: {UUID}` 표시

#### 전체 진행률
- 프로그레스 바 (보라) + %
- 현재 상세 (예: `롱폼 영상 다운로드: https://...`)

#### 단계별 진행 (6단계)
| # | 스텝 | 기술 |
|---|---|---|
| 1 | 🎬 롱폼 영상 다운로드 | yt-dlp |
| 2 | 🎤 롱폼 음성 인식 (STT) | Whisper |
| 3 | 🎬 쇼츠 처리 | 대본 파싱 + [2-1] 섹션 분석 |
| 4 | 🌐 한국어 번역 | Gemini (STT → 한국어) |
| 5 | 🔗 의미 매칭 | 한국어 gloss vs 원음 STT 유사도 매칭 → 신뢰도 % |
| 6 | 🖼️ 시각 매칭 보강 | MediaPipe 얼굴 감지 + PySceneDetect → 9:16 크롭 keyframe |

#### 백그라운드 특성
- Job ID 발급 → **다른 탭 이동해도 계속 실행**
- 완료 시 🔔 알림
- 📋 작업 목록에서 언제든 재확인
- 실패 시: 어느 단계에서 실패했는지 표시 + [다시 시도] + 부분 결과 검토 가능

---

### 화면 4. 검토 & 조정 (시안 확인)

#### 상단
- 🎉 타이틀: **"컷편집 완료 — 검토 & 조정"**
- 안내: "▶로 컷을 확인하고, 어긋나면 🎚️ 조정에서 파형을 드래그한 뒤 다시 생성하세요 (9:16 세로)"

#### 미리보기
- 원본 롱폼 재생 · 타임코드 (`11:02 / 24:04`)
- **▶ 전체 재생** 버튼 (컷 순서대로 이어붙여 재생)

#### 컷 리스트
- 요약: `전체 15컷 · 원음 11 · 나레이션 4 (제목 안읽음)`
- 각 컷 행:
  - ▶ 개별 재생
  - 타입 뱃지: 🟢 `원음` / 🟣 `무음+TTS`
  - **매칭 신뢰도 %** (원음만): `92%`, `100%`
    - `<50%`: 빨강 · `<70%`: 노랑 · `≥70%`: 녹색
  - 텍스트 미리보기 (일본어 or 영어)
  - 타임코드 (`9:29.6~9:34.7`)
  - 🎚️ 조정 · 🗑️ 제외

---

### 화면 5. 🎚️ 개별 컷 조정 (설계 제안 — 미확인)

#### 상단
- 뒤로 · 컷 번호 · 원음/나레이션 타입

#### 파형 시각화
- 컷 구간 파형 표시 (librosa 로 파형 이미지 생성)
- 좌우 두 개 드래그 핸들 (시작·끝)
- 정밀 입력: `시작: 09:29.6` `끝: 09:34.7` (숫자 직접 편집 가능)

#### 미리듣기
- 조정 후 즉시 재생

#### 신뢰도 재계산
- 조정 후 STT 재비교 → 신뢰도 % 다시 표시

#### 액션
- [저장] · [원래대로] · [닫기]

---

### 화면 6. 📋 작업 목록 (설계 제안 — 미확인)

- 진행 중 / 완료 / 실패 3탭
- 각 잡: 프로젝트명 · 시작 시각 · 소요 시간 · 상태
- [상세보기] [재시도] [삭제]
- 실패 잡: 어느 스텝에서 실패했는지, 원인 로그 (마지막 100줄)

---

### 캡컷 프로젝트 자동 생성 (⭐ 핵심)

#### 프로젝트 이름 규칙
```
AutoCut_{8자hash}_{제목슬러그}
예: AutoCut_ES5o2d95_snap_clips_invention
```

#### 파일 구조 (캡컷 프로젝트 폴더에 직접 쓰기)
```
{CapCut프로젝트루트}/AutoCut_XXX_YYY/
├── draft_content.json     ← 편집 타임라인
├── draft_info.json        ← 메타데이터
├── draft_cover.jpg        ← 프로젝트 썸네일
├── materials/
│   ├── long_video.mp4     ← yt-dlp 롱폼 원본
│   ├── 01.wav             ← TTS 파일 복사 (제목 낭독 시)
│   ├── 02.wav
│   ├── 03.wav
│   ├── 04.wav
│   └── 05.wav
└── metadata.json          ← 우리 앱 메타 (Job ID, 신뢰도, ...)
```

#### 캡컷 프로젝트 폴더 위치 (OS별)
| OS | 경로 |
|---|---|
| **Mac** | `~/Library/Application Support/CapCut/User Data/Projects/com.lveditor.draft/` |
| **Windows** | `%APPDATA%\CapCut\User Data\Projects\com.lveditor.draft\` |
| **Linux** | `~/.config/CapCut/User Data/Projects/com.lveditor.draft/` |

- 설정 화면에서 자동 감지 → 감지 실패 시 수동 지정
- 캡컷 미설치 시 → ZIP으로 폴백 다운로드

#### 타임라인 구성 (3 트랙)

**Track 1. 자막 (일본어)**
- 섹션 [2. 자막용] 파싱
- 각 세그먼트당 텍스트 클립
- 위치: 하단 25% (시니어 시청성)
- 스타일: **Noto Sans JP Bold** · 흰색 · 검정 외곽선 2px · 크기 40pt
- 파이프 `|` 그대로 유지 (시안대로)

**Track 2. 비디오**
- 컷 순서대로 배치
- 각 컷:
  - 원음 컷: 원본 mp4 + `source_start`, `duration`
  - 나레이션 컷: 원음과 별개 세그먼트 (원본 프레임 유지, 오디오는 무음)
- 9:16 크롭 keyframe:
  - MediaPipe 얼굴 좌표 시퀀스 → 5fps 샘플링 → 스무딩 → keyframe 3~5초당 1개
  - 얼굴 없는 프레임: 이전 위치 유지
  - 여러 명: 프레임에 들어가면 넓힘, 안 되면 활발한 화자 우선

**Track 3. TTS 오디오**
- 나레이션 세그먼트 위치에 wav 배치
- 원음 구간엔 없음 (원본 오디오가 그대로 들리는 부분)
- 볼륨: 1.0 (원본 오디오는 자동 ducking 0.3)

#### 캡컷 자동 실행
- 완료 후 [🎬 캡컷에서 열기] 버튼
- OS별 명령:
  - Mac: `open -a CapCut`
  - Windows: 캡컷 exe 경로 지정

---

## 4. 통합대본 스펙

### 4섹션 구조
```
===================
【1. 의미 확인용】
===================
   タイトル : ジムクリップの | 天才的な | 発明
   (타이틀 : 헬스장 클립의 | 천재적인 | 발명 |
    타이토루 | 지무쿠립푸노 | 텐사이테키나 | 핫메에)

   耐久性もない | 使いにくい | 安全でもない
   (내구성도 없고 | 사용자 친화적이지 않고 | 안전하지도 않다 |
    "They're not durable, they're not user-friendly, and they're not safe.")

===================
【2. 자막용】
===================
   ジムクリップの | 天才的な | 発明
   既存クリップの | 問題点を | 指摘するんだけど
   ...

===================
【2-1. 영어 확인】
===================
   ジムクリップの | 天才的な | 発明
   既存クリップの | 問題点を | 指摘するんだけど
   "They're not durable, they're not user-friendly, and they're not safe."
   "Wow."
   ...

===================
【3. TTS용】
===================
   ジムクリップの天才的な発明
   既存クリップの問題点を指摘するんだけど
   ...
```

### 파싱 규칙
```python
def parse_unified_script(text):
    sections = extract_sections(text)  # === 【N. 이름】 === 파싱
    return {
        "review":   parse_review(sections["1. 의미 확인용"]),
        "subtitle": parse_subtitles(sections["2. 자막용"]),
        "segments": parse_segments(sections["2-1. 영어 확인"]),
        "tts":      parse_narrations(sections["3. TTS용"])
    }

def parse_segments(text):
    """[2-1] → 원음/나레이션 분기"""
    segments = []
    for i, line in enumerate(text.splitlines()):
        line = line.strip()
        if not line: continue
        if line.startswith('"') and line.endswith('"'):
            segments.append({"idx": i, "type": "original", "text": line.strip('"')})
        else:
            segments.append({"idx": i, "type": "narration", "text": line})
    return segments
```

### 원본 진실은 [1] 만
- 사용자가 편집 가능한 유일한 섹션
- [2], [2-1], [3]은 [1]에서 자동 파생
- 파이프 개수 정합성 자동 검증 (한/일 파이프 개수 다르면 오류)
- [1] 저장 시 나머지 자동 재생성

### 파이프 `|`의 3가지 역할
| 역할 | 대상 | 처리 |
|---|---|---|
| 시각 자막 구분 | [2] → 캡컷 | 그대로 유지 (일본어 띄어쓰기 대체) |
| 매칭 세그먼트 마커 | [2-1] → 컷편집 | 세그먼트 분할 |
| TTS 호흡 pause | [3] → VOICEVOX | 파이프 제거 (자연 발음) |

---

## 5. 데이터 모델

### SQLite 스키마 (MVP)

```sql
-- 사용자 (Google OAuth)
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    google_id TEXT UNIQUE NOT NULL,
    email TEXT NOT NULL,
    name TEXT,
    picture_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    settings JSON
);

-- OAuth 토큰 (리프레시용)
CREATE TABLE oauth_tokens (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    access_token TEXT,
    refresh_token TEXT,
    expires_at TIMESTAMP
);

-- 레퍼런스 채널 (유저별)
CREATE TABLE ref_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    channel_id TEXT NOT NULL,  -- YouTube 채널 ID
    title TEXT,
    subscribers INTEGER,
    avg_views_shorts INTEGER,
    avg_views_long INTEGER,
    category TEXT,  -- 가족/역경극복/친절/황혼열정/기타
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_refreshed_at TIMESTAMP,
    UNIQUE(user_id, channel_id)
);

-- 영상 캐시
CREATE TABLE videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT UNIQUE NOT NULL,
    channel_id TEXT,
    title TEXT,
    duration_seconds INTEGER,
    format TEXT,  -- shorts / long
    views INTEGER,
    published_at TIMESTAMP,
    thumbnail_url TEXT,
    subtitle_available BOOLEAN,
    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 검색 히스토리
CREATE TABLE searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    query TEXT,
    filters JSON,
    result_count INTEGER,
    searched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 컬렉션
CREATE TABLE collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    name TEXT NOT NULL,
    description TEXT,
    cover_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE collection_items (
    collection_id INTEGER REFERENCES collections(id),
    video_id TEXT REFERENCES videos(video_id),
    note TEXT,
    order_index INTEGER,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (collection_id, video_id)
);

-- 북마크
CREATE TABLE bookmarks (
    user_id INTEGER REFERENCES users(id),
    video_id TEXT REFERENCES videos(video_id),
    bookmarked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, video_id)
);

-- 알림
CREATE TABLE notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    type TEXT,  -- new_video / viral / system
    title TEXT,
    body TEXT,
    payload JSON,
    read_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 통합대본
CREATE TABLE scripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    source_video_id TEXT,
    title TEXT,
    section_1 TEXT,  -- 의미 확인용
    section_2 TEXT,  -- 자막용
    section_2_1 TEXT,  -- 영어 확인
    section_3 TEXT,  -- TTS용
    settings JSON,  -- 톤, 길이, 파이프 밀도
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- TTS 생성 기록
CREATE TABLE tts_generations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    script_id INTEGER REFERENCES scripts(id),
    engine TEXT,  -- voicevox / openai / elevenlabs
    speaker_id TEXT,
    speed FLOAT,
    zip_path TEXT,
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 컷편집 잡 (백그라운드)
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,  -- UUID
    user_id INTEGER REFERENCES users(id),
    script_id INTEGER REFERENCES scripts(id),
    long_video_url TEXT,
    tts_files JSON,  -- ["01.wav", "02.wav", ...]
    title_read BOOLEAN,
    mode TEXT,  -- unified / shorts_match
    project_name TEXT,
    status TEXT,  -- pending / running / completed / failed
    current_step INTEGER,  -- 0-5
    progress FLOAT,  -- 0.0 ~ 1.0
    error_message TEXT,
    capcut_project_path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

-- 컷 리스트
CREATE TABLE cuts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT REFERENCES jobs(id),
    segment_idx INTEGER,
    type TEXT,  -- original / narration
    text TEXT,
    start_seconds FLOAT,
    end_seconds FLOAT,
    confidence FLOAT,  -- 0.0 ~ 1.0
    excluded BOOLEAN DEFAULT FALSE,
    adjusted BOOLEAN DEFAULT FALSE,
    tts_file TEXT
);
```

---

## 6. 배포 아키텍처

### MVP (사용자 PC 로컬 실행)
```
[사용자 PC]
├── Next.js Dev Server (localhost:3000)
├── FastAPI (localhost:8000)
├── Redis (localhost:6379) — RQ 큐
├── SQLite 파일 (~/JapanShorts/data.db)
├── 파일 저장 (~/JapanShorts/materials/)
└── Docker Compose 로 통합 실행
```
- 실행: `docker compose up` 하나로 전체 스택 부팅
- 사장님 PC 배포: 실행 배치 파일 (`일본쇼츠실행.bat`)

### SaaS 확장 (프로덕션)
```
[Vercel]              → Next.js 프론트
[Railway / Fly.io]    → FastAPI 백엔드 + Redis + Worker
[Cloudflare R2]       → 파일 저장
[Supabase / Neon]     → PostgreSQL
[Google Cloud]        → OAuth · YouTube API · TTS
```
- 캡컷 자동 생성은 **로컬 실행 필수** (사용자 PC의 캡컷 폴더에 써야 함)
- SaaS는 대본 생성·TTS까지 → 컷편집만 사용자 PC에서 실행

---

## 7. 구현 로드맵

### Phase 0 — 기반 (1주)
- [ ] Next.js + FastAPI 프로젝트 세팅
- [ ] Google OAuth (NextAuth.js)
- [ ] SQLite 스키마 · 마이그레이션
- [ ] 공통 UI 컴포넌트 (사이드바 · 카드 · 뱃지)
- [ ] 포털 메인 (3-도구 랜딩)

### Phase 1 — RefTracker MVP (2주)
- [ ] 검색 화면 (키워드 · 필터 · 결과 그리드)
- [ ] 배수 계산 로직
- [ ] 레퍼런스 채널 등록·관리
- [ ] 북마크
- [ ] YouTube API 캐싱 (쿼터 절약)

### Phase 2 — 번역봇 MVP (2주)
- [ ] STEP 1: 유튜브 링크 · 자막 추출 · 미리보기
- [ ] STEP 2: Gemini 번역 · 파이프 자동 삽입
- [ ] STEP 3: 통합대본 4섹션 자동 생성 · 사용자 편집
- [ ] TTS 생성 (VOICEVOX 우선 · OpenAI/ElevenLabs)
- [ ] ZIP 다운로드 + 자동 압축해제

### Phase 3 — 컷편집 MVP (3주)
- [ ] 통합대본 모드 입력 폼
- [ ] 파이프라인 6단계 백그라운드 잡 (RQ)
- [ ] Whisper STT
- [ ] Gemini 번역 (STT → 한국어)
- [ ] 의미 매칭 (신뢰도 %)
- [ ] MediaPipe 얼굴 추적 + 9:16 크롭 keyframe
- [ ] 검토 & 조정 화면
- [ ] 캡컷 draft_content.json 생성

### Phase 4 — 통합 완성 (2주)
- [ ] 트렌드 피드 크론 + 알림
- [ ] YouTube 발굴 (카테고리 브라우징)
- [ ] 컬렉션 관리
- [ ] 쇼츠 매칭 모드
- [ ] 개별 컷 조정 (파형 드래그)
- [ ] 작업 목록 상세

### Phase 5 — 폴리싱 (1주)
- [ ] 다크모드
- [ ] 반응형 (모바일 접속 시 축소 뷰)
- [ ] 온보딩 튜토리얼
- [ ] 에러 리포팅 (Sentry)
- [ ] 사용량 대시보드

**총 예상 기간: 11주 (약 2.5개월)**

---

## 8. 리스크·대응

| # | 리스크 | 영향 | 대응 |
|---|---|---|---|
| 1 | **캡컷 JSON 포맷 변경** | 프로젝트 자동 생성 실패 | 캡컷 버전 감지 · 포맷 v1/v2 어댑터 · 실패 시 ZIP 폴백 |
| 2 | **YouTube API 쿼터** | 검색·수집 중단 | 쿼터 캐싱 (배수 계산 통계 24시간 유지) · 사용자별 개인키 지원 |
| 3 | **TTS 비용** (OpenAI/ElevenLabs) | 월 사용료 폭증 | VOICEVOX 기본 · 유료 엔진은 사용자 개인키 |
| 4 | **얼굴 감지 성능** | 파이프라인 지연 | 5fps 샘플링 + 프레임 캐싱 · GPU 있으면 활용 |
| 5 | **저작권** | 유튜브 채널 페널티 | 인용 범위 준수 · 소스 채널에 허가 요청 옵션 · 페어유스 가이드 |
| 6 | **매칭 신뢰도 낮음** | 컷 위치 어긋남 | 조정 UI 필수 · 신뢰도 <50% 자동 강조 · Gemini 재매칭 옵션 |
| 7 | **일본어 톤 이슈** | 시니어에게 어색 | 시니어 친화 어휘 사전 · 검증자(다른 LLM) 재점검 |
| 8 | **캡컷 프로젝트 폴더 못 찾음** | 자동 저장 실패 | 자동 감지 + 수동 지정 UI · ZIP 폴백 |

---

## 부록. Q&A 결정 이력

시안 리뷰 중 물어봤던 질문·답변 요약 (구현 시 참조).

### RefTracker
| # | 질문 | 결정 |
|---|---|---|
| A1 | 사이드바 순서 | 시안대로 (트렌드 피드 → YouTube 발굴 → 검색 → 레퍼런스 채널 → 컬렉션 → 북마크 → 알림 → 설정) |
| A2 | 트렌드 피드 vs YouTube 발굴 | 트렌드 피드=등록 채널 자동 알림 / YouTube 발굴=카테고리·인기 급상승 브라우징 |
| B1 | 최근 검색 chip `3m` | 3개월 전 검색 (히스토리 기간) |
| C1 | "내 레퍼런스 채널만" | 등록 채널의 영상만 검색 |
| D1 | 언어 멀티/단일 | 멀티 체크박스 |
| D2 | 언어 뜻 | 영상 언어 (YouTube API `relevanceLanguage`) |
| E1 | ⭐ 별 | 북마크 토글 |
| F1 | `+ 추가` | 채널을 레퍼런스로 등록 |
| F2 | `✓ 등록` 표시 | 배수 뱃지 + 등록 뱃지 |
| G1 | 배수 계산 | 영상조회수 ÷ 채널 평균조회수 (형식별 분리) |
| G2 | 평균 모수 | 최근 20개 영상 (Shorts/롱폼 분리 평균) |
| H1 | 📜 자막 | 자막 팝업 + 번역봇 이송 |
| H2 | ✏️ 원본 | 유튜브 새 탭 |
| H3 | 📰 유사 | YouTube related + LLM 유사도 |
| H4 | 🔗 링크 | URL 클립보드 복사 |
| I1 | 필터 클라이언트 사이드 | ✅ 확정 |
| J1 | 유저 유형 | 멀티 유저 (Google OAuth) |
| J2 | 데이터 분리 | 유저별 완전 분리 |
| K1 | 스택 | Next.js 14 + FastAPI |
| K2 | 저장소 | 이 repo에 서브폴더 → 안정화 후 분리 |
| L1 | 채널 탭 | 검색어 매칭 채널 리스트 |
| L2 | 배수 색상 | ×2회색 → ×5주황 → ×10빨강 → ×50진빨강 |

### 번역봇
| # | 질문 | 결정 |
|---|---|---|
| M1 | 파이프 용도 | 자막 시각 구분 · 매칭 세그먼트 · TTS 호흡 |
| M2 | "인서" 뜻 | Insert (텍스트 자동 생성) |
| M3 | ZIP 파일 순서 | 01=제목 · 02~N=나레이션 순번 |
| M4 | 도구간 전달 | 세션 (Job ID + 공유 DB) |
| M5 | ElevenLabs 목소리 | 엔진별 별도 리스트 |

### 컷편집
| # | 질문 | 결정 |
|---|---|---|
| N1 | 캡컷 포맷 | 프로젝트 폴더 직접 쓰기 (draft_content.json 등) |
| N2 | 두 모드 차이 | 통합=1롱폼→1쇼츠 / 쇼츠매칭=여러 쇼츠 대본→1롱폼 |
| N3 | 원음/나레이션 감지 | 섹션 [2-1] 큰따옴표 |
| N4 | 9:16 변환 | MediaPipe 얼굴 추적 크롭 |
| N5 | 자막 스타일 | Noto Sans JP Bold · 흰색 · 검정 외곽선 40pt |
| N6 | 작업 목록 | 진행/완료/실패 3탭 |
| N7 | 파일 부족 시 | 실시간 경고 표시 · 실행 불가 |
| P1 | 파일명 자리수 | 2자리 (`01.wav`) |
| P2 | 번호 규칙 | 순번 · 스킵 없음 |
| P3 | WAV 포맷 | VOICEVOX 원본 (24kHz mono 16-bit) |
| P4 | ZIP 구조 | 프로젝트명 폴더 감싸기 |
| P5 | Mac 숨김 파일 | 자동 필터 |
| P6 | 자동 압축 해제 | 앱이 자동 |
| P7 | 속도 적용 시점 | 파일에 이미 적용 |
| R1 | URL 미리보기 | 즉시 (썸네일·제목·길이) |
| R2 | 링크 vs 업로드 | 링크 기본 · 업로드는 로컬 파일 대안 |
| R3 | 쇼츠 URL | 롱폼 전용 (쇼츠 URL 거부) |
| S1 | 조정 UX | 파형 + 시작/끝 드래그 핸들 |
| S2 | 제외 | 삭제 · 앞뒤 컷 합침 |
| S3 | 신뢰도 임계값 | <50% 빨강 · <70% 노랑 |
| S4 | 다시 생성 | 조정된 컷만 재처리 |
| S5 | 다운로드 링크 | 없음 (캡컷 직접 통합) |
| T1 | 쇼츠 처리 | 대본 파싱 · [2-1] 분석 |
| T2 | 시각 매칭 보강 | 얼굴 감지 + 씬 감지 |
| T3 | 진행 시간 | 24분 영상 기준 5~10분 |
| T4 | 실패 UX | 어느 단계 실패 · 재시도 · 부분 결과 |
| T5 | 페이지 이탈 | 백그라운드 계속 · 완료 시 🔔 |
| U1 | 캡컷 버전 | 데스크톱 (한국·글로벌판) |
| U2 | 프로젝트명 | `AutoCut_{hash}_{slug}` |
| U3 | 자동 편집 범위 | 컷 + 자막 + TTS 배치 (색보정·BGM은 사용자) |
| U4 | 저신뢰 표시 | 캡컷에서 마커 |
| U5 | 폴백 | ZIP 다운로드 · 캡컷 설치 안내 |
| U6 | 캡컷 자동 실행 | 옵션 버튼 |
| V1 | 다중 화자 | 프레임에 들어가면 넓힘 · 안 되면 활발한 화자 |
| V2 | 얼굴 없음 | 이전 크롭 유지 |
| V3 | 파이프 자막 표시 | 그대로 유지 |
| V4 | 자막 스타일 | Noto Sans JP Bold |
| V5 | 얼굴 추적 성능 | 5fps + 스무딩 |
| W1 | STEP 1·2 | 위 설계 |
| W2 | [1] 수정 시 파생 | 자동 |
| W3 | [2-1] 자동 생성 | 필수 |
| X1 | [1] 만 편집 | ✅ 확정 |

---

## 🚀 다음 단계

1. **Phase 0 시작 승인 여부 확인** — 사장님 GO 사인
2. **저장소 결정** — 이 repo 서브폴더 vs 새 repo
3. **API 키 준비** — YouTube · Gemini (`.env`)
4. **로컬 개발 환경 셋업** — Docker Compose 파일 작성

준비되시면 Phase 0부터 착수하겠습니다.

---

*© 2026 박남정 · 이 설계는 whiteh2r@gmail.com 전용 · 재배포 금지*
