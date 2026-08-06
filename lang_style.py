"""lang_style.py — 🌐 나라별 제목·설명·태그 작성 관례(현지화 스타일 가이드).

나라마다 유튜브 알고리즘·검색 키워드·제목/설명 관례가 다르다. 이 모듈은
언어별 '작성 규칙 + 사장님이 붙여넣은 실제 예시'를 보관하고, 생성 프롬프트에
주입해 **번역이 아니라 그 나라식 현지화**가 되게 한다.

- 시드(SEED): 코드 안 기본 관례(한국어/일본어/영어).
- 로컬 저장: lang_style.json (gitignore) — 사장님이 예시를 붙여넣으면 이 PC 에 보존.
Streamlit 비의존.
"""
from __future__ import annotations

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
STYLE_PATH = os.path.join(_HERE, "lang_style.json")

LANG_NAMES = {"ko": "한국어", "ja": "일본어", "en": "영어(영어권)"}

# 나라별 기본 관례 (내가 아는 유튜브 관례를 시드로)
SEED: dict[str, dict] = {
    "ko": {
        "title": "감성 카피 + 이모지 + '|' 구분. 검색 키워드(플레이리스트/브이로그/노동요 등)를 "
                 "뒤 칸에 배치. 상황·감정 형용사(잔잔한/설레는/시원한). 특수 굵은글씨체 자주.",
        "desc": "감성 도입 1~2줄 → 듣기 좋은 상황 → (곡 리스트/타임스탬프) → 저작권·문의 → 해시태그. "
                "존댓말 위주, 따뜻한 톤.",
        "tags": "한국어 검색어 위주. 감정어+상황어+장르어 조합. 12~18개.",
        "examples": "",
    },
    "ja": {
        "title": "짧고 감성적. 「playlist |」 접두어 자주. 季節·感情 + ジャンル 조합(예: 夏、桃ジャズ / "
                 "落ち着いた夏に聴きたい). 全角 문자·읽기 쉬운 여백. 이모지 절제. 用途(作業用/勉強用) "
                 "키워드는 태그·설명에 몰아넣음.",
        "desc": "① 감성 詩적 도입 2~4줄(장면·기분을 부드럽게, 존댓말 아닌 서정체 OK) → ② [Tracklist] "
                "타임스탬프 + 곡명(日本語(英訳) 병기) → ③ // MUSIC // VISUALS // SUPPORT // "
                "COLLABORATION 섹션(제작 툴·오리지널 표기·구독 부탁·이메일) → ④ 해시태그 대량(日本語+英語). "
                "정중하지만 브랜드 세계관이 강함.",
        "tags": "해시태그를 아주 많이(20~35개). 日本語(#夏ジャズ #作業用BGM #集中用BGM #勉強用BGM "
                "#カフェ音楽 #癒やし音楽 #歌詞なし音楽) + 英語(#summerjazz #lofi #cafemusic #studymusic "
                "#backgroundmusic) 를 섞어 검색 커버리지를 넓힌다.",
        "examples": """[예시1 · ChillCozy【美メロ Playlist】]
제목: 落ち着いた夏に聴きたい / For a Relaxing Summer
설명: (감성 도입) → 0:00 永遠のFULL MOON / 4:22 MUSIC BOOK … (타임스탬프+곡명) →
곡명은 日本語와 英訳(Eternal Full Moon 등)을 함께 제시.

[예시2 · centralgrocery 중앙식품점]
제목: playlist | 夏、桃ジャズ
설명:
桃の中には、なぜだか / 愛された陽ざしが入っているような気がする
ひとくち頬ばると / なんだか自分まで / 愛されているような気持ちになる。
…こんなにも愛おしい、夏。

[Tracklist]
00:00 Bite Into Summer（ひとくちかじった夏）
02:35 The Sweetest Afternoon（いちばん甘い午後） … (英題（日本語）병기)

// MUSIC  この動画で使用されているすべての音楽は … Suno と Ableton Live で制作。
// VISUALS  イラストと映像はすべてオリジナル。Clip Studio で制作。
// SUPPORT  気に入っていただけたら、チャンネル登録と高評価を。
// COLLABORATION INQUIRIES  hello...@gmail.com

#ジャズ #桃ジャズ #夏ジャズ #カフェジャズ #ボサノヴァ #モーニングジャズ #作業用BGM
#集中用BGM #勉強用BGM #読書用BGM #夏プレイリスト #歌詞なし音楽 #落ち着く音楽 #癒やし音楽
#summerjazz #morningjazz #peachjazz #jazzplaylist #relaxingjazz #cafemusic #studymusic""",
    },
    "en": {
        "title": "Title Case. 'Playlist', '1 Hour', 'Chill/Lofi/Vibes', 'to study/relax/sleep to'. "
                 "이모지 절제. 브랜드/시리즈명 유지.",
        "desc": "짧은 hook 1~2줄 → tracklist/timestamps → follow/subscribe links → hashtags. 간결.",
        "tags": "lowercase keyword phrases (lofi hip hop, chill beats, study music). 12~18개.",
        "examples": "",
    },
}


