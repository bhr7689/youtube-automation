"""jpshorts 백엔드 — FastAPI.

실행:  uvicorn main:app --port 8787 --app-dir jpshorts/backend
키:    YOUTUBE_API_KEY 없으면 데모 데이터 모드로 동작 (UI 개발·시연용).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import store
import taxonomy
import youtube_client as yc

try:  # .env 자동 로드 (저장소 루트)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env"))
    yc.YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()
except ImportError:
    pass

app = FastAPI(title="jpshorts API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _annotate(cards: list[dict]) -> list[dict]:
    """카드에 북마크·레퍼런스 등록 상태 플래그를 붙인다."""
    bm = store.bookmark_ids()
    ch = store.channel_ids()
    for c in cards:
        c["bookmarked"] = c["video_id"] in bm
        c["registered"] = c["channel_id"] in ch
    return cards


@app.get("/api/health")
def health():
    return {"ok": True, "demo": not yc.has_key(), "version": app.version}


@app.get("/api/taxonomy")
def get_taxonomy():
    return taxonomy.load()


class QueryReq(BaseModel):
    category: str = "music_playlist"
    genres: list[str] = Field(default_factory=list)
    situations: list[str] = Field(default_factory=list)
    emotions: list[str] = Field(default_factory=list)
    langs: list[str] = Field(default_factory=lambda: ["ko"])
    limit: int = 10


@app.post("/api/discover/queries")
def discover_queries(req: QueryReq):
    qs = taxonomy.generate_queries(
        category=req.category, genres=req.genres, situations=req.situations,
        emotions=req.emotions, langs=req.langs, limit=req.limit,
    )
    return {"queries": qs}


class DiscoverSearchReq(BaseModel):
    queries: list[str]
    video_type: str = "all"
    max_per_query: int = 15
    lang: str = ""              # 지역 필터(regionCode/relevanceLanguage) 적용용


@app.post("/api/discover/search")
def discover_search(req: DiscoverSearchReq):
    merged: dict[str, dict] = {}
    # 발굴 쿼리는 taxonomy 가 이미 해당 언어로 만들어줌 → 재번역 없이 지역만 적용
    for q in req.queries[:12]:
        for card in yc.search_videos(q, video_type=req.video_type,
                                     max_results=req.max_per_query,
                                     lang=req.lang, translate=False):
            merged.setdefault(card["video_id"], card)
    cards = sorted(merged.values(), key=lambda c: -(c.get("multiplier") or 0))
    return {"cards": _annotate(cards), "demo": not yc.has_key()}


@app.get("/api/search")
def search(
    q: str,
    video_type: str = "all",
    order: str = "viewCount",
    max_results: int = 100,
    period_days: int = 0,
    lang: str = "",
):
    store.touch_search(q)
    cards = yc.search_videos(
        q, video_type=video_type, order=order,
        max_results=max_results, period_days=period_days, lang=lang,
    )
    used = yc.translate_query(q, lang)      # 실제 검색에 쓰인 현지어(캐시)
    return {"cards": _annotate(cards), "demo": not yc.has_key(),
            "query_used": used, "translated": used if used.strip() != q.strip() else ""}


# ── 🌸 번역봇 (도구 ②) ─────────────────────────────────

import translator as tr
import tts as ttsmod


class TranslateReq(BaseModel):
    text: str = ""
    mode: str = "auto"          # shorts | literal | japanese | auto | check


@app.get("/api/translate/status")
def translate_status():
    return {"gemini": tr.has_gemini(), "voicevox": ttsmod.voicevox_available(),
            "voices": ttsmod.VOICES}


@app.post("/api/translate")
def translate(req: TranslateReq):
    t = req.text or ""
    m = req.mode
    if m == "shorts":
        return {"result": tr.to_korean_shorts(t), "gemini": tr.has_gemini()}
    if m == "literal":
        return {"result": tr.to_korean_literal(t), "gemini": tr.has_gemini()}
    if m == "japanese":
        ja = tr.to_japanese(t)
        return {"result": ja, "sentences": [{"id": i + 1, "jp": s}
                for i, s in enumerate(tr.split_sentences(ja))], "gemini": tr.has_gemini()}
    if m == "check":
        return tr.quality_check(t)
    return tr.auto_translate(t)


class TTSReq(BaseModel):
    sentences: list[dict] = Field(default_factory=list)   # [{"jp":..,"src":..}]
    ja_text: str = ""
    voice: int = 3
    speed: float = 1.2


@app.post("/api/tts")
def make_tts(req: TTSReq):
    sents = req.sentences
    if not sents and req.ja_text:
        sents = [{"id": i + 1, "jp": s} for i, s in enumerate(tr.split_sentences(req.ja_text))]
    if not sents:
        raise HTTPException(400, "일본어 대본이 없어요")
    manifest = ttsmod.build_job(sents, voice=req.voice, speed=req.speed)
    manifest.pop("zip_path", None)   # 경로는 감춤(다운로드는 별도 엔드포인트)
    return manifest


@app.get("/api/tts/jobs")
def tts_jobs():
    return {"jobs": ttsmod.list_jobs()}


@app.get("/api/tts/{job_id}/download")
def tts_download(job_id: str):
    if any(c in job_id for c in ("/", "\\", "..")):
        raise HTTPException(400, "잘못된 경로")
    p = ttsmod.job_zip_path(job_id)
    if not p:
        raise HTTPException(404, "작업을 찾을 수 없어요")
    return FileResponse(p, filename=f"{job_id}.zip", media_type="application/zip")


# ── 📚 대본 코퍼스 + ✍️ 시선 비틀기 대본 작성 ────────────

import script_corpus as sc
import scriptwriter as sw


class CorpusCollectReq(BaseModel):
    genre: str = "heartwarming"
    target: int = 100
    min_multiplier: float = 2.0


@app.post("/api/corpus/collect")
def corpus_collect(req: CorpusCollectReq):
    return sc.collect(req.genre, req.target, req.min_multiplier)


@app.get("/api/corpus/stats")
def corpus_stats(genre: str = ""):
    return {"count": store.corpus_count(genre),
            "items": [{k: i.get(k) for k in
                       ("video_id", "title", "multiplier", "views")}
                      for i in store.corpus_list(genre, limit=20)]}


@app.post("/api/corpus/learn")
def corpus_learn(genre: str = ""):
    return sc.learn_rules(genre)


@app.get("/api/corpus/rules")
def corpus_rules(genre: str = ""):
    r = sc.load_rules(genre)
    return r or {"error": "규칙이 아직 없어요 — 수집 후 학습하세요."}


@app.get("/api/corpus/genres")
def corpus_genres():
    """카테고리 현황 — 각자 몇 개 쌓였고 규칙이 학습됐는지 (섞임 없음)."""
    return {"genres": sc.list_genres()}


class ScriptReq(BaseModel):
    source_transcript: list[dict] = Field(default_factory=list)  # [{t,dur,text}]
    source_video_id: str = ""       # 있으면 자막 자동 수집
    viral_script: str = ""
    viral_video_id: str = ""        # 있으면 자막·댓글 자동 수집
    comments: list[str] = Field(default_factory=list)
    angle: str = "lesson"
    language: str = "ko"
    genre: str = ""
    hook_type: str = "auto"   # question|shock|number|negation|address|cliffhang|scene|auto


@app.post("/api/script/write")
def script_write(req: ScriptReq):
    transcript = req.source_transcript
    if not transcript and req.source_video_id:
        transcript = sc._fetch_transcript(req.source_video_id)
    if not transcript:
        raise HTTPException(400, "원본 롱폼 자막이 필요해요 (source_transcript 또는 source_video_id)")
    viral = req.viral_script
    comments = req.comments
    if req.viral_video_id:
        if not viral:
            viral = " ".join(s.get("text", "") for s in sc._fetch_transcript(req.viral_video_id))
        if not comments:
            comments = sc._fetch_comments(req.viral_video_id)
    return sw.write_script(transcript, viral, comments, req.angle, req.language,
                           genre=req.genre, hook_type=req.hook_type)


class AnchoredTTSReq(BaseModel):
    sentences: list[dict] = Field(default_factory=list)  # [{text, src_anchor_ms}]
    voice: int = 3
    speed: float = 1.2


@app.post("/api/script/to-narration")
def script_to_narration(req: AnchoredTTSReq):
    """시선 비틀기 대본(앵커) → 일본어 변환(앵커 유지) → narration job."""
    if not req.sentences:
        raise HTTPException(400, "대본 문장이 없어요")
    ja_sents = sw.translate_anchored(req.sentences)
    manifest = ttsmod.build_job(ja_sents, voice=req.voice, speed=req.speed)
    manifest.pop("zip_path", None)
    return manifest


# ── 🏷️ 제목·키워드 엔진 ─────────────────────────────────

import title_engine as te


class TitleReq(BaseModel):
    topic: str = ""
    script_first_line: str = ""
    genre: str = ""
    language: str = "ko"
    n: int = 5


@app.post("/api/title/generate")
def title_generate(req: TitleReq):
    if not (req.topic or req.script_first_line):
        raise HTTPException(400, "주제 또는 대본 첫 문장이 필요해요")
    return te.generate_titles(req.topic or req.script_first_line,
                              req.script_first_line, req.genre, req.language, req.n)


@app.get("/api/title/keywords")
def title_keywords(genre: str = ""):
    return te.gather_keywords(genre)


class TitleLogReq(BaseModel):
    video_id: str = ""
    title: str
    keywords: list[str] = Field(default_factory=list)
    views: int = 0
    note: str = ""
    genre: str = ""


@app.post("/api/title/log")
def title_log(req: TitleLogReq):
    te.log_title(req.video_id, req.title, req.keywords, req.views, req.note, req.genre)
    return {"ok": True}


# ── 🌡️ 키워드 레이더 (시기성·상승 키워드 탐지) ──────────

import keyword_radar as kr


@app.get("/api/keyword-radar/rising")
def radar_rising(category: str, lang: str = ""):
    if not category.strip():
        raise HTTPException(400, "카테고리(예: 플레이리스트, shark tank)가 필요해요")
    return kr.rising_keywords(category.strip(), lang)


@app.get("/api/keyword-radar/heat")
def radar_heat(keyword: str, days: int = 14, lang: str = ""):
    if not keyword.strip():
        raise HTTPException(400, "키워드가 필요해요")
    return kr.keyword_heat(keyword.strip(), days, lang)


@app.get("/api/keyword-radar/seasonal")
def radar_seasonal(month: int = 0):
    return kr.seasonal_pack(month or None)


@app.get("/api/script/structures")
def script_structures():
    """훅 유형별 대본 구조 템플릿 목록."""
    return {"structures": [{"hook_type": k, "name": v["name"], "beats": v["beats"]}
                           for k, v in sw.STRUCTURES.items()],
            "angles": sw.ANGLES}


# ── 📱 폰 연결 QR + LAN 주소 ────────────────────────────

import socket


def _lan_ip() -> str:
    """이 서버의 사무실 내 IP (라우팅 기준 주 인터페이스). 오프라인이어도 안전."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def _all_ipv4() -> list[str]:
    """이 서버에 붙은 IPv4 전부(로컬 제외) — LAN·Tailscale 등 구분용."""
    ips = set()
    try:
        for res in socket.getaddrinfo(socket.gethostname(), None):
            if res[0] == socket.AF_INET:
                ips.add(res[4][0])
    except Exception:
        pass
    ips.add(_lan_ip())
    return [i for i in ips if not i.startswith("127.")]


