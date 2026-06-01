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

st.set_page_config(
    page_title="루이의 떡상 채널 찾기",
    page_icon="💧",
    layout="wide",
    menu_items={},
)

st.markdown("""
<style>
.stApp { background-color: #1a1a2e; color: #e0e0e0; }
.block-container { padding: 60px 0 0 0 !important; max-width: 100% !important; }

/* ── 툴바 완전 숨김 (모든 버전 대응) ── */
header, header * { display: none !important; height: 0 !important; visibility: hidden !important; }
[data-testid="stToolbar"] { display: none !important; }
[data-testid="stAppToolbar"] { display: none !important; }
[data-testid="stDecoration"] { display: none !important; }
[data-testid="stStatusWidget"] { display: none !important; }
#MainMenu, #MainMenu * { display: none !important; visibility: hidden !important; }
footer, footer * { display: none !important; visibility: hidden !important; }
.stDeployButton { display: none !important; }
.stApp > header { display: none !important; }
div[data-testid="collapsedControl"] { display: none !important; }
section[data-testid="stSidebar"] > div:first-child { padding-top: 0 !important; }

/* 입력 요소 */
div[data-testid="stSelectbox"] > div { background: #1e293b !important; border-color: #3a3a5e !important; color: #e0e0e0 !important; }
div[data-testid="stTextInput"] input { background: #1e293b !important; border-color: #3a3a5e !important; color: #e0e0e0 !important; }
div[data-testid="stButton"] button { border-radius: 8px !important; }
label { color: #aaa !important; font-size: 12px !important; }

/* 등급 뱃지 */
.badge-god    { background: linear-gradient(90deg,#e91e8c,#ff4757); color:#fff; width:100%; padding:7px 0; border-radius:8px; font-size:13px; font-weight:700; text-align:center; margin-bottom:8px; }
.badge-ultra  { background: #ff6b35; color:#fff; width:100%; padding:7px 0; border-radius:8px; font-size:13px; font-weight:700; text-align:center; margin-bottom:8px; }
.badge-great  { background: #7c3aed; color:#fff; width:100%; padding:7px 0; border-radius:8px; font-size:13px; font-weight:700; text-align:center; margin-bottom:8px; }
.badge-rising { background: #0891b2; color:#fff; width:100%; padding:7px 0; border-radius:8px; font-size:13px; font-weight:700; text-align:center; margin-bottom:8px; }
.badge-good   { background: #16a34a; color:#fff; width:100%; padding:7px 0; border-radius:8px; font-size:13px; font-weight:700; text-align:center; margin-bottom:8px; }
.badge-normal { background: #374151; color:#aaa; width:100%; padding:7px 0; border-radius:8px; font-size:13px; font-weight:700; text-align:center; margin-bottom:8px; }
</style>
""", unsafe_allow_html=True)

