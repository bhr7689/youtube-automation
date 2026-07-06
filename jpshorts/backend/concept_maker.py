"""🎨 플리 컨셉 제조기 — 플레이리스트 채널 분석 → 신규 컨셉 + Suno 패키지.

사용자 제공 'GPT 커스텀 지침 v1.4' 를 앱에 내장. ChatGPT 커스텀 GPT 연결이 아니라
같은 지침을 우리 LLM 경로(Gemini 우선, OPENAI_API_KEY 있으면 GPT 폴백)로 실행한다.

GPT 버전보다 나은 점: 채널 URL 만 넣으면 YouTube Data API 로 제목·조회수·업로드
날짜를 자동 수집(실데이터) — 캡처 업로드 불필요. 썸네일 '시각' 분석은 이미지 미첨부
상태이므로 지침 원칙(근거 기반·추정 표시)에 따라 텍스트 근거 기반 추정으로 표기한다.
키 없으면 데모 리포트(형식 검증용).
"""
from __future__ import annotations

import os
import re

import translator
import youtube_client as yc

MAX_VIDEOS = 30

# ── 지침 v1.4 (시스템 프롬프트로 내장 — 핵심 전문 유지) ──
SPEC = """너는 "플리컨셉제조기"다. 유튜브 플레이리스트 채널의 제목 리스트·조회수·업로드
흐름(및 가능한 메타데이터)을 분석해 새로운 플레이리스트 채널 컨셉과 Suno 곡 제작
패키지까지 설계하는 전문 컨설턴트다. 답변은 한국어, 실무자가 바로 쓸 수 있게 간결하고
실행 중심으로.

[핵심 원칙]
1. 100% 복제 금지 — 원본 채널명·로고·캐릭터·썸네일 구도·제목을 그대로 따라 하지 않는다.
2. 85% 결 유지 — 타겟층·감정 무드·소비 목적·제목 문형·전체 톤은 원본과 비슷한 계열 유지.
3. 15% 변형 — 컬러 포인트·계절감·시그니처 오브젝트·악기 조합·인물 표현·제목 감정·채널명
   톤 중 1~2개만 새롭게 바꾼다.
4. 근거 기반 — 모든 분석에 어떤 제목·반복 패턴·데이터에서 판단했는지 근거를 붙인다.
   근거 없는 추측 금지.
5. 데이터 부족 시 멈추지 않기 — 조회수 없으면 "조회수 데이터가 없어 조회수 패턴은 확정
   분석이 아니라 제목 반복, 썸네일 반복, 업로드 흐름을 기반으로 한 추정입니다." 표시 후
   추정 진행. 썸네일 이미지가 없으면 시각 분석은 '추정'으로 표기.

[분석 6단계 — 표 형식 사용]
① 채널 아이덴티티: 전체 무드/세계관/타겟/시청 목적/감정 포인트/근거 표.
② 썸네일 스타일: 컬러/인물/구도 + 근거 표 (이미지 없으면 추정 표기).
③ 조회수 패턴: 고조회 공통 키워드·문형, 저조회와의 차이. 데이터 없으면 추정 표기.
④ 썸네일 변화 패턴: 초기/중기/최근/진단 표 (시간순 자료 기반, 없으면 업로드 흐름 추정).
⑤ 제목 키워드: 반복 키워드 Top10/감성 단어/장소·시간대/장르 단어/문형/제목 구조 표.
⑥ 브랜딩 점수: 일관성/차별성/기억용이성/확장성/클릭유도력 각 10점, 총점 50점 + 한줄평.

[다중 채널] 2개 이상이면: 개별 분석→공통 무드→차이점→융합 요소→신규 컨셉.
융합 비율 표시(예: A 60% 제목 문형·타겟 / B 30% 색감 / C 10% 악기·계절감).
메인 기준 채널 1개, 나머지는 보조. 요소를 너무 섞어 컨셉이 흐려지지 않게.

[신규 컨셉 1~2안] 컨셉명 / 한 줄 정의("이 채널은 [타겟]에게 [무드]를 [소재]로 전달") /
무드보드(색감·분위기·레퍼런스 단어 5~7개) / 유지한 85% / 새롭게 비튼 15% / 차별화
포인트 / 왜 이렇게 잡았는지(근거 1~2문장). 원본과 전혀 다른 장르·타겟으로 튀는 것 금지.

[채널 세팅] ①채널이름 2~3안 ②채널핸들 2~3안 + "동일하거나 유사한 핸들이 이미 사용
중일 수 있으니, 유튜브 채널 설정에서 직접 검색해 사용 가능 여부를 확인하세요." 문구
③채널설명문 3~5문장(무드·장르·듣기 좋은 상황) ④채널키워드 10~15개 쉼표 구분
⑤업로드 기본 설정: 고정 제목 템플릿/기본 설명문 템플릿/태그 10~15개/해시태그 3~7개.

[채널 미리보기] 프로필(형태/컬러/상징 오브젝트/분위기/피해야 할 요소), 배너(배경/메인
오브젝트/텍스트 배치/여백/분위기), 썸네일(구도/컬러/인물·오브젝트/텍스트 위치/클릭
포인트). 원본 이미지 편집·복제 금지, 참고만. 필요 시 이미지 생성 프롬프트 제공.

[썸네일 대표안] 콘셉트/선정 이유/구도/컬러 코드/폰트 톤/인물·오브젝트 규칙/텍스트
배치/금지 요소(원본 로고 복제·동일 캐릭터·랜덤 텍스트·과도한 네온·복잡한 배경)/
이미지 생성 프롬프트.

[신규 제목 10개] 표로. 원본 그대로 베끼지 않기. 감성 문장+검색 키워드 조합 우선.
질문형/감탄형/시적 서술형/검색 키워드형 혼합. 과도한 낚시 금지.
필요 시 한국어+일본어+영어 검색 키워드 조합.

[Suno 곡 제작] 가사곡: 곡 컨셉 요약/Suno 스타일 프롬프트/곡 구조/가사/곡 제목 후보
3~5/유튜브 제목 연결 예시. 연주곡: 곡 컨셉 요약/Suno 스타일 프롬프트/Instrumental
Structure/곡 제목 후보 3~5/유튜브 제목 연결 예시.
명시 없으면 채널 성격으로 판단(샹송·팝·엔카·트로트·동요→가사곡 / 클래식·재즈카페·
로파이·수면·명상·작업용→연주곡)하고 "채널 성격상 이번 곡은 [가사곡/연주곡]으로
설계했습니다." 표시. 연주곡 요청에 가사 금지, 가사곡 요청에 연주곡 구조만 제공 금지.
Suno 스타일 프롬프트는 영어: [Main genre], [sub genre], [era/mood], [instruments],
[vocal tone or no vocals], [BPM], [rhythm], [emotion], [ambience], [mixing texture],
[playlist use case].
가사곡 구조: [Intro][Verse 1][Pre-Chorus][Chorus][Verse 2][Bridge][Final Chorus][Outro]
— 감정을 직접 설명하지 말고 장면·이미지로 암시, 후렴은 기억하기 쉽게, 짧은 문장.
연주곡 구조: [Intro][Main Theme][Variation][Bridge][Final Theme][Outro] — 구간마다
악기·분위기·리듬 변화·감정선 짧게.
곡 묶음(10곡/25곡) 요청 시 표(번호/곡 제목/무드/Suno 스타일 요약/썸네일·영상 제목
연결). 25곡 흐름: 1~3 오프닝 / 4~10 몰입 / 11~17 감정 확장 / 18~22 클라이맥스 /
23~25 잔잔한 엔딩.

[최종 출력 순서 — 반드시 이 순서, 마크다운 ## 제목으로 구분]
1.입력 가정 2.채널별 분석 3.채널 아이덴티티 4.썸네일 스타일 분석 5.조회수 패턴 분석
6.썸네일 변화 패턴 분석 7.텍스트 제목 키워드 분석 8.브랜딩 점수 9.신규 컨셉안 1~2개
10.유튜브 채널 세팅 추천 11.채널 미리보기 방향 12.썸네일 대표안 13.신규 제목 샘플 10개
14.Suno AI 아웃풋 15.다음 실행 체크리스트

[금지] 원본 복제 제안/거의 같은 채널명/로고·캐릭터·고유 구도 복제/데이터 없이 확정적
인기 분석/핸들 가용성 단정/원본 제목 단어만 바꾼 유사 제목/원본과 전혀 다른 방향/분석
없이 컨셉만 제시."""


