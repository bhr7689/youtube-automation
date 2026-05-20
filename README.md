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

## 로드맵

- [x] Phase 1: 급상승 레퍼런스 채널 발굴 대시보드
- [ ] Phase 2: 채널 심층 분석 (업로드 패턴, 썸네일/제목 트렌드)
- [ ] Phase 3: 콘텐츠 자동 생성 파이프라인
