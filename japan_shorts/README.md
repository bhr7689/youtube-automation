# 🎬 일본쇼츠 자동 프로그램

해외 예능/리얼리티 쇼츠 소스를 발굴 → 일본어 번역·TTS → 자동 컷편집하여
**일본 시니어 타깃 유튜브 쇼츠 채널**을 자동화하는 통합 프로그램.

> 전체 설계도: [`../ideas/japan_senior_architecture.md`](../ideas/japan_senior_architecture.md)

## 3개 도구
- 📺 **RefTracker** — 채널 등록·트렌딩·검색·컬렉션 (← **지금 구현됨: 검색 화면**)
- 🌸 **번역봇** — 영/한 대본 → 일본어 쇼츠 + TTS (예정)
- ✂️ **자동 컷편집** — 롱폼 + JP대본 → 쇼츠 MP4 (예정)

## 데이터 정확도 원칙 ⭐
- **정확**(YouTube 공식): 조회수·좋아요·댓글·구독자·업로드시각·길이
- **정확**(직접 계산): 배수(조회수÷채널 중앙값), 구독자 대비 배수, 시간당 조회수(VPH)
- **추정**(라벨 표시): 키워드 검색량·경쟁도 — 아무도 정확히 못 줌(vidIQ도 추정)

## 실행 방법

### Windows (사용자용)
`일본쇼츠실행.bat` 더블클릭 → 자동으로 서버 켜고 브라우저 열림.

### 수동 실행
```bash
cd japan_shorts
pip install -r requirements.txt
cp .env.example .env      # YOUTUBE_API_KEY 입력 (없으면 데모 모드)
python -m backend.main    # → http://127.0.0.1:8600
```

## 배수(multiplier) 계산 — 정확
```
채널 평균 = 그 채널 최근 15개 영상의 중앙값 조회수   # 이상치에 강함
배수 = round(영상 조회수 / 채널 평균, 1)              # 시안 ×38.1 방식
```
키가 없으면 데모 데이터로 화면이 뜹니다(시현용). 키를 넣으면 실데이터로 자동 전환.

## 폴더
```
japan_shorts/
├── backend/   main.py · youtube_api.py · mock_data.py · storage.py
├── frontend/  index.html (Tailwind 단일 페이지)
├── data/      app.db (gitignore)
└── 일본쇼츠실행.bat
```
