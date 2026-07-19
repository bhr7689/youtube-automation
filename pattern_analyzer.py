"""pattern_analyzer.py — 링크 여러 개 → 썸네일·제목 패턴 분석 → 자동 프롬프트화.

한 장르의 잘된 영상 링크 N개를 받아:
  1) 메타(제목·썸네일·태그) 수집
  2) GPT-4o Vision 이 실제 썸네일들을 직접 보고 + 제목 읽고 →
     · 썸네일↔제목 일치성 채점(전체 + 영상별)
     · 썸네일 패턴(구도·각도·인물·색#·문구·배경·무드)
     · 제목 패턴(고정문구·상황·감각어·이모지·구조·톤)
     · 재사용 생성 프롬프트(이미지 프롬프트 + 제목 공식 + 예시 제목)
키 없으면 휴리스틱(제목 통계) 폴백. Streamlit 비의존.
"""
from __future__ import annotations

import json
import os
import sys

_BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jpshorts", "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import link_classifier as LC
import tier_lab as T

_SCHEMA = """아래 JSON 스키마로만 답하라(한국어 값, 프롬프트는 지정 언어):
{
 "consistency": {"avg_score": <0-100 정수>, "note": "<전체 일치성 한 줄 평>"},
 "per_video": [{"i": <1부터>, "score": <0-100>, "note": "<한 줄>"}],
 "thumbnail_pattern": {
   "composition": "<공통 구도/레이아웃>", "angle": "<카메라 각도>",
   "subject": "<인물/오브젝트 유무·특징>", "colors": ["#hex","#hex","#hex"],
   "text_overlay": "<이미지 위 문구 스타일: 폰트굵기·위치·색·글자수>",
   "background": "<배경 유형>", "mood": "<지배 무드>"
 },
 "title_pattern": {
   "fixed_phrases": ["<반복 고정문구>"], "situation": "<상황/장면 묘사 방식>",
   "sensory": ["<자주 쓰는 감각어>"], "emoji": "<이모지 사용 패턴>",
   "structure": "<문형/구조>", "tone": "<톤>"
 },
 "generation_prompt": {
   "thumbnail_prompt": "<이 패턴을 재현하는 영어 이미지생성 프롬프트 — 구도·색#·조명·무드, 글자는 빼고 장면만>",
   "title_template": "<한국어 제목 공식 템플릿, 예: [감각어]+[상황]+[장르] (이모지1)>",
   "example_titles": ["<예시 제목1>","<예시 제목2>","<예시 제목3>"]
 }
}"""


def _vision_analyze(thumbs: list[str], titles: list[str], genre: str) -> dict | None:
    """GPT-4o Vision 으로 썸네일들 직접 보고 패턴+일치성+프롬프트 JSON 추출."""
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return None
    pairs = [(t, ti) for t, ti in zip(thumbs, titles) if LC and _is_img(t)][:9]
    if not pairs:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key)
        head = (f"너는 유튜브 '{genre}' 장르 썸네일·제목 분석가다. "
                f"아래 {len(pairs)}개 영상의 실제 썸네일 이미지와 제목을 보고, "
                f"공통 승리 패턴과 썸네일↔제목 일치성을 분석하라.\n" + _SCHEMA)
        content: list = [{"type": "text", "text": head}]
        for i, (th, ti) in enumerate(pairs):
            content.append({"type": "text", "text": f"#{i+1} 제목: {ti}"})
            content.append({"type": "image_url", "image_url": {"url": th, "detail": "low"}})
        r = client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": content}],
            temperature=0.4, max_tokens=1600, response_format={"type": "json_object"})
        return json.loads(r.choices[0].message.content or "{}")
    except Exception:                   # noqa: BLE001
        return None


def _is_img(u: str) -> bool:
    try:
        import concept_maker as CM
        return CM._is_image_ref(u)
    except Exception:                   # noqa: BLE001
        return isinstance(u, str) and u.startswith("http")


def _heuristic(titles: list[str], agg: dict, genre: str) -> dict:
    """키 없을 때: 제목 통계만으로 패턴·프롬프트 구성(썸네일은 미상)."""
    sens = [w for w, _ in agg.get("sensory", [])][:4]
    situ = [w for w, _ in agg.get("situation", [])][:4]
    emo = "".join(w for w, _ in agg.get("top_emojis", [])[:2])
    template = " + ".join(x for x in [
        ("[감각어:" + "·".join(sens) + "]") if sens else "",
        ("[상황:" + "·".join(situ) + "]") if situ else "",
        f"(이모지 {emo})" if emo else ""] if x) or "[상황]+[감각어]"
    return {
        "consistency": {"avg_score": 0, "note": "썸네일 이미지 분석은 GPT 키가 필요합니다(제목 통계만 표시)."},
        "per_video": [],
        "thumbnail_pattern": {"composition": "(GPT 키 필요)", "angle": "", "subject": "",
                              "colors": [], "text_overlay": "", "background": "", "mood": ""},
        "title_pattern": {"fixed_phrases": [], "situation": "·".join(situ),
                          "sensory": sens, "emoji": emo, "structure": "", "tone": genre},
        "generation_prompt": {
            "thumbnail_prompt": f"{genre} playlist thumbnail, cozy cinematic mood (GPT 키로 정밀화 가능)",
            "title_template": template,
            "example_titles": [t for t in titles[:3]]},
    }


