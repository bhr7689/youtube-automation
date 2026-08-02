# 🌐 국가별 메타데이터 엔진 (KR/JP/US) — 기획서

> 작성: 2026-08-01 (claude/elements-tools-planning-list-yqqo2t)
> 목적: 가사 없는 곡(instrumental/BGM/ambient/piano/study/sleep) 1곡을
> **KR·JP·US 3개 로컬라이즈드 메타데이터 세트**(제목·설명·태그·해시태그 + **일치 썸네일**)로
> 자동 생성하는 대시보드. "제목 번역기"가 아니라 **국가별 검색 문법 기반 재작성 엔진.**

---

## 0. 경험자 결론 — 스택은 갈아엎지 말 것

브리프는 "React+Node로 새로 만들라"고 했지만, 사장님 자산은 **Python(FastAPI/Streamlit)** 이다.
새 스택으로 재작성 = 기존 70% 폐기. **기존 `jpshorts` 백엔드 + 정적 HTML 위에 탭 하나로 얹는다.**

핵심: **이 엔진의 부품 대부분이 이미 존재**한다. 새로 만들 건 "국가별로 묶는 오케스트레이션 +
SERP 검증 + 3세트 패키지 화면"뿐이다.

---

## 1. 브리프 7탭 ↔ 기존 자산 대조

| 브리프 탭 | 이미 있는 코드 | 판정 |
|---|---|---|
| **트렌드 레이더** (KR/JP/US 인기·급등) | `youtube_client.global_surge`(regionCode 멀티) · `search`(regionCode) | ✅ 있음 |
| **키워드 랩** (국가별 검색어 구조·품질) | `keyword_radar.rising_keywords`(lang별) · `keyword_heat`(14일 추세) | ✅ 있음(품질점수 보강) |
| **제목 생성기** (검색형/추천형 분리) | `concept_maker`(title_sets·클릭심리) · `nation_prompts`(나라 DNA) · `title_engine`(L1~L3 토큰) | ✅ 있음 |
| **설명글 생성기** (국가별 4단 구조) | `channel_desc_generator`(의식의흐름) · `lyrics_generator`(다국어) | ✅ 있음(4단 매핑) |
| **태그/해시태그** (핵심 3~5개) | `channel_desc_generator`(태그·해시태그) | ✅ 있음(개수 정책) |
| **SERP 검증** (시크릿 브라우저) | — (Playwright는 컨테이너에 있으나 미연결) | 🆕 **신규** |
| **업로드 패키지** (복붙/CSV/JSON) | 각 앱 `st.code` 복붙 블록 | ✅ 있음(3세트 묶기) |
| **일치 썸네일** (제목=썸네일) | `concept_maker.title_sets`(제목+thumb_text+씬) · `generate_thumbnail_image`(무드이식) · `thumb_overlay`(한글 렌더) | ✅ **있음 — 핵심 강점** |

→ **7탭 중 6탭 로직 존재. 신규는 SERP 검증 1개 + 국가별 오케스트레이션/패키지 화면.**

---

## 2. ⭐ 썸네일을 제목과 일치시키는 법 (사장님 질문의 답)

이미 `concept_maker`에 **"제목과 썸네일은 한 세트"** 철학이 구현돼 있다. 그대로 엔진에 연결한다.

### 원리 5단
1. **한 몸 생성** — 제목·`thumb_text`(썸네일에 얹을 문구)·`image_prompt`(씬)를
   **한 번의 호출에서 같이** 만든다. 따로 만들지 않으니 어긋날 수가 없다.
   (concept_maker `title_sets` = [{title, thumb_text, image_prompt}] ×N)
2. **패턴 접지(SERP 실측)** — 그 나라 고조회 썸네일 상위 N개를 **GPT Vision**으로 실측
   (색·구도·인물·헤어·텍스트 오버레이·무드) → 그 패턴을 `image_prompt`에 주입.
   생성 썸네일이 **그 나라 터지는 썸네일 풀과 같은 결**이 된다. (`analyze_thumbnails_vision`)
3. **역할 분담** — 제목 = **검색형**(핵심 키워드 앞배치, 검색 유입) ·
   썸네일 문구 = **후킹형**(호기심 한 방). 둘이 같은 소재를 다른 각도로 = 일치하되 중복 아님.
4. **무드 이식 생성** — `generate_thumbnail_image(refs=상위 썸네일)` → `images.edit`로
   그 나라 색감·조명·필름결을 85% 흡수(구도 복제 금지, 새 씬 15%).
5. **한글 깨짐 방지** — 문구는 GPT가 이미지에 새기되, 최종 보정은 `thumb_overlay.overlay_title`
   (PIL 로컬 렌더)로 폰트 통일·깨짐 0.

