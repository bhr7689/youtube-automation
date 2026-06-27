"""다국어 자동 번역 + YouTube 동시 검색.

한국어 키워드 1개 → Gemini로 N개 언어 동시 번역 (각 나라 자연스러운 표현) →
각 (region, language)로 YouTube search.list 병렬 호출 → 통합 결과.

각 영상 dict에 'search_lang_label' (예: '🇯🇵 일본어') 와 'search_query'
(번역된 검색어)가 붙어 있어 결과 표에서 어느 언어로 잡혔는지 표시 가능.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional


# (label, lang_code(검색용 relevanceLanguage), region_code)
LANGUAGES: list[tuple[str, str, str]] = [
    ("🇰🇷 한국어",            "ko",    "KR"),
    ("🇺🇸 영어 (미국)",       "en",    "US"),
    ("🇬🇧 영어 (영국)",       "en",    "GB"),
    ("🇯🇵 일본어",            "ja",    "JP"),
    ("🇫🇷 프랑스어",          "fr",    "FR"),
    ("🇮🇳 힌디어 (인도)",     "hi",    "IN"),
    ("🇮🇳 영어 (인도)",       "en",    "IN"),
    ("🇪🇸 스페인어 (스페인)", "es",    "ES"),
    ("🇲🇽 스페인어 (멕시코)", "es",    "MX"),
    ("🇧🇷 포르투갈어 (브라질)", "pt",   "BR"),
    ("🇹🇼 중국어 번체 (대만)", "zh-TW", "TW"),
    ("🇩🇪 독일어",            "de",    "DE"),
    ("🇮🇩 인도네시아어",      "id",    "ID"),
    ("🇻🇳 베트남어",          "vi",    "VN"),
    ("🇹🇭 태국어",            "th",    "TH"),
]

LABEL_TO_LANG = {l[0]: (l[1], l[2]) for l in LANGUAGES}


# Gemini 모델 이름은 시간이 지나면서 바뀌고 deprecate 됨.
# 최신 → 구버전 순으로 fallback 시도해서 안정성 확보.
# 환경변수 GEMINI_MODELS (콤마구분) 으로 override 가능.
GEMINI_MODELS_DEFAULT = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-flash-latest",
    "gemini-2.0-flash-exp",
    "gemini-1.5-flash-latest",
    "gemini-1.5-flash",
]


def _get_gemini_models() -> list[str]:
    env = os.environ.get("GEMINI_MODELS", "").strip()
    if env:
        return [m.strip() for m in env.split(",") if m.strip()]
    return GEMINI_MODELS_DEFAULT


def _gemini_generate_with_fallback(api_key: str, prompt: str) -> tuple[str, Optional[str], list[str]]:
    """여러 모델 순차 시도. (응답텍스트, 에러메시지, 시도한모델목록)
    하나라도 성공하면 그걸로 반환. 다 실패하면 마지막 에러 반환."""
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    tried = []
    last_err = ""
    for model_name in _get_gemini_models():
        tried.append(model_name)
        try:
            model = genai.GenerativeModel(model_name)
            resp = model.generate_content(prompt)
            text = (resp.text or "").strip()
            if text:
                return text, None, tried
            last_err = "빈 응답"
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:120]}"
            continue
    return "", f"모든 모델 실패. 마지막: {last_err}", tried


def translate_keyword(
    korean_keyword: str,
    labels: list[str],
    *,
    api_key: str = "",
) -> tuple[dict[str, str], Optional[str]]:
    """한국어 키워드 → {label: 번역된 검색어}.

    여러 Gemini 모델을 순차 시도해서 모델 deprecation 에 강인함.
    실패해도 한국어 라벨은 그대로 통과 (= 부분 동작 보장).
    """
    api_key = api_key or os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        # API 키 없어도 한국어는 그대로 검색 가능
        return ({label: korean_keyword for label in labels},
                "GEMINI_API_KEY 가 없어서 번역 없이 같은 키워드로 검색해요.")

    try:
        import google.generativeai as genai  # noqa: F401
    except Exception as e:
        return ({label: korean_keyword for label in labels},
                f"google-generativeai 미설치 — 같은 키워드로 검색: {e}")

    # 한국어 라벨은 번역 안 함 (그대로 유지)
    keep_korean = {label: korean_keyword for label in labels if "한국어" in label}
    targets = [label for label in labels if "한국어" not in label]
    if not targets:
        return keep_korean, None

    lang_list = "\n".join(f"- {label}" for label in targets)
    prompt = (
        f'한국어 키워드 "{korean_keyword}" 를 다음 나라/언어들로 번역해줘.\n'
        '각 나라 사람들이 유튜브 검색창에 실제로 칠 만한 자연스러운 표현으로. '
        '직역 X, 그 나라 콘텐츠 제목·해시태그에서 쓰는 표현으로.\n\n'
        f'{lang_list}\n\n'
        '오직 JSON 한 덩어리만 답해. 마크다운 코드블록 ``` 도 쓰지 마. 키는 위 라벨 그대로:\n'
        '{"🇺🇸 영어 (미국)": "...", "🇯🇵 일본어": "..."}'
    )

    text, gemini_err, tried = _gemini_generate_with_fallback(api_key, prompt)
    out: dict[str, str] = {**keep_korean}

    if gemini_err:
        # Gemini 전부 실패 → 한국어 키워드로라도 모두 검색 (부분 동작)
        for label in targets:
            out[label] = korean_keyword
        return out, (
            f"Gemini 번역 실패 — 모든 언어를 한국어 키워드로 검색합니다. "
            f"시도한 모델: {', '.join(tried)}. {gemini_err}"
        )

    # 코드블록 제거 + JSON 파싱
    try:
        cleaned = re.sub(r"^```(?:json)?\s*", "", text)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            raise ValueError("응답이 JSON 객체가 아님")
    except (json.JSONDecodeError, ValueError) as e:
        for label in targets:
            out[label] = korean_keyword
        return out, (
            f"Gemini JSON 파싱 실패 — 한국어 키워드로 검색합니다. "
            f"오류: {e}. 응답: {text[:200]}"
        )

    for label in targets:
        translated = data.get(label) or korean_keyword
        out[label] = str(translated).strip()
    return out, None


def _parse_duration_to_seconds(s: str) -> Optional[int]:
    if not s:
        return None
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s)
    if not m:
        return None
    h, mi, se = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + se


def _search_one_language(
    youtube, *, query: str, region: str, lang: str,
    per_lang: int, days: int, order: str,
) -> list[str]:
    """단일 (region, lang)로 search.list → 영상 ID 리스트."""
    published_after = None
    if days > 0:
        published_after = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat(timespec="seconds").replace("+00:00", "Z")

    ids: list[str] = []
    page_token = None
    while len(ids) < per_lang:
        params = {
            "part": "id", "q": query, "type": "video", "order": order,
            "maxResults": min(50, per_lang - len(ids)),
            "pageToken": page_token,
            "regionCode": region, "relevanceLanguage": lang,
        }
        if published_after:
            params["publishedAfter"] = published_after
        resp = youtube.search().list(**params).execute()
        for it in resp.get("items", []):
            vid = it.get("id", {}).get("videoId")
            if vid:
                ids.append(vid)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return ids


def _hydrate_videos(youtube, ids: list[str]) -> dict[str, dict]:
    """video_id → 메타 dict (snippet + statistics + contentDetails)."""
    out: dict[str, dict] = {}
    for i in range(0, len(ids), 50):
        resp = youtube.videos().list(
            part="snippet,statistics,contentDetails",
            id=",".join(ids[i:i + 50]), maxResults=50,
        ).execute()
        for it in resp.get("items", []):
            vid = it["id"]
            sn = it.get("snippet", {})
            stat = it.get("statistics", {})
            cd = it.get("contentDetails", {})
            out[vid] = {
                "video_id": vid,
                "title": sn.get("title", ""),
                "channel_id": sn.get("channelId"),
                "channel_title": sn.get("channelTitle", ""),
                "published_at": (sn.get("publishedAt", "") or "")[:10],
                "thumbnail_url": (
                    sn.get("thumbnails", {}).get("medium", {}).get("url")
                    or sn.get("thumbnails", {}).get("default", {}).get("url")
                    or ""
                ),
                "view_count": int(stat.get("viewCount", 0) or 0),
                "like_count": int(stat.get("likeCount", 0) or 0),
                "comment_count": int(stat.get("commentCount", 0) or 0),
                "duration_s": _parse_duration_to_seconds(cd.get("duration", "")),
            }
    return out


def _hydrate_channels(youtube, channel_ids: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(0, len(channel_ids), 50):
        resp = youtube.channels().list(
            part="snippet,statistics",
            id=",".join(channel_ids[i:i + 50]), maxResults=50,
        ).execute()
        for it in resp.get("items", []):
            cid = it["id"]
            sn = it.get("snippet", {})
            stat = it.get("statistics", {})
            hidden = stat.get("hiddenSubscriberCount", False)
            out[cid] = {
                "subscriber_count": (None if hidden else
                                      int(stat.get("subscriberCount", 0) or 0)),
                "channel_video_count": int(stat.get("videoCount", 0) or 0),
                "channel_created_at": (sn.get("publishedAt", "") or "")[:10],
                "channel_total_views": int(stat.get("viewCount", 0) or 0),
            }
    return out


def search_multilang(
    yt_api_key: str,
    translations: dict[str, str],
    *,
    per_lang: int = 15,
    days: int = 30,
    order: str = "viewCount",
    min_ratio: float = 0.0,
    min_views: int = 0,
) -> tuple[list[dict], Optional[str]]:
    """{label: 검색어} → 각 언어로 병렬 검색 → 통합 list[dict].

    각 영상에 search_lang_label, search_query 메타 추가.
    중복 영상은 가장 먼저 잡힌 라벨 유지.
    """
    if not translations:
        return [], "번역 결과가 없어요."

    try:
        from googleapiclient.discovery import build
    except Exception as e:
        return [], f"googleapiclient 가 없어요: {e}"

    yt = build("youtube", "v3", developerKey=yt_api_key, cache_discovery=False)

    # 1) 언어별 ID 수집 (병렬)
    lang_ids: dict[str, list[str]] = {}

    def _job(label_q: tuple[str, str]) -> tuple[str, list[str]]:
        label, query = label_q
        lang, region = LABEL_TO_LANG.get(label, ("", ""))
        try:
            ids = _search_one_language(
                yt, query=query, region=region, lang=lang,
                per_lang=per_lang, days=days, order=order,
            )
        except Exception as e:
            print(f"[{label}] 검색 실패: {e}")
            ids = []
        return label, ids

    with cf.ThreadPoolExecutor(max_workers=min(8, len(translations))) as ex:
        for label, ids in ex.map(_job, translations.items()):
            lang_ids[label] = ids

    # 2) 영상 메타 한 번에 (중복 ID 합쳐서 1회 호출)
    all_ids = list({vid for ids in lang_ids.values() for vid in ids})
    if not all_ids:
        return [], None
    videos_meta = _hydrate_videos(yt, all_ids)

    # 3) 채널 통계 (구독자, 영상수)
    chan_ids = list({v["channel_id"] for v in videos_meta.values() if v.get("channel_id")})
    chan_meta = _hydrate_channels(yt, chan_ids)

    # 4) 합치기 — 한 영상이 여러 언어 검색에 잡히면 모든 언어 라벨 누적
    seen: dict[str, dict] = {}
    for label, ids in lang_ids.items():
        for vid in ids:
            if vid not in videos_meta:
                continue
            if vid in seen:
                # 이미 본 영상 — 라벨/검색어만 추가
                if label not in seen[vid]["search_lang_labels"]:
                    seen[vid]["search_lang_labels"].append(label)
                    seen[vid]["search_queries"].append(translations.get(label, ""))
                continue
            v = dict(videos_meta[vid])
            ch = chan_meta.get(v.get("channel_id") or "", {})
            v["subscriber_count"] = ch.get("subscriber_count")
            v["channel_video_count"] = ch.get("channel_video_count")
            v["channel_created_at"] = ch.get("channel_created_at", "")
            v["channel_total_views"] = ch.get("channel_total_views", 0)
            subs = v.get("subscriber_count") or 0
            v["viral_ratio"] = (
                v["view_count"] / max(subs, 100) if v.get("view_count") else 0.0
            )
            v["search_lang_labels"] = [label]
            v["search_queries"] = [translations.get(label, "")]
            # 첫 번째 라벨/쿼리는 호환성을 위해 단일 필드로도 유지
            v["search_lang_label"] = label
            v["search_query"] = translations.get(label, "")
            seen[vid] = v

    # 콤마구분 라벨 만들기 (표/카드에서 보여주기 쉽게)
    for v in seen.values():
        labels_list = v.get("search_lang_labels", [])
        # 국기 부분만 골라서 짧게
        flags = []
        for lab in labels_list:
            # "🇰🇷 한국어" → "🇰🇷"
            parts = lab.split()
            if parts:
                flags.append(parts[0])
        v["search_lang_flags"] = " ".join(flags)
        v["search_lang_count"] = len(labels_list)

    results = list(seen.values())

    # 5) 필터
    if min_views > 0:
        results = [v for v in results if v["view_count"] >= min_views]
    if min_ratio > 0:
        results = [v for v in results if v.get("viral_ratio", 0) >= min_ratio]

    # 정렬: 바이럴 배수 큰 순
    results.sort(key=lambda x: -(x.get("viral_ratio") or 0))
    return results, None
