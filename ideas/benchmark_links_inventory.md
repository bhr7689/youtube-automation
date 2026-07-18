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

### 5차 배치 (라벨 없음 — 여름 힌트)
- https://youtu.be/9ESo0BO6Glg
- https://youtu.be/8J6avjeh1SM
- https://youtu.be/gidQv3LmwKE  — ☀️ 초여름
- https://youtu.be/WaefwC8kyRg  — ☀️ 여름

### 6차 배치 (상세 코멘트 — 사장님 관찰. 장르 공식 근거로 최우선 활용)
1. https://www.youtube.com/watch?v=8GD_B0h1BLg — [Playlist] 커피 마시러 왔다가 자리 못 뜨는 노래 ☕ | Chill R&B / **여자 리듬 좋다**
2. https://www.youtube.com/watch?v=laRCjrj2wmM — [playlist] 숲속 작은 카페, 아무 생각 없이 쉬어가는 시간 | JazzVintage92 · Cozy Notes / **여자 목소리 느린 템포**
3. https://www.youtube.com/watch?v=7-rL_MGWctQ — Chill guitar｜새벽 두 시, 너만 아는 시간 − Relaxing Lo-fi / **클래식 리라 같기도, 느린 템포 기타 주멜로디**
4. https://www.youtube.com/watch?v=_RS9ohsqliw — 疲れて何もしたくない夜に…【洋楽】 / **남자 목소리 느린 템포 조회수 대박** 🔥
   - https://www.youtube.com/watch?v=1zhM4mVqXyE — 最高の一日の始まり…【洋楽】 / 같은 채널, 남자 목소리 리듬·테크닉 은근 매력
5. https://www.youtube.com/watch?v=ZEfhDiPkZ-o — 도시가 깨어나기 전, 파리 카페에서 맞이하는 아침 | Slow Jazz / **여자 목소리 경쾌한 재즈풍 피아노** 🗼
6. https://www.youtube.com/@UnwindLofiRoom — 일본인 채널, 기타 로파이, **설명글이 특히 좋다**
7. https://www.youtube.com/watch?v=QhX2-0E84xw — [playlist] 책과 커피 사이로 부드럽게 흐르는 재즈 / 남자 템포 느리다
8. https://www.youtube.com/@Jayurhy — 연인들의 풋풋함, **내 채널과 분위기 어울릴 듯** ⭐
9. https://www.youtube.com/watch?v=WaefwC8kyRg — [playlist] 여름이었고, 우리는 파리에 있었지 with 파라다이스시티 / 노래는 별로, **제목·영상이 포인트** 🗼☀️ (5차와 중복)
10. https://www.youtube.com/@Mysig.Sounds — 일본인 채널 (재즈카페 통, 중복)
11. https://www.youtube.com/watch?v=n5O8q5U9ZJ8 — **에펠탑+신디피아노 손 클로즈업 좋다, 노래=스텔라장, 라따뚜이 스타일 좋다, 템포 조금 느리게** 🗼⭐
12. https://www.youtube.com/watch?v=ih5DKY56gM0 — 재즈 좋다, 남자 목소리·반주도
13. https://www.youtube.com/@oaplaylist — 낭만적인 파리의 아침 | Sarah Kang, Stella Jang, Pink Martini, Luca Minor, Anthony Lazaro | **프렌치팝** 🗼⭐
14. https://www.youtube.com/@onto_japan — 첫번째 제목·이미지 레퍼런스 채널 ⭐
15. https://www.youtube.com/@OOOffi — 도시 배경, **제목도 나랑 결이 비슷** ⭐
16. (URL 미기재) 夏のシャンソン… / **여름의 여유롭고 스윗한 드라이브 샹송 플레이리스트** 🗼☀️
17. https://www.youtube.com/@EMMAJAZZRADIO — 템포 적당, 여자 보컬
    - https://www.youtube.com/watch?v=Mdfng79O6vE — 파도 소리 넣음, 베이스가 좀더 리드미컬했으면