# ── LLM 디스패처: Gemini 우선 → OpenAI(키 있으면) ──────

def _openai(prompt: str) -> str | None:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key)
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7)
        return (r.choices[0].message.content or "").strip()
    except Exception:
        return None


def _llm(prompt: str) -> str | None:
    return translator._gemini(prompt, temperature=0.7) or _openai(prompt)


def llm_status() -> dict:
    return {"gemini": translator.has_gemini(),
            "openai": bool(os.environ.get("OPENAI_API_KEY", "").strip())}


# ── 채널 데이터 자동 수집 (URL 만 넣으면 실데이터) ──────

def _extract_channel_ref(url: str) -> tuple[str, str]:
    """URL → ('id'|'handle'|'search', 값)"""
    u = url.strip()
    m = re.search(r"youtube\.com/channel/(UC[\w-]+)", u)
    if m:
        return "id", m.group(1)
    m = re.search(r"youtube\.com/(@[\w.\-가-힣]+)", u)
    if m:
        return "handle", m.group(1)
    if u.startswith("UC") and len(u) >= 20:
        return "id", u
    if u.startswith("@"):
        return "handle", u
    return "search", u


def collect_channel(url: str, max_videos: int = MAX_VIDEOS) -> dict:
    """채널 URL/핸들 → 채널 정보 + 최근 영상(제목·조회수·날짜). 실데이터."""
    if not yc.has_key():
        return _demo_channel(url)
    try:
        yt = yc._yt()
        kind, val = _extract_channel_ref(url)
        params = dict(part="snippet,statistics,contentDetails", maxResults=1)
        if kind == "id":
            params["id"] = val
        elif kind == "handle":
            params["forHandle"] = val
        else:
            s = yt.search().list(part="id", q=val, type="channel",
                                 maxResults=1).execute()
            items = s.get("items", [])
            if not items:
                return {"error": f"채널을 찾지 못했어요: {url}"}
            params["id"] = items[0]["id"]["channelId"]
        resp = yt.channels().list(**params).execute()
        items = resp.get("items", [])
        if not items:
            return {"error": f"채널을 찾지 못했어요: {url}"}
        ch = items[0]
        uploads = ch.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
        videos = []
        if uploads:
            pl = yt.playlistItems().list(part="contentDetails", playlistId=uploads,
                                         maxResults=min(50, max_videos)).execute()
            ids = [i["contentDetails"]["videoId"] for i in pl.get("items", [])][:max_videos]
            if ids:
                vr = yt.videos().list(part="snippet,statistics",
                                      id=",".join(ids)).execute()
                for v in vr.get("items", []):
                    sn, st = v["snippet"], v.get("statistics", {})
                    videos.append({
                        "title": sn["title"],
                        "views": int(st.get("viewCount", 0)),
                        "published": sn["publishedAt"][:10],
                    })
        st = ch.get("statistics", {})
        return {
            "url": url,
            "title": ch["snippet"]["title"],
            "description": ch["snippet"].get("description", "")[:500],
            "subscribers": int(st.get("subscriberCount", 0) or 0),
            "video_count": int(st.get("videoCount", 0) or 0),
            "videos": videos,
            "demo": False,
        }
    except Exception as e:
        return {"error": f"수집 실패({url}): {e}"}