### 무가사 음악 채널 특화
- 제목도 썸네일도 **"언제·왜 듣는지"(용도)를 앞세운다** — 아티스트 브랜딩 X, 검색의도 O.
- KR: 아늑한 씬(카페·새벽·창가) + "집중이 되는" 류 상황 문구
- JP: 作業机·手元·文房具 씬 + "作業用BGM/勉強用" 관용 문구
- US: cozy desk/rain window 씬 + "Deep Focus / No Lyrics" use-case 문구
- → 국가별로 **씬·문구·화풍이 다른** 3장의 일치 썸네일이 나온다.

### 피드백 루프
업로드 후 성과(CTR·조회속도)로 **제목·썸네일 재생성** — 한 번 만들고 끝이 아니라 재학습.

---

## 3. 핵심 알고리즘 (브리프 점수식을 기존 로직에 매핑)

### Keyword Quality Score (저품질 키워드 자동 탈락)
`keyword_radar` 에 품질 점수 추가:
```
KQS = 상위10 평균조회 ×0.35 + (상위10 조회/업로드일) ×0.25
    + 3개국 확장성 ×0.15 + 무가사 적합도 ×0.15 - 신생저조회 점유율 ×0.10
```
→ "검색하면 신생 저조회만 뜨는 키워드"는 KQS 미달로 **버림**. (사장님이 겪은 문제 해결)

### Title / Video Trend Score
`viral_lab`·`tier_lab`의 배수·구간 로직 재사용 + 브리프 가중치로 랭킹.

---

## 4. SERP 검증 (유일한 실질 신규 — Playwright)

- **시크릿 세션**(로그인·이력 제거) + **국가 locale/프록시**로 실제 검색 화면 캡처
- 상위 10개 썸네일·조회수·업로드일·채널 수집 → **경쟁 강도** 계산
- 판정: *"내 제목으로 검색 시 상위가 고조회·최신·강채널인가?"* → Yes 채택 / No 자동 재작성
- ⚠️ **웹 컨테이너는 유튜브 프록시 차단** → SERP 검증은 **사장님 PC(Playwright 로컬)** 에서 작동.
  API 1차 분석은 컨테이너/cron 가능, 브라우저 2차 검증은 PC.
- 참고: Chromium 이 이미 설치돼 있음(`/opt/pw-browsers`), 코드만 붙이면 됨.

---

## 5. 화면 구조 (기존 스타일 유지)

- **좌**: 곡 정보 입력(장르·무드·악기·BPM·길이·용도)
- **상단 탭**: 🇰🇷 KR / 🇯🇵 JP / 🇺🇸 US
- **중앙**: 트렌드 키워드 → 상위 영상 패턴 → 제목 후보(검색형5·추천형5) → 설명글 → **일치 썸네일 미리보기**
- **우**: SERP 검증 스냅샷 + 경쟁강도 + 채택/탈락 이유
- **하단**: YouTube Studio 붙여넣기용 3세트 패키지(복붙/CSV/JSON) + 언어별 제목·설명 반영 안내

---

## 6. seed keyword (시작점, 이후 상위 제목에서 자동 확장)

- **KR**: 집중 음악 · 공부할 때 듣는 음악 · 잔잔한 피아노 · 수면 음악 · 휴식 BGM · 카페 음악 · 무가사 연주곡 · 새벽 감성 음악
- **JP**: 作業用BGM · 勉強用BGM · 睡眠用BGM · 癒し音楽 · 集中音楽 · ピアノBGM · カフェ音楽 · リラックス音楽
- **EN**: instrumental music · no lyrics music · study music · focus music · relaxing piano · sleep music · background music · calm ambient music

`nation_prompts.json` 시드 방식과 동일하게 **코드 시드 + 자동 갱신**.

---

## 7. 자동화 운영 흐름

```
[곡 준비] → 엔진: KR/JP/US 3세트(제목·설명·태그·썸네일) 생성
        → SERP 검증(PC) → 약하면 자동 재작성 → 최종 채택
        → YouTube Studio 언어별 제목·설명 반영 + 썸네일 업로드
        → 성과 데이터로 재생성 루프
```
- cron 후보: 매일 KR/JP/US 트렌드·키워드 수집을 `viral_hits.json`처럼 커밋(무인).

---

## 8. 신규 작업 목록 (최소)

- [ ] `metadata_engine.py` — 국가별 오케스트레이션(regionData 수집 → 패턴추출 → 3세트 생성)
- [ ] `keyword_radar` 에 **KQS(품질점수)** 추가 → 저품질 키워드 탈락
- [ ] SERP 검증 `serp_probe.py` (Playwright 시크릿 + locale) — PC 전용
- [ ] 화면 1개(정적 HTML 탭 or Streamlit) — 좌입력/3탭/썸네일 미리보기/패키지
- [ ] 기존 재사용: youtube_client · concept_maker(제목·썸네일) · nation_prompts · channel_desc · thumb_overlay

→ **새로 짜는 코드는 오케스트레이터 + KQS + SERP 2차검증 정도. 나머지는 조립.**