18. https://www.youtube.com/@JazzRecording — **제목·썸네일 이미지 일치, 파리 나옴, 빈티지 재즈** 🗼
19. https://www.youtube.com/@Jackscompany — **대만 채널, 카페 분위기 레퍼런스** ⭐
20. https://www.youtube.com/watch?v=sVDE5E1TXD0 — 재즈 여자 목소리 살짝 무거운 듯 듣기 좋다, 박자 살짝 아쉬움
21. https://www.youtube.com/@wavehibi — 음악 리듬 좋다
22. https://www.youtube.com/@BGMstudio_Tokyo — 전형적 일본 채널, **여자 그림 만화**
23. https://www.youtube.com/@LuckyCloverRadio — 22번과 비슷
24. https://www.youtube.com/@GoodlifeGroove — 일본 채널, 5월에 만듦(신생)
25. https://www.youtube.com/@TokyosongsMusic — 일본
26. https://youtu.be/wlEIQVYyn3o
27. https://youtu.be/h84x1mhg5C4
28. https://youtu.be/jIcAmWCtbmY — 일본풍
29. https://youtu.be/ywtY6ST_ypU
30. https://youtu.be/i8W-LdXKT6s — **나이트 무드, 조회수 미침** 🔥
31. https://youtu.be/hvfOJIss3ho
32. https://youtu.be/mWaHmKOchs0 — 레게
33. https://youtu.be/jkNP4lu-VoE — 심야의 딥베이스 재즈, 일본
34. https://youtu.be/qZvQT1LJvlg — 일본판 조선힙합
35. https://youtu.be/TMeeP_LBQUY — 일본
36. https://youtu.be/V8IIc7mrOCw — 잘생겼다, 카메라 비디오
37. https://youtu.be/MrFHHpRTpBI — 일본 왕자, 애니한 채널
38. https://youtu.be/kqOLhq6U4J4 — **2주 전 428만 미쳤다** 🔥🔥
39. https://youtu.be/YdjGqVLkJWE
40. https://youtu.be/pWuFhj5H0gc
41. https://youtu.be/hBCefXKUD1c
42. https://youtu.be/iBSYd1NKfUI — 감성 좋다, 영화 같다
43. https://youtu.be/Ga8YU1fjspo — 일본 스타일
44. https://youtu.be/lPC7FEhkLFc — 인스타 감성, **제목들을 잘 봐야겠다**
45. https://youtu.be/UGaYkMthUGo — 청량 하이틴
46. https://youtu.be/zAtTl356oFY
47. https://youtu.be/fI7rRLKScuQ — 애니한 감성
48. https://youtu.be/ZJ6KTok41GU
49. https://youtu.be/qN5M41xK-AI
50. https://youtu.be/GoZyyoDjmIA
51. https://youtu.be/pCBh3_Ii-L0 — 애니한 스타일
52. https://youtu.be/HUVqXAp8FZg — 고대 아라비아 음악
53. https://youtu.be/ihELFBtuVIA — **그림 예쁘다, 공주 스타일 접목해도 좋을 듯**
54. https://youtu.be/F7N6zC2vwIw — 일본 취향 특이
55. https://youtu.be/5G8pi9spFC4 — 일본 젠(zen)
56. https://youtu.be/rIcX8C3c5Dk — 바이올린 힙합, 일본
57. https://youtu.be/lpTSLdTVEh4 — 힙합 조선힙합 스타일 일본판
58. https://youtu.be/ZM9eJJWH1X0 — 애니한 스타일
59. https://youtu.be/oCA8DkQHC40 — 스터디 음악, 특이
60. https://youtu.be/2P7HOmKGHaU — 중국과 인도
61. https://youtu.be/IUARG6yQKvE — **7개월 전 178만** 🔥
62. https://youtu.be/fKk6Ox0r4zg — **왈츠, 148만** 🔥
63. https://youtu.be/t01_UPHuP60 — 남자 사진 장면컷 연출, 영상 초반
64. https://youtu.be/CDD_yRgRyJc — 왈츠
65. https://youtu.be/9RDlaKu8mYU — 다비드 상에 옷을 입혔다(썸네일)
66. https://youtu.be/fCGHfBFJxzY — 남성을 위한 심야
67. https://youtu.be/hgOtkOc4Vws — 아라빅 재즈
68. https://youtu.be/kJw7MBx1dcs — 빨강, 여자, "이유 없이 다 짜증날 때"
69. https://youtu.be/rblH2SbMNr8 — 어두운 일본 인트로, 멘탈
70. https://youtu.be/6dCO_a44874 — 작업용/공부용, 만화 캐릭터 여자, 일본
71. https://youtu.be/mxjSyrNE8J8 — **썸네일 그림과 제목이 찰떡**
72. https://youtu.be/AU0xtFBg0-w — 썸네일 특이, 그림자·빨간 배경
73. https://youtu.be/Cl75mzNUKBM — 72번과 결 비슷, 일본 문화와도 어울릴 듯
74. https://youtu.be/XcMW7_HEj9M
75. https://youtu.be/09K79_bD6w0 — 일본 감성
76. https://youtu.be/PB8ZrGinWi0 — 수도승 모드, 조회수 좋아 🔥
77. https://youtu.be/x5s7l3vnRj8 — 갱스타
78. https://youtu.be/z63KyqrIpok — 공부
79. https://www.youtube.com/@FallingForMemories-p5e — **슬픈 노래, 여자 얼굴과 제목의 거의 일관성**
    - https://www.youtube.com/@QuietlyYoursMusic — 딥 하우스, 남자 목소리 좋다, **벤치마킹 해볼까?**