# ── 세션 상태 ──
for k, v in {
    "yt_api_key": os.environ.get("YOUTUBE_API_KEY", ""),
    "ai_key": os.environ.get("GEMINI_API_KEY", ""),
    "results": [],
    "sort_by": "떡상지수순",
    "sort_asc": False,
    "selected": set(),
    "ai_idea_text": "",
    "ai_idea_show": False,
    "ai_idea_vid": "",
    "bulk_result": "",
    "bulk_show": False,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── 헬퍼 함수 ──
def fmt_num(n):
    try: n = int(n)
    except: return "0"
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000: return f"{n/1_000:.1f}K"
    return str(n)

def get_badge(ratio):
    if ratio >= 10000: return ("👑 신의 간택", "badge-god")
    if ratio >= 5000:  return ("🔥 조대박",    "badge-ultra")
    if ratio >= 1000:  return ("🎯 대박",       "badge-great")
    if ratio >= 500:   return ("💧 떡상",       "badge-rising")
    if ratio >= 100:   return ("⭐ 우수",       "badge-good")
    return ("▪️ 일반", "badge-normal")

def parse_duration(iso):
    import isodate
    try:
        td = isodate.parse_duration(iso)
        total = int(td.total_seconds())
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
    except: return ""

def published_after(option):
    now = datetime.now(timezone.utc)
    mapping = {
        "오늘(24시간)": now - timedelta(days=1),
        "이번주(7일)":  now - timedelta(days=7),
        "14일":         now - timedelta(days=14),
        "이번달(30일)": now - timedelta(days=30),
        "올해(1년)":    now - timedelta(days=365),
    }
    dt = mapping.get(option)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None

def video_duration_filter(option):
    return {"4분 미만": "short", "4분~20분": "medium", "20분 초과": "long"}.get(option)

def search_order(option):
    return {"관련성": "relevance", "조회수순": "viewCount", "최신순": "date"}.get(option, "relevance")

def search_youtube(keywords, api_key, date_option, length_option, order_option, max_results=50):
    base_search   = "https://www.googleapis.com/youtube/v3/search"
    base_videos   = "https://www.googleapis.com/youtube/v3/videos"
    base_channels = "https://www.googleapis.com/youtube/v3/channels"

    all_items, seen_ids = [], set()
    per_kw = max(50, max_results // max(len(keywords), 1))

    for kw in keywords:
        fetched = 0
        page_token = None
        while fetched < per_kw:
            batch = min(50, per_kw - fetched)
            params = {
                "part": "snippet", "q": kw.strip(), "type": "video",
                "maxResults": batch, "key": api_key,
                "order": search_order(order_option),
            }
            if page_token: params["pageToken"] = page_token
            pub = published_after(date_option)
            if pub: params["publishedAfter"] = pub
            dur = video_duration_filter(length_option)
            if dur: params["videoDuration"] = dur

            resp = requests.get(base_search, params=params, timeout=10)
            if resp.status_code != 200:
                st.error(f"YouTube 오류: {resp.json().get('error',{}).get('message', resp.text)}")
                return []
            data = resp.json()
            items = data.get("items", [])
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
            fetched += len(items)
            page_token = data.get("nextPageToken")
            if not page_token or len(items) == 0: break

    if not all_items: return []

    video_ids = [x["video_id"] for x in all_items]
    stats_map = {}
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i+50]
        vr = requests.get(base_videos, params={"part":"statistics,contentDetails","id":",".join(chunk),"key":api_key}, timeout=10)
        for vit in vr.json().get("items", []):
            stats_map[vit["id"]] = {
                "view_count": int(vit["statistics"].get("viewCount", 0)),
                "duration": parse_duration(vit["contentDetails"].get("duration", "")),
            }

    channel_ids = list({x["channel_id"] for x in all_items})
    sub_map = {}
    for i in range(0, len(channel_ids), 50):
        cr = requests.get(base_channels, params={"part":"statistics","id":",".join(channel_ids[i:i+50]),"key":api_key}, timeout=10)
        for cit in cr.json().get("items", []):
            sub_map[cit["id"]] = int(cit["statistics"].get("subscriberCount", 0))

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

def generate_ai_idea(title, channel, api_key):
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = f"""나는 유튜브 크리에이터야.\n\n아래 영상을 간단히 분석해줘.\n\n제목: {title}\n채널: {channel}\n\n요청:\n1. 이 영상이 클릭을 부른 이유 3가지\n2. 비슷한 느낌의 제목 3개\n3. 내 채널에 적용할 아이디어 3개"""
        return model.generate_content(prompt).text
    except Exception as e:
        return f"AI 아이디어 생성 실패: {e}"

def generate_bulk_analysis(items, api_key, mode="common"):
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        video_list = "\n".join([
            f"- [{i+1}] 제목: {it['title']} | 채널: {it['channel_title']} | 조회수: {fmt_num(it['view_count'])} | 비율: {it['ratio']:.0f}%"
            for i, it in enumerate(items)
        ])
        if mode == "common":
            prompt = f"""아래 유튜브 영상들을 분석해서 공통점 프롬프트를 만들어줘.

{video_list}

아래 형식으로 정확히 답해줘:

1. 떡상 영상 공통 심리 트리거 5개
각 트리거를 번호와 함께 구체적으로 설명해줘.

2. 제목 공식 10개
[변수1] [변수2] 형태로 실제 적용 가능한 제목 공식 10개를 만들어줘.

3. 썸네일 문구 10개
강렬하고 클릭을 유도하는 썸네일 텍스트 10개를 만들어줘.

4. Suno 프롬프트 추천
이 영상들의 분위기에 맞는 Suno 음악 프롬프트 (영어, 50단어 이내)"""
        else:
            prompt = f"""아래 상위 유튜브 영상들을 종합 분석해줘.

{video_list}

아래 형식으로 정확히 답해줘:

1. 떡상 영상 공통 심리 트리거 5개
각 트리거를 번호와 함께 구체적으로 설명해줘.

2. 제목 공식 10개
[변수1] [변수2] 형태로 실제 적용 가능한 제목 공식 10개를 만들어줘.

3. 썸네일 문구 10개
강렬하고 클릭을 유도하는 썸네일 텍스트 10개를 만들어줘.

4. 내 채널 적용 전략 3가지
구체적인 실행 방법과 함께 설명해줘."""
        return model.generate_content(prompt).text
    except Exception as e:
        return f"분석 실패: {e}"

def results_to_csv(results):
    rows = [{"제목": r["title"], "채널명": r["channel_title"], "업로드날짜": r["published_at"],
             "조회수": r["view_count"], "구독자수": r["subscriber_count"],
             "비율(%)": round(r["ratio"], 1), "등급": r["badge_label"],
             "영상길이": r["duration"], "유튜브링크": r["youtube_url"]} for r in results]
    return pd.DataFrame(rows).to_csv(index=False, encoding="utf-8-sig")

# ── 사이드바 ──
with st.sidebar:
    st.markdown("## 💧 루이의 떡상 채널 찾기")
    st.markdown("<div style='font-size:12px;color:#888;margin-bottom:16px'>무료판 | Deep Search 200개</div>", unsafe_allow_html=True)
    st.markdown("---")
    st.markdown("### 🔑 YouTube API Key")
    key_input = st.text_input("YT Key", value=st.session_state.yt_api_key, type="password",
                               label_visibility="collapsed", placeholder="AIza...", key="key_input_field")
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
    st.success("✅ 등록됨") if st.session_state.yt_api_key else st.warning("⚠️ Key 필요")

    st.markdown("---")
    st.markdown("### 🤖 Gemini API Key")
    gemini_input = st.text_input("Gemini Key", value=st.session_state.ai_key, type="password",
                                  label_visibility="collapsed", placeholder="AIza...", key="gemini_input_field")
    if st.button("💾 Gemini Key 저장", use_container_width=True):
        st.session_state.ai_key = gemini_input
        st.success("저장됨!")
    st.success("✅ 등록됨") if st.session_state.ai_key else st.info("ℹ️ AI 기능에 필요")

# ── JS로 툴바 강제 제거 ──
st.markdown("""
<script>
(function hideToolbar() {
    const selectors = [
        'header', '[data-testid="stToolbar"]', '[data-testid="stAppToolbar"]',
        '[data-testid="stDecoration"]', '#MainMenu', 'footer'
    ];
    function remove() {
        selectors.forEach(s => {
            document.querySelectorAll(s).forEach(el => {
                el.style.display = 'none';
                el.style.visibility = 'hidden';
                el.style.height = '0';
            });
        });
    }
    remove();
    const observer = new MutationObserver(remove);
    observer.observe(document.body, { childList: true, subtree: true });
})();
</script>
""", unsafe_allow_html=True)

# ── 메인 타이틀 ──
st.markdown("""<div style="padding:8px 0 12px 0;">
    <span style="font-size:26px;font-weight:700;color:#fff;">💧 루이의 떡상 채널 찾기</span><br>
    <span style="font-size:12px;color:#888;">무료판 | 검색 최대 200개 | 기본 분석용</span>
</div>""", unsafe_allow_html=True)

# ── API Key 미설정 시 상단 배너 ──
if not st.session_state.yt_api_key:
    st.markdown("""<div style="background:#1e3a5f;border:2px solid #3b82f6;border-radius:12px;
        padding:20px 24px;margin-bottom:16px;">
        <div style="font-size:16px;font-weight:700;color:#fff;margin-bottom:12px;">
            🔑 시작하기 — YouTube API Key를 입력해주세요
        </div>
        <div style="font-size:13px;color:#93c5fd;margin-bottom:6px;">
            왼쪽 사이드바 ( ← 화살표 클릭) 또는 아래에서 바로 입력하세요
        </div>
    </div>""", unsafe_allow_html=True)
    kb1, kb2, kb3 = st.columns([4, 1, 1])
    with kb1:
        inline_key = st.text_input("🔑 YouTube API Key 입력", placeholder="AIzaSy...",
                                    type="password", key="inline_key_input")
    with kb2:
        if st.button("✅ 저장", use_container_width=True, type="primary"):
            if inline_key:
                st.session_state.yt_api_key = inline_key
                st.success("저장됨!")
                st.rerun()
    with kb3:
        st.markdown("<div style='font-size:11px;color:#888;padding-top:8px'>※ 새로고침해도 유지됩니다</div>",
                    unsafe_allow_html=True)
    st.markdown("<hr style='border-color:#2a2a4e;margin:8px 0 12px 0'>", unsafe_allow_html=True)
else:
    st.markdown("<hr style='border-color:#2a2a4e;margin:0 0 12px 0'>", unsafe_allow_html=True)

# ── 필터 패널 ──
with st.container(border=True):
    fc1, fc2, fc3, fc4 = st.columns(4)
    with fc1:
        st.markdown("📅 **업로드 날짜**")
        date_opt = st.selectbox("날짜", ["전체", "오늘(24시간)", "이번주(7일)", "14일", "이번달(30일)", "올해(1년)"],
                                 label_visibility="collapsed", key="date_opt")
    with fc2:
        st.markdown("🎬 **영상 길이**")
        len_opt = st.selectbox("길이", ["전체 길이", "4분 미만", "4분~20분", "20분 초과"],
                                label_visibility="collapsed", key="len_opt")
    with fc3:
        st.markdown("🔍 **검색 기준**")
        order_opt = st.selectbox("기준", ["관련성", "조회수순", "최신순"],
                                  label_visibility="collapsed", key="order_opt")
    with fc4:
        st.markdown("🏷️ **카테고리**")
        category_opt = st.selectbox("카테고리",
            ["전체", "트로트", "시니어 경제", "건강/운동", "요리", "여행", "종교", "뉴스/시사", "육아", "패션/뷰티"],
            label_visibility="collapsed", key="category_opt")

    kw_col, btn1_col, btn2_col = st.columns([5, 1, 1])
    with kw_col:
        keywords_raw = st.text_input("키워드", placeholder="트로트메들리, 홍폭발  (콤마로 여러 키워드 구분)",
                                      label_visibility="collapsed", key="kw_input")
    with btn1_col:
        search_clicked = st.button("🔍 Search (50개)", use_container_width=True, type="primary")
    with btn2_col:
        deep_clicked = st.button("🚀 Deep Search (200개)", use_container_width=True)

# ── 검색 실행 ──
def do_search(max_results):
    if not st.session_state.yt_api_key:
        st.error("YouTube API Key를 먼저 입력하고 저장해주세요.")
        return
    if not keywords_raw.strip():
        st.warning("키워드를 입력해주세요.")
        return
    kws = [k.strip() for k in keywords_raw.split(",") if k.strip()]
    if category_opt != "전체":
        kws = [f"{kw} {category_opt}" for kw in kws]
    with st.spinner(f"YouTube에서 검색 중... (최대 {max_results}개)"):
        res = search_youtube(kws, st.session_state.yt_api_key, date_opt, len_opt, order_opt, max_results)
    st.session_state.results = res
    st.session_state.sort_by = "떡상지수순"
    st.session_state.sort_asc = False
    st.session_state.selected = set()

if search_clicked:
    do_search(50)
if deep_clicked:
    do_search(200)

results = st.session_state.results

# ── 정렬 바 ──
with st.container(border=True):
    sb_cols = st.columns([1, 1, 1, 1, 1, 0.3, 1, 1, 3])
    with sb_cols[0]:
        st.markdown("<span style='color:#aaa;font-size:13px;line-height:2.4'>결과 재정렬:</span>", unsafe_allow_html=True)
    for i, label in enumerate(["조회수순", "구독자수순", "떡상지수순", "최신순"]):
        with sb_cols[i+1]:
            if st.button(label, key=f"sort_{i}",
                         type="primary" if st.session_state.sort_by == label else "secondary"):
                st.session_state.sort_by = label
                st.rerun()
    with sb_cols[5]:
        st.markdown("<span style='color:#444;font-size:18px;line-height:2.4'>|</span>", unsafe_allow_html=True)
    with sb_cols[6]:
        if st.button("↓ 내림차순", key="sort_desc",
                     type="primary" if not st.session_state.sort_asc else "secondary"):
            st.session_state.sort_asc = False
            st.rerun()
    with sb_cols[7]:
        if st.button("↑ 오름차순", key="sort_asc_btn",
                     type="primary" if st.session_state.sort_asc else "secondary"):
            st.session_state.sort_asc = True
            st.rerun()
    with sb_cols[8]:
        selected_cnt = len(st.session_state.selected)
        cnt_text = f"검색 결과: {len(results)}개  |  선택: {selected_cnt}개" if results else "대기 중..."
        st.markdown(f"<div style='text-align:right;color:#aaa;font-size:13px;padding-top:8px'>{cnt_text}</div>",
                    unsafe_allow_html=True)

# ── 액션 바 (결과 있을 때) ──
if results:
    sort_key = {
        "조회수순":   lambda x: x["view_count"],
        "구독자수순": lambda x: x["subscriber_count"],
        "떡상지수순": lambda x: x["ratio"],
        "최신순":     lambda x: x["published_at"],
    }.get(st.session_state.sort_by, lambda x: x["ratio"])
    sorted_results = sorted(results, key=sort_key, reverse=not st.session_state.sort_asc)

    # 액션 버튼 행
    ac1, ac2, ac3 = st.columns([1, 1, 2])
    with ac1:
        csv_data = results_to_csv(sorted_results)
        st.download_button("📥 CSV 다운로드", data=csv_data,
                           file_name=f"loui_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                           mime="text/csv", key="csv_dl")
    with ac2:
        if st.button("☐ 선택 해제", use_container_width=True):
            st.session_state.selected = set()
            st.rerun()
    with ac3:
        ai_key = st.session_state.ai_key or os.environ.get("GEMINI_API_KEY", "")
        if st.button("✨ 선택 영상 Gemini 분석", use_container_width=True, type="primary",
                     disabled=len(st.session_state.selected) == 0):
            sel_items = [r for r in sorted_results if r["video_id"] in st.session_state.selected]
            with st.spinner("Gemini 분석 중..."):
                st.session_state.bulk_result = generate_bulk_analysis(sel_items, ai_key, "common")
            st.session_state.bulk_show = True
            st.rerun()

    # 두 번째 액션 행
    ac4, ac5, ac6 = st.columns([3, 2, 2])
    with ac4:
        total_selected = len(st.session_state.selected)
        st.markdown(f"<div style='color:#aaa;font-size:12px;padding-top:8px'>선택된 영상: {total_selected}개</div>",
                    unsafe_allow_html=True)
    with ac5:
        if st.button("🔗 선택 영상 공통점 프롬프트", use_container_width=True,
                     disabled=len(st.session_state.selected) == 0):
            sel_items = [r for r in sorted_results if r["video_id"] in st.session_state.selected]
            with st.spinner("프롬프트 생성 중..."):
                st.session_state.bulk_result = generate_bulk_analysis(sel_items, ai_key, "common")
            st.session_state.bulk_show = True
            st.rerun()
    with ac6:
        if st.button("🏆 상위 10개 전체 Gemini 분석", use_container_width=True):
            top10 = sorted_results[:10]
            with st.spinner("상위 10개 분석 중..."):
                st.session_state.bulk_result = generate_bulk_analysis(top10, ai_key, "top")
            st.session_state.bulk_show = True
            st.rerun()

    # 벌크 분석 결과
    if st.session_state.get("bulk_show") and st.session_state.get("bulk_result"):
        with st.container(border=True):
            br1, br2 = st.columns([4, 1])
            with br1:
                st.markdown("### 📊 Gemini 분석 결과")
            with br2:
                cp1, cp2 = st.columns(2)
                with cp1:
                    if st.button("📋 결과 복사", key="copy_bulk", use_container_width=True):
                        st.toast("📋 결과가 복사되었습니다!")
                        st.markdown(
                            f"<script>navigator.clipboard.writeText({json.dumps(st.session_state.bulk_result)});</script>",
                            unsafe_allow_html=True)
                with cp2:
                    if st.button("✕ 닫기", key="close_bulk", use_container_width=True):
                        st.session_state.bulk_show = False
                        st.rerun()
            st.markdown(st.session_state.bulk_result)

    # ── 카드 그리드 ──
    badge_colors = {
        "badge-god":    "background:linear-gradient(90deg,#e91e8c,#ff4757);color:#fff",
        "badge-ultra":  "background:#ff6b35;color:#fff",
        "badge-great":  "background:#7c3aed;color:#fff",
        "badge-rising": "background:#0891b2;color:#fff",
        "badge-good":   "background:#16a34a;color:#fff",
        "badge-normal": "background:#374151;color:#aaa",
    }
    COLS = 4
    for row_start in range(0, len(sorted_results), COLS):
        cols = st.columns(COLS)
        for col_idx, item in enumerate(sorted_results[row_start:row_start + COLS]):
            with cols[col_idx]:
                vid = item["video_id"]
                is_selected = vid in st.session_state.selected

                # 선택 체크박스
                checked = st.checkbox("선택", value=is_selected, key=f"chk_{vid}")
                if checked and vid not in st.session_state.selected:
                    st.session_state.selected.add(vid)
                elif not checked and vid in st.session_state.selected:
                    st.session_state.selected.discard(vid)

                # 썸네일
                border_color = "#22d3ee" if is_selected else "transparent"
                st.markdown(
                    f"""<a href="{item['youtube_url']}" target="_blank">
                        <div style="position:relative;padding-top:56.25%;overflow:hidden;border-radius:8px;border:2px solid {border_color};">
                            <img src="{item['thumbnail']}" style="position:absolute;top:0;left:0;width:100%;height:100%;object-fit:cover;">
                            <span style="position:absolute;bottom:6px;right:6px;background:rgba(0,0,0,.8);color:#fff;font-size:11px;padding:2px 6px;border-radius:4px;">{item['duration']}</span>
                        </div>
                    </a>""", unsafe_allow_html=True)

                # 제목
                st.markdown(
                    f"<div style='font-size:13px;font-weight:600;color:#e0e0e0;line-height:1.4;height:3.2em;overflow:hidden;margin:8px 0 4px 0'>{item['title'][:80]}{'...' if len(item['title'])>80 else ''}</div>",
                    unsafe_allow_html=True)
                # 채널
                st.markdown(
                    f"<div style='font-size:11px;color:#888;margin-bottom:8px'>📺 {item['channel_title']} • {item['published_at']}</div>",
                    unsafe_allow_html=True)
                # 뱃지
                bstyle = badge_colors.get(item["badge_cls"], "background:#374151;color:#aaa")
                st.markdown(
                    f"<div style='width:100%;padding:7px 0;border-radius:8px;font-size:13px;font-weight:700;text-align:center;margin-bottom:8px;{bstyle}'>{item['badge_label']}</div>",
                    unsafe_allow_html=True)
                # 통계
                st.markdown(
                    f"""<div style='font-size:12px;color:#aaa;display:flex;justify-content:space-between;margin-bottom:2px'>
                        <span>조회수</span><span style='color:#e0e0e0;font-weight:600'>{fmt_num(item['view_count'])}</span>
                        <span>구독자</span><span style='color:#e0e0e0;font-weight:600'>{fmt_num(item['subscriber_count'])}</span>
                    </div>
                    <div style='font-size:12px;color:#aaa;margin-bottom:10px'>
                        비율 <span style='color:#22d3ee;font-weight:700'>{item['ratio']:,.0f}%</span>
                    </div>""", unsafe_allow_html=True)

                # 버튼
                btn_c1, btn_c2, btn_c3 = st.columns(3)
                with btn_c1:
                    if st.button("제목 복사", key=f"copy_{vid}", use_container_width=True):
                        st.toast("📋 제목 복사됨!")
                        st.markdown(f"<script>navigator.clipboard.writeText({json.dumps(item['title'])});</script>",
                                    unsafe_allow_html=True)
                with btn_c2:
                    if st.button("🔗 링크", key=f"link_{vid}", use_container_width=True):
                        st.toast("🔗 링크 복사됨!")
                        st.markdown(f"<script>navigator.clipboard.writeText({json.dumps(item['youtube_url'])});</script>",
                                    unsafe_allow_html=True)
                with btn_c3:
                    if st.button("AI 💡", key=f"ai_{vid}", use_container_width=True, type="primary"):
                        ai_key = st.session_state.ai_key or os.environ.get("GEMINI_API_KEY", "")
                        if not ai_key:
                            st.warning("Gemini API Key가 필요합니다.")
                        else:
                            with st.spinner("AI 분석 중..."):
                                idea = generate_ai_idea(item["title"], item["channel_title"], ai_key)
                            st.session_state.ai_idea_text = idea
                            st.session_state.ai_idea_vid = vid
                            st.session_state.ai_idea_show = True
                            st.rerun()

                if st.session_state.get("ai_idea_show") and st.session_state.get("ai_idea_vid") == vid:
                    with st.expander("💡 AI 아이디어", expanded=True):
                        st.markdown(st.session_state.ai_idea_text)
                        st.code(st.session_state.ai_idea_text, language=None)
                        if st.button("닫기", key=f"close_ai_{vid}"):
                            st.session_state.ai_idea_show = False
                            st.rerun()

else:
    st.markdown("""<div style='text-align:center;padding:60px 0;color:#555'>
        <div style='font-size:48px'>🔍</div>
        <div style='font-size:16px;margin-top:12px;color:#888'>키워드를 입력하고 Search 버튼을 눌러주세요</div>
        <div style='font-size:13px;margin-top:6px;color:#444'>예: 트로트메들리, 홍폭발</div>
    </div>""", unsafe_allow_html=True)
