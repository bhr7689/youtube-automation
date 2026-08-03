"""👥 메타데이터 전문가 팀 — "한 명이 다" → "10명이 각자 전문분야를 깊게 + 편집장이 종합".

사장님 통찰: 직원 1명이 전부 하는 것보다, 전문가 10명이 자기 분야만 세밀하게 파고
편집장이 하나로 정리하면 결과물의 깊이(전문성)·넓이(다차원)가 달라진다.

구조: 공유 Brief(작업지시서)를 파이프라인으로 흘리며 각 전문가가 자기 파트를 채운다.
     기존 모듈(trend_meta·metadata_engine·serp_judge)을 전문가로 재배치 + 신규 전문가 추가.
     지금은 규칙기반으로 동작, 키가 있으면 각 전문가를 LLM 페르소나로 '심화'(deepen) 가능.

전문가 명단 (10 + 편집장):
  1 트렌드 애널리스트   2 키워드 리서처     3 경쟁/SERP 분석가
  4 제목 카피라이터     5 설명글 SEO 작가   6 태그·해시태그 전략가
  7 썸네일 디렉터       8 로컬라이제이션    9 정책 검수관
 10 품질 평가관(QA)     ★ 편집장(오케스트레이터·종합)
"""
from __future__ import annotations
from dataclasses import dataclass, field

import metadata_engine as ME
import serp_judge
try:
    import trend_meta
except Exception:
    trend_meta = None
try:
    import ref_titles
except Exception:
    ref_titles = None
try:
    import asset_ledger
except Exception:
    asset_ledger = None
try:
    import sre_store as _sre_store   # SRE 실험 리더보드(이긴 각도) 소프트 연결
except Exception:
    _sre_store = None

# A/B/C/D 각도 라벨(SRE 전략 ↔ 제목 각도 매핑)
_ANGLE_LABEL = {"A": "경험(체험 인증)", "B": "스토리(서사·반전)",
                "C": "사실(정보·권위)", "D": "호기심(정보 격차)"}
_ANGLE_HINT = {
    "A": "제목·훅을 1인칭 체험/인증 각도로",
    "B": "제목·훅을 이야기/반전 구조로",
    "C": "제목·훅을 정보/권위 각도로",
    "D": "제목·훅을 호기심 격차/미완결 각도로",
}


def winning_angle() -> dict | None:
    """SRE 실험 리더보드에서 '가장 자주 이긴 각도'를 읽어 제목 전략 힌트로 반환.
    실험 데이터가 없으면 None(무영향)."""
    if not _sre_store:
        return None
    try:
        lb = _sre_store.strategy_leaderboard()
    except Exception:
        return None
    top = lb.get("topStrategy")
    if not top or lb.get("totalBatches", 0) < 1:
        return None
    return {
        "strategy": top,
        "label": _ANGLE_LABEL.get(top, top),
        "hint": _ANGLE_HINT.get(top, ""),
        "wins": lb.get("wins", {}).get(top, 0),
        "totalBatches": lb.get("totalBatches", 0),
    }


def _niche(country: str, concept: str) -> str:
    """장르(니치) 결정 — 자산 축적·점령의 단위."""
    co = country.upper()
    cmap = {"KR": ME.CONCEPTS, "JP": ME.CONCEPTS_JP, "US": ME.CONCEPTS_US}[co]
    c = cmap.get(concept, {})
    g = c.get("genre")
    if g:
        return g[0]
    return {"KR": "여름 재즈", "JP": "洋楽ジャズ", "US": "summer jazz"}[co]


@dataclass
class Brief:
    """공유 작업지시서 — 전문가들이 순서대로 채운다."""
    country: str = "KR"
    concept: str | None = None            # 없으면 트렌드 애널리스트가 정함
    serp_results: list | None = None      # 있으면 경쟁분석가가 실판정
    artifacts: dict = field(default_factory=dict)   # 각 전문가 산출물
    report: list = field(default_factory=list)      # 전문가별 요약(팀 리포트)

    def log(self, role, summary, detail=None):
        self.report.append({"role": role, "summary": summary, "detail": detail or {}})


# ── 전문가 베이스 ──────────────────────────────────────────
class Specialist:
    role = "전문가"
    def run(self, b: Brief): ...


# 1) 트렌드 애널리스트 — 지금 뜨는 테마축 결정 (trend_meta)
class TrendAnalyst(Specialist):
    role = "🧭 트렌드 애널리스트"
    def run(self, b: Brief):
        if b.concept:
            theme, src = b.concept, "지정됨"
        elif trend_meta:
            theme, src = trend_meta.current_theme(b.country), "live/seasonal"
        else:
            theme, src = "수박", "폴백"
        if theme not in ME.CONCEPTS:
            theme = "수박"
        b.concept = theme
        boost = trend_meta.rising_boost(b.country) if trend_meta else []
        b.artifacts["theme"] = {"theme": theme, "source": src, "rising_terms": boost}
        b.log(self.role, f"지금 밀 테마 = '{theme}' ({src})",
              {"rising_terms": boost[:6]})


