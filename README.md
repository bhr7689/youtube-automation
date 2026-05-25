# 🎵 YouTube 음악 채널 자동화 파이프라인

급상승 레퍼런스 채널 발굴 대시보드 (Phase 1)

## 개요

상황/감정 키워드(예: "비 오는 날 카페", "잠 안 올 때 듣는 lofi")로 최근 N일 내 업로드된
YouTube 영상을 검색해, **구독자 수 대비 조회수 비율이 폭발적인 신규/소형 채널**만
필터링해 리스트업하는 Streamlit 대시보드입니다.

## 빠른 시작

### 1. YouTube Data API v3 키 발급
1. https://console.cloud.google.com/ 접속
2. 새 프로젝트 생성 → **APIs & Services → Library**
3. `YouTube Data API v3` 검색 후 **사용 설정**
4. **Credentials → Create Credentials → API key** 생성

### 2. 설치 및 실행
```bash
# 가상환경 (선택)
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt

# API 키 설정
cp .env.example .env
# .env 파일을 열어 YOUTUBE_API_KEY=... 입력

# 대시보드 실행
streamlit run app.py
```

브라우저에서 자동으로 `http://localhost:8501` 이 열립니다.

## 사용법

1. 사이드바에 **상황/감정 기반 키워드**를 줄바꿈으로 입력
2. 검색 기간(최근 N일), 키워드당 결과 수 조정
3. **급상승 필터** 설정
   - 최대 구독자 수 (예: 10,000 이하)
   - 최소 조회수 (예: 5,000 이상)
   - 최소 조회수/구독자 비율 (예: 2.0 이상 = 구독자보다 조회수가 2배 많은 영상)
4. **🚀 발굴 시작** 클릭
5. 결과 CSV 다운로드 가능

## 파일 구조

```
youtube-automation/
├── app.py              # Streamlit 대시보드 메인
├── requirements.txt    # Python 의존성
├── .env.example        # API 키 템플릿
├── .gitignore
└── README.md
```

## API 할당량 메모

YouTube Data API v3 무료 할당량: **하루 10,000 units**
- `search.list` : 100 units / 호출
- `videos.list` : 1 unit / 호출 (최대 50개 ID)
- `channels.list` : 1 unit / 호출 (최대 50개 ID)

키워드 4개 × 50개 결과 검색 ≈ 400 units. 결과는 30분간 캐시됩니다.

## 분석 기능

발굴된 영상 리스트 아래에 두 개의 분석 섹션이 자동 표시됩니다.

### 🧩 제목 패턴 분석
- 1/2/3-gram 빈도 (한·영 토크나이즈, 불용어 제거)
- 평균 글자수·단어수, 이모지/괄호 포함 비율
- **고성과 단어 (Lift)** — 조회/구독 비율 상위 25% 영상에서 두드러진 단어

### 🎬 제목 서사 분석
- **장면 태깅** — 시간(새벽/밤…), 날씨(비/눈…), 장소(카페/방…), 활동(공부/수면…), 감정(위로/감성…), 장르(lofi/재즈/피아노…)
- **서사 골격** — "비 · 카페 · lofi" 처럼 카테고리 단서를 정해진 순서로 이어 만든 스토리 템플릿
- **고성과 서사 (Lift)** — 어떤 골격이 상위 25% 영상에서 반복되는지
- **청자 페르소나** — "공부할 때", "혼자 위한", "for studying" 등 누구를 위한 BGM 인지 시사하는 표현
- **카테고리 동시 출현** — 어떤 장면 조합이 자주 묶이는지 (예: 비 × 카페)
- **지배 서사 한 줄 요약** — 카테고리별 1위를 이어 자동 생성

### 🎯 알고리즘 추천 제목 & 태그
- **5개 추천 제목** — 분석된 장면/감정/페르소나/장르 표면형을 10여 종 한국어/영문 템플릿에 끼워 자동 합성
- **🔄 다시 생성** — 무작위 시드를 바꿔 새로운 5개 생성. 동일 시드/키워드면 결과 재현 가능
- **시드 테마** — "비 오는 새벽" 같은 강조 키워드를 넣으면 자연스럽게 결합
- **언어 토글** — 자동 감지(데이터 기반) / 한국어 / English
- **추천 태그** — 검색 키워드 + 카테고리 표면형(KR+EN) + 고성과 단어 + `lofi for studying` 같은 콤보 태그까지 25개

