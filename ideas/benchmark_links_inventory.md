# 🎬 썸네일·제목 분석 앱 — 벤치마킹 링크 인벤토리

> 사장님이 배치로 주는 벤치마킹 링크를 장르별로 누적 보관하는 파일.
> (앱 구현 전 데이터 보존용 — 컨테이너 리셋 대비. "만들어" 신호 시 앱에 시드로 이식.)
> 이 컨테이너는 프록시가 유튜브를 막아 제목을 못 읽음 → **제목 미확인 영상은 PC 앱에서 자동 재분류.**

## 앱 설계 요약 (확정본)
- 구조: **장르 = 독립 채널 프로젝트** (여러 채널 운영 대시보드)
- 조회수: 발행 **6개월 이내**, 구간 1만/3만/5만/10만/20만/30만+
- 분석: 장르별 썸네일(구도·각도·색·문구·배경) + 제목(감각어·상황·장르·이모지) 공식
- 일치성: 썸네일↔제목 100점 채점
- 추천: 장르 공식 + 채널 정체성으로 새 썸네일·제목 세트
- 감시: 벤치마킹 채널 새 영상 → 자동 분석 → **카톡 알림**(GitHub Actions cron, 나에게 보내기)
- 입력: 캡처 업로드 + YouTube 자동수집 둘 다

---

## 📁 장르별 분류

### 🎷 재즈·카페 BGM (cozy jazz)
- https://www.youtube.com/@Mysig.Sounds  — "quiet & cozy jazz BGM, 커피향"(검색확인)
- https://www.youtube.com/@maruko_jazz
- https://www.youtube.com/@groove_salon
- https://www.youtube.com/@AmberBrewJazz  — 메모: 썸네일 색상만 바꿈

### ☕ 보사노바·여름 카페 (일본/도쿄 여름)
- https://www.youtube.com/@CozyBossaCafeMelodies  — 일본 채널, **여름 키워드 장악**
- https://www.youtube.com/@played_for_you  — **도쿄의 여름 키워드**

### 🎧 감성 / Lofi
- https://www.youtube.com/@meloenvy  — ⭐ 제목·썸네일 = 우리 채널 레퍼런스
- https://www.youtube.com/@살구사운드  (@%EC%82%B4%EA%B5%AC%EC%82%AC%EC%9A%B4%EB%93%9C)
- https://www.youtube.com/@alma-g1s8o  — (확인 필요)

### 🎻 클래식
- https://youtu.be/ExAC84tuF38
- https://youtu.be/IsGUh_yMxDg
- https://youtu.be/PgjiEHEjMNk
- https://youtu.be/7xBdtvLx9UE
- https://youtu.be/6JV0EdYHLdA
- https://youtu.be/yfKdKyiCnYY
- https://youtu.be/F4cELULw0q4
- https://youtu.be/XJOkzLJZhDI
- https://youtu.be/sIQrpnVil2c
- https://youtu.be/_8wTn-ptDAM
- https://youtu.be/hzfbBth3OEo
- https://youtu.be/RXChHfrG3lA
- https://youtu.be/klh7I70h3vg
- https://youtu.be/UKbZ4r88z3Q
- https://youtu.be/yswDXtmZde8
- https://youtu.be/-MEjaHzrcuU
- https://youtu.be/rIyRtfQOhxM
- https://youtu.be/saM94vXxxxA  — 🗼파리

### 🧘 확언·명상 음악 (아웃라이어 — 음악 플레이리스트와 성격 다름)
- https://www.youtube.com/@affirmwithmusic  — "I AM affirmations, manifestation"(검색확인)

### 🗣️ 영어학습 (아웃라이어 — 음악 채널 아님)
- https://www.youtube.com/@englishwithHOPEEE

---

## 🎼 개별 영상 — 테마 힌트 있음 (장르 미정)
- https://youtu.be/fXX2sS-BUG8  — 파리 카페
- https://youtu.be/-AGoTdlnqJk  — 고양이
- https://youtu.be/MUsvU-JxoZs  — 남자 잘생긴 (썸네일 인물)
- https://youtu.be/0-HoSewcCyU  — 연못 아래 음악

