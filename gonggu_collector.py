"""
공구 인플루언서 수집기
1. 엑셀/CSV 대량 임포트  (크몽 구매 리스트 등)
2. 구글 검색 기반 반자동 수집  (공개 검색결과, 합법)
3. 중복 제거 + 자동 카테고리 분류
"""
import re
import time
import random
import urllib.parse
import urllib.request
from pathlib import Path
import pandas as pd

import gonggu_db as db

# ── 카테고리 키워드 자동 분류 ─────────────────────────────
CATEGORY_KEYWORDS = {
    "뷰티":    ["뷰티", "화장품", "스킨케어", "메이크업", "코스메틱", "선크림", "립", "파운데이션", "향수", "beauty", "skincare"],
    "식품":    ["식품", "먹방", "음식", "맛집", "요리", "레시피", "과일", "채소", "수산", "농산", "밀키트", "간식", "건식"],
    "패션":    ["패션", "코디", "옷", "의류", "신발", "가방", "ootd", "스타일", "fashion", "outfit"],
    "건강식품": ["건강", "영양제", "비타민", "홍삼", "콜라겐", "다이어트", "보충제", "프로바이오틱", "헬스"],
    "생활용품": ["생활", "주방", "인테리어", "홈", "청소", "수납", "리빙", "home", "living"],
    "육아":    ["육아", "아이", "유아", "어린이", "엄마", "출산", "임산부", "맘", "키즈", "mom", "baby"],
    "반려동물": ["강아지", "고양이", "반려", "펫", "pet", "dog", "cat"],
    "가전":    ["가전", "전자", "IT", "스마트", "기기", "tech"],
}


def classify_category(text: str) -> str:
    """텍스트에서 카테고리 자동 추론"""
    text_lower = text.lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return cat
    return "기타"


def clean_instagram_id(raw: str) -> str:
    """@제거, URL에서 ID 추출, 공백 제거"""
    raw = str(raw).strip()
    # URL 형태 처리 (instagram.com/xxx)
    m = re.search(r'instagram\.com/([A-Za-z0-9_.]+)', raw)
    if m:
        return m.group(1)
    # @id 형태
    raw = raw.lstrip("@").strip()
    # 특수문자 제거 (알파벳/숫자/_/. 만 허용)
    raw = re.sub(r'[^A-Za-z0-9_.]', '', raw)
    return raw


def parse_followers(raw) -> int:
    """'12.3만', '1,234', '12300' 등 → int"""
    try:
        raw = str(raw).replace(",", "").replace(" ", "").strip()
        if "만" in raw:
            num = float(raw.replace("만", "")) * 10000
            return int(num)
        if "천" in raw:
            num = float(raw.replace("천", "")) * 1000
            return int(num)
        if "k" in raw.lower():
            num = float(raw.lower().replace("k", "")) * 1000
            return int(num)
        if "m" in raw.lower():
            num = float(raw.lower().replace("m", "")) * 1000000
            return int(num)
        return int(float(raw))
    except Exception:
        return 0


# ── 1. 엑셀/CSV 임포트 ────────────────────────────────────

COLUMN_ALIASES = {
    # 인스타그램 ID
    "instagram_id":  ["instagram_id", "인스타id", "인스타그램id", "인스타아이디", "계정", "id", "아이디",
                      "instagram", "insta_id", "계정명", "인스타계정", "인스타그램계정"],
    # 이름/닉네임
    "name":          ["name", "이름", "닉네임", "활동명", "인플루언서명", "채널명"],
    # 팔로워
    "followers":     ["followers", "팔로워", "팔로워수", "팔로워 수", "구독자", "구독자수", "follower"],
    # 카테고리
    "category":      ["category", "카테고리", "분야", "주제", "장르"],
    # 이메일
    "email":         ["email", "이메일", "메일", "e-mail"],
    # 연락처
    "dm_link":       ["dm_link", "dm", "링크", "연락처", "contact", "url"],
    # 메모
    "note":          ["note", "비고", "메모", "특이사항", "설명"],
}