def _is_tailscale(ip: str) -> bool:
    # Tailscale CGNAT 대역 100.64.0.0/10 (둘째 옥텟 64~127)
    try:
        a, b = ip.split(".")[:2]
        return a == "100" and 64 <= int(b) <= 127
    except Exception:
        return False


def _qr_svg(url: str) -> str:
    try:
        import qrcode
        import qrcode.image.svg as svgimg
        import io as _io
        img = qrcode.make(url, image_factory=svgimg.SvgPathImage, box_size=9, border=2)
        buf = _io.BytesIO()
        img.save(buf)
        return buf.getvalue().decode("utf-8")
    except Exception:
        return ""


@app.get("/api/connect-info")
def connect_info():
    port = int(os.getenv("PORT", "8787"))
    lan = _lan_ip()
    tail = next((i for i in _all_ipv4() if _is_tailscale(i)), "")
    lan_url = f"http://{lan}:{port}/"
    tail_url = f"http://{tail}:{port}/" if tail else ""
    # 어디서나 접속(Tailscale)이 있으면 그걸 우선 홈화면 주소로.
    best = tail_url or lan_url
    return {
        "url": lan_url, "ip": lan, "port": port,
        "lan_url": lan_url,
        "tailscale_url": tail_url,     # 있으면 외출 중에도 접속 가능
        "best_url": best,
        "qr_svg": _qr_svg(best),       # QR = 어디서나 주소 우선
        "has_remote": bool(tail_url),
    }


