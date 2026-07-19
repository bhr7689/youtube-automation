"""YouTube URL → 설명 수집 → Gemini → SEO·감성 채널 설명 + 해시태그.

흐름:
  1) URL 파싱: channel / video / handle / playlist
  2) YouTube Data API v3 로 채널 메타 + 최근 영상 N개의 description 일괄 수집
  3) 설명들을 합쳐서 (a) 가벼운 키워드 빈도 분석 (b) Gemini 호출
  4) Gemini 가 채널 브리프(channel_brief) + 의식의 흐름 4단 전략을 따라
     "이 채널을 봐야겠다" 느끼게 만드는 설명 + 해시태그 콤마문자열 생성
  5) 결과는 dict — UI 가 코드 블록으로 복붙 가능하게 보여 준다.

테스트는 llm_call 주입 가능 (헤드리스).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

import channel_brief

DEFAULT_MODEL = "gemini-2.0-flash"


# ────────────────────────────────────────────────────────────────────────────
# 1) URL 파싱
# ────────────────────────────────────────────────────────────────────────────
_RE_VIDEO   = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})")
_RE_CHANNEL = re.compile(r"youtube\.com/channel/([A-Za-z0-9_-]+)")
_RE_HANDLE  = re.compile(r"youtube\.com/@([A-Za-z0-9._-]+)")
_RE_USER    = re.compile(r"youtube\.com/(?:c|user)/([A-Za-z0-9._-]+)")


@dataclass
class ParsedURL:
    kind: str        # "video" | "channel_id" | "handle" | "user" | "unknown"
    value: str = ""


def parse_url(url: str) -> ParsedURL:
    u = (url or "").strip()
    if not u:
        return ParsedURL("unknown")
    m = _RE_VIDEO.search(u)
    if m:
        return ParsedURL("video", m.group(1))
    m = _RE_CHANNEL.search(u)
    if m:
        return ParsedURL("channel_id", m.group(1))
    m = _RE_HANDLE.search(u)
    if m:
        return ParsedURL("handle", m.group(1))
    m = _RE_USER.search(u)
    if m:
        return ParsedURL("user", m.group(1))
    return ParsedURL("unknown")


# ────────────────────────────────────────────────────────────────────────────
# 2) YouTube Data API 수집
# ────────────────────────────────────────────────────────────────────────────
@dataclass
class ChannelPayload:
    channel_id: str = ""
    title: str = ""
    description: str = ""
    subscriber_count: int = 0
    video_count: int = 0
    view_count: int = 0
    uploads_playlist_id: str = ""
    # 영상 N개 — 각각 {video_id, title, description, view_count}
    videos: list[dict] = field(default_factory=list)


def _build_youtube(api_key: str):
    from googleapiclient.discovery import build
    return build("youtube", "v3", developerKey=api_key, cache_discovery=False)


def _resolve_channel_id(youtube, parsed: ParsedURL) -> str:
    """파싱된 URL → channel_id 로 표준화."""
    if parsed.kind == "channel_id":
        return parsed.value
    if parsed.kind == "video":
        resp = youtube.videos().list(part="snippet", id=parsed.value, maxResults=1).execute()
        items = resp.get("items", [])
        if items:
            return items[0]["snippet"]["channelId"]
        return ""
    if parsed.kind == "handle":
        # forHandle 지원 (2023+)
        try:
            resp = youtube.channels().list(part="id", forHandle="@" + parsed.value).execute()
            items = resp.get("items", [])
            if items:
                return items[0]["id"]
        except Exception:
            pass
        # fallback: 검색
        resp = youtube.search().list(part="snippet", q="@" + parsed.value, type="channel", maxResults=1).execute()
        items = resp.get("items", [])
        if items:
            return items[0]["snippet"]["channelId"]
        return ""
    if parsed.kind == "user":
        try:
            resp = youtube.channels().list(part="id", forUsername=parsed.value).execute()
            items = resp.get("items", [])
            if items:
                return items[0]["id"]
        except Exception:
            pass
        return ""
    return ""


def fetch_channel_payload(api_key: str, url: str, max_videos: int = 25) -> ChannelPayload:
    """URL → 채널 정체성 + 최근 영상 설명 N개."""
    parsed = parse_url(url)
    if parsed.kind == "unknown":
        raise ValueError("지원하지 않는 URL 형식이에요. 채널 URL 또는 영상 URL 을 넣어주세요.")

    youtube = _build_youtube(api_key)
    channel_id = _resolve_channel_id(youtube, parsed)
    if not channel_id:
        raise ValueError("채널을 찾지 못했어요. URL 을 다시 확인해주세요.")

    # 채널 메타
    ch = youtube.channels().list(
        part="snippet,statistics,contentDetails", id=channel_id, maxResults=1,
    ).execute()
    items = ch.get("items", [])
    if not items:
        raise ValueError("채널 정보를 가져오지 못했어요.")
    c = items[0]
    snip = c.get("snippet", {})
    stats = c.get("statistics", {})
    uploads = (
        c.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads", "")
    )

    payload = ChannelPayload(
        channel_id=channel_id,
        title=snip.get("title", ""),
        description=snip.get("description", ""),
        subscriber_count=int(stats.get("subscriberCount", 0)),
        video_count=int(stats.get("videoCount", 0)),
        view_count=int(stats.get("viewCount", 0)),
        uploads_playlist_id=uploads,
    )

    # 최근 영상 max_videos 개의 id 수집
    video_ids: list[str] = []
    page_token = None
    while uploads and len(video_ids) < max_videos:
        resp = youtube.playlistItems().list(
            part="contentDetails", playlistId=uploads,
            maxResults=min(50, max_videos - len(video_ids)), pageToken=page_token,
        ).execute()
        for it in resp.get("items", []):
            vid = it.get("contentDetails", {}).get("videoId")
            if vid:
                video_ids.append(vid)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    # videos.list 로 description / 통계 일괄
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i + 50]
        if not chunk:
            break
        v = youtube.videos().list(part="snippet,statistics", id=",".join(chunk)).execute()
        for it in v.get("items", []):
            s = it.get("snippet", {})
            st = it.get("statistics", {})
            payload.videos.append({
                "video_id": it.get("id", ""),
                "title": s.get("title", ""),
                "description": s.get("description", ""),
                "tags": s.get("tags", []) or [],
                "view_count": int(st.get("viewCount", 0)),
            })

    return payload


# ────────────────────────────────────────────────────────────────────────────
# 3) 가벼운 키워드 빈도 — Gemini 가 SEO 의도를 잡도록 보조 입력
# ────────────────────────────────────────────────────────────────────────────
_STOP = {
    "youtube", "youtu", "be", "subscribe", "channel", "watch", "https", "http", "www",
    "com", "video", "shorts", "the", "and", "for", "with", "from", "your", "you", "our",
    "this", "that", "all", "are", "was", "have", "has", "but", "not", "out", "more",
    "구독", "좋아요", "알림", "벨", "댓글", "공유", "영상", "음악", "노래", "유튜브",
    "출처", "원곡", "광고", "협찬", "문의", "이메일", "instagram", "facebook", "twitter",
    "tiktok", "kakao", "tel", "fax", "all rights reserved", "copyright",
}

_TOKEN_RE = re.compile(r"[\w가-힣]{2,}", re.UNICODE)


def extract_top_keywords(descriptions: list[str], top_n: int = 30) -> list[tuple[str, int]]:
    """설명 묶음에서 SEO 의도 키워드 상위 N개."""
    counter: Counter = Counter()
    for d in descriptions:
        text = (d or "").lower()
        for token in _TOKEN_RE.findall(text):
            if token in _STOP:
                continue
            if token.isdigit():
                continue
            counter[token] += 1
    return counter.most_common(top_n)


def aggregate_tags(videos: list[dict], top_n: int = 30) -> list[tuple[str, int]]:
    """영상 tags 필드 집계 — YouTube 알고리즘이 직접 참고하는 신호."""
    counter: Counter = Counter()
    for v in videos:
        for tag in v.get("tags") or []:
            counter[tag.strip().lower()] += 1
    return counter.most_common(top_n)


# ────────────────────────────────────────────────────────────────────────────
# 4) Gemini 프롬프트 — 의식의 흐름 + 채널 브리프 자동 주입
# ────────────────────────────────────────────────────────────────────────────
def build_prompt(
    *,
    payload: ChannelPayload,
    top_keywords: list[tuple[str, int]],
    top_tags: list[tuple[str, int]],
    brief: dict | None = None,
    n_variants: int = 2,
    description_length: str = "medium",
) -> str:
    """Gemini 에 줄 지시문 — 항상 채널 브리프와 4단 끌어당김 전략을 적용."""

    brief_block = channel_brief.as_prompt_block(brief)

    length_hint = {
        "short":  "200~350자 (모바일 화면 한 눈에 들어오게)",
        "medium": "400~700자 (SEO 본문 권장 길이)",
        "long":   "800~1200자 (서사형, 음악 채널 깊은 몰입)",
    }.get(description_length, "400~700자")

    sample_descs = "\n\n".join(
        f"[영상 {i+1}] {v.get('title','')}\n{(v.get('description','') or '')[:600]}"
        for i, v in enumerate(payload.videos[:8])
    )

    keyword_lines = ", ".join(f"{w}({c})" for w, c in top_keywords[:15]) or "(없음)"
    tag_lines     = ", ".join(f"{t}({c})" for t, c in top_tags[:15])     or "(없음)"

    return f"""당신은 한국 유튜브 알고리즘과 시청자 심리를 모두 이해하는 시니어 채널 카피라이터입니다.
