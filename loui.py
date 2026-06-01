"""
루이의 떡상 채널 찾기
YouTube 영상 검색 + 비율 분석 + AI 아이디어 생성
"""

import streamlit as st
import requests
import pandas as pd
import json
import os
from datetime import datetime, timedelta, timezone

# ───────────────────────────────────────────────
# 페이지 설정
# ───────────────────────────────────────────────
st.set_page_config(
    page_title="루이의 떡상 채널 찾기",
    page_icon="💧",
    layout="wide",
    menu_items={},
)

# ───────────────────────────────────────────────
# 다크 테마 CSS
# ───────────────────────────────────────────────
st.markdown("""
<style>
/* 전체 배경 */
.stApp { background-color: #1a1a2e; color: #e0e0e0; }
.block-container { padding: 60px 0 0 0 !important; max-width: 100% !important; }

/* Streamlit 상단 툴바 완전 숨기기 */
header { display: none !important; visibility: hidden !important; }
header[data-testid="stHeader"] { display: none !important; }
[data-testid="stToolbar"] { display: none !important; }
[data-testid="stDecoration"] { display: none !important; }
[data-testid="stStatusWidget"] { display: none !important; }
#MainMenu { display: none !important; visibility: hidden !important; }
footer { display: none !important; visibility: hidden !important; }
.stDeployButton { display: none !important; }
.viewerBadge_container__r5tak { display: none !important; }
.styles_viewerBadge__CvC9N { display: none !important; }

/* 헤더 */
.header-bar {
    background: #0f0f1a;
    padding: 14px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 1px solid #2a2a3e;
    margin-bottom: 20px;
}
.header-title { font-size: 22px; font-weight: 700; color: #fff; }
.header-sub { font-size: 12px; color: #888; margin-top: 2px; }

/* 필터 패널 */
.filter-panel {
    background: #16213e;
    border: 1px solid #2a2a4e;
    border-radius: 12px;
    padding: 20px 24px;
    margin: 0 16px 16px 16px;
}

/* 정렬 바 */
.sort-bar {
    background: #16213e;
    border: 1px solid #2a2a4e;
    border-radius: 12px;
    padding: 12px 20px;
    margin: 0 16px 16px 16px;
    display: flex;
    align-items: center;
    gap: 10px;
}

/* 카드 그리드 */
.card-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 16px;
    padding: 0 16px 32px 16px;
}

/* 카드 */
.video-card {
    background: #16213e;
    border: 1px solid #2a2a4e;
    border-radius: 12px;
    overflow: hidden;
    transition: transform 0.2s;
}
.video-card:hover { transform: translateY(-2px); border-color: #4a4a8e; }

.thumb-wrap {
    position: relative;
    width: 100%;
    padding-top: 56.25%;
    overflow: hidden;
    cursor: pointer;
}
.thumb-wrap img {
    position: absolute;
    top: 0; left: 0;
    width: 100%; height: 100%;
    object-fit: cover;
}
.duration-badge {
    position: absolute;
    bottom: 6px; right: 6px;
    background: rgba(0,0,0,0.8);
    color: #fff;
    font-size: 11px;
    padding: 2px 6px;
    border-radius: 4px;
}

.card-body { padding: 12px; }
.card-title {
    font-size: 13px;
    font-weight: 600;
    color: #e0e0e0;
    line-height: 1.4;
    height: 2.8em;
    overflow: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    margin-bottom: 6px;
}
.card-channel {
    font-size: 11px;
    color: #888;
    margin-bottom: 10px;
    display: flex;
    align-items: center;
    gap: 4px;
}

/* 등급 뱃지 */
.badge {
    width: 100%;
    padding: 7px 0;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 700;
    text-align: center;
    margin-bottom: 10px;
    cursor: default;
}
.badge-god    { background: linear-gradient(90deg,#e91e8c,#ff4757); color:#fff; }
.badge-ultra  { background: #ff6b35; color: #fff; }
.badge-great  { background: #7c3aed; color: #fff; }
.badge-rising { background: #0891b2; color: #fff; }
.badge-good   { background: #16a34a; color: #fff; }
.badge-normal { background: #374151; color: #aaa; }

/* 스탯 */
.stats-row {
    display: flex;
    justify-content: space-between;
    font-size: 12px;
    color: #aaa;
    margin-bottom: 4px;
}
.stat-value { color: #e0e0e0; font-weight: 600; }
.ratio-value { color: #22d3ee; font-weight: 700; }

/* 액션 버튼 */
.btn-row {
    display: flex;
    gap: 8px;
    margin-top: 12px;
}
.btn-copy {
    flex: 1;
    padding: 8px 0;
    border-radius: 8px;
    background: #374151;
    color: #e0e0e0;
    border: none;
    font-size: 12px;
    cursor: pointer;
    transition: background 0.2s;
}
.btn-copy:hover { background: #4b5563; }
.btn-ai {
    flex: 1;
    padding: 8px 0;
    border-radius: 8px;
    background: #2563eb;
    color: #fff;
    border: none;
    font-size: 12px;
    cursor: pointer;
    transition: background 0.2s;
}
.btn-ai:hover { background: #1d4ed8; }

/* Streamlit 기본 요소 스타일 덮어쓰기 */
div[data-testid="stSelectbox"] > div { background: #1e293b !important; border-color: #3a3a5e !important; color: #e0e0e0 !important; }
div[data-testid="stTextInput"] input { background: #1e293b !important; border-color: #3a3a5e !important; color: #e0e0e0 !important; }
div[data-testid="stButton"] button { border-radius: 8px !important; }

/* 파란 버튼 */
.search-btn button {
    background: #2563eb !important;
    color: #fff !important;
    border: none !important;
    font-weight: 700 !important;
    font-size: 15px !important;
}

/* 토스트 */
.toast {
    position: fixed;
    bottom: 30px;
    left: 50%;
    transform: translateX(-50%);
    background: #22d3ee;
    color: #000;
    padding: 10px 24px;
    border-radius: 20px;
    font-weight: 700;
    z-index: 9999;
    animation: fadeout 2s forwards;
}
@keyframes fadeout {
    0%{opacity:1} 70%{opacity:1} 100%{opacity:0}
}

/* 정렬 pill 버튼 */
.pill-active {
    background: #2563eb !important;
    color: #fff !important;
    border: none !important;
    border-radius: 20px !important;
    padding: 4px 18px !important;
    font-size: 13px !important;
    font-weight: 600 !important;
    cursor: pointer;
}
.pill-inactive {
    background: #374151 !important;
    color: #aaa !important;
    border: none !important;
    border-radius: 20px !important;
    padding: 4px 18px !important;
    font-size: 13px !important;
    cursor: pointer;
}

label { color: #aaa !important; font-size: 12px !important; }
</style>
""", unsafe_allow_html=True)