# ── 🎨 플리 컨셉 제조기 (지침 v1.4 내장) ────────────────

import concept_maker as cm


class ConceptReq(BaseModel):
    channels: list[str] = Field(default_factory=list)   # 채널 URL/핸들 1~3개
    song_type: str = "auto"      # lyric | instrumental | auto
    num_songs: int = 1           # 1 | 10 | 25
    extra_notes: str = ""
    images: list[str] = Field(default_factory=list)     # 업로드 썸네일 캡처(data URL)
    titles: str = ""             # 붙여넣은 인기 상승 제목(줄바꿈 구분)


@app.post("/api/concept/analyze")
def concept_analyze(req: ConceptReq):
    urls = [u for u in req.channels if u.strip()][:3]
    if not urls and not req.images and not req.titles.strip():
        raise HTTPException(400, "채널 URL·썸네일 캡처·제목 중 하나는 넣어주세요")
    r = cm.generate_report(urls, req.song_type, req.num_songs, req.extra_notes,
                           images=req.images, titles_text=req.titles)
    if r.get("error"):
        raise HTTPException(400, r["error"])
    if r.get("result"):        # 📂 성공 리포트는 서버에 저장(모바일↔데스크톱 이어작업)
        try:
            r["saved_id"] = cm.save_report(r, urls)
        except Exception:
            pass
    return r