def _load() -> dict:
    data = {k: dict(v) for k, v in SEED.items()}
    if os.path.exists(STYLE_PATH):
        try:
            saved = json.load(open(STYLE_PATH, encoding="utf-8"))
            for lang, fields in (saved or {}).items():
                if lang in data and isinstance(fields, dict):
                    data[lang].update({k: v for k, v in fields.items() if v})
        except Exception:  # noqa: BLE001
            pass
    return data


def get(lang: str) -> dict:
    return _load().get(lang, {})


def all_styles() -> dict:
    return _load()


def save(lang: str, fields: dict) -> None:
    """사장님이 편집/붙여넣은 값 저장(빈 값은 무시해 시드 유지)."""
    cur = {}
    if os.path.exists(STYLE_PATH):
        try:
            cur = json.load(open(STYLE_PATH, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            cur = {}
    cur.setdefault(lang, {})
    for k, v in fields.items():
        if v and v.strip():
            cur[lang][k] = v.strip()
    json.dump(cur, open(STYLE_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def as_prompt(langs: list[str]) -> str:
    """선택 언어들의 작성 관례 + 사장님 예시를 프롬프트 주입용 텍스트로."""
    st = _load()
    blocks = []
    for lang in langs:
        s = st.get(lang, {})
        if not s:
            continue
        b = [f"[{LANG_NAMES.get(lang, lang)} 작성 관례]"]
        if s.get("title"):
            b.append("· 제목: " + s["title"])
        if s.get("desc"):
            b.append("· 설명란: " + s["desc"])
        if s.get("tags"):
            b.append("· 태그: " + s["tags"])
        if s.get("examples"):
            b.append("· 사장님이 준 실제 예시(이 결을 최대한 따라라):\n" + s["examples"])
        blocks.append("\n".join(b))
    if not blocks:
        return ""
    return ("[나라별 현지화 관례 — 번역 금지, 각 나라식으로 새로 작성]\n"
            + "\n\n".join(blocks))


if __name__ == "__main__":
    STYLE_PATH = os.path.join(os.path.dirname(STYLE_PATH), "_lang_style_selftest.json")
    if os.path.exists(STYLE_PATH):
        os.remove(STYLE_PATH)
    assert "作業用" in get("ja")["title"]
    assert "桃ジャズ" in get("ja")["examples"]        # 사장님 실제 예시 시드 탑재
    save("ja", {"examples": get("ja")["examples"] + "\n【作業用BGM】テスト"})
    assert "テスト" in get("ja")["examples"]
    p = as_prompt(["ko", "ja", "en"])
    assert "일본어" in p and "사장님이 준 실제 예시" in p
    os.remove(STYLE_PATH)
    print("as_prompt 미리보기:\n", p[:200])
    print("self-test OK")