# 2) 키워드 리서처 — 3계층 + 뜨는 실검색어 보강, 저품질 회피 목록
class KeywordResearcher(Specialist):
    role = "🔑 키워드 리서처"
    def run(self, b: Brief):
        tiers = dict(ME.keyword_tiers(b.country))
        boost = b.artifacts.get("theme", {}).get("rising_terms", [])
        if boost:
            tiers = {**tiers, "emotion": ME._dedup(boost + tiers["emotion"])}
        avoid = ["나만의", "브이로그 배경", "초보", "무명", "신곡 공개"]  # 저조회 유발 회피어
        b.artifacts["keywords"] = {"tiers": tiers, "avoid": avoid}
        b.log(self.role,
              f"3계층 키워드 확보(메인 {len(tiers['main'])}·감성 {len(tiers['emotion'])}·영문 {len(tiers['global'])})",
              {"avoid_low_quality": avoid})


# 3) 경쟁/SERP 분석가 — 상위 패턴 + SERP 판정(있으면 실판정)
class CompetitorAnalyst(Specialist):
    role = "🕵️ 경쟁/SERP 분석가"
    def run(self, b: Brief):
        pkg = ME.generate_package(b.country, b.concept)
        my_kw = pkg["my_keywords"]
        if b.serp_results:
            verdict = serp_judge.judge(b.serp_results, my_kw)
        else:
            verdict = {"verdict": "unknown", "fit_score": None,
                       "reasons": ["SERP 실판정은 사장님 PC serp_probe(Playwright 시크릿)에서"]}
        b.artifacts["competition"] = {"my_keywords": my_kw, "serp": verdict}
        b.log(self.role,
              f"SERP 판정 = {verdict['verdict']}"
              + (f" (Fit {verdict['fit_score']})" if verdict.get('fit_score') is not None else ""),
              {"reasons": verdict["reasons"][:3]})


# 4) 제목 카피라이터 — ① 레퍼런스 조합(1단계 기준) 우선 + 어휘형 보조
class TitleCopywriter(Specialist):
    role = "✍️ 제목 카피라이터"
    def run(self, b: Brief):
        co = b.country.upper()
        t = ME.generate_titles_kr(b.concept) if co == "KR" else \
            (ME.generate_titles_jp(b.concept) if co == "JP" else ME.generate_titles_us(b.concept))
        # ① 레퍼런스 고조회 제목 재조합 = 첫 단계 기준(사장님 방법)
        corpus, n_ref = [], 0
        if ref_titles:
            try:
                corpus = ref_titles.combine_titles(co, b.concept, n=5)
                n_ref = len(ref_titles.all_titles(co))
            except Exception:
                corpus = []
        # 🏛️ 우리 검증 자산(점령한 제목)이 있으면 최우선 재료로 재투입(복리)
        niche = _niche(co, b.concept)
        assets = asset_ledger.winners(co, niche) if asset_ledger else []
        search = ME._dedup(assets + (corpus or t["search_titles"]))   # 검증자산 > 레퍼런스 > 어휘
        recommended = search[0]
        b.artifacts["titles"] = {
            "search": search, "emotion": t["emotion_titles"], "thumb_text": t["thumb_text"],
            "recommended": recommended, "ref_count": n_ref, "asset_count": len(assets),
            "niche": niche, "vocab_search": t["search_titles"],
        }
        src = (f"검증자산 {len(assets)}개 재사용" if assets
               else (f"레퍼런스 {n_ref}개 재조합" if corpus else "어휘 기반"))
        b.log(self.role, f"제목 {len(search)}(1순위: {src}) + 감성형 {len(t['emotion_titles'])}",
              {"recommended": recommended})


# 5) 설명글 SEO 작가 — ④ 채택 제목 키워드로 2차 결착
class DescriptionWriter(Specialist):
    role = "📄 설명글 SEO 작가"
    def run(self, b: Brief):
        title = b.artifacts["titles"]["recommended"]
        desc = ME.describe_from_title(title, b.country, b.concept)   # 제목 키워드 재주입
        top = desc.strip().splitlines()[0]
        b.artifacts["description"] = {"text": desc, "top_line": top, "bound_to": title}
        b.log(self.role, "설명글 4단 + 제목 키워드 재주입(2차 결착)", {"top_line": top})