### 🖼️ 썸네일 분석 (색감 · 구도 · 인물 · 배경)
- **색감** — PIL `quantize` 로 상위 5색 팔레트 추출, 무드 매핑(warm orange / cool blue / near black …), 평균 밝기·채도·색온도 계산
- **구도** — 9분할 격자에서 휘도 무게중심으로 포컬 포인트(좌하단/정중앙/…) 추정
- **인물** — OpenCV Haar cascade 로 얼굴 개수 + 화면 점유율 (opencv 미설치 시 자동 스킵)
- **배경 톤 추정** — 인물 비중 + 평균 밝기/색온도로 "중심 인물 위주" vs "환경 중심" 분류
- **분석된 썸네일 미리보기** — 상위 N개 썸네일을 카드로 펼쳐 시각 비교

### 🎬 영상 합성 (탭 3 — 인코딩)
직접 만든 곡과 배경을 합쳐 유튜브 업로드용 MP4 를 만드는 ffmpeg 기반 워크플로.

- **다중 트랙 업로드** — 업로드 순서대로 ffmpeg `concat` 필터로 한 트랙으로 결합 → 1~4시간 분량 mix 영상 제작 가능
- **배경 영상/이미지** — 이미지면 정지 프레임으로 늘이고, 영상이 오디오보다 짧으면 `-stream_loop` 로 자동 루프
- **자막 SRT 자동 생성** — 곡별 가사 텍스트영역에 한 줄 한 라인으로 입력 → 각 트랙 내부는 균등 분배, 트랙 간 누적 타임스탬프로 단일 SRT 출력
- **자막 burn-in 옵션** — 영상 픽셀에 직접 가사를 새기거나, 끄고 SRT 파일만 받아 유튜브 CC 트랙으로 별도 첨부 가능
- **인코딩 옵션** — 해상도(720p~4K) · 오디오 비트레이트 · CRF · 페이드 인/아웃 초
- **결과 카드** — MP4 미리보기(500MB 이하), MP4/SRT 별도 다운로드, "임시 파일 삭제" 정리 버튼

**선결 조건**: 시스템에 `ffmpeg` (+ `ffprobe`) 설치 필요. 미설치 시 탭 진입 시 설치 가이드 카드만 노출하고 다른 탭에는 영향 없음.

```bash
# macOS
brew install ffmpeg
# Ubuntu / Debian (이 프로젝트 서버 환경)
sudo apt-get install -y ffmpeg
# Windows (winget)
winget install --id=Gyan.FFmpeg -e
```

> **이 리포지토리의 클라우드 실행 환경에는 ffmpeg 6.1.1 이 이미 설치되어 있습니다.**

`.streamlit/config.toml` 에 `maxUploadSize = 1024` (MB) 가 설정되어 있어 1시간 mp3 여러 개 + 배경 영상 동시 업로드가 가능합니다.

### ✍️ AI 스토리텔링 & 가사 생성 (탭 2)
상단의 두 번째 탭. **OpenAI 또는 Google Gemini** API 키와 채널 컨셉(주제·감정)을 입력하면 다음 3개를 한 번에 생성합니다.

- **[유튜브 SEO]** — 썸네일 헤드라인 3개, 제목 5개(서로 다른 진입각), 설명란, 해시태그 12~15개 (JSON 응답을 파싱)
- **[오프닝 대본]** — 15~30초 AI 음성 더빙용 내레이션, 한 줄 한 호흡
- **[음악 맞춤형 가사]** — `[Verse 1] / [Pre-Chorus] / [Chorus] / [Verse 2] / [Bridge] / [Outro]` 완전 구조 + Suno/Udio 호환 영문 Style Prompts

대본·가사의 톤 가이드는 모든 프롬프트에 자동 주입됩니다:
- 공감·위로·평안함의 언어, "사랑받고 있다"는 느낌
- **청취자의 마음(감정)과 육신(몸의 건강·컨디션)을 묻는 질문을 반드시 포함**
- 단정형 지양, 청유형·물음형 위주

각 카드는 `st.code` 의 복사 아이콘으로 원클릭 클립보드 복사가 가능하고, Markdown/Text 다운로드 버튼도 함께 제공합니다.

기본 모델: Gemini `gemini-2.0-flash`, OpenAI `gpt-4o`. 모델 ID 칸에 다른 모델을 입력해 오버라이드 가능.

