"""title_forge.py — 🔥 VPH 제목 대장간 (벤치마킹 2개 조합 → 우리 채널 제목).

사장님의 검증된 수작업 제목 작성법을 그대로 자동화한 공용 도구.

방법론(사장님):
  1) 시크릿모드로 벤치마킹 콘텐츠(VPH 높은 제목) 검색
  2) 나오는 벤치마킹 콘텐츠 2개의 VPH 확인 (최소 1k 이상)
  3) 그 2개 제목을 조합해 새 제목 1개를 만들어 다시 시크릿 검색 →
     참고한 제목 2개가 상위 노출되면 그 제목을 채택.

이 모듈:
  · rank_by_vph      — 표본을 VPH(시간당 조회수) 높은 순으로 정렬
  · combine_titles   — 참고 제목들을 조합해 새 제목 후보 N개 (LLM 주입 가능)
  · incognito_search_url — 후보 제목의 유튜브 검색 링크(무료·시크릿에서 그대로 확인)
  · validate_title   — API relevance 검색으로 참고 2개가 상위 노출되는지 자동 확인(옵션·쿼터)
  · render_forge     — 두 앱(썸네일·1만) 제목 생성 자리에 붙이는 Streamlit 명령도구

순수 로직은 streamlit/네트워크 없이 테스트 가능(LLM·검색 함수 주입).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sys
import urllib.parse

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.join(_HERE, "jpshorts", "backend")


# ── VPH (시간당 조회수) ────────────────────────────────────────
def vph_of(v: dict, now: _dt.datetime | None = None) -> float:
    """영상 dict → VPH. 이미 'vph' 필드가 있으면 그대로, 없으면 조회수/게시후시간 으로 계산.

    published_at(시간까지) 우선, 없으면 published(날짜만) → 자정 기준(대략).
    """
    try:
        if v.get("vph") not in (None, "", 0):
            return float(v["vph"])
    except (TypeError, ValueError):
        pass
    views = int(v.get("views", 0) or 0)
    pub = (v.get("published_at") or v.get("published") or "").strip()
    if not pub or not views:
        return 0.0
    try:
        s = pub.replace("Z", "+00:00")
        t = _dt.datetime.fromisoformat(s) if "T" in s else \
            _dt.datetime.fromisoformat(s + "T00:00:00+00:00")
        if t.tzinfo is None:
            t = t.replace(tzinfo=_dt.timezone.utc)
        cur = now or _dt.datetime.now(_dt.timezone.utc)
        hours = max((cur - t).total_seconds() / 3600.0, 1.0)
        return round(views / hours, 1)
    except (ValueError, TypeError):
        return 0.0


def rank_by_vph(videos: list[dict], min_vph: float = 0.0,
                now: _dt.datetime | None = None) -> list[dict]:
    """표본을 VPH 높은 순으로. 각 항목에 계산된 'vph' 를 채워 반환(원본 불변)."""
    out = []
    for v in videos or []:
        vv = dict(v)
        vv["vph"] = vph_of(v, now)
        if vv["vph"] >= min_vph:
            out.append(vv)
    out.sort(key=lambda x: x.get("vph", 0.0), reverse=True)
    return out


# ── 링크/검색 ─────────────────────────────────────────────────
_VID_RE = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/)([\w-]{11})")


def extract_video_id(url_or_id: str) -> str:
    """URL 또는 11자 ID → video_id. 못 찾으면 ''。"""
    s = (url_or_id or "").strip()
    if re.fullmatch(r"[\w-]{11}", s):
        return s
    m = _VID_RE.search(s)
    return m.group(1) if m else ""


def incognito_search_url(title: str) -> str:
    """제목 → 유튜브 검색 URL(시크릿 모드에서 그대로 붙여 확인 = 사장님 3단계)."""
    q = urllib.parse.quote_plus((title or "").strip())
    return f"https://www.youtube.com/results?search_query={q}"


# ── 제목 조합 (LLM) ────────────────────────────────────────────
def build_combine_prompt(refs: list[dict], n: int = 5, tone_notes: str = "",
                         genre: str = "") -> str:
    """참고 제목들을 조합해 새 제목 후보를 만드는 LLM 프롬프트.

    핵심 규칙: 두(이상) 참고 제목의 **강한 검색 키워드를 모두 살려서** 자연스럽게 합친다.
    → 새 제목으로 검색했을 때 참고한 영상들이 상위에 걸리도록(사장님 검증법의 원리).
    """
    ref_lines = "\n".join(f"  {i+1}. {r.get('title','')}"
                          + (f"  (VPH {int(r.get('vph',0)):,})" if r.get("vph") else "")
                          for i, r in enumerate(refs))
    genre_line = f"\n채널/장르: {genre}" if genre else ""
    tone_line = f"\n우리 채널 톤·주의: {tone_notes}" if tone_notes else ""
    return f"""너는 유튜브 제목 카피라이터다. 아래는 '검증된 벤치마킹 제목'들이다(조회수·VPH로 이미 성공 확인).{genre_line}{tone_line}