def detect_column_mapping(df_columns: list) -> dict:
    """컬럼명 자동 매핑 반환 {표준필드: 실제컬럼명}"""
    mapping = {}
    cols_lower = {c.lower().replace(" ", "").replace("_", ""): c for c in df_columns}
    for field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            key = alias.lower().replace(" ", "").replace("_", "")
            if key in cols_lower:
                mapping[field] = cols_lower[key]
                break
    return mapping


def import_from_dataframe(df: pd.DataFrame, default_category: str = "기타") -> dict:
    """
    DataFrame → DB 임포트
    반환: {imported, skipped, duplicate, errors}
    """
    mapping = detect_column_mapping(list(df.columns))
    results = {"imported": 0, "skipped": 0, "duplicate": 0, "errors": []}

    for _, row in df.iterrows():
        try:
            raw_id = row.get(mapping.get("instagram_id", ""), "")
            insta_id = clean_instagram_id(raw_id)
            if not insta_id or len(insta_id) < 2:
                results["skipped"] += 1
                continue

            followers_raw = row.get(mapping.get("followers", ""), 0)
            followers = parse_followers(followers_raw)

            name = str(row.get(mapping.get("name", ""), "")).strip() or insta_id
            email = str(row.get(mapping.get("email", ""), "")).strip()
            dm_link = str(row.get(mapping.get("dm_link", ""), "")).strip()
            note = str(row.get(mapping.get("note", ""), "")).strip()

            # 카테고리: 명시 > 이름+메모 텍스트 추론 > 기본값
            cat_raw = str(row.get(mapping.get("category", ""), "")).strip()
            if cat_raw and cat_raw != "nan":
                category = classify_category(cat_raw) if cat_raw not in list(CATEGORY_KEYWORDS.keys()) else cat_raw
            else:
                category = classify_category(f"{name} {note}") or default_category

            db.upsert_influencer({
                "instagram_id": insta_id,
                "name": name,
                "followers": followers,
                "category": category,
                "email": email if email != "nan" else "",
                "dm_link": dm_link if dm_link != "nan" else "",
                "note": note if note != "nan" else "",
            })
            results["imported"] += 1

        except Exception as e:
            results["errors"].append(str(e))

    return results


def import_from_file(filepath: str, default_category: str = "기타", sheet: int = 0) -> dict:
    """엑셀(.xlsx/.xls) 또는 CSV 파일 → DB 임포트"""
    path = Path(filepath)
    if path.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(filepath, sheet_name=sheet, dtype=str)
    elif path.suffix.lower() == ".csv":
        for enc in ("utf-8-sig", "cp949", "utf-8"):
            try:
                df = pd.read_csv(filepath, dtype=str, encoding=enc)
                break
            except UnicodeDecodeError:
                continue
    else:
        raise ValueError(f"지원하지 않는 파일 형식: {path.suffix}")
    df = df.dropna(how="all")
    return import_from_dataframe(df, default_category)


# ── 2. 구글 검색 기반 반자동 수집 ────────────────────────

SEARCH_QUERIES = {
    "뷰티":    ["인스타그램 뷰티 공구 진행중", "인스타 화장품 공동구매 인플루언서"],
    "식품":    ["인스타그램 식품 공구 인플루언서", "인스타 먹방 공동구매 진행"],
    "패션":    ["인스타그램 패션 공구 진행중", "인스타 의류 공동구매"],
    "건강식품": ["인스타그램 건강식품 공구", "인스타 영양제 다이어트 공동구매"],
    "생활용품": ["인스타그램 생활용품 공구 진행", "인스타 주방 인테리어 공동구매"],
    "육아":    ["인스타그램 육아 공구 엄마", "인스타 맘 유아용품 공동구매"],
    "반려동물": ["인스타그램 펫 공구 진행중", "인스타 강아지 고양이 공동구매"],
}

INSTAGRAM_PATTERN = re.compile(r'instagram\.com/([A-Za-z0-9_.]{2,30})(?:/|\?|$|\s)')
AT_PATTERN = re.compile(r'@([A-Za-z0-9_.]{2,30})')


