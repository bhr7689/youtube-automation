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
# Ubuntu / Debian
sudo apt-get install -y ffmpeg
# Windows (winget)
winget install --id=Gyan.FFmpeg -e
```

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

## 로드맵

- [x] Phase 1: 급상승 레퍼런스 채널 발굴 대시보드
- [x] Phase 1.5: 제목 패턴 & 서사 분석
- [x] Phase 1.6: 알고리즘 친화적 제목/태그 합성
- [x] Phase 1.7: 썸네일 색감/구도/인물 분석 + T2I 프롬프트
- [x] Phase 1.8: AI 스토리텔링 — SEO · 오프닝 대본 · 구조화된 가사
- [x] Phase 1.9: 영상 합성 — 다중 트랙 concat + 가사 SRT (선택 burn-in) + MP4 인코딩
- [ ] Phase 2: 자동 발굴 스케줄러 (cron + Slack/Sheets 동기화)
- [ ] Phase 3: 오프닝 TTS 자동 더빙 + 영상 자동 합성 파이프라인