@app.get("/api/concept/reports")
def concept_reports():
    return {"reports": cm.list_reports()}


@app.get("/api/concept/reports/{rid}")
def concept_report_get(rid: str):
    rec = cm.load_report(rid)
    if not rec:
        raise HTTPException(404, "저장된 리포트를 찾을 수 없어요")
    return rec["response"]


@app.delete("/api/concept/reports/{rid}")
def concept_report_delete(rid: str):
    return {"ok": cm.delete_report(rid)}


@app.get("/api/concept/status")
def concept_status():
    return {**cm.llm_status(), "youtube_key": yc.has_key()}


class ThumbGenReq(BaseModel):
    prompt: str
    size: str = "1536x1024"      # 1536x1024(썸네일·배너) | 1024x1024(로고)
    refs: list[str] = Field(default_factory=list)   # 🎯 레퍼런스 썸네일(무드 반영)


@app.post("/api/concept/thumbnail")
def concept_thumbnail(req: ThumbGenReq):
    """🖼️ 이미지 프롬프트(+레퍼런스 무드) → GPT 이미지 생성(썸네일·로고·배너)."""
    size = req.size if req.size in ("1536x1024", "1024x1024", "1024x1536") else "1536x1024"
    r = cm.generate_thumbnail_image(req.prompt, size=size, refs=req.refs[:8])
    if not r.get("ok"):
        from fastapi import HTTPException as _HE
        raise _HE(400, r.get("error", "이미지 생성 실패"))
    return r


@app.get("/api/concept/thumbnail/file/{name}")
def concept_thumbnail_file(name: str):
    from fastapi import HTTPException as _HE
    from fastapi.responses import FileResponse as _FR
    if any(c in name for c in ("/", "\\", "..")):
        raise _HE(400, "잘못된 경로")
    p = os.path.join(cm.THUMBS_DIR, name)
    if not os.path.isfile(p):
        raise _HE(404, "파일 없음")
    return _FR(p, media_type="image/png")


# ── ✂️ 자동 컷편집 (도구 ③) ─────────────────────────────

import cutplanner as cp


class CutPlanReq(BaseModel):
    job_id: str = ""
    manifest: dict = Field(default_factory=dict)
    source_duration_sec: float = 600.0
    source_name: str = "source.mp4"
    seg_min_s: float = 3.0
    seg_max_s: float = 5.0


def _load_manifest(job_id: str) -> dict | None:
    import json as _json
    p = os.path.join(ttsmod.JOBS_DIR, job_id, "manifest.json")
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as f:
            return _json.load(f)
    return None


@app.post("/api/cut/plan")
def cut_plan(req: CutPlanReq):
    manifest = req.manifest or (_load_manifest(req.job_id) if req.job_id else None)
    if not manifest or not manifest.get("sentences"):
        raise HTTPException(400, "narration job(manifest)이 필요해요. 번역봇에서 먼저 저장하세요.")
    plan = cp.plan_cuts(manifest, source_duration_sec=req.source_duration_sec,
                        seg_min_s=req.seg_min_s, seg_max_s=req.seg_max_s)
    return plan


@app.get("/api/cut/jobs")
def cut_jobs():
    return {"jobs": ttsmod.list_jobs()}


@app.get("/api/cut/{plan_id}/capcut")
def cut_capcut(plan_id: str, source_name: str = "source.mp4"):
    if any(c in plan_id for c in ("/", "\\", "..")):
        raise HTTPException(400, "잘못된 경로")
    p = cp.save_capcut(plan_id, source_name)
    if not p:
        raise HTTPException(404, "플랜을 찾을 수 없어요")
    return FileResponse(p, filename=f"{plan_id}_capcut.json", media_type="application/json")