아래 [채널 브랜드 브리프] 와 [의식의 흐름 4단] 을 반드시 따라,
같은 시청자가 한 번 보면 **"아, 이 채널은 내가 봐야겠다"** 라고 느끼고
구독 버튼을 누르게 만드는 **채널 설명란(About)** 을 작성합니다.

{brief_block}

[참고 — 이 채널의 실제 데이터]
- 채널명: {payload.title}
- 현재 채널 소개(원본): {payload.description[:500]}
- 구독자 수: {payload.subscriber_count:,}
- 총 영상 수: {payload.video_count}
- 총 조회수: {payload.view_count:,}

[참고 — 영상 설명에서 자주 등장한 키워드 상위(빈도)]
{keyword_lines}

[참고 — 영상 태그 빈도 상위]
{tag_lines}

[참고 — 최근 영상 제목/설명 일부]
{sample_descs}

[작성 규칙 — 매우 중요]
1) 첫 1~2줄(약 100자)이 검색결과·미리보기에 노출됩니다. **여기에 가장 강한 갈고리**를 놓으세요.
2) 의식의 흐름 4단(브리프 안 4단 흐름)을 그대로 따릅니다.
   ① 시청자가 지금 겪는 감정/상황 호명 → ② 그림 한 컷(시각·청각·온도) →
   ③ 약속(매일 무엇을 받게 되는가) → ④ 강요 없는 초대(구독 권유)