### 🎨 썸네일 추천 프롬프트 (Text-to-Image)
- **5종 스타일** — anime/lofi · cinematic photo · 3d diorama · minimal vector · painterly oil
- 분석된 색 무드, 밝기 라벨, 포컬 포인트, 인물 비중을 그대로 프롬프트에 주입
- Negative prompt 동봉, Markdown 으로 일괄 다운로드
- **🔄 다시 생성** + 비주얼 컨셉 시드 입력 가능

### 🎚️ Suno 프롬프트 스튜디오 (탭 5)
나라·무드·보컬·악기·솔로·리듬·빠르기를 **빌딩블록처럼 골라 Suno 스타일 프롬프트를 즉시
조립**하고, 마음에 든 조합과 **'비슷한 유형'의 변주를 여러 개 자동 생성(벤치마킹)**합니다.

어휘는 코드가 아닌 **`vocab.json`(통제 어휘 사전)**에 데이터로 보관 — 항목마다 `country`/`mood`
태그가 붙어 프리셋(나라)·무드를 고르면 후보가 자동 필터링됩니다. 조립 로직은 Streamlit 의존이
없는 **`suno_studio.py`** 엔진에 있어 대시보드와 향후 n8n/Gemini 자동화가 동일 엔진을 씁니다.

- **차원**: 장르/나라 앵커 · 무드 · 리듬 패턴 · 악기 · 솔로/간주 · 보컬(편성/성별/음색·음역/기교) · 프로덕션 · BPM
- **음색/음역**: 중저음(굵은) · 중음 · 고음(남/여 미성) · 허스키 · 맑은
- **보컬 기교**: 비브라토 · 꺾기(KR) · 코부시(JP) · 벨팅 · 크루닝
- **자동 추천**: 무드만 고르면 차원별로 무작위 조합 1건 제안 (시드 고정 시 재현 가능)
- **벤치마킹 변주**: 현재 조합을 기준으로, 고정할 차원(예: 무드·성별)만 잠그고 나머지를 다시
  샘플링해 서로 다른 N개 변주를 생성. 마음에 든 곡 스타일로 양산할 때 사용
- **확장**: `vocab.json` 에 프리셋(`jp_enka`, `global_senior`)과 어휘만 추가하면 나라 확장 완료
- **📒 나만의 레시피**: 마음에 든 조합을 이름 붙여 `recipes.json`(내 자산)에 저장 → 불러와 변주 생성,
  여러 레시피를 **블렌딩**(단일 차원은 하나 선택, 다중 차원은 합집합, BPM 평균)해 새 조합 합성.
  엔진은 `recipes.py`. 향후 역설계 분석기가 추출한 picks 도 같은 형식으로 적재 → 스타일 지문 자산화

```bash
python suno_studio.py   # 헤드리스 데모: 자동 추천 1건 + 벤치마킹 변주 4건 출력
```

## 🤖 무인 자동화 파이프라인 (`pipeline.py` — mp3 → MP4)

대시보드(`app.py`)가 사람이 보고 조작하는 도구라면, `pipeline.py` 는 **사람 없이 매일
도는 헤드리스 엔진**입니다. **폴더를 통합 지점**으로 삼아, 사람이 직접 Suno 결과 mp3 를
떨구든 / 비공식 Suno API 가 자동으로 떨구든 **동일하게 동작**합니다 (느슨한 결합).

인코딩·자막·합성 로직은 대시보드 합성 탭과 **`media_core.py` 를 공유**합니다 (단일 소스).

### 폴더 구조 (`--root`, 기본 `./pipeline_data`)

```
pipeline_data/
├── inbox/<job_id>/      # 작업 투입: job.json + 오디오(.mp3 …) + (선택) 배경
├── output/<job_id>/     # 결과물: <job_id>.mp4, <job_id>.srt, meta.json
├── processed/<job_id>/  # 성공한 입력 보관 (재처리 방지 = 멱등성)
├── failed/<job_id>/     # 실패한 입력 + error.log
└── pipeline_log.jsonl   # 처리 이력 (한 줄 = 한 건)
```

### job.json (모두 선택 · 합리적 기본값)

```json
{
  "title": "달려보자 인생길",
  "audio": ["track1.mp3", "track2.mp3"],
  "background": "bg.jpg",
  "background_color": "0x101418",
  "lyrics": "얼씨구 좋다\n달려보자 인생길",
  "resolution": "1920x1080",
  "audio_bitrate": "192k",
  "crf": 22,
  "fade_seconds": 2.0,
  "burn_subtitles": false
}
```