def _gather(urls: list[str], per_channel: int = 2) -> list[dict]:
    """채널/핸들 URL → 그 채널의 실제 영상 썸네일(로고 아님), 영상 URL → 그대로.
    로고를 분석하던 버그 방지: 패턴은 영상 썸네일로만 본다."""
    try:
        import concept_maker as CM
    except Exception:                   # noqa: BLE001
        CM = None
    metas, video_urls = [], []
    for u in urls:
        kind, _ = LC.extract_ref(u)
        if kind in ("channel", "handle") and CM is not None:
            data = CM.collect_channel(u)
            vids = sorted(data.get("videos", []), key=lambda v: v.get("views", 0), reverse=True)
            for v in vids[:per_channel]:
                metas.append({"url": f"https://youtu.be/{v.get('video_id','')}",
                              "title": v.get("title", ""), "thumb": v.get("thumb", ""),
                              "channel": data.get("title", ""), "desc": "", "tags": []})
        else:
            video_urls.append(u)
    if video_urls:
        metas += LC.fetch_meta(video_urls)
    return metas


def analyze_videos(videos: list[dict], genre: str = "") -> dict:
    """이미 확보한 영상 dict 목록({title,thumb}) → 패턴 분석."""
    titles = [v.get("title", "") for v in videos]
    thumbs = [v.get("thumb", "") for v in videos]
    agg = T.aggregate_titles([{"title": t} for t in titles if t])
    vision = _vision_analyze(thumbs, titles, genre)
    engine = "gpt-4o-vision"
    if vision is None:
        vision = _heuristic(titles, agg, genre)
        engine = "heuristic(제목만)"
    return {"n": len(videos), "genre": genre, "engine": engine,
            "metas": videos, "title_stats": agg, **vision}


def analyze(urls: list[str], genre: str = "", per_channel: int = 2) -> dict:
    """링크 N개(채널/영상 혼합) → 영상 썸네일로 확장 → 패턴 분석."""
    return analyze_videos(_gather(urls, per_channel), genre)


_BRAND_SCHEMA = """아래 JSON 만(한국어 값):
{"palette":["#hex","#hex","#hex"],"visual_style":"<전체 비주얼 스타일>",
 "mood":"<지배 무드/정서>","logo_style":"<로고 특징>","banner_style":"<배너 특징>",
 "thumbnail_consistency":"<썸네일들의 공통 결·일관성>","tone":"<채널 톤>",
 "signature_summary":"<이 채널의 '결'을 한 문단으로 — 색·스타일·무드·정체성>"}"""


def _brand_vision(logo, banner, thumbs, title, desc, keywords, genre):
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    imgs = [u for u in ([logo, banner] + list(thumbs)) if _is_img(u)][:8]
    if not key or not imgs:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key)
        head = (f"너는 유튜브 채널 브랜드 분석가다. 채널 '{title}'({genre})의 로고·배너·썸네일 "
                f"이미지와 아래 텍스트를 보고 이 채널의 '결'(비주얼 정체성)을 종합 분석하라.\n"
                f"설명글: {(desc or '')[:300]}\n채널 키워드/태그: {(keywords or '')[:200]}\n" + _BRAND_SCHEMA)
        content = [{"type": "text", "text": head}]
        labels = ["[로고]", "[배너]"] + ["[썸네일]"] * len(thumbs)
        for lab, u in zip(labels, imgs):
            content.append({"type": "text", "text": lab})
            content.append({"type": "image_url", "image_url": {"url": u, "detail": "low"}})
        r = client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": content}],
            temperature=0.4, max_tokens=900, response_format={"type": "json_object"})
        return json.loads(r.choices[0].message.content or "{}")
    except Exception:                   # noqa: BLE001
        return None


def channel_brand(url: str, genre: str = "") -> dict:
    """채널 URL → 로고·배너·설명·태그·썸네일 수집 + Vision '결' 분석."""
    try:
        import youtube_client as yc
        import channel_watcher as W
        import concept_maker as CM
    except Exception:                   # noqa: BLE001
        return {"error": "모듈 로드 실패"}
    if not yc.has_key():
        return {"error": "YouTube 키가 필요해요(설정 탭)."}
    cid = W.resolve_channel_id(url)
    if not cid:
        return {"error": f"채널을 찾지 못했어요: {url}"}
    try:
        r = yc._yt().channels().list(part="snippet,brandingSettings,statistics", id=cid).execute()
        items = r.get("items", [])
        if not items:
            return {"error": "채널 정보 없음"}
        it = items[0]
        sn, bs = it["snippet"], it.get("brandingSettings", {})
        th = sn.get("thumbnails", {})
        logo = next((th[q]["url"] for q in ("high", "medium", "default") if th.get(q, {}).get("url")), "")
        banner = bs.get("image", {}).get("bannerExternalUrl", "")
        if banner:
            banner = banner + "=w1280"
        desc = sn.get("description", "")
        keywords = bs.get("channel", {}).get("keywords", "")
        data = CM.collect_channel(url)
        thumbs = [v["thumb"] for v in data.get("videos", [])[:6] if v.get("thumb")]
        vision = _brand_vision(logo, banner, thumbs, sn["title"], desc, keywords, genre)
        return {"title": sn["title"], "description": desc, "keywords": keywords,
                "logo": logo, "banner": banner, "thumbs": thumbs,
                "subscribers": int(it.get("statistics", {}).get("subscriberCount", 0) or 0),
                "vision": vision}
    except Exception as e:              # noqa: BLE001
        return {"error": f"수집 실패: {e}"}