@app.get("/api/cut/{plan_id}/ffmpeg")
def cut_ffmpeg(plan_id: str, source_name: str = "source.mp4"):
    if any(c in plan_id for c in ("/", "\\", "..")):
        raise HTTPException(400, "잘못된 경로")
    p = cp.save_ffmpeg(plan_id, source_name)
    if not p:
        raise HTTPException(404, "플랜을 찾을 수 없어요")
    return FileResponse(p, filename=f"{plan_id}_render.sh", media_type="text/plain")


# ── ⚙️ 시스템 상태 + 작업 기록 (설정·알림 화면용) ──────

@app.get("/api/system/status")
def system_status():
    import shutil as _sh
    return {
        "youtube_key": yc.has_key(),
        "gemini": tr.has_gemini(),
        "voicevox": ttsmod.voicevox_available(),
        "ffmpeg": bool(_sh.which("ffmpeg")),
        "corpus": sc.list_genres(),
        "narration_jobs": len(ttsmod.list_jobs()),
        "cut_plans": len(cp.list_plans()),
        "version": app.version,
    }


@app.get("/api/cut/plans")
def cut_plans_list():
    return {"plans": cp.list_plans()}


@app.get("/api/title/logs")
def title_logs():
    return {"logs": te.read_logs()}


# ── 🔥 트렌드 피드 (등록 레퍼런스 채널의 급등 영상) ────

@app.get("/api/trend")
def trend(
    period_days: int = 7,
    video_type: str = "all",       # shorts | long | all
    max_results: int = 200,
):
    channel_ids = list(store.channel_ids())
    cards = yc.trending_from_channels(
        channel_ids, period_days=period_days,
        video_type=video_type, max_results=max_results,
    )
    cards = _annotate(cards)
    # 트렌드 피드의 카드는 정의상 '등록 채널'에서 나온 것 → 배수 배지 항상 표시
    for c in cards:
        c["registered"] = True
    return {
        "cards": cards,
        "demo": not yc.has_key(),
        "channel_count": len([c for c in channel_ids if not c.startswith("demo_")]),
    }


# ── 북마크 (크로스 화면 공유 자산) ──────────────────────

class CardReq(BaseModel):
    card: dict


@app.get("/api/bookmarks")
def get_bookmarks():
    return {"cards": _annotate(store.list_bookmarks())}


@app.post("/api/bookmarks")
def post_bookmark(req: CardReq):
    store.add_bookmark(req.card["video_id"], req.card)
    return {"ok": True}


@app.delete("/api/bookmarks/{video_id}")
def delete_bookmark(video_id: str):
    store.remove_bookmark(video_id)
    return {"ok": True}


# ── 레퍼런스 채널 ───────────────────────────────────────

class ChannelReq(BaseModel):
    channel_id: str
    title: str = ""
    payload: dict = Field(default_factory=dict)


@app.get("/api/channels")
def get_channels():
    return {"channels": store.list_channels()}


@app.post("/api/channels")
def post_channel(req: ChannelReq):
    store.add_channel(req.channel_id, req.title, req.payload)
    return {"ok": True}


@app.delete("/api/channels/{channel_id}")
def delete_channel(channel_id: str):
    store.remove_channel(channel_id)
    return {"ok": True}


# ── 🌍 글로벌 급등 채널 (전 세계 24h) ──────────────────

@app.get("/api/global-surge")
def global_surge(fmt: str = "shorts", hours: int = 24, top_n: int = 0):
    if not top_n:
        top_n = 100 if fmt == "shorts" else 50
    data = yc.global_surge(fmt=fmt, hours=hours, top_n=top_n)
    return data


@app.get("/api/surge-analysis")
def surge_analysis(fmt: str = "shorts"):
    return yc.surge_analysis(fmt=fmt)


# ── 📁 컬렉션 (채널 폴더) ───────────────────────────────

class CollectionReq(BaseModel):
    name: str = "새 폴더"


class CollectionMemberReq(BaseModel):
    channel_id: str
    title: str = ""
    payload: dict = Field(default_factory=dict)


@app.get("/api/collections")
def get_collections():
    return {"collections": store.list_collections()}


@app.post("/api/collections")
def post_collection(req: CollectionReq):
    return store.create_collection(req.name)


@app.get("/api/collections/{cid}")
def get_collection(cid: str):
    col = store.get_collection(cid)
    if not col:
        raise HTTPException(404, "컬렉션을 찾을 수 없어요")
    return col


@app.patch("/api/collections/{cid}")
def patch_collection(cid: str, req: CollectionReq):
    store.rename_collection(cid, req.name)
    return {"ok": True}