# ───────────────────────────────────────────────
# 세션 상태 초기화
# ───────────────────────────────────────────────
if "yt_api_key" not in st.session_state:
    st.session_state.yt_api_key = os.environ.get("YOUTUBE_API_KEY", "")
if "results" not in st.session_state:
    st.session_state.results = []
if "sort_by" not in st.session_state:
    st.session_state.sort_by = "조회수순"
if "sort_asc" not in st.session_state:
    st.session_state.sort_asc = False  # False=내림차순
if "ai_key" not in st.session_state:
    st.session_state.ai_key = os.environ.get("GEMINI_API_KEY", "")

# ───────────────────────────────────────────────
# 헬퍼 함수
# ───────────────────────────────────────────────

def fmt_num(n):
    """숫자를 K/M 형식으로 포맷"""
    try:
        n = int(n)
    except Exception:
        return "0"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def get_badge(ratio: float):
    """비율(%)에 따라 등급 반환"""
    if ratio >= 10000:
        return ("👑 신의 간택", "badge-god")
    if ratio >= 5000:
        return ("🔥 조대박", "badge-ultra")
    if ratio >= 1000:
        return ("🎯 대박", "badge-great")
    if ratio >= 500:
        return ("💧 떡상", "badge-rising")
    if ratio >= 100:
        return ("⭐ 우수", "badge-good")
    return ("▪️ 일반", "badge-normal")


def parse_duration(iso: str) -> str:
    """ISO 8601 duration → mm:ss 또는 hh:mm:ss"""
    import isodate
    try:
        td = isodate.parse_duration(iso)
        total = int(td.total_seconds())
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"
    except Exception:
        return ""


def published_after(option: str) -> str | None:
    """업로드 날짜 옵션 → RFC3339 문자열 (None이면 전체)"""
    now = datetime.now(timezone.utc)
    mapping = {
        "오늘(24시간)": now - timedelta(days=1),
        "이번주(7일)": now - timedelta(days=7),
        "14일": now - timedelta(days=14),
        "이번달(30일)": now - timedelta(days=30),
        "올해(1년)": now - timedelta(days=365),
    }
    dt = mapping.get(option)
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def video_duration_filter(option: str) -> str | None:
    """영상 길이 옵션 → YouTube API videoDuration 파라미터"""
    mapping = {
        "4분 미만": "short",
        "4분~20분": "medium",
        "20분 초과": "long",
    }
    return mapping.get(option)


