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


@app.post("/api/discover/search")
def discover_search(req: DiscoverSearchReq):
    merged: dict[str, dict] = {}
    for q in req.queries[:12]:
        for card in yc.search_videos(q, video_type=req.video_type, max_results=req.max_per_query):
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
    return {"cards": _annotate(cards), "demo": not yc.has_key()}


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
def corpus_rules():
    r = sc.load_rules()
    return r or {"error": "규칙이 아직 없어요 — 수집 후 학습하세요."}


class ScriptReq(BaseModel):
    source_transcript: list[dict] = Field(default_factory=list)  # [{t,dur,text}]
    source_video_id: str = ""       # 있으면 자막 자동 수집
    viral_script: str = ""
    viral_video_id: str = ""        # 있으면 자막·댓글 자동 수집
    comments: list[str] = Field(default_factory=list)
    angle: str = "lesson"
    language: str = "ko"


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
    return sw.write_script(transcript, viral, comments, req.angle, req.language)


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


# ── 정적 UI (japan_shorts_app) — 같은 포트에서 서빙 ─────
_UI_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "japan_shorts_app"
)
if os.path.isdir(_UI_DIR):
    app.mount("/", StaticFiles(directory=_UI_DIR, html=True), name="ui")