@app.delete("/api/collections/{cid}")
def del_collection(cid: str):
    store.delete_collection(cid)
    return {"ok": True}


@app.post("/api/collections/{cid}/channels")
def add_collection_member(cid: str, req: CollectionMemberReq):
    store.add_to_collection(cid, req.channel_id, req.title, req.payload)
    return {"ok": True}


@app.delete("/api/collections/{cid}/channels/{channel_id}")
def del_collection_member(cid: str, channel_id: str):
    store.remove_from_collection(cid, channel_id)
    return {"ok": True}


# ── 최근 검색 ──────────────────────────────────────────

@app.get("/api/recent")
def get_recent():
    return {"queries": store.recent_searches()}


@app.delete("/api/recent")
def delete_recent():
    store.clear_searches()
    return {"ok": True}


# ── 🔎 원본 소스 찾기 (source_finder) ───────────────────

from fastapi import HTTPException
from fastapi.responses import FileResponse

import source_finder as sf


class SourceFinderReq(BaseModel):
    url: str
    hints: dict = Field(default_factory=dict)   # 수동 단서: {"title": "...", "handle": "@..."}


@app.post("/api/source-finder")
def sf_start(req: SourceFinderReq):
    url = req.url.strip()
    if not url.startswith("http"):
        raise HTTPException(400, "URL 형식이 아니에요")
    job = sf.start_job(url, req.hints)
    return {"job_id": job["job_id"]}


@app.get("/api/source-finder")
def sf_list():
    return {"jobs": sf.list_jobs()}


@app.get("/api/source-finder/{job_id}")
def sf_status(job_id: str):
    job = sf.load_job(job_id)
    if not job:
        raise HTTPException(404, "작업을 찾을 수 없어요")
    return job


@app.get("/api/source-finder/{job_id}/file/{name}")
def sf_file(job_id: str, name: str):
    if any(c in job_id + name for c in ("/", "\\", "..")):
        raise HTTPException(400, "잘못된 경로")
    path = os.path.join(sf.job_dir(job_id), name)
    if not os.path.isfile(path):
        raise HTTPException(404, "파일 없음")
    return FileResponse(path)


# ── 🔑 API 키 저장 (설정 화면에서 직접) ──────────────────
# 키는 이 PC의 .env 파일에만 저장됩니다(.gitignore 처리 → 절대 업로드 안 됨).
# 저장 즉시 os.environ + youtube_client 모듈에 반영 → 서버 재시작 불필요.

ENV_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env"
)
_ENV_HEADER = (
    "# 일본쇼츠 자동 프로그램 — API 키\n"
    "# 이 파일은 이 컴퓨터에만 저장되며 절대 공유·업로드되지 않습니다.\n"
)


def _write_env(updates: dict[str, str]) -> None:
    """기존 .env 의 다른 줄(주석·다른 변수)은 보존하며 지정 키만 upsert."""
    lines: list[str] = []
    if os.path.isfile(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for ln in lines:
        s = ln.strip()
        if s and not s.startswith("#") and "=" in s:
            k = s.split("=", 1)[0].strip()
            if k in updates:
                out.append(f"{k}={updates[k]}")
                seen.add(k)
                continue
        out.append(ln)
    for k, v in updates.items():
        if k not in seen:
            out.append(f"{k}={v}")
    text = "\n".join(out).rstrip("\n") + "\n"
    if not os.path.isfile(ENV_PATH):
        text = _ENV_HEADER + text
    tmp = ENV_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, ENV_PATH)


def _mask(v: str) -> str:
    v = (v or "").strip()
    if not v:
        return ""
    if len(v) <= 4:
        return "•" * len(v)
    return "••••" + v[-4:]


def _keys_status_payload() -> dict:
    return {
        "youtube": {"set": yc.has_key(),
                    "mask": _mask(os.environ.get("YOUTUBE_API_KEY", ""))},
        "gemini": {"set": tr.has_gemini(),
                   "mask": _mask(os.environ.get("GEMINI_API_KEY", ""))},
        "openai": {"set": bool(os.environ.get("OPENAI_API_KEY", "").strip()),
                   "mask": _mask(os.environ.get("OPENAI_API_KEY", ""))},
        "env_exists": os.path.isfile(ENV_PATH),
    }


class KeysReq(BaseModel):
    youtube: str | None = None
    gemini: str | None = None
    openai: str | None = None