def search_order(option: str) -> str:
    mapping = {
        "관련성": "relevance",
        "조회수순": "viewCount",
        "최신순": "date",
    }
    return mapping.get(option, "relevance")


def search_youtube(keywords: list[str], api_key: str, date_option: str,
                   length_option: str, order_option: str) -> list[dict]:
    """YouTube Data API로 영상 검색 후 통계 포함 결과 반환"""
    base_search = "https://www.googleapis.com/youtube/v3/search"
    base_videos = "https://www.googleapis.com/youtube/v3/videos"
    base_channels = "https://www.googleapis.com/youtube/v3/channels"

    all_items = []
    seen_ids = set()

    for kw in keywords:
        params = {
            "part": "snippet",
            "q": kw.strip(),
            "type": "video",
            "maxResults": 50,
            "key": api_key,
            "order": search_order(order_option),
        }
        pub_after = published_after(date_option)
        if pub_after:
            params["publishedAfter"] = pub_after
        dur = video_duration_filter(length_option)
        if dur:
            params["videoDuration"] = dur

        resp = requests.get(base_search, params=params, timeout=10)
        if resp.status_code != 200:
            st.error(f"YouTube 검색 오류: {resp.json().get('error', {}).get('message', resp.text)}")
            return []

        items = resp.json().get("items", [])
        for it in items:
            vid = it["snippet"].get("videoId") or it.get("id", {}).get("videoId")
            if vid and vid not in seen_ids:
                seen_ids.add(vid)
                all_items.append({
                    "video_id": vid,
                    "title": it["snippet"]["title"],
                    "channel_id": it["snippet"]["channelId"],
                    "channel_title": it["snippet"]["channelTitle"],
                    "published_at": it["snippet"]["publishedAt"][:10],
                    "thumbnail": it["snippet"]["thumbnails"].get("medium", {}).get("url", ""),
                })

    if not all_items:
        return []

    # 영상 통계 + duration 일괄 조회
    video_ids = [x["video_id"] for x in all_items]
    chunks = [video_ids[i:i+50] for i in range(0, len(video_ids), 50)]
    stats_map = {}
    for chunk in chunks:
        vresp = requests.get(base_videos, params={
            "part": "statistics,contentDetails",
            "id": ",".join(chunk),
            "key": api_key,
        }, timeout=10)
        for vit in vresp.json().get("items", []):
            stats_map[vit["id"]] = {
                "view_count": int(vit["statistics"].get("viewCount", 0)),
                "duration": parse_duration(vit["contentDetails"].get("duration", "")),
            }

    # 채널 구독자 일괄 조회
    channel_ids = list({x["channel_id"] for x in all_items})
    sub_map = {}
    for i in range(0, len(channel_ids), 50):
        cresp = requests.get(base_channels, params={
            "part": "statistics",
            "id": ",".join(channel_ids[i:i+50]),
            "key": api_key,
        }, timeout=10)
        for cit in cresp.json().get("items", []):
            sub_map[cit["id"]] = int(cit["statistics"].get("subscriberCount", 0))

    # 결과 합산
    results = []
    for item in all_items:
        vid = item["video_id"]
        vs = stats_map.get(vid, {})
        views = vs.get("view_count", 0)
        subs = sub_map.get(item["channel_id"], 0)
        ratio = (views / subs * 100) if subs > 0 else 0
        badge_label, badge_cls = get_badge(ratio)
        results.append({
            **item,
            "view_count": views,
            "subscriber_count": subs,
            "ratio": ratio,
            "duration": vs.get("duration", ""),
            "badge_label": badge_label,
            "badge_cls": badge_cls,
            "youtube_url": f"https://www.youtube.com/watch?v={vid}",
        })

    return results


def generate_ai_idea(title: str, channel: str, api_key: str) -> str:
    """Gemini로 AI 아이디어 생성"""
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = f"""나는 유튜브 크리에이터야.

아래 영상을 간단히 분석해줘.

제목: {title}
채널: {channel}

요청:
1. 이 영상이 클릭을 부른 이유 3가지
2. 비슷한 느낌의 제목 3개
3. 내 채널에 적용할 아이디어 3개"""
        resp = model.generate_content(prompt)
        return resp.text
    except Exception as e:
        return f"AI 아이디어 생성 실패: {e}"