# 6) 태그·해시태그 전략가 — ④ 채택 제목 키워드로 2차 결착
class TagStrategist(Specialist):
    role = "🏷️ 태그·해시태그 전략가"
    def run(self, b: Brief):
        title = b.artifacts["titles"]["recommended"]
        pkg = ME.generate_package(b.country, b.concept)
        tags = ME.tags_from_title(title, b.country, b.concept)       # 제목 키워드 앞배치
        b.artifacts["tags"] = {"tags": tags, "hashtags": pkg["hashtags"]}
        b.log(self.role, f"태그 {len(tags)}개(제목 키워드 앞배치) + 해시태그", {"hashtags": pkg["hashtags"]})


# 7) 썸네일 디렉터 — 제목↔썸네일 소재 일치 + 가독성
class ThumbnailDirector(Specialist):
    role = "🖼️ 썸네일 디렉터"
    def run(self, b: Brief):
        thumb_text = b.artifacts.get("titles", {}).get("thumb_text", "")
        c = ME.CONCEPTS.get(b.concept, ME.CONCEPTS["수박"])
        brief = {
            "thumb_text": thumb_text,
            "scene": f"{c['phrase']} — {c.get('desc_open','여름')} 감성 씬 ({c['emoji']})",
            "readability": "굵은 폰트 + 외곽선/그림자, 딥그린·레드·브라운 등 진한 톤(모바일 대비)",
            "match": "썸네일 소재 = 제목 소재 (일치)",
        }
        b.artifacts["thumbnail"] = brief
        b.log(self.role, "제목과 소재 일치하는 썸네일 브리프", {"thumb_text": thumb_text})


# 8) 로컬라이제이션 전문가 — 나라별 뉘앙스 체크
class Localizer(Specialist):
    role = "🌐 로컬라이제이션"
    NOTES = {
        "KR": "상황+감성(시원한·청량한) + 목적어(공부/일/카페)",
        "JP": "用途(作業用BGM·勉強用) + 洋楽ジャズ(해외감성) + カタカナ/영문 혼용",
        "US": "use-case first(for Work/Study) + No Lyrics/Instrumental",
    }
    def run(self, b: Brief):
        note = self.NOTES.get(b.country.upper(), self.NOTES["KR"])
        b.artifacts["localization"] = {"note": note}
        b.log(self.role, f"{b.country} 현지화 원칙 적용", {"note": note})


# 9) 정책 검수관 — 스팸/오해성 금지선
class PolicyReviewer(Specialist):
    role = "🛡️ 정책 검수관"
    def run(self, b: Brief):
        tags = b.artifacts.get("tags", {}).get("tags", [])
        hashtags = b.artifacts.get("description", {}).get("text", "")
        issues = []
        if len(tags) > 40:
            issues.append("태그 과다(40+) — 축소 권장")
        if hashtags.count("#") > 15:
            issues.append("해시태그 과다(15+) — 유튜브 무시/불이익 위험")
        b.artifacts["policy"] = {"issues": issues, "ok": not issues}
        b.log(self.role, "스팸/오해성 금지선 검수 " + ("✅ 통과" if not issues else "⚠️ 지적"),
              {"issues": issues})


# 10) 품질 평가관(QA) — 각 산출물 채점 + 임계 미달 플래그
class QAEvaluator(Specialist):
    role = "🏆 품질 평가관(QA)"
    def run(self, b: Brief):
        scores, flags = {}, []
        title = b.artifacts.get("titles", {}).get("search", [""])[0]
        s = 0
        s += 3 if title.startswith(("[Playlist]", "Playlist")) else 0   # 분류 신호
        s += 3 if title.count("·") >= 2 or title.count(",") >= 2 or " & " in title else 0  # 밀도
        s += 2 if any(e in title for e in "🍉🍋🍑🌊🍏🍹☕🌧️🌙🔥") else 0            # 이모지
        s += 2 if "|" in title else 0                                    # 영문 꼬리
        scores["title"] = s
        if s < 7:
            flags.append("제목: 밀도/분류신호 보강 필요")

        tags = b.artifacts.get("tags", {}).get("tags", [])
        st = 0
        st += 4 if 12 <= len(tags) <= 30 else 1
        st += 3 if any(_is_ascii(t) for t in tags) and any(not _is_ascii(t) for t in tags) else 0  # 한/영
        st += 3 if len(set(tags)) == len(tags) else 0
        scores["tags"] = st
        if st < 7:
            flags.append("태그: 개수/한영균형 보강 필요")

        desc = b.artifacts.get("description", {}).get("text", "")
        sd = (4 if desc.count("\n") >= 4 else 1) + (3 if "#" in desc else 0) + (3 if "Tracklist" in desc else 0)
        scores["description"] = sd

        total = sum(scores.values())
        b.artifacts["qa"] = {"scores": scores, "total": total, "flags": flags}
        b.log(self.role, f"품질 점수 총 {total} (제목 {scores['title']}·태그 {scores['tags']}·설명 {scores['description']})",
              {"flags": flags})


