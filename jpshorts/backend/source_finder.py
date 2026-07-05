"""🔎 원본 영상 소스 찾기 — 쇼츠 URL → 원본 출처(최초 공개·원 촬영자) 역추적.

파이프라인 (각 단계 실패 허용 — 실패해도 다음 단계 진행, 보고서에 한계 기록):
  meta → download → frames → handles → candidates → report

판정 체계:
  · "가장 이른 공개 후보"와 "원본 촬영 후보"를 분리해서 판정
  · 근거 우선순위: 워터마크 @핸들 > 페이지 메타 날짜 > 자막 텍스트 일치
  · 메타·검색만으로 단정 금지 — 실제 프레임 추출이 기본

조사 범위(기본): YouTube · Instagram · TikTok · Xiaohongshu(샤오홍슈) · Douyin(더우인)
자동 크롤링은 로그인·차단 때문에 실패할 수 있음 → 항상 프로필/검색 링크 + 수동 확인
가이드를 함께 생성 (자동 추출 성공은 보너스).

CLI:  python source_finder.py <url>
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.parse

OUT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "source_finder")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

STAGES = ["meta", "download", "frames", "handles", "candidates", "report"]

JOBS: dict[str, dict] = {}          # job_id → 상태 dict (in-memory)
_LOCK = threading.Lock()


# ── 유틸 ──────────────────────────────────────────────

def _run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _tool(name: str) -> str | None:
    return shutil.which(name)


def new_job(url: str, hints: dict | None = None) -> dict:
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    h = hashlib.md5(url.encode()).hexdigest()[:8]
    job_id = f"{ts}-{h}"
    job = {
        "job_id": job_id,
        "url": url,
        "status": "running",
        "stage": "meta",
        "stages": {s: {"status": "pending", "note": ""} for s in STAGES},
        "meta": {},
        "handles": [],
        "candidates": {},
        "verdict": {},
        "files": [],
        "hints": hints or {},
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    with _LOCK:
        JOBS[job_id] = job
    os.makedirs(os.path.join(OUT_ROOT, job_id), exist_ok=True)
    return job


def _set(job: dict, stage: str, status: str, note: str = "") -> None:
    job["stages"][stage] = {"status": status, "note": note}
    job["stage"] = stage
    _persist(job)


def _persist(job: dict) -> None:
    path = os.path.join(OUT_ROOT, job["job_id"], "report.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(job, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def job_dir(job_id: str) -> str:
    return os.path.join(OUT_ROOT, job_id)


def load_job(job_id: str) -> dict | None:
    with _LOCK:
        if job_id in JOBS:
            return JOBS[job_id]
    path = os.path.join(OUT_ROOT, job_id, "report.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


def list_jobs(limit: int = 30) -> list[dict]:
    if not os.path.isdir(OUT_ROOT):
        return []
    out = []
    for name in sorted(os.listdir(OUT_ROOT), reverse=True)[:limit]:
        j = load_job(name)
        if j:
            out.append({
                "job_id": j["job_id"], "url": j.get("url", ""),
                "status": j.get("status", ""), "created_at": j.get("created_at", ""),
                "title": (j.get("meta") or {}).get("title", ""),
                "handles": j.get("handles", []),
            })
    return out


# ── 1단계: 메타 수집 ──────────────────────────────────

def stage_meta(job: dict) -> None:
    url = job["url"]
    meta: dict = {}
    ytdlp = _tool("yt-dlp")
    if ytdlp:
        try:
            p = _run([ytdlp, "--dump-json", "--no-download", "--no-playlist", url], timeout=90)
            if p.returncode == 0 and p.stdout.strip():
                d = json.loads(p.stdout.strip().splitlines()[0])
                up = d.get("upload_date", "")  # YYYYMMDD
                ts = d.get("timestamp")
                kst = utc = ""
                if ts:
                    utc_dt = dt.datetime.fromtimestamp(ts, dt.timezone.utc)
                    utc = utc_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
                    kst = (utc_dt + dt.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S KST")
                meta = {
                    "source": "yt-dlp",
                    "id": d.get("id", ""),
                    "title": d.get("title", ""),
                    "channel": d.get("channel") or d.get("uploader", ""),
                    "channel_handle": d.get("uploader_id", ""),
                    "upload_date": up,
                    "upload_utc": utc,
                    "upload_kst": kst,
                    "view_count": d.get("view_count"),
                    "description": (d.get("description") or "")[:2000],
                    "duration": d.get("duration"),
                    "webpage_url": d.get("webpage_url", url),
                }
            else:
                meta = {"error": f"yt-dlp 메타 실패: {(p.stderr or '')[-200:]}"}
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
            meta = {"error": f"yt-dlp 메타 실패: {e}"}
    if not meta.get("title"):
        # oEmbed 폴백
        try:
            import requests
            r = requests.get("https://www.youtube.com/oembed",
                             params={"url": url, "format": "json"},
                             headers={"User-Agent": UA}, timeout=20)
            if r.ok:
                d = r.json()
                meta.update({"source": meta.get("source", "") + "+oembed",
                             "title": d.get("title", ""),
                             "channel": d.get("author_name", "")})
        except Exception as e:  # noqa: BLE001 — 네트워크 실패 허용
            meta.setdefault("error", "")
            meta["error"] += f" / oEmbed 실패: {e}"
    job["meta"] = meta
    if meta.get("title"):
        _set(job, "meta", "ok", f"제목·채널 확보 ({meta.get('source')})")
    else:
        _set(job, "meta", "fail", meta.get("error", "메타 수집 실패"))


# ── 2단계: 영상 다운로드 ──────────────────────────────

def stage_download(job: dict) -> None:
    ytdlp = _tool("yt-dlp")
    if not ytdlp:
        _set(job, "download", "skip", "yt-dlp 없음")
        return
    out = os.path.join(job_dir(job["job_id"]), "reference.%(ext)s")
    try:
        p = _run([ytdlp, "-f", "best[height<=480]/best", "--no-playlist",
                  "-o", out, job["url"]], timeout=300)
        files = [f for f in os.listdir(job_dir(job["job_id"])) if f.startswith("reference.")]
        if p.returncode == 0 and files:
            job["files"].append(files[0])
            _set(job, "download", "ok", files[0])
        else:
            _set(job, "download", "fail",
                 (p.stderr or "")[-300:] or "다운로드 실패 (네트워크/차단 가능)")
    except subprocess.TimeoutExpired:
        _set(job, "download", "fail", "다운로드 타임아웃(300s)")


# ── 3단계: 프레임 추출 + contact sheet + 워터마크 스트립 ──

def _ref_video(job: dict) -> str | None:
    d = job_dir(job["job_id"])
    for f in os.listdir(d):
        if f.startswith("reference."):
            return os.path.join(d, f)
    return None


def stage_frames(job: dict) -> None:
    ffmpeg, ffprobe = _tool("ffmpeg"), _tool("ffprobe")
    ref = _ref_video(job)
    if not (ffmpeg and ref):
        _set(job, "frames", "skip", "영상 파일 또는 ffmpeg 없음 — 프레임 비교 불가(보고서에 명시)")
        return
    d = job_dir(job["job_id"])
    dur = 30.0
    if ffprobe:
        try:
            p = _run([ffprobe, "-v", "quiet", "-show_entries", "format=duration",
                      "-of", "csv=p=0", ref], timeout=30)
            dur = max(1.0, float(p.stdout.strip()))
        except (ValueError, subprocess.TimeoutExpired):
            pass
    frames_dir = os.path.join(d, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    try:
        # 균등 24프레임
        _run([ffmpeg, "-y", "-i", ref, "-vf", f"fps=24/{dur},scale=480:-2",
              "-frames:v", "24", os.path.join(frames_dir, "f%02d.jpg")], timeout=120)
        # contact sheet 6×4
        _run([ffmpeg, "-y", "-i", os.path.join(frames_dir, "f%02d.jpg"),
              "-filter_complex", "scale=320:-2,tile=6x4",
              os.path.join(d, "contact_sheet.jpg")], timeout=60)
        # 워터마크 스트립: 6프레임 하단 28% 크롭 → 2배 확대 → 세로 타일
        _run([ffmpeg, "-y", "-i", ref,
              "-vf", f"fps=6/{dur},crop=iw:ih*0.28:0:ih*0.72,scale=iw*2:-2,tile=1x6",
              "-frames:v", "1", os.path.join(d, "watermark_strip.jpg")], timeout=120)
        made = [f for f in ("contact_sheet.jpg", "watermark_strip.jpg")
                if os.path.exists(os.path.join(d, f))]
        job["files"] += made
        n = len(os.listdir(frames_dir))
        if made:
            _set(job, "frames", "ok", f"프레임 {n}장 + {', '.join(made)}")
        else:
            _set(job, "frames", "fail", "프레임 추출 실패")
    except subprocess.TimeoutExpired:
        _set(job, "frames", "fail", "ffmpeg 타임아웃")


# ── 4단계: @핸들 단서 추출 ────────────────────────────

_HANDLE_RE = re.compile(r"@([A-Za-z0-9_.\-]{3,30})")


def stage_handles(job: dict) -> None:
    meta = job.get("meta", {})
    hints = job.get("hints", {})
    text = " ".join(str(meta.get(k, "")) for k in ("title", "description", "channel_handle"))
    text += " " + str(hints.get("handle", "")) + " " + str(hints.get("title", ""))
    handles = list(dict.fromkeys(_HANDLE_RE.findall(text)))

    # OCR 시도 (pytesseract 있으면 보너스)
    ocr_note = ""
    strip = os.path.join(job_dir(job["job_id"]), "watermark_strip.jpg")
    if os.path.exists(strip):
        try:
            import pytesseract  # type: ignore
            from PIL import Image
            txt = pytesseract.image_to_string(Image.open(strip))
            found = _HANDLE_RE.findall(txt)
            handles += [h for h in found if h not in handles]
            ocr_note = f" (OCR {len(found)}건)"
        except ImportError:
            ocr_note = " (OCR 모듈 없음 — 워터마크 스트립 육안 확인 필요)"
        except Exception as e:  # noqa: BLE001
            ocr_note = f" (OCR 실패: {e})"
    else:
        ocr_note = " (프레임 없음 — 육안 확인 불가)"

    # 유튜브 채널 자체 핸들은 '원 촬영자' 단서가 아니라 재업로더일 수 있음 — 구분 저장
    own = (meta.get("channel_handle") or "").lstrip("@")
    job["handles"] = handles
    job["own_handle"] = own
    external = [h for h in handles if h.lower() != own.lower()]
    if external:
        _set(job, "handles", "ok", f"@핸들 {len(handles)}건 (외부 단서 {len(external)}건){ocr_note}")
    elif handles:
        _set(job, "handles", "ok", f"@핸들 {len(handles)}건 — 전부 업로더 자신{ocr_note}")
    else:
        _set(job, "handles", "fail", f"@핸들 미검출{ocr_note}")


# ── 5단계: 5플랫폼 후보 생성 ──────────────────────────

def _probe(url: str) -> str:
    """가벼운 HTTP 접근성 확인. 로그인 장벽·차단은 정상 상황."""
    try:
        import requests
        r = requests.get(url, headers={"User-Agent": UA}, timeout=15, allow_redirects=True)
        return f"HTTP {r.status_code}"
    except Exception as e:  # noqa: BLE001
        return f"접근 실패({type(e).__name__})"


def _ddg_links(query: str, limit: int = 5) -> list[str]:
    """DuckDuckGo HTML 검색 시도 — 막히면 빈 리스트 (링크 제공으로 폴백)."""
    try:
        import requests
        r = requests.get("https://html.duckduckgo.com/html/", params={"q": query},
                         headers={"User-Agent": UA}, timeout=20)
        if not r.ok:
            return []
        links = re.findall(r'href="[^"]*uddg=([^"&]+)', r.text)
        out = []
        for u in links[:limit]:
            u = urllib.parse.unquote(u)
            if u.startswith("http") and u not in out:
                out.append(u)
        return out
    except Exception:  # noqa: BLE001
        return []


def stage_candidates(job: dict) -> None:
    meta = job.get("meta", {})
    title = meta.get("title", "") or job.get("hints", {}).get("title", "")
    own = job.get("own_handle", "")
    handles = job.get("handles", [])
    external = [h for h in handles if h.lower() != own.lower()] or handles
    q = urllib.parse.quote

    cand: dict = {"profiles": [], "searches": [], "auto_found": []}

    # 핸들 기반 프로필 확인 루트 (4플랫폼)
    for h in external[:3]:
        for platform, url in [
            ("TikTok", f"https://www.tiktok.com/@{h}"),
            ("Instagram", f"https://www.instagram.com/{h}/"),
            ("Douyin", f"https://www.douyin.com/search/{q(h)}"),
            ("Xiaohongshu", f"https://www.xiaohongshu.com/search_result?keyword={q(h)}"),
        ]:
            cand["profiles"].append({
                "platform": platform, "handle": h, "url": url, "probe": _probe(url),
            })

    # 제목·핸들 기반 검색 루트 (항상 생성 — 수동 확인용)
    terms = [t for t in [title] + [f"@{h}" for h in external[:2]] if t]
    for t in terms[:3]:
        cand["searches"] += [
            {"platform": "TikTok", "url": f"https://www.google.com/search?q={q('site:tiktok.com ' + t)}"},
            {"platform": "Instagram", "url": f"https://www.google.com/search?q={q('site:instagram.com ' + t)}"},
            {"platform": "Douyin", "url": f"https://www.douyin.com/search/{q(t)}"},
            {"platform": "Xiaohongshu", "url": f"https://www.xiaohongshu.com/search_result?keyword={q(t)}"},
            {"platform": "웹 전체", "url": f"https://duckduckgo.com/?q={q(t)}"},
        ]

    # 프로그램 검색 시도 (보너스 — 막히면 그냥 링크만)
    for t in terms[:2]:
        for u in _ddg_links(f"{t} tiktok OR instagram OR douyin OR xiaohongshu"):
            if any(p in u for p in ("tiktok.com", "instagram.com", "douyin.com", "xiaohongshu.com", "xhslink")):
                if u not in [c["url"] for c in cand["auto_found"]]:
                    cand["auto_found"].append({"url": u, "query": t})

    job["candidates"] = cand
    n_auto = len(cand["auto_found"])
    _set(job, "candidates", "ok",
         f"프로필 루트 {len(cand['profiles'])}건 · 검색 루트 {len(cand['searches'])}건 · 자동 발견 {n_auto}건")


# ── 6단계: 판정 + 보고서 ──────────────────────────────

def stage_report(job: dict) -> None:
    meta = job.get("meta", {})
    own = job.get("own_handle", "")
    handles = job.get("handles", [])
    external = [h for h in handles if h.lower() != own.lower()]
    frames_ok = job["stages"]["frames"]["status"] == "ok"

    if external:
        strongest = f"@{external[0]} (제목/설명/OCR 단서)"
        yt_original = "낮음 — 외부 계정 워터마크/단서 존재"
        platform_first = "TikTok 또는 Instagram"
    elif frames_ok:
        strongest = "워터마크 자동 검출 없음 — contact_sheet.jpg / watermark_strip.jpg 육안 확인 필요"
        yt_original = "불확실 — 프레임 육안 확인 후 판정"
        platform_first = "미정 (육안 확인 후)"
    else:
        strongest = "프레임 미확보 — 메타 기반 단서만 있음 (판정 보류)"
        yt_original = "판정 불가 (프레임 필요)"
        platform_first = "미정"

    job["verdict"] = {
        "yt_original_likelihood": yt_original,
        "strongest_clue": strongest,
        "platform_first": platform_first,
        "earliest_publication": "미확정 — 후보 링크에서 게시일 확인 필요",
        "original_creator": f"@{external[0]} 유력" if external else "미확정",
    }
    job["stages"]["report"] = {"status": "ok", "note": "report.md 생성"}

    # report.md
    lines = [
        f"# 🔎 원본 소스 찾기 보고서 — {job['job_id']}",
        "",
        f"- 입력: {job['url']}",
        f"- 제목: {meta.get('title', '?')}",
        f"- 채널: {meta.get('channel', '?')} ({meta.get('channel_handle', '')})",
        f"- 업로드: {meta.get('upload_utc', '?')} / {meta.get('upload_kst', '')}",
        f"- 조회수: {meta.get('view_count', '?')}",
        "",
        "## 현재 판정",
        f"- YouTube 원본 가능성: **{yt_original}**",
        f"- 가장 강한 단서: **{strongest}**",
        f"- 원본 플랫폼 1순위: {platform_first}",
        f"- 가장 이른 공개 후보: {job['verdict']['earliest_publication']}",
        f"- 원본 촬영 후보: {job['verdict']['original_creator']}",
        "",
        "## 단계별 결과",
    ]
    for s in STAGES:
        st = job["stages"][s]
        icon = {"ok": "✅", "fail": "⚠️", "skip": "⏭️", "pending": "⏳"}.get(st["status"], "·")
        lines.append(f"- {icon} {s}: {st['note']}")
    lines += ["", "## 확인 루트 (5플랫폼)"]
    for p in job["candidates"].get("profiles", []):
        lines.append(f"- [{p['platform']}] @{p['handle']} → {p['url']} ({p['probe']})")
    for sch in job["candidates"].get("searches", [])[:10]:
        lines.append(f"- [검색·{sch['platform']}] {sch['url']}")
    for a in job["candidates"].get("auto_found", []):
        lines.append(f"- [자동 발견] {a['url']}")
    lines += [
        "",
        "## 한계·다음 단계",
        "- TikTok private/임베드 차단, Instagram 비로그인, 샤오홍슈/더우인 로그인 장벽으로",
        "  자동 추출이 막힐 수 있음 — 위 확인 루트에서 같은 장면을 직접 대조하세요.",
        "- 판정 원칙: 워터마크 @핸들 > 페이지 메타 날짜 > 자막 텍스트 일치.",
        "- '가장 이른 공개 후보'와 '원본 촬영 후보'는 별개 — 둘 다 확인해야 최종 판정.",
    ]
    with open(os.path.join(job_dir(job["job_id"]), "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    job["files"].append("report.md")
    job["stage"] = "report"
    _persist(job)


# ── 실행기 ────────────────────────────────────────────

def run_pipeline(job: dict) -> dict:
    try:
        stage_meta(job)
        stage_download(job)
        stage_frames(job)
        stage_handles(job)
        stage_candidates(job)
        stage_report(job)
        job["status"] = "done"
    except Exception as e:  # noqa: BLE001 — 잡 전체는 절대 죽지 않게
        job["status"] = "error"
        job["error"] = str(e)
    _persist(job)
    return job


def start_job(url: str, hints: dict | None = None) -> dict:
    """백그라운드 스레드로 파이프라인 실행 (FastAPI 용)."""
    job = new_job(url, hints)
    t = threading.Thread(target=run_pipeline, args=(job,), daemon=True)
    t.start()
    return job


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    j = new_job(sys.argv[1])
    run_pipeline(j)
    print(json.dumps({k: j[k] for k in ("job_id", "status", "verdict", "handles")},
                     ensure_ascii=False, indent=2))
    print("보고서:", os.path.join(job_dir(j["job_id"]), "report.md"))