def results_to_csv(results: list[dict]) -> str:
    rows = []
    for r in results:
        rows.append({
            "제목": r["title"],
            "채널명": r["channel_title"],
            "업로드날짜": r["published_at"],
            "조회수": r["view_count"],
            "구독자수": r["subscriber_count"],
            "비율(%)": round(r["ratio"], 1),
            "등급": r["badge_label"],
            "영상길이": r["duration"],
            "유튜브링크": r["youtube_url"],
        })
    return pd.DataFrame(rows).to_csv(index=False, encoding="utf-8-sig")


# ───────────────────────────────────────────────
# 사이드바 — API Key 설정
# ───────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 💧 루이의 떡상 채널 찾기")
    st.markdown("<div style='font-size:12px;color:#888;margin-bottom:16px'>무료판 | 검색 50개 | 기본 분석용</div>", unsafe_allow_html=True)
    st.markdown("---")
    st.markdown("### 🔑 YouTube API Key")
    key_input = st.text_input(
        "YouTube API Key",
        value=st.session_state.yt_api_key,
        type="password",
        label_visibility="collapsed",
        placeholder="AIza...",
        key="key_input_field",
    )
    sc1, sc2 = st.columns(2)
    with sc1:
        if st.button("💾 저장", use_container_width=True):
            st.session_state.yt_api_key = key_input
            st.success("저장됨!")
    with sc2:
        if st.button("🗑️ 초기화", use_container_width=True):
            st.session_state.yt_api_key = ""
            st.session_state.results = []
            st.rerun()

    if st.session_state.yt_api_key:
        st.success("✅ API Key 등록됨")
    else:
        st.warning("⚠️ API Key를 입력해주세요")

    st.markdown("---")
    st.markdown("### 🤖 Gemini API Key (AI 아이디어용)")
    gemini_input = st.text_input(
        "Gemini API Key",
        value=st.session_state.ai_key,
        type="password",
        label_visibility="collapsed",
        placeholder="AIza...",
        key="gemini_input_field",
    )
    if st.button("💾 Gemini Key 저장", use_container_width=True):
        st.session_state.ai_key = gemini_input
        st.success("저장됨!")

# ───────────────────────────────────────────────
# 메인 타이틀
# ───────────────────────────────────────────────
st.markdown(
    """<div style="padding:8px 0 16px 0;">
        <span style="font-size:26px;font-weight:700;color:#fff;">💧 루이의 떡상 채널 찾기</span><br>
        <span style="font-size:12px;color:#888;">무료판 | 검색 50개 | 기본 분석용</span>
    </div>""",
    unsafe_allow_html=True,
)
st.markdown("<hr style='border-color:#2a2a4e;margin:0 0 16px 0'>", unsafe_allow_html=True)

# ───────────────────────────────────────────────
# 필터 패널
# ───────────────────────────────────────────────
with st.container():
    st.markdown("<div style='padding:0 16px'>", unsafe_allow_html=True)
    with st.container(border=True):
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            st.markdown("📅 **업로드 날짜**")
            date_opt = st.selectbox(
                "업로드 날짜",
                ["전체", "오늘(24시간)", "이번주(7일)", "14일", "이번달(30일)", "올해(1년)"],
                label_visibility="collapsed",
                key="date_opt",
            )
        with fc2:
            st.markdown("🎬 **영상 길이**")
            len_opt = st.selectbox(
                "영상 길이",
                ["전체 길이", "4분 미만", "4분~20분", "20분 초과"],
                label_visibility="collapsed",
                key="len_opt",
            )
        with fc3:
            st.markdown("🔍 **검색 기준**")
            order_opt = st.selectbox(
                "검색 기준",
                ["관련성", "조회수순", "최신순"],
                label_visibility="collapsed",
                key="order_opt",
            )

        kw_col, btn_col = st.columns([5, 1])
        with kw_col:
            keywords_raw = st.text_input(
                "키워드",
                placeholder="트로트메들리, 홍폭발  (콤마로 여러 키워드 구분)",
                label_visibility="collapsed",
                key="kw_input",
            )
        with btn_col:
            search_clicked = st.button("🔍 Search (최대 50개)", use_container_width=True, type="primary")
    st.markdown("</div>", unsafe_allow_html=True)