def _demo_channel(url: str) -> dict:
    titles = [
        ("비 오는 새벽, 창가에서 듣는 재즈 피아노 ☔", 1_240_000, "2026-06-28"),
        ("퇴근길 버스에서 | 마음이 풀리는 로파이 재즈", 890_000, "2026-06-21"),
        ("새벽 2시의 카페 | 아무도 없는 조용한 재즈", 2_100_000, "2026-06-14"),
        ("공부할 때 듣는 잔잔한 피아노 3시간", 760_000, "2026-06-07"),
        ("일요일 아침, 커피와 보사노바 ☕", 1_530_000, "2026-05-31"),
        ("잠들기 전 30분 | 느린 재즈 발라드", 680_000, "2026-05-24"),
        ("창밖에 눈이 내리면 | 겨울밤 재즈", 3_400_000, "2026-01-18"),
        ("혼자 있는 밤, 위스키 한 잔과 재즈", 1_020_000, "2026-05-10"),
    ]
    return {
        "url": url or "(데모 채널)",
        "title": "새벽카페 재즈 (데모)",
        "description": "새벽 감성 재즈·로파이 플레이리스트 채널 (데모 데이터)",
        "subscribers": 87_000, "video_count": 142,
        "videos": [{"title": t, "views": v, "published": d}
                   for t, v, d in titles],
        "demo": True,
    }


# ── 리포트 생성 ─────────────────────────────────────────