### 7차 배치 (라벨·코멘트 없음 — 대량 수집, 미분류. PC 앱 자동분류 예정)
> 배치 내 중복 제거(1회만): IgIVGCwJ80Y, B00YlkCiBK4, Sv4ezSLAppM, xbUa_8CIuAQ, 0vQOzpJ0VJ8.
> 앞 배치와 중복: _RS9ohsqliw(6차) · 8GD_B0h1BLg(6차) · tw9QJzHZjeM(1차) · ZEfhDiPkZ-o(6차) · UKbZ4r88z3Q(클래식) · CDD_yRgRyJc(6차). #94 공란.

- https://youtu.be/gNVzIeDRNLg
- https://youtu.be/U8ugO8stnBk
- https://youtu.be/jNfaUkATxHg
- https://youtu.be/6dGvamv4im4
- https://youtu.be/VShXQiRLMqU
- https://youtu.be/wJkNXfmB3Rc
- https://youtu.be/toSvP83EebU
- https://youtu.be/Yl-7KMk8Ejo
- https://youtu.be/IPgALki7Cig
- https://youtu.be/NW32tyK1d70
- https://youtu.be/3UgpbEhvoTY
- https://youtu.be/lsRfflGKqQc
- https://youtu.be/wiGVohAv478
- https://youtu.be/iKShF6iv0sI
- https://youtu.be/ghpiAxqq4aw
- https://youtu.be/QA9FpizKFeU
- https://youtu.be/foEjHAkrIDA
- https://youtu.be/KbuvnS9vTYI
- https://youtu.be/BOyNLX3ocKs
- https://youtu.be/aBVC8L_fhAc
- https://youtu.be/IgIVGCwJ80Y
- https://youtu.be/B00YlkCiBK4
- https://youtu.be/f0uhfNcRdug
- https://youtu.be/uB1QpupEHGo
- https://youtu.be/NM5wf7o-hNo
- https://youtu.be/OC9I6BSA0rg
- https://youtu.be/EulgkeAjD74
- https://youtu.be/bqVhWdjxKdU
- https://youtu.be/nn7hXZr4Lqg
- https://youtu.be/i8v-vQ0lNTQ
- https://youtu.be/Bnpk0mEKCa0
- https://youtu.be/Sv4ezSLAppM
- https://youtu.be/o0YjmJrmpYI
- https://youtu.be/SM7eHVToU-Q
- https://youtu.be/FaSpRBr38cY
- https://youtu.be/s2P-O5uAoNo
- https://youtu.be/uLwpqSYKZW0
- https://youtu.be/qbFhggCAVNY
- https://youtu.be/VX2d1Et0ywc
- https://youtu.be/PJjt5Z0TLjY
- https://youtu.be/jHoChZ2ykbk
- https://youtu.be/GYAIctA2Mtw
- https://youtu.be/30bfrx8-Cbc
- https://youtu.be/0cfBJG_wMiU
- https://youtu.be/U-V_rOICToM
- https://youtu.be/_8yv1SJquVQ
- https://youtu.be/ypEZ2S0prk4
- https://youtu.be/_bqppPXwid4
- https://youtu.be/x6c-lgeA15k
- https://youtu.be/Py3IKxJcbAA
- https://youtu.be/QgtDgADXHS4
- https://youtu.be/JLXNQNRwgEs
- https://youtu.be/7InR9hxF2Qo
- https://youtu.be/w-ePzTAY-9Y
- https://youtu.be/lI1hxHjWQvM
- https://youtu.be/Ooz81q6NcZY
- https://youtu.be/RCWD6Mnhni0
- https://youtu.be/j6UN0SH1rek
- https://youtu.be/nkXhoJnTazs
- https://youtu.be/RwAIdGJAl78
- https://youtu.be/Fw32PPy3CUU
- https://youtu.be/AX9T2emPoQo
- https://youtu.be/OgXKTJ8TItc
- https://youtu.be/ydW5mgwVemc
- https://youtu.be/xbUa_8CIuAQ
- https://youtu.be/xZtj_7-BrNc
- https://youtu.be/fYmDt5bWDxg
- https://youtu.be/tkWEpUtsJ2Y
- https://youtu.be/1O3o_c4a-J4
- https://youtu.be/cie55mgMF3c
- https://youtu.be/Gu83u73hiiw
- https://youtu.be/0vQOzpJ0VJ8
- https://youtu.be/QtBUvmBOhho
- https://youtu.be/GofEvLBdWQw
- https://youtu.be/L1E4rkvGo-Y
- https://youtu.be/NIMForVc-qc
- https://youtu.be/buZSS052oq0
- https://youtu.be/yYBN2bnIzs4
- https://youtu.be/t-Jhy7XhdGI
- https://youtu.be/91VpHUKYgR4
- https://youtu.be/QaJyPtUgUO4
- https://youtu.be/GfuiuFgSUw0