# ───────────────────────────────────────────────
# 검색 실행
# ───────────────────────────────────────────────
if search_clicked:
    if not st.session_state.yt_api_key:
        st.error("YouTube API Key를 먼저 입력하고 저장해주세요.")
    elif not keywords_raw.strip():
        st.warning("키워드를 입력해주세요.")
    else:
        keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
        with st.spinner("YouTube에서 검색 중..."):
            results = search_youtube(
                keywords,
                st.session_state.yt_api_key,
                date_opt,
                len_opt,
                order_opt,
            )
        st.session_state.results = results
        st.session_state.sort_by = "조회수순"
        st.session_state.sort_asc = False

# ───────────────────────────────────────────────
# AI 아이디어 (세션 상태 처리)
# ───────────────────────────────────────────────
if "ai_idea_text" not in st.session_state:
    st.session_state.ai_idea_text = ""
if "ai_idea_show" not in st.session_state:
    st.session_state.ai_idea_show = False

# ───────────────────────────────────────────────
# 결과 영역
# ───────────────────────────────────────────────
results = st.session_state.results

# 정렬 바 — 항상 표시
with st.container(border=True):
    sb1, sb2, sb3, sb4, sb5, sb6, sb7 = st.columns([1.2, 1, 1, 0.4, 1, 1, 2])
    with sb1:
        st.markdown("<span style='color:#aaa;font-size:13px;line-height:2.2'>결과 정렬:</span>", unsafe_allow_html=True)
    with sb2:
        if st.button(
            "조회수순",
            key="sort_views",
            type="primary" if st.session_state.sort_by == "조회수순" else "secondary",
        ):
            st.session_state.sort_by = "조회수순"
            st.rerun()
    with sb3:
        if st.button(
            "최신순",
            key="sort_date",
            type="primary" if st.session_state.sort_by == "최신순" else "secondary",
        ):
            st.session_state.sort_by = "최신순"
            st.rerun()
    with sb4:
        st.markdown("<span style='color:#444;font-size:18px;line-height:2.0'>|</span>", unsafe_allow_html=True)
    with sb5:
        if st.button(
            "↓ 내림차순",
            key="sort_desc",
            type="primary" if not st.session_state.sort_asc else "secondary",
        ):
            st.session_state.sort_asc = False
            st.rerun()
    with sb6:
        if st.button(
            "↑ 오름차순",
            key="sort_asc_btn",
            type="primary" if st.session_state.sort_asc else "secondary",
        ):
            st.session_state.sort_asc = True
            st.rerun()
    with sb7:
        cnt_text = f"검색 결과: {len(results)}개" if results else "대기 중..."
        st.markdown(
            f"<div style='text-align:right;color:#aaa;font-size:13px;padding-top:6px'>{cnt_text}</div>",
            unsafe_allow_html=True,
        )