3) 채널 브리프의 톤·금지어·시그니처 문구를 **반드시 반영**.
4) 위 키워드/태그 중에서 의미 있는 SEO 단어를 본문에 **자연스럽게** 녹여 넣되,
   키워드 나열·반복 금지(YouTube 스팸 가드 트리거).
5) 본문 길이: {length_hint}.
6) 본문 끝에 시그니처 문구 1줄 + 구독 초대 1줄.
7) **해시태그**: 12~15개. 첫 3개는 YouTube 영상 제목 위에 노출되는 자리이므로 가장 정체성을 강하게 드러내는 것.
   브랜드 해시태그 1~2개 + 장르 해시태그 3~4개 + 감정·상황 해시태그 4~5개 + 사용 맥락 해시태그 2~3개.
   해시태그는 "#" 포함, 콤마로 구분된 한 줄 문자열.

[변주]
- 같은 채널에 어울리는 서로 다른 톤의 설명 {n_variants}개를 만들어주세요.
  · 변주 1: "감성 위주 — 한 편의 글처럼 따뜻하게"
  · 변주 2: "구체 약속 위주 — 어떤 상황에 무엇을 들려주는지 명확히"
  (n_variants 가 3 이상이면 세 번째는 "짧고 강한 카피 — 모바일 한눈에")