def _is_ascii(s: str) -> bool:
    return all(ord(ch) < 128 for ch in s)


# ★ 편집장 — 순서 조율 + 종합 + 최종 복붙 패키지
class ChiefEditor:
    role = "📋 편집장(종합)"
    TEAM = [TrendAnalyst, KeywordResearcher, CompetitorAnalyst, TitleCopywriter,
            DescriptionWriter, TagStrategist, ThumbnailDirector, Localizer,
            PolicyReviewer, QAEvaluator]

    def produce(self, country="KR", concept=None, serp_results=None) -> dict:
        b = Brief(country=country, concept=concept, serp_results=serp_results)
        for Sp in self.TEAM:
            Sp().run(b)
        titles = b.artifacts["titles"]
        niche = titles.get("niche", _niche(country, b.concept))
        serp = b.artifacts["competition"]["serp"]

        # 🏛️ 자산 축적 — SERP 실판정이 있으면 원장에 기록(채택 = 검증 자산)
        if asset_ledger and serp_results is not None and serp.get("fit_score") is not None:
            asset_ledger.record(country, niche, titles["recommended"],
                                fit=serp["fit_score"], verdict=serp["verdict"],
                                adopted=(serp["verdict"] == "adopt"))
        playbook = asset_ledger.genre_playbook(country, niche) if asset_ledger else {}

        # 🧪 SRE 실험 학습 — 이 계정에서 가장 자주 이긴 각도를 제목 전략에 반영
        angle = winning_angle()
        if angle:
            b.log("🧪 실험 학습(각도)",
                  f"이긴 각도: {angle['label']} — {angle['wins']}승/{angle['totalBatches']}회",
                  {"hint": angle["hint"]})

        # 최종 복붙 패키지 종합
        final = {
            "country": country,
            "theme": b.artifacts["theme"]["theme"],
            "title_recommended": titles["recommended"],      # 레퍼런스 조합 1순위
            "ref_count": titles.get("ref_count", 0),
            "titles_search": titles["search"],
            "titles_emotion": titles["emotion"],
            "description": b.artifacts["description"]["text"],
            "tags": b.artifacts["tags"]["tags"],
            "hashtags": b.artifacts["tags"]["hashtags"],
            "thumbnail": b.artifacts["thumbnail"],
            "qa": b.artifacts["qa"],
            "serp": serp,
            "niche": niche,
            "genre_playbook": playbook,                       # 📖 이 장르 승리 패턴(축적)
            "asset_count": titles.get("asset_count", 0),
            "winning_angle": angle,                           # 🧪 실험서 이긴 각도(있으면)
            "team_report": b.report,                          # 전문가 10명 각자 요약
        }
        return final


def produce_package(country="KR", concept=None, serp_results=None) -> dict:
    return ChiefEditor().produce(country, concept, serp_results)


# ── 자기검증 ───────────────────────────────────────────────
if __name__ == "__main__":
    out = produce_package("KR", concept="수박")
    print("=" * 60)
    print(f"📋 편집장 종합 — {out['country']} / 테마 '{out['theme']}'")
    print("=" * 60)
    print("\n👥 전문가 10명 리포트:")
    for r in out["team_report"]:
        print(f"  {r['role']}: {r['summary']}")
    print(f"\n⭐ 추천 제목: {out['title_recommended']}")
    print(f"🏆 QA 총점: {out['qa']['total']}  플래그: {out['qa']['flags'] or '없음'}")
    print(f"🖼️ 썸네일 문구: {out['thumbnail']['thumb_text']}  ({out['thumbnail']['match']})")
    print(f"🏷️ 해시태그: {out['hashtags']}")

    # 구조 검증
    assert len(out["team_report"]) == 10, "전문가 10명이 다 일해야"
    assert out["title_recommended"] and out["tags"] and out["description"]
    assert out["qa"]["total"] > 0
    # SERP 데이터 주면 경쟁분석가가 실판정
    weak = [{"title": "무명 브이로그", "views": 200, "published_at": "2025-07-30",
             "subscribers": 30, "channel_age_months": 1}] * 3
    out2 = produce_package("KR", concept="수박", serp_results=weak)
    assert out2["serp"]["verdict"] == "regenerate"
    print("\n✅ metadata_team self-test 통과 — 전문가 10명 + 편집장 종합 동작")