@app.post("/api/keys/save")
def keys_save(req: KeysReq):
    mapping = {
        "YOUTUBE_API_KEY": req.youtube,
        "GEMINI_API_KEY": req.gemini,
        "OPENAI_API_KEY": req.openai,
    }
    # 빈칸은 "변경 안 함" — 기존 키를 실수로 지우지 않도록
    updates = {k: v.strip() for k, v in mapping.items() if v is not None and v.strip()}
    if not updates:
        raise HTTPException(400, "입력된 키가 없어요. 최소 한 개는 넣어주세요.")
    _write_env(updates)
    for k, v in updates.items():       # 즉시 적용 (서버 재시작 불필요)
        os.environ[k] = v
    yc.YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()
    return {"ok": True, "saved": list(updates.keys()), **_keys_status_payload()}


@app.get("/api/keys/status")
def keys_status():
    return _keys_status_payload()


# ── 🧬 SRE-OS (역설계 → A/B/C/D 전략 → KR/JP 로컬라이제이션) ─────
# 런타임 모듈은 저장소 루트에 있으므로 루트를 import 경로에 추가.
# (backend/store.py 등 기존 import 를 해치지 않도록 '뒤에' append)
_SRE_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
if _SRE_ROOT not in sys.path:
    sys.path.append(_SRE_ROOT)
try:
    import sre_runtime as _sre
    import sre_store as _sre_db
    import sre_provider as _sre_prov
    import sre_sources as _sre_src
    _SRE_OK, _SRE_ERR = True, ""
except Exception as _e:            # 로드 실패해도 나머지 API 는 계속 동작
    _SRE_OK, _SRE_ERR = False, str(_e)
    _sre_prov = None
    _sre_src = None


class SREReq(BaseModel):
    text: str = ""
    kind: str = "script"           # script/transcript/keyword/idea
    url: str = ""
    markets: list[str] = Field(default_factory=lambda: ["KR"])
    project_name: str = "SRE 프로젝트"
    provider: str = "auto"         # auto/off/openai/gemini/anthropic
    winning_formula: dict | None = None   # 다중 소스 공통 승리공식(선택 주입)
    force: bool = False


@app.get("/api/sre/health")
def sre_health():
    prov = _sre_prov.status() if _sre_prov else {"active": "mock", "available": [], "live": False}
    return {"ok": _SRE_OK, "error": _SRE_ERR,
            "mock": not prov.get("live"),
            "provider": prov,
            "markets": ["KR", "JP", "US"]}


@app.post("/api/sre/analyze")
def sre_analyze(req: SREReq):
    if not _SRE_OK:
        raise HTTPException(500, f"SRE 런타임 로드 실패: {_SRE_ERR}")
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(400, "분석할 대본/자막/키워드/아이디어를 입력해주세요.")
    markets = req.markets or ["KR"]
    try:
        report = _sre.run_analysis(
            text=text, kind=req.kind, url=req.url, markets=markets,
            project_name=req.project_name, provider=req.provider,
            winning_formula=req.winning_formula, force=req.force)
    except Exception as e:
        raise HTTPException(500, f"분석 중 오류: {e}")
    return report


@app.get("/api/sre/run/{run_id}")
def sre_run(run_id: str):
    if not _SRE_OK:
        raise HTTPException(500, "SRE 런타임 미로드")
    if any(c in run_id for c in ("/", "\\", "..")):
        raise HTTPException(400, "잘못된 run_id")
    rep = _sre_db.latest_result(run_id)
    if not rep:
        raise HTTPException(404, "결과를 찾을 수 없어요")
    return rep


# ── Phase 3: URL 자동수집 · 다중 소스 비교 · A/B/C/D 승자판정 ─────
class SRECollectReq(BaseModel):
    url: str
    allow_whisper: bool = False


@app.post("/api/sre/collect-url")
def sre_collect_url(req: SRECollectReq):
    if not (_SRE_OK and _sre_src):
        raise HTTPException(500, "SRE 소스 모듈 미로드")
    url = (req.url or "").strip()
    if not url:
        raise HTTPException(400, "URL 을 입력해주세요.")
    key = os.environ.get("OPENAI_API_KEY", "").strip() or None
    return _sre_src.collect_source(url, allow_whisper=req.allow_whisper, openai_key=key)


class SREBatchReq(BaseModel):
    urls: list[str] = Field(default_factory=list)
    markets: list[str] = Field(default_factory=lambda: ["KR"])
    allow_whisper: bool = False