---

## ❓ 제목 미확인 — 장르 미정 (PC 앱에서 자동 재분류 예정)

### 1차 배치 (라벨 없음)
- https://www.youtube.com/watch?v=ty364PbyH34
- https://youtu.be/H3urFo3u-lo
- https://www.youtube.com/watch?v=W-kGrtuPfv4
- https://youtu.be/f0akZYtxLhY
- https://youtu.be/tw9QJzHZjeM
- https://youtu.be/jQf9eUGEg40
- https://youtu.be/PI2UvXH2WlY
- https://youtu.be/TXJyHiJ-QN0
- https://youtu.be/qbFCawqmP_0
- https://youtu.be/pqm-4hJ5Y-o
- https://youtu.be/lgNq1hwrec0
- https://youtu.be/NMnKm4sHSIE
- https://youtu.be/2BD8dfhbW_s
- https://youtu.be/5CxZwPmhYrs
- https://youtu.be/ZnV8pzl4QQc
- https://youtu.be/m-Gh_pV3Ki0
- https://youtu.be/2bEmWCwdCds
- https://youtu.be/UVkZULN3n_U
- https://youtu.be/PdfWtOWGq3g
- https://youtu.be/-Ji_MpGldes
- https://youtu.be/Uy7jqiBIuXE
- https://youtu.be/-B0hiNCyMfQ
- https://youtu.be/mDkyPzypfuo
- https://youtu.be/jCJh2a01wPw
- https://youtu.be/2SV-ueN0hxA
- https://youtu.be/DoftddXO274
- https://youtu.be/dZRIvCujbIw
- https://youtu.be/quHlA8hoepU
- https://youtu.be/oss3OobocFU
- https://youtu.be/XcGAwz5O-e4
- https://youtu.be/SjVQqOG0jBk

### 3차 배치 (라벨 없음 — 장르 확인 필요)
- https://youtu.be/c5-Z87XUSQM
- https://youtu.be/ml-5eZLsjC8
- https://youtu.be/PMgaphD1l44
- https://youtu.be/Wp6JEf6R6g0
- https://youtu.be/Uw-WquFlaok
- https://youtu.be/r6kRv57n7yE
- https://youtu.be/72nMc4jEmbE
- https://youtu.be/bM_RZ7DeCxo  — 조회수 어마어마함
- https://youtu.be/75UVeYGkF-s  — 조회수 어마어마함
- https://youtu.be/dGsDHKbySCk
- https://youtu.be/bxoC3tmy6D4  — 조회수 어마어마함
- https://youtu.be/PgexXFHT5j0
- https://youtu.be/Ng7FLbSkHNI  — 🗼파리
- https://youtu.be/XJBYylTf6-A  — 조회수
- https://youtu.be/5ugCSMoCkxA  — 조회수
- https://youtu.be/bvjX2hIwzXk
- https://youtu.be/rRWs-z5Lqi8
- https://youtu.be/LRZg1CNQnx4

### 4차 배치 (라벨 없음 — 장르 확인 필요)
- https://youtu.be/XoWuDjvhAAw
- https://youtu.be/FP6P9Yvb12k
- https://youtu.be/Ac_nVJASVfc
- https://youtu.be/bw2giAeU1sc
- https://youtu.be/jNLUrg_y0fQ
- (중복: c5-Z87XUSQM — 3차와 겹침)

> 중복 제거: jQf9eUGEg40·-AGoTdlnqJk(고양이)·saM94vXxxxA(파리·클래식배치) 는 앞 배치와 겹쳐 1회만 유효.
> 반복 키워드 관찰: **파리**(fXX2sS-BUG8·saM94vXxxxA·Ng7FLbSkHNI) 가 여러 번 등장 → 파리/샹송 테마가 주력 후보.