if results:
    # 정렬 적용
    sorted_results = sorted(
        results,
        key=lambda x: x["view_count"] if st.session_state.sort_by == "조회수순" else x["published_at"],
        reverse=not st.session_state.sort_asc,
    )

    # CSV 다운로드
    csv_data = results_to_csv(sorted_results)
    st.download_button(
        label="📥 CSV 다운로드",
        data=csv_data,
        file_name=f"toto_finder_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
        key="csv_dl",
    )

    # ─── 카드 그리드 ───
    COLS = 4
    for row_start in range(0, len(sorted_results), COLS):
        cols = st.columns(COLS)
        for col_idx, item in enumerate(sorted_results[row_start:row_start + COLS]):
            with cols[col_idx]:
                ratio_fmt = f"{item['ratio']:,.0f}%"
                # 썸네일 (클릭 → 유튜브)
                st.markdown(
                    f"""<a href="{item['youtube_url']}" target="_blank">
                        <div class="thumb-wrap" style="position:relative;padding-top:56.25%;overflow:hidden;border-radius:8px;cursor:pointer;">
                            <img src="{item['thumbnail']}" style="position:absolute;top:0;left:0;width:100%;height:100%;object-fit:cover;">
                            <span style="position:absolute;bottom:6px;right:6px;background:rgba(0,0,0,.8);color:#fff;font-size:11px;padding:2px 6px;border-radius:4px;">{item['duration']}</span>
                        </div>
                    </a>""",
                    unsafe_allow_html=True,
                )
                # 제목
                st.markdown(
                    f"<div style='font-size:13px;font-weight:600;color:#e0e0e0;line-height:1.4;height:3.2em;overflow:hidden;margin:8px 0 4px 0'>{item['title'][:80]}{'...' if len(item['title'])>80 else ''}</div>",
                    unsafe_allow_html=True,
                )
                # 채널 + 날짜
                st.markdown(
                    f"<div style='font-size:11px;color:#888;margin-bottom:8px'>📺 {item['channel_title']} • {item['published_at']}</div>",
                    unsafe_allow_html=True,
                )
                # 등급 뱃지
                badge_colors = {
                    "badge-god":    "background:linear-gradient(90deg,#e91e8c,#ff4757);color:#fff",
                    "badge-ultra":  "background:#ff6b35;color:#fff",
                    "badge-great":  "background:#7c3aed;color:#fff",
                    "badge-rising": "background:#0891b2;color:#fff",
                    "badge-good":   "background:#16a34a;color:#fff",
                    "badge-normal": "background:#374151;color:#aaa",
                }
                bstyle = badge_colors.get(item["badge_cls"], "background:#374151;color:#aaa")
                st.markdown(
                    f"<div style='width:100%;padding:7px 0;border-radius:8px;font-size:13px;font-weight:700;text-align:center;margin-bottom:8px;{bstyle}'>{item['badge_label']}</div>",
                    unsafe_allow_html=True,
                )
                # 통계
                st.markdown(
                    f"""<div style='font-size:12px;color:#aaa;display:flex;justify-content:space-between;margin-bottom:2px'>
                        <span>조회수</span><span style='color:#e0e0e0;font-weight:600'>{fmt_num(item['view_count'])}</span>
                        <span>구독자</span><span style='color:#e0e0e0;font-weight:600'>{fmt_num(item['subscriber_count'])}</span>
                    </div>
                    <div style='font-size:12px;color:#aaa;margin-bottom:10px'>
                        비율 <span style='color:#22d3ee;font-weight:700'>{ratio_fmt}</span>
                    </div>""",
                    unsafe_allow_html=True,
                )
                # 액션 버튼
                btn_c1, btn_c2, btn_c3 = st.columns(3)
                with btn_c1:
                    if st.button("제목 복사", key=f"copy_{item['video_id']}", use_container_width=True):
                        st.toast("📋 제목이 복사되었습니다!")
                        st.markdown(
                            f"""<script>navigator.clipboard.writeText({json.dumps(item['title'])});</script>""",
                            unsafe_allow_html=True,
                        )

                with btn_c2:
                    if st.button("🔗 링크 복사", key=f"link_{item['video_id']}", use_container_width=True):
                        st.toast("🔗 링크가 복사되었습니다!")
                        st.markdown(
                            f"""<script>navigator.clipboard.writeText({json.dumps(item['youtube_url'])});</script>""",
                            unsafe_allow_html=True,
                        )

                with btn_c3:
                    if st.button("AI 아이디어", key=f"ai_{item['video_id']}", use_container_width=True, type="primary"):
                        ai_key = st.session_state.ai_key or os.environ.get("GEMINI_API_KEY", "")
                        if not ai_key:
                            st.warning("GEMINI_API_KEY가 필요합니다.")
                        else:
                            with st.spinner("AI 분석 중..."):
                                idea = generate_ai_idea(item["title"], item["channel_title"], ai_key)
                            st.session_state.ai_idea_text = idea
                            st.session_state.ai_idea_vid = item["video_id"]
                            st.session_state.ai_idea_show = True
                            st.rerun()

                # AI 아이디어 결과 표시
                if st.session_state.get("ai_idea_show") and st.session_state.get("ai_idea_vid") == item["video_id"]:
                    with st.expander("💡 AI 아이디어", expanded=True):
                        st.markdown(st.session_state.ai_idea_text)
                        copy_text = st.session_state.ai_idea_text
                        st.code(copy_text, language=None)
                        st.info("위 텍스트를 복사해서 사용하세요!")
                        if st.button("닫기", key=f"close_ai_{item['video_id']}"):
                            st.session_state.ai_idea_show = False
                            st.rerun()

elif not search_clicked:
    st.markdown(
        """<div style='text-align:center;padding:60px 0;color:#555'>
            <div style='font-size:48px'>🔍</div>
            <div style='font-size:16px;margin-top:12px'>키워드를 입력하고 Search 버튼을 눌러주세요</div>
            <div style='font-size:13px;margin-top:6px;color:#444'>예: 트로트메들리, 홍폭발</div>
        </div>""",
        unsafe_allow_html=True,
    )