[참고(벤치마킹) 제목]
{ref_lines}

목표: 위 참고 제목들을 **조합**해서 우리 채널이 쓸 새 제목 {n}개를 만든다.
제약(반드시 지켜라):
1) 두(또는 그 이상) 참고 제목의 **핵심 검색 키워드를 최대한 모두 살려** 자연스럽게 한 제목으로 녹여라.
   (이유: 새 제목으로 검색했을 때 참고한 원본 영상들이 상위에 노출되어야 하기 때문.)
2) 어색한 나열 금지 — 사람이 클릭하고 싶게 매끄럽게. 감각어 + 구체적 상황/분위기.
3) 참고 제목의 언어·정서 결을 따르되, 통째 복붙 금지(조합·재구성).
4) 이모지는 0~1개.
JSON 만: {{"titles": ["제목1", "제목2", ...]}} (정확히 {n}개)"""


def combine_titles(refs: list[dict], n: int = 5, llm_call=None,
                   tone_notes: str = "", genre: str = "") -> list[str]:
    """참고 제목들 → 새 제목 후보 N개. llm_call(prompt, json_mode=True)->str 주입 가능.

    llm_call 없으면 concept_maker._llm 을 시도, 그래도 없으면 간단 휴리스틱 폴백.
    """
    refs = [r for r in (refs or []) if (r.get("title") or "").strip()]
    if len(refs) < 2:
        return []
    if llm_call is None:
        llm_call = _default_llm()
    if llm_call is not None:
        try:
            raw = llm_call(build_combine_prompt(refs, n, tone_notes, genre), json_mode=True)
            titles = _parse_titles(raw)
            if titles:
                return titles[:n]
        except Exception:                # noqa: BLE001
            pass
    return _heuristic_combine(refs, n)   # 키 없을 때 최소 동작


def _parse_titles(raw: str) -> list[str]:
    if not raw:
        return []
    s = raw.strip()
    if "```" in s:                       # 코드펜스 제거
        s = re.sub(r"^```[a-zA-Z]*\n?|```$", "", s.strip()).strip()
    try:
        d = json.loads(s[s.find("{"): s.rfind("}") + 1] if "{" in s else s)
        if isinstance(d, dict) and isinstance(d.get("titles"), list):
            return [str(t).strip() for t in d["titles"] if str(t).strip()]
        if isinstance(d, list):
            return [str(t).strip() for t in d if str(t).strip()]
    except (json.JSONDecodeError, ValueError):
        pass
    # 폴백: 줄단위(번호·불릿 제거)
    lines = [re.sub(r'^[\s\-*\d.)"]+', "", ln).strip().strip('"')
             for ln in s.splitlines() if ln.strip()]
    return [ln for ln in lines if ln][:12]


def _heuristic_combine(refs: list[dict], n: int) -> list[str]:
    """LLM 없이 최소한의 조합(키워드 앞뒤 결합) — 참고용 초안."""
    a, b = refs[0]["title"].strip(), refs[1]["title"].strip()
    half = lambda t: t.split()[: max(1, len(t.split()) // 2)]      # noqa: E731
    tail = lambda t: t.split()[max(1, len(t.split()) // 2):]        # noqa: E731
    cands = [
        " ".join(half(a) + tail(b)),
        " ".join(half(b) + tail(a)),
        f"{a.split('|')[0].strip()} · {b.split('|')[0].strip()}",
    ]
    seen, out = set(), []
    for c in cands:
        c = re.sub(r"\s+", " ", c).strip()
        if c and c not in seen:
            seen.add(c); out.append(c)
    return out[:n]


def _default_llm():
    if _BACKEND not in sys.path:
        sys.path.insert(0, _BACKEND)
    try:
        import concept_maker as CM
        return CM._llm
    except Exception:                    # noqa: BLE001
        return None


# ── 검증(참고 2개가 상위 노출?) ────────────────────────────────
def validate_title(title: str, ref_ids: list[str], top_n: int = 10,
                   search_fn=None) -> dict:
    """새 제목으로 relevance 검색 → 참고 영상들의 순위. search_fn(query, top_n)->[video_id..] 주입 가능.

    반환: {ranks:{id:순위(1부터)|None}, found:상위N에 걸린 참고 수, total:참고 수, passed:bool}
    passed = 참고 영상이 하나라도(있으면 전부일수록 좋음) 상위 top_n 에 노출.
    """
    ref_ids = [r for r in (ref_ids or []) if r]
    if not title or not ref_ids:
        return {"ranks": {}, "found": 0, "total": 0, "passed": False, "no_key": False}
    if search_fn is None:
        search_fn = _default_search
    try:
        ordered = search_fn(title, top_n) or []
    except Exception as e:               # noqa: BLE001
        return {"ranks": {}, "found": 0, "total": len(ref_ids),
                "passed": False, "no_key": False, "error": str(e)}
    ranks: dict[str, int | None] = {}
    for rid in ref_ids:
        ranks[rid] = (ordered.index(rid) + 1) if rid in ordered else None
    found = sum(1 for r in ranks.values() if r is not None)
    return {"ranks": ranks, "found": found, "total": len(ref_ids),
            "passed": found >= 1, "no_key": False, "ordered": ordered}


def _default_search(query: str, top_n: int) -> list[str]:
    if _BACKEND not in sys.path:
        sys.path.insert(0, _BACKEND)
    import youtube_client as yc
    cards = yc.search_videos(query, video_type="all", order="relevance",
                             max_results=max(top_n, 10), translate=False)
    return [c.get("video_id", "") for c in cards]


def _has_youtube_key() -> bool:
    if _BACKEND not in sys.path:
        sys.path.insert(0, _BACKEND)
    try:
        import youtube_client as yc
        return yc.has_key()
    except Exception:                    # noqa: BLE001
        return bool(os.environ.get("YOUTUBE_API_KEY", "").strip())


# ── Streamlit 명령도구 (두 앱 공용) ────────────────────────────
def render_forge(videos: list[dict], kp: str, tone_notes: str = "",
                 genre: str = "", expanded: bool = False) -> None:
    """제목 생성 자리에 붙이는 '🔥 VPH 제목 대장간' 명령도구.

    videos = 현재 표본(제목·조회수·published·video_id·vph 중 있는 것). kp=위젯 키 접두사.
    """
    import streamlit as st

    with st.expander("🔥 VPH 제목 대장간 — 벤치마킹 2개 조합 → 우리 채널 제목", expanded=expanded):
        st.caption("사장님 방식 자동화: **VPH 높은 벤치마킹 2개**를 골라(또는 직접 입력) → "
                   "조합해 새 제목 후보 → **🔍 시크릿 검색**으로 그 2개가 상위에 뜨면 채택.")

        pick_tab, paste_tab = st.tabs(["📊 분석 영상에서 고르기", "✍️ 제목 직접 입력"])
        refs: list[dict] = []

        with pick_tab:
            ranked = rank_by_vph(videos)
            ranked = [v for v in ranked if (v.get("title") or "").strip()]
            if ranked:
                st.caption("VPH(시간당 조회수) 높은 순. 조합할 **2개 이상**을 고르세요. "
                           "(VPH=전체 조회수÷게시 후 시간 — VidIQ의 실시간 VPH와는 다를 수 있어요.)")
                opts = {}
                for v in ranked[:40]:
                    lbl = f"VPH {int(v.get('vph',0)):,} · 👁{int(v.get('views',0)):,} · {v['title'][:44]}"
                    opts[lbl] = v
                sel = st.multiselect("벤치마킹 영상 선택 (VPH 높은 2개 권장)",
                                     list(opts), key=f"tf_pick_{kp}")
                refs = [opts[s] for s in sel]
            else:
                st.info("분석된 표본이 없어요. 먼저 위에서 분석하거나, 오른쪽 '✍️ 제목 직접 입력'을 쓰세요.")

        with paste_tab:
            st.caption("시크릿 검색으로 찾은 **VPH 높은 벤치마킹 제목 2개**를 그대로 붙여넣으세요. "
                       "(영상 링크를 함께 넣으면 📊 자동검증도 가능)")
            t1 = st.text_input("참고 제목 1", key=f"tf_t1_{kp}")
            l1 = st.text_input("참고 영상 링크 1 (선택)", key=f"tf_l1_{kp}",
                               placeholder="https://youtu.be/... (자동검증용)")
            t2 = st.text_input("참고 제목 2", key=f"tf_t2_{kp}")
            l2 = st.text_input("참고 영상 링크 2 (선택)", key=f"tf_l2_{kp}")
            paste_refs = []
            if t1.strip():
                paste_refs.append({"title": t1.strip(), "video_id": extract_video_id(l1)})
            if t2.strip():
                paste_refs.append({"title": t2.strip(), "video_id": extract_video_id(l2)})
            if paste_refs:
                refs = paste_refs        # 직접 입력이 있으면 그것을 사용

        n = st.slider("만들 제목 후보 수", 3, 8, 5, key=f"tf_n_{kp}")
        go = st.button("🔥 두 제목 조합 → 우리 채널 제목 만들기", type="primary",
                       key=f"tf_go_{kp}", use_container_width=True)
        if go:
            if len([r for r in refs if r.get("title")]) < 2:
                st.warning("조합하려면 제목이 **2개 이상** 필요해요 (분석 영상 2개 선택 또는 직접 2개 입력).")
            else:
                with st.spinner("두 제목의 핵심 키워드를 살려 조합하는 중…"):
                    cands = combine_titles(refs, n=n, tone_notes=tone_notes, genre=genre)
                if not cands:
                    st.error("제목 생성 실패 — GPT/Gemini 키가 없으면 조합 품질이 낮아요(⚙️ 설정).")
                st.session_state[f"tf_cand_{kp}"] = {"cands": cands, "refs": refs}

        data = st.session_state.get(f"tf_cand_{kp}")
        if data and data.get("cands"):
            st.markdown("**🔥 조합된 제목 후보** — 📋 복사 후 시크릿 검색으로 확인하세요.")
            ref_ids = [r.get("video_id", "") for r in data["refs"] if r.get("video_id")]
            has_key = _has_youtube_key()
            for i, c in enumerate(data["cands"]):
                with st.container(border=True):
                    st.code(c, language=None)
                    b1, b2 = st.columns([1, 1])
                    b1.markdown(f"[🔍 시크릿 검색으로 확인]({incognito_search_url(c)})")
                    if ref_ids:
                        if b2.button("📊 자동검증(참고 상위노출?)", key=f"tf_val_{kp}_{i}",
                                     use_container_width=True, disabled=not has_key,
                                     help=None if has_key else "YouTube 키가 필요해요(⚙️ 설정)"):
                            with st.spinner("relevance 검색으로 참고 영상 순위 확인 중…"):
                                res = validate_title(c, ref_ids, top_n=10)
                            st.session_state[f"tf_valres_{kp}_{i}"] = res
                        if not has_key:
                            b2.caption("🔒 자동검증엔 키 필요 — 없으면 왼쪽 시크릿 검색으로 직접 확인")
                    vr = st.session_state.get(f"tf_valres_{kp}_{i}")
                    if vr:
                        if vr.get("error"):
                            st.caption(f"검증 오류: {vr['error']}")
                        elif vr["passed"]:
                            ranks = [f"{r}위" for r in vr["ranks"].values() if r]
                            st.success(f"✅ 참고 {vr['found']}/{vr['total']}개가 상위 노출 "
                                       f"({', '.join(ranks)}) → 채택 후보!")
                        else:
                            st.warning(f"△ 참고 {vr['found']}/{vr['total']}개만 상위10 노출 — "
                                       "조합을 조금 바꾸거나 다른 후보를 보세요.")
            all_c = "\n".join(data["cands"])
            st.markdown("**📋 후보 전체복사**")
            st.code(all_c, language=None)


# ── 자기검증 (네트워크·LLM 없이 순수 로직) ─────────────────────
if __name__ == "__main__":
    # VPH 계산 + 정렬
    now = _dt.datetime(2026, 1, 11, tzinfo=_dt.timezone.utc)
    vids = [
        {"title": "겨울밤 재즈", "views": 24000, "published_at": "2026-01-10T00:00:00Z"},  # ~1000/h
        {"title": "봄날 보사노바", "views": 100, "published_at": "2026-01-01T00:00:00Z"},   # 낮음
        {"title": "이미VPH", "views": 5, "vph": 3000},                                    # vph 필드 우선
    ]
    ranked = rank_by_vph(vids, now=now)
    assert ranked[0]["title"] == "이미VPH", ranked
    assert abs(ranked[1]["vph"] - 1000) < 5, ranked[1]["vph"]
    print("VPH 정렬:", [(r["title"], r["vph"]) for r in ranked])

    # 링크/검색 URL
    assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert "search_query=" in incognito_search_url("겨울밤 재즈")
    print("링크추출·검색URL OK")

    # combine (LLM 주입)
    fake_llm = lambda p, json_mode=False: '{"titles":["겨울밤 재즈 보사노바 카페","눈 오는 밤 재즈 플레이리스트"]}'  # noqa: E731
    cs = combine_titles([{"title": "겨울밤 재즈"}, {"title": "봄날 보사노바"}], n=5, llm_call=fake_llm)
    assert cs == ["겨울밤 재즈 보사노바 카페", "눈 오는 밤 재즈 플레이리스트"], cs
    print("combine(LLM):", cs)

    # combine 폴백(LLM 없음)
    cs2 = combine_titles([{"title": "겨울밤 재즈 감성"}, {"title": "새벽 보사노바 카페"}],
                         n=3, llm_call=False or None)
    # llm_call=None → _default_llm 시도(키 없으면 None) → 휴리스틱
    print("combine(폴백):", cs2)
    assert cs2, "폴백도 최소 1개는 나와야"

    # validate (검색 주입)
    fake_search = lambda q, top_n: ["xxx", "REF1", "yyy", "REF2"]  # noqa: E731
    vr = validate_title("새 제목", ["REF1", "REF2"], top_n=10, search_fn=fake_search)
    assert vr["passed"] and vr["found"] == 2 and vr["ranks"]["REF1"] == 2, vr
    print("validate:", vr["ranks"], "passed=", vr["passed"])

    vr2 = validate_title("새 제목", ["NOPE"], top_n=10, search_fn=fake_search)
    assert not vr2["passed"], vr2
    print("self-test OK")
