"""스코어러 — 댓글 감성 정성 분석(Gemini) → store.video_features 적재.

파이썬-우선 자동화 2단계. store 에서 '아직 분석 안 된' 영상을 꺼내, 그 영상의
댓글을 한 번에 묶어 Gemini 에게 보낸다(영상당 1회 = 레이트리밋·비용 절감).
같은 입력은 콘텐츠 해시 캐시로 재호출하지 않아 비용·일관성을 동시에 잡는다.

정성 점수(0~45), 정량(55)과 합쳐 100점:
  - comment_reaction  (최대 20)  댓글 반응의 강도·양
  - senior_emotion    (최대 15)  5070 정서(눈물/고향/위로/추억) 환기력
  - performance_energy(최대 10)  무대/연주 에너지
무드는 vocab.json 의 통제 어휘에서 골라 스튜디오/분석기와 정렬한다.

LLM 호출은 주입(llm_call) 가능 — 헤드리스 테스트 시 스텁을 넣는다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import store
import suno_studio

DEFAULT_MODEL = "gemini-2.0-flash"
CACHE_PATH = Path(__file__).parent / "score_cache.json"

MAX_COMMENTS = 30
MAX_COMMENT_LEN = 200

SUBSCORE_CAPS = {
    "comment_reaction": 20,
    "senior_emotion": 15,
    "performance_energy": 10,
}


def _moods(vocab: dict) -> dict[str, str]:
    return {m["suno"].lower(): m["suno"] for m in vocab["dimensions"]["mood"]}


def build_prompt(title: str, comments: list[str], vocab: dict) -> str:
    mood_list = [m["suno"] for m in vocab["dimensions"]["mood"]]
    trimmed = [c[:MAX_COMMENT_LEN] for c in comments[:MAX_COMMENTS] if c]
    comment_block = "\n".join(f"  · {c}" for c in trimmed) or "  (댓글 없음)"
    return f"""당신은 한국 5070 시니어의 마음을 위로하는 철학자이자 음악 기획자입니다.
아래 영상의 제목과 댓글을 보고, 시니어 청자의 감성 반응을 분석해 점수를 매기세요.

[영상 제목]
{title}

[상위 댓글]
{comment_block}

[채점 기준]
- comment_reaction (0~20): 댓글 반응의 강도와 양(눈물·공감·감탄이 많을수록 높음)
- senior_emotion   (0~15): 5070 정서(눈물·고향·어머니·위로·추억) 환기력
- performance_energy (0~10): 무대/연주/흥의 에너지
- mood: 아래 목록에서 정확히 하나 선택
- energy: low | mid | high 중 하나
- emotion_summary: 지배 감정을 한국어 한 줄로

[mood 목록]
{json.dumps(mood_list, ensure_ascii=False)}