def search_google(query: str, num_results: int = 20) -> list[str]:
    """
    구글 검색결과 HTML에서 인스타그램 계정명 추출
    (공개 HTML 파싱 — robots.txt 허용 범위, 상업적 대량 수집 아님)
    """
    encoded = urllib.parse.quote(query + " site:instagram.com")
    url = f"https://www.google.com/search?q={encoded}&num={num_results}&hl=ko"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return []

    ids = set()
    ids.update(INSTAGRAM_PATTERN.findall(html))
    ids.update(AT_PATTERN.findall(html))

    # 시스템 계정 제외
    exclude = {"p", "explore", "reel", "reels", "stories", "tv", "accounts",
               "instagram", "help", "about", "press", "api", "privacy", "legal"}
    return [i for i in ids if i.lower() not in exclude and len(i) >= 3]


def search_naver(query: str) -> list[str]:
    """네이버 검색결과에서 인스타그램 계정 추출"""
    encoded = urllib.parse.quote(query)
    url = f"https://search.naver.com/search.naver?query={encoded}"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1)"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return []
    ids = set()
    ids.update(INSTAGRAM_PATTERN.findall(html))
    ids.update(AT_PATTERN.findall(html))
    exclude = {"p", "explore", "reel", "reels", "stories", "tv", "accounts", "instagram"}
    return [i for i in ids if i.lower() not in exclude and len(i) >= 3]


def collect_by_category(category: str, use_naver: bool = True, delay: float = 2.0) -> list[dict]:
    """
    카테고리 키워드로 구글+네이버 검색 → 인스타 계정 목록 반환
    반환: [{"instagram_id": ..., "category": ..., "source": ...}, ...]
    """
    queries = SEARCH_QUERIES.get(category, [f"인스타그램 {category} 공구 진행중"])
    found = {}

    for q in queries:
        ids_g = search_google(q)
        for iid in ids_g:
            if iid not in found:
                found[iid] = {"instagram_id": iid, "category": category, "source": f"구글:{q[:20]}"}
        time.sleep(delay + random.uniform(0, 1))

        if use_naver:
            ids_n = search_naver(q)
            for iid in ids_n:
                if iid not in found:
                    found[iid] = {"instagram_id": iid, "category": category, "source": f"네이버:{q[:20]}"}
            time.sleep(delay + random.uniform(0, 1))

    return list(found.values())


def bulk_import_from_search(
    categories: list[str],
    delay: float = 2.5,
    progress_callback=None,
) -> dict:
    """
    여러 카테고리 검색 후 DB 저장
    progress_callback(category, found_count) — UI 진행상황 보고용
    """
    total_new = 0
    total_found = 0
    log = []

    for cat in categories:
        candidates = collect_by_category(cat, delay=delay)
        total_found += len(candidates)
        imported = 0
        for c in candidates:
            db.upsert_influencer({
                "instagram_id": c["instagram_id"],
                "name": c["instagram_id"],
                "category": c["category"],
                "note": f"[자동수집] {c['source']}",
                "followers": 0,
            })
            imported += 1
            total_new += 1
        log.append({"category": cat, "found": len(candidates), "imported": imported})
        if progress_callback:
            progress_callback(cat, len(candidates))

    return {"total_found": total_found, "total_imported": total_new, "log": log}


# ── 3. 중복 제거 유틸 ────────────────────────────────────

def deduplicate_db() -> int:
    """DB 내 instagram_id 기준 중복 제거 (낮은 ID의 레코드 유지)"""
    import sqlite3
    conn = sqlite3.connect(db.DB_PATH)
    cur = conn.execute("""
        DELETE FROM influencers
        WHERE id NOT IN (
            SELECT MIN(id) FROM influencers GROUP BY instagram_id
        )
    """)
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted


def get_import_stats() -> dict:
    """DB 통계: 전체 수, 카테고리별, 팔로워 0인 미확인 계정"""
    import sqlite3
    conn = sqlite3.connect(db.DB_PATH)
    total = conn.execute("SELECT COUNT(*) FROM influencers").fetchone()[0]
    by_cat = conn.execute(
        "SELECT category, COUNT(*) as cnt FROM influencers GROUP BY category ORDER BY cnt DESC"
    ).fetchall()
    unknown = conn.execute("SELECT COUNT(*) FROM influencers WHERE followers=0").fetchone()[0]
    conn.close()
    return {"total": total, "by_category": [dict(zip(["category", "count"], r)) for r in by_cat], "unknown_followers": unknown}