### 8차 배치 (일본 채널 벤치마킹 — 상세 관찰)
1. https://www.youtube.com/@cozyhibi
2. https://www.youtube.com/@wavehibi — 청량감 (6차 #21 중복)
3. https://www.youtube.com/@Nonbiri-BGM — 피아노·기타
4. https://www.youtube.com/@블루레인 (@%EB%B8%94%EB%A3%A8%EB%A0%88%EC%9D%B8) — **대한민국 채널인데 일본어 검색으로 노출됨**
5. https://www.youtube.com/@Odiroom — 일본 채널, 4월 생성, **수익창출됨**
6. https://www.youtube.com/@calmtime_jp — 한국인이 만든 일본 채널, 4월, 아직 수창 안됨, 핸들 끝에 jp
7. https://www.youtube.com/@TWF66666 — 일본 감성, 참 특이
8. https://www.youtube.com/watch?v=Cy91zTIAfEI — **일본 시니어 채널 추정**, 자막에 글 쓰고 시니어들이 댓글, 음악=느린 재즈
9. https://www.youtube.com/@3freeBGM — 정말 음향효과 같다
10. https://www.youtube.com/@mocomocoroomdiary — 일본 채널, 4월 생성, 수창 안됨, 구독자 부족
11. https://www.youtube.com/@NAGISORASounds — 일본, 5/15 생성, 수창 안됨, 구독자 너무 적음, 일본 정통 음악가 피아노·클래식, **내가 좋아하는 스타일**, ⚠️ **썸네일 그림과 제목 불일치 → 노출 안되는 듯, 음악은 좋다** (일치성 앱의 핵심 사례!)
12. https://www.youtube.com/@Otoakari1 — **제목 짓는 걸 벤치마킹하자** ⭐
13. https://www.youtube.com/@-manzanillamusic- — 일본 채널, **그림체·제목 벤치마킹하자** ⭐
14. https://www.youtube.com/@COZYSOUNDS-l2q — 제목에 "서양 플레이리스트", 일본 채널
15. https://www.youtube.com/@GoodDayPop — 핸들에 'pop', 제목에 '서양', 일본 채널
16. (16번 = @wavehibi 재중복)

> 8차 인사이트:
> - ⚠️ **썸네일↔제목 불일치 = 노출 저하**(11번) → 앱 "일치성 점수"의 실전 근거.
> - 🇯🇵 **일본 신생 채널(4~5월 생성) 다수** 관찰 — 수익창출/구독자 상태까지 체크 → "지금 뜨는 신생 벤치마크" 추적 가치.
> - ⭐ 제목·그림체 벤치마킹 지정: @Otoakari1(제목) · @-manzanillamusic-(그림체+제목).
> - 🌏 한국 채널이 일본어 검색으로 노출(4번), 한국인의 일본 타깃 채널(6번) → **일본어 타깃 전략** 반복 신호.

> 6차 관찰 요약(반복 신호):
> - 🗼 **파리/샹송/프렌치팝** 계열이 가장 강함 (스텔라장·라따뚜이·에펠탑·Pink Martini·Sarah Kang·여름 드라이브 샹송) → **내 채널 주력 후보**
> - ⭐ **"내 채널과 결이 맞다"** 표시: @Jayurhy·@oaplaylist·@onto_japan·@OOOffi·@Jackscompany·11번(스텔라장) → 채널 정체성 시드
> - 🇯🇵 **일본 채널 대량** — 애니/만화 그림 썸네일, 젠, 일본판 힙합, 신생 채널 등 (구도·그림체 벤치마크 소스)
> - 🔥 **조회수 폭발** 표시: 428만(2주), 178만(7개월), 148만(왈츠), i8W 나이트무드, 76번 수도승 → 구간 분석 최우선
> - 실험 장르 탐색: 왈츠·아라빅재즈·레게·딥하우스·갱스타·공주풍

> 중복 제거: jQf9eUGEg40·-AGoTdlnqJk(고양이)·saM94vXxxxA(파리·클래식배치) 는 앞 배치와 겹쳐 1회만 유효.
> 반복 키워드 관찰: **파리**(fXX2sS-BUG8·saM94vXxxxA·Ng7FLbSkHNI) 가 여러 번 등장 → 파리/샹송 테마가 주력 후보.