@app.post("/api/sre/collect-batch")
def sre_collect_batch(req: SREBatchReq):
    """여러 URL 한 번에 수집 → 자막 있는 것끼리 자동 비교 + 공통 승리공식 추출."""
    if not (_SRE_OK and _sre_src):
        raise HTTPException(500, "SRE 소스 모듈 미로드")
    urls = [u for u in (req.urls or []) if (u or "").strip()]
    if not urls:
        raise HTTPException(400, "URL 을 한 줄에 하나씩 넣어주세요.")
    key = os.environ.get("OPENAI_API_KEY", "").strip() or None
    collected = _sre_src.collect_batch(urls, allow_whisper=req.allow_whisper, openai_key=key)
    # 자막(본문) 확보된 소스만 비교 대상
    usable = [c for c in collected if (c.get("text") or "").strip()]
    comparison, formula = None, {}
    if len(usable) >= 2:
        reports, labels = [], []
        for c in usable:
            rep = _sre.run_analysis(text=c["text"], kind=c.get("kind", "transcript"),
                                    markets=req.markets, provider="off", persist=False)
            reports.append(rep)
            labels.append(c.get("label", "소스"))
        comparison = _sre_src.compare_sources(reports, labels)
        formula = _sre_src.winning_formula(comparison)
    return {"collected": collected, "usableCount": len(usable),
            "comparison": comparison, "winningFormula": formula}


class SRESourceItem(BaseModel):
    label: str = ""
    text: str = ""
    kind: str = "script"


class SRECompareReq(BaseModel):
    sources: list[SRESourceItem] = Field(default_factory=list)
    markets: list[str] = Field(default_factory=lambda: ["KR"])
    provider: str = "off"          # 비교는 규칙기반 기본(빠름·결정론)


@app.post("/api/sre/compare")
def sre_compare(req: SRECompareReq):
    if not (_SRE_OK and _sre_src):
        raise HTTPException(500, "SRE 소스 모듈 미로드")
    items = [s for s in req.sources if (s.text or "").strip()]
    if len(items) < 2:
        raise HTTPException(400, "비교하려면 본문 있는 소스가 2개 이상 필요해요.")
    reports, labels = [], []
    for i, s in enumerate(items):
        rep = _sre.run_analysis(text=s.text.strip(), kind=s.kind,
                                markets=req.markets, provider=req.provider,
                                persist=False)
        reports.append(rep)
        labels.append(s.label.strip() or f"소스{i+1}")
    comparison = _sre_src.compare_sources(reports, labels)
    formula = _sre_src.winning_formula(comparison)
    return {"reports": reports, "comparison": comparison,
            "winningFormula": formula, "labels": labels}


class SREJudgeEntry(BaseModel):
    strategy: str
    metricName: str = ""
    value: float | None = None
    title: str = ""


class SREJudgeReq(BaseModel):
    entries: list[SREJudgeEntry] = Field(default_factory=list)
    higher_is_better: bool = True
    country: str | None = None
    niche: str | None = None
    record: bool = False
    run_id: str = ""               # 어느 분석 결과에 대한 실험인지(옵션)
    persist: bool = True           # 성과를 store 에 영속 저장


@app.post("/api/sre/judge")
def sre_judge(req: SREJudgeReq):
    if not (_SRE_OK and _sre_src):
        raise HTTPException(500, "SRE 소스 모듈 미로드")
    entries = [e.model_dump() for e in req.entries]
    res = _sre_src.judge_experiment(
        entries, higher_is_better=req.higher_is_better,
        country=req.country, niche=req.niche, record=req.record)
    if not res.get("ok"):
        raise HTTPException(400, res.get("error", "판정 실패"))
    # 실험 성과 영속 저장(승자 표식 포함) — 학습 리더보드로 축적
    if req.persist:
        scored = [e for e in entries if isinstance(e.get("value"), (int, float))]
        try:
            batch = _sre_db.save_experiment(
                scored, winner=res["winner"]["strategy"], run_id=req.run_id)
            res["batchId"] = batch
            res["leaderboard"] = _sre_db.strategy_leaderboard()
        except Exception as e:
            res["persistError"] = str(e)
    return res


@app.get("/api/sre/experiments")
def sre_experiments(run_id: str = ""):
    if not (_SRE_OK and _sre_db):
        raise HTTPException(500, "SRE 저장소 미로드")
    return {"experiments": _sre_db.list_experiments(run_id=run_id or None, limit=100),
            "leaderboard": _sre_db.strategy_leaderboard()}


# ── 정적 UI (japan_shorts_app) — 같은 포트에서 서빙 ─────
_UI_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "japan_shorts_app"
)
if os.path.isdir(_UI_DIR):
    app.mount("/", StaticFiles(directory=_UI_DIR, html=True), name="ui")
