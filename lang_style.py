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
        "title": "두 형태 공존: (A) 짧고 감성적(예: 夏、桃ジャズ / 落ち着いた夏に聴きたい). "
                 "(B) 프로 채널은 **다단 `|` 구조**: 「Playlist | 감성문구+이모지 | 軽快で心弾むジャズBGM | "
                 "카페 등 상황 | サマージャズ(검색키워드)」— 한국 채널과 같은 골격. 全角·이모지 1~2개.",
        "desc": "프로 구조: ① 📢 저작권·オリジナル 제작·문의 이메일 → ② ✔️ 채널등록·高評価 부탁 → "
                "③ 감성 도입(みずみずしい夏を感じる…) → ④ こんにちは！…です！ 인사 + 이번 테마를 고른 "
                "스토리텔링 → ⑤ 🎧【おすすめプレイリスト】 다른 영상 2~3개 크로스프로모(제목+링크) → "
                "⑥ 🎧【Timeline】 타임스탬프(리피트 재생 안내 포함) → ⑦ 해시태그. "
                "(간소 버전은 감성詩→[Tracklist]→//MUSIC/VISUALS/SUPPORT/COLLAB→해시태그)",
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
#summerjazz #morningjazz #peachjazz #jazzplaylist #relaxingjazz #cafemusic #studymusic

[예시3 · JazzNe(37.5万) — 프로 다단 구조]
제목: Playlist | 爽やかさ弾けるサマージャズ 🍅💕 | 軽快で心弾むジャズBGM | カフェ | サマージャズ
설명:
📢 すべての音源は、私たちが直接作曲・編曲・演奏したオリジナル作品です。
📢 本チャンネル外での無断使用は禁止されています。
📢 お問い合わせ：official@...
✔️ 新しい音楽をもっと楽しみたい方は、チャンネル登録と高評価をお願いします！🔔

みずみずしい夏を感じる Summer Jazz Playlist 🍅🌿
こんにちは！気分Jazzneです！😊💕 (…이번엔 토마토로 여름을 표현한 이유 스토리…)

🎧【おすすめプレイリスト】
   • Playlist | 화창한 여름엔 상큼한 재즈가… (다른 영상 링크)
   • Playlist | 상쾌한 아침 재즈와 함께 ☀️💕 …

🎧【Timeline】
00:00 One Note Samba / 03:03 Greenery / … 56:26 🔄 2回目リピート再生

#SummerJazz #Tomato #JazzPlaylist #CafeJazz #CafeMusic #JazzBGM #SummerMusic #WorkBGM #RelaxingJazz""",
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