- `audio` 생략 → 폴더 내 오디오 파일을 이름순으로 전부 이어붙임
- `background` 생략 → 폴더 내 이미지/영상 자동 탐색, 그래도 없으면 `background_color` 단색 배경 자동 생성
- `lyrics` 입력 → 길이에 맞춰 균등 분배한 SRT 자동 생성 (`tracks` 로 곡별 가사도 가능)
- `burn_subtitles: true` → 영상에 자막 굽기, `false` → SRT 파일만 별도 출력
- 부분 업로드 방지: 폴더가 `--min-age` 초(기본 10) 동안 변경 없으면 "준비됨" 으로 판단. `.ready` 빈 파일을 넣으면 즉시 처리

### 실행

```bash
python pipeline.py init                      # 폴더 구조 + 샘플 job 생성
python pipeline.py --once                    # inbox 1회 스캔 후 종료 (cron / n8n Execute Command 용)
python pipeline.py --watch --interval 30     # 데몬 모드 (폴더 상시 감시)
```

`--once` 는 외부 스케줄러(cron, n8n)가 주기적으로 호출하는 용도, `--watch` 는 자체 폴링
데몬으로 상주시키는 용도입니다. ffmpeg(+ffprobe) 설치가 필요합니다.

## 로드맵

- [x] Phase 1: 급상승 레퍼런스 채널 발굴 대시보드
- [x] Phase 1.5: 제목 패턴 & 서사 분석
- [x] Phase 1.6: 알고리즘 친화적 제목/태그 합성
- [x] Phase 1.7: 썸네일 색감/구도/인물 분석 + T2I 프롬프트
- [x] Phase 1.8: AI 스토리텔링 — SEO · 오프닝 대본 · 구조화된 가사
- [x] Phase 1.9: 영상 합성 — 다중 트랙 concat + 가사 SRT (선택 burn-in) + MP4 인코딩
- [x] Phase 2.0: 가사 자동 동기화 — Whisper API 기반 SRT 생성 (CapCut/Premiere 임포트용)
- [x] Phase 2.1: 무인 mp3 → MP4 합성 파이프라인 (`pipeline.py`, 폴더 감시 · 멱등 · cron/n8n 연동)
- [x] Phase 2.2: Suno 프롬프트 스튜디오 (`vocab.json` + `suno_studio.py`, 조합·자동추천·벤치마킹 변주)
- [x] Phase 2.3: 나만의 레시피 저장·블렌딩 (`recipes.py` + `recipes.json`)
- [ ] Phase 2.4: 역설계 분석기 — 유튜브 링크 → 스타일 추출 → picks (하이브리드: 메타데이터 + 선별 오디오)
- [ ] Phase 2: 자동 발굴 스케줄러 (cron + Slack/Sheets 동기화)
- [ ] Phase 3: 오프닝 TTS 자동 더빙 + Suno 연동 (수동 B / 비공식 API A)

### 🎤 가사 자동 동기화 (탭 4 — SRT 생성)
직접 만든 곡의 가사를 **실제로 불리는 시점에 정확히** 맞춘 SRT 자막을 만들어 CapCut/Premiere/Davinci 에 그대로 임포트하기 위한 도구.

- **입력**: MP3/WAV/FLAC/M4A 등 오디오 또는 MP4/MOV 영상 (영상이면 자동으로 오디오 추출)
- **OpenAI Whisper API** (`whisper-1`, segment + word level timestamps) 호출 — 약 $0.006/분
- **두 가지 모드**
  - **Whisper 인식 결과 그대로** — 가사 미입력 시 자동. 텍스트는 Whisper 가 들은 그대로
  - **내 가사를 Whisper 타이밍에 정렬** — 직접 쓴 가사 텍스트를 Whisper 가 잡은 구간에 매핑. 라인 수와 구간 수가 달라도:
    - L = N: 1:1 매핑
    - L < N: 인접 구간을 묶어 1라인에 흡수
    - L > N: 한 구간을 길이로 비례 분할해 여러 라인에 분배
- **25MB 자동 압축** — Whisper API 업로드 한도를 넘으면 mono 64kbps 22kHz MP3 로 다운샘플 후 재시도
- **언어 명시 옵션** — ko/en/ja/zh 또는 자동 감지. 명시하면 인식 정확도 ↑
- **다운로드 + 인라인 미리보기** — `.srt` 파일은 CapCut "자막 → 자막 가져오기 (SRT)" 로 즉시 임포트 가능