[반드시 아래 JSON 만 출력 — 마크다운/설명/주석 금지]
{{
  "variants": [
    {{
      "title": "<이 변주의 한 줄 컨셉>",
      "hook":  "<첫 1~2줄 갈고리, 100자 이내>",
      "description": "<완성된 채널 설명 본문 — 줄바꿈 포함>",
      "hashtags": "#tag1, #tag2, #tag3, ...",
      "channel_keywords": "<채널 설정 키워드(쉼표 구분) — 500자 이내>"
    }}
    // {n_variants}개
  ],
  "seo_summary": "<왜 이 설명이 SEO·알고리즘에 강한지 2~3줄 요약>"
}}"""


# ────────────────────────────────────────────────────────────────────────────
# 5) LLM 호출 + 파싱
# ────────────────────────────────────────────────────────────────────────────
def _loads(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def parse(raw: str) -> dict:
    data = _loads(raw)
    variants = []
    for v in data.get("variants") or []:
        variants.append({
            "title": (v.get("title") or "").strip() or "(제목없음)",
            "hook": (v.get("hook") or "").strip(),
            "description": (v.get("description") or "").strip(),
            "hashtags": (v.get("hashtags") or "").strip(),
            "channel_keywords": (v.get("channel_keywords") or "").strip(),
        })
    return {
        "variants": variants,
        "seo_summary": (data.get("seo_summary") or "").strip(),
    }


def gemini_call(prompt: str, *, api_key: str, model: str = DEFAULT_MODEL) -> str:
    import google.generativeai as genai  # type: ignore

    genai.configure(api_key=api_key)
    m = genai.GenerativeModel(
        model_name=model,
        generation_config={"temperature": 0.8, "response_mime_type": "application/json"},
    )
    resp = m.generate_content(prompt)
    return (resp.text or "").strip()


def generate(
    *,
    payload: ChannelPayload,
    brief: dict | None = None,
    n_variants: int = 2,
    description_length: str = "medium",
    llm_call: Callable[[str], str] | None = None,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
) -> dict:
    """채널 페이로드 + 브리프 → 채널 설명 변주 결과."""
    descs = [v.get("description", "") for v in payload.videos]
    top_keywords = extract_top_keywords(descs)
    top_tags = aggregate_tags(payload.videos)

    prompt = build_prompt(
        payload=payload,
        top_keywords=top_keywords,
        top_tags=top_tags,
        brief=brief,
        n_variants=n_variants,
        description_length=description_length,
    )

    if llm_call is None:
        if not api_key:
            raise ValueError("api_key 또는 llm_call 중 하나가 필요합니다.")
        raw = gemini_call(prompt, api_key=api_key, model=model)
    else:
        raw = llm_call(prompt)

    out = parse(raw)
    out["top_keywords"] = top_keywords
    out["top_tags"] = top_tags
    return out


# ────────────────────────────────────────────────────────────────────────────
# CLI 자가검증 (LLM 없이)
# ────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # URL 파싱 검증
    for url in [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://youtube.com/channel/UCabc123def",
        "https://www.youtube.com/@stellajang",
        "https://youtube.com/c/somechannel",
    ]:
        p = parse_url(url)
        print(f"{url}  →  {p.kind}: {p.value}")

    # 키워드 추출 검증
    sample = [
        "프렌치 샹송 카페 음악, 비 오는 날 듣기 좋은 잔잔한 피아노. 위로받고 싶은 밤에.",
        "잠들기 전 듣는 부드러운 피아노 모음. 카페 무드 음악, 아코디언, 어쿠스틱.",
        "스텔라장식 스타일의 따뜻한 샹송. 혼자 듣는 위로의 음악.",
    ]
    top = extract_top_keywords(sample, top_n=10)
    print("\n[Top keywords]")
    for w, c in top:
        print(f"  {w}: {c}")

    # 가짜 LLM 으로 generate 검증
    payload = ChannelPayload(
        channel_id="UCtest", title="파리지앵 샹송 카페", description="비 오는 파리의 작은 카페",
        subscriber_count=12345, video_count=80, view_count=500000,
        videos=[{"video_id": "v1", "title": "비오는 카페", "description": d, "tags": [], "view_count": 1000}
                for d in sample],
    )

    def stub(_p: str) -> str:
        return json.dumps({
            "variants": [
                {
                    "title": "감성 위주",
                    "hook": "오늘 하루도 길었죠.",
                    "description": "비 오는 파리의 작은 카페에서…\n오늘의 당신께 7분의 위로를.",
                    "hashtags": "#프렌치샹송, #카페음악, #잠들기전음악, #위로, #피아노",
                    "channel_keywords": "프렌치 샹송, 카페 음악, 잠들기 전, 위로",
                },
                {
                    "title": "구체 약속 위주",
                    "hook": "퇴근길, 잠들기 전, 비 오는 날.",
                    "description": "매일 한 곡, 7~12분의 카페 무드 음악…",
                    "hashtags": "#프렌치샹송, #피아노, #카페음악, #감성, #힐링",
                    "channel_keywords": "프렌치 샹송, 피아노, 카페 음악",
                },
            ],
            "seo_summary": "감성 키워드 + 사용 맥락 키워드를 자연스럽게 결합.",
        }, ensure_ascii=False)

    out = generate(payload=payload, n_variants=2, llm_call=stub)
    print(f"\n[generate] {len(out['variants'])}개 변주")
    for v in out["variants"]:
        print(f"  · {v['title']}: {v['hashtags']}")