def generate_report(channel_urls: list[str], song_type: str = "auto",
                    num_songs: int = 1, extra_notes: str = "") -> dict:
    collected = [collect_channel(u) for u in channel_urls if u.strip()]
    channels = [c for c in collected if not c.get("error")]
    if not channels:
        errs = [c["error"] for c in collected if c.get("error")]
        return {"error": " / ".join(errs) or "채널 URL 을 넣어주세요."}

    data_block = ""
    for i, c in enumerate(channels, 1):
        vids = "\n".join(
            f"  - [{v['published']}] {v['title']} — 조회수 {v['views']:,}"
            for v in c["videos"])
        data_block += (
            f"\n[채널 {i}] {c['title']} (구독자 {c['subscribers']:,} · "
            f"총 영상 {c['video_count']}개)\n채널 설명: {c['description']}\n"
            f"최근 영상 {len(c['videos'])}개 (제목·조회수·날짜 = 실데이터):\n{vids}\n")

    song_line = {"lyric": "가사곡으로 제작", "instrumental": "연주곡으로 제작",
                 "auto": "채널 성격에 따라 가사곡/연주곡 자동 판단"}.get(song_type, "자동 판단")
    songs_line = (f"곡 묶음 {num_songs}곡을 13번 형식(표+흐름 설계)으로 제공하라."
                  if num_songs > 1 else "곡 1곡 패키지를 제공하라.")

    prompt = (
        SPEC + "\n\n[입력 데이터 — YouTube API 실측]\n" + data_block +
        ("\n[사용자 추가 메모]\n" + extra_notes + "\n" if extra_notes.strip() else "") +
        f"\n[곡 유형] {song_line}\n[곡 수] {songs_line}\n"
        "\n[주의] 썸네일 이미지는 첨부되지 않았다 — 썸네일 시각 분석(②④)은 제목·업로드"
        " 흐름 기반 추정으로 표기하라. 위 '최종 출력 순서' 1~15를 마크다운으로 전부 출력하라."
    )
    out = _llm(prompt)
    engine = ("gemini" if translator.has_gemini() else
              "openai" if os.environ.get("OPENAI_API_KEY", "").strip() else "demo")
    if not out:
        out = _demo_report(channels[0])
        engine = "demo"
    return {
        "report": out,
        "channels": [{"title": c["title"], "subscribers": c["subscribers"],
                      "videos": len(c["videos"]), "demo": c.get("demo", False)}
                     for c in channels],
        "engine": engine,
    }


def _demo_report(ch: dict) -> str:
    return f"""# 플리 컨셉 리포트 (데모 — GEMINI/OPENAI 키를 넣으면 실제 분석)

## 1. 입력 가정
- 분석 대상: **{ch['title']}** (구독자 {ch['subscribers']:,}, 최근 영상 {len(ch['videos'])}개 실데이터)
- 썸네일 이미지 미첨부 → 시각 분석은 제목·업로드 흐름 기반 **추정**입니다.

## 3. 채널 아이덴티티
| 항목 | 분석 |
| --- | --- |
| 전체 무드 | 새벽·비·카페의 고요한 위로 |
| 세계관 | 혼자 있는 시간의 안식처 |
| 타겟 | 20~40대, 심야·출퇴근·작업 BGM 수요 |
| 시청 목적 | 수면 유도·집중·감정 정리 |
| 감정 포인트 | 외로움을 부정하지 않고 감싸줌 |
| 근거 | 제목 8개 중 6개가 시간대(새벽·밤)+장소(카페·창가) 조합 |

## 5. 조회수 패턴 분석
- 고조회 공통: **계절·날씨 키워드** (겨울밤 340만, 새벽 2시 210만) — 시기성 훅
- 저조회 대비: 기능성 제목(공부용 76만)보다 **장면 묘사형**이 평균 1.8배

## 8. 브랜딩 점수
| 항목 | 점수 |
| --- | --- |
| 일관성 | 9/10 |
| 차별성 | 6/10 |
| 기억용이성 | 6/10 |
| 확장성 | 8/10 |
| 클릭유도력 | 7/10 |

**총점 36/50** — 결은 탄탄하나 시그니처 오브젝트가 없어 기억에 안 남는다.

## 9. 신규 컨셉안
### 컨셉안 1 — "심야서점 라디오"
- 한 줄 정의: 혼자 있는 밤의 20~40대에게 **책 냄새 나는 고요함**을 재즈·로파이로 전달
- 유지한 85%: 심야 시간대·위로 무드·장면 묘사형 제목·잔잔한 재즈 결
- 새롭게 비튼 15%: 카페→**서점**(시그니처: 스탠드 불빛+책), 컬러 앰버→**딥그린**
- 근거: 원본의 '장소+시간대' 공식은 검증됐고, 서점은 같은 정서의 미개척 공간

## 14. Suno AI 아웃풋
채널 성격상 이번 곡은 **연주곡**으로 설계했습니다.
- Suno 스타일: Jazz, lofi jazz piano trio, late-night 1960s mood, soft piano + upright bass + brushed drums, no vocals, 68 BPM, slow swing, wistful but warm, small bookstore ambience with vinyl crackle, warm analog mixing, midnight reading playlist
- Instrumental Structure: [Intro] 솔로 피아노 → [Main Theme] 브러시 드럼 합류 → [Variation] 베이스 워킹 → [Bridge] 피아노만 → [Final Theme] → [Outro] 페이드

## 15. 다음 실행 체크리스트
- [ ] 채널핸들 후보를 유튜브에서 직접 검색해 사용 가능 확인
- [ ] 대표 썸네일 1장 제작 → 3영상 테스트
- [ ] 25곡 묶음이 필요하면 곡 수를 25로 다시 요청

*(데모 리포트는 요약본 — 키를 넣으면 1~15 전체가 상세 출력됩니다)*"""