반드시 아래 JSON 만 출력(설명/마크다운 금지):
{{
  "comment_reaction": 0,
  "senior_emotion": 0,
  "performance_energy": 0,
  "mood": "<목록 중 하나>",
  "energy": "low",
  "emotion_summary": "<한 줄>"
}}"""


def _loads(raw: str) -> dict:
    import re
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _clamp_num(value, cap: int) -> float:
    try:
        return max(0.0, min(float(value), float(cap)))
    except (ValueError, TypeError):
        return 0.0


def parse_score(raw: str, vocab: dict) -> dict:
    data = _loads(raw)
    subs = {k: _clamp_num(data.get(k), cap) for k, cap in SUBSCORE_CAPS.items()}
    qual_score = round(sum(subs.values()), 2)

    mood = _moods(vocab).get((data.get("mood") or "").strip().lower())
    energy = (data.get("energy") or "").strip().lower()
    if energy not in {"low", "mid", "high"}:
        energy = None

    return {
        "subscores": subs,
        "qual_score": qual_score,
        "mood": mood,
        "energy": energy,
        "emotion_summary": (data.get("emotion_summary") or "").strip(),
    }


def _cache_key(title: str, comment_texts: list[str]) -> str:
    payload = json.dumps([title, sorted(comment_texts)], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_cache(path: str | Path = CACHE_PATH) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_cache(cache: dict, path: str | Path = CACHE_PATH) -> None:
    Path(path).write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def gemini_call(prompt: str, *, api_key: str, model: str = DEFAULT_MODEL) -> str:
    import google.generativeai as genai  # type: ignore
    genai.configure(api_key=api_key)
    m = genai.GenerativeModel(
        model_name=model,
        generation_config={"temperature": 0.3, "response_mime_type": "application/json"},
    )
    resp = m.generate_content(prompt)
    return (resp.text or "").strip()


def score_video(
    video_id: str,
    *,
    vocab: dict,
    llm_call=None,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    db_path=store.DB_PATH,
    cache: dict | None = None,
) -> dict | None:
    video = store.get_video(video_id, path=db_path)
    if not video:
        return None
    comments = [c["text"] for c in store.get_comments(video_id, path=db_path) if c.get("text")]
    title = video.get("title", "") or ""

    key = _cache_key(title, comments)
    if cache is not None and key in cache:
        result = cache[key]
    else:
        prompt = build_prompt(title, comments, vocab)
        if llm_call is not None:
            raw = llm_call(prompt)
        elif api_key:
            raw = gemini_call(prompt, api_key=api_key, model=model)
        else:
            raise ValueError("api_key 또는 llm_call 이 필요합니다.")
        result = parse_score(raw, vocab)
        if cache is not None:
            cache[key] = result

    store.set_video_features(
        video_id,
        mood=result.get("mood"),
        energy=result.get("energy"),
        qual_score=result.get("qual_score"),
        emotion_summary=result.get("emotion_summary"),
        style_tags={"subscores": result.get("subscores", {})},
        path=db_path,
    )
    return result


def score_pending(
    *,
    vocab: dict | None = None,
    llm_call=None,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    limit: int = 50,
    db_path=store.DB_PATH,
    cache_path=CACHE_PATH,
) -> dict:
    """아직 분석 안 된 영상들을 정성 채점. (캐시 자동 로드/저장)"""
    vocab = vocab or suno_studio.load_vocab()
    cache = load_cache(cache_path)
    pending = store.videos_missing("features", limit=limit, path=db_path)
    scored = 0
    for v in pending:
        try:
            score_video(v["video_id"], vocab=vocab, llm_call=llm_call,
                        api_key=api_key, model=model, db_path=db_path, cache=cache)
            scored += 1
        except Exception as e:
            print(f"  [skip] {v['video_id']}: {type(e).__name__}: {e}", file=sys.stderr)
    save_cache(cache, cache_path)
    return {"pending": len(pending), "scored": scored, "cache_size": len(cache)}


def ranked_candidates(*, limit: int = 20, db_path=store.DB_PATH) -> list[dict]:
    """정량+정성 합산 상위 후보 (검수/생성 큐). 두 점수가 다 있는 영상만."""
    conn = store.connect(db_path)
    try:
        rows = conn.execute(
            """SELECT v.video_id, v.title, v.channel_title, v.quant_score,
                      f.qual_score, f.mood, f.emotion_summary,
                      (COALESCE(v.quant_score,0) + COALESCE(f.qual_score,0)) AS total_score
               FROM videos v JOIN video_features f ON v.video_id = f.video_id
               ORDER BY total_score DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="댓글 정성 스코어러 → store.video_features")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--db", default=str(store.DB_PATH))
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--api-key", default=os.getenv("GEMINI_API_KEY", ""))
    p.add_argument("--show-ranking", action="store_true")
    args = p.parse_args(argv)

    if not args.api_key:
        print("GEMINI_API_KEY 가 필요합니다 (.env 또는 --api-key).", file=sys.stderr)
        return 2

    summary = score_pending(api_key=args.api_key, model=args.model,
                            limit=args.limit, db_path=args.db)
    print(f"정성 채점 완료: 대상 {summary['pending']}개, 채점 {summary['scored']}개, "
          f"캐시 {summary['cache_size']}건")
    if args.show_ranking:
        print("\n=== 정량+정성 합산 상위 후보 ===")
        for r in ranked_candidates(db_path=args.db):
            print(f"  [{r['total_score']:.1f}] {r['title']}  "
                  f"(정량 {r['quant_score']}, 정성 {r['qual_score']}, {r['mood']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
