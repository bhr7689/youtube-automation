"""나라별 작사 도서관 — 각 언어/지역의 작사 DNA를 박아둔 라이브러리.

쓰는 이유:
- "프랑스어로 써 줘" 한 줄로는 번역체 가사가 나옴.
- 그 나라 작사 전통(모티프·운율·대표 작사가·피해야 할 것)을 LLM 에 주입해야
  진짜 그 나라 사람이 쓴 듯한 가사가 나옴.

저장: nation_prompts.json (사용자가 편집·추가 가능)
"""

from __future__ import annotations

import json
from pathlib import Path

PROMPTS_PATH = Path(__file__).resolve().parent / "nation_prompts.json"


# ────────────────────────────────────────────────────────────────────────────
# 시드 — 12개국 작사 DNA (lyrics_app.py 의 LANGUAGES key 와 일치)
# ────────────────────────────────────────────────────────────────────────────
SEED_NATION_PROMPTS: dict[str, dict] = {
    "한국어": {
        "writer_persona": (
            "한국 5070 트로트·발라드 작사가. 1인칭 회상으로 어머니·고향·세월·"
            "계절의 디테일을 짧고 명료한 한 줄에 담는다. 직접적 감정 표출보다 "
            "풍경 안에 정서를 숨긴다."
        ),
        "motifs": ["어머니", "고향", "봄날", "단풍", "가을바람", "세월", "그 손길", "마당", "툇마루"],
        "rhyme_rules": "짧고 명료한 한 줄(7~10자). 끝말 운(-네, -구나, -다네, -던가요). 4·4조 또는 7·5조 운율 의식.",
        "famous_writers": "정두수, 김순곤, 이순희, 박건호",
        "avoid": "영어 단어 남용, 도시적·세련된 표현, 추상적 감정 단어 직접 사용",
        "sample_line": "엄마 손 잡고 걷던 그 봄날의 마당",
    },
    "영어": {
        "writer_persona": (
            "Modern English pop/folk songwriter. Specific sensory imagery in first person, "
            "urban or seasonal landscapes, restrained emotion that lands in the chorus."
        ),
        "motifs": ["city lights", "midnight", "coffee", "summer rain", "neon", "drive", "ghost", "sky", "back roads"],
        "rhyme_rules": "AABB or ABAB scheme. 9~12 syllables per line. Short punchy hook in the chorus.",
        "famous_writers": "Taylor Swift, Phoebe Bridgers, Bon Iver, Lana Del Rey, Hozier",
        "avoid": "Clichés like 'baby don't go'. Forced rhymes. Overused 'fire/desire' pairs.",
        "sample_line": "Streetlights flicker like a memory in June",
    },
    "일본어": {
        "writer_persona": (
            "J-pop / enka 作詞家。日常風景の細部に深い情緒を込める。"
            "桜・雨・駅・海など季節の具体物を1人称で描く。"
        ),
        "motifs": ["桜", "雨", "駅", "海", "約束", "涙", "月夜", "想い出", "夏の終わり"],
        "rhyme_rules": "5-7-5 音数律の影響。短く整った行。名詞止め多用。漢字とひらがなのバランス。",
        "famous_writers": "阿久悠, 松本隆, 秋元康, 米津玄師, 中島みゆき",
        "avoid": "直接的な感情表現(「悲しい」「寂しい」を直接書く)。漢字の過剰使用。",
        "sample_line": "桜散る駅で君を待っていた",
    },
    "대만식 중국어 (번체)": {
        "writer_persona": (
            "台灣國語流行歌詞作家。都市夜景與詩意情感的結合。"
            "用繁體字書寫,意象細膩,情感含蓄。"
        ),
        "motifs": ["城市", "夜空", "寂寞", "等待", "雨", "燈", "心跳", "記憶", "霓虹"],
        "rhyme_rules": "韻腳統一(-ing, -ong, -ang)。4-4 或 7-7 句式。押韻收尾。",
        "famous_writers": "方文山, 林夕, 姚謙, 黃偉文, 阿信",
        "avoid": "直譯腔。英文單字無謂插入。簡體字。",
        "sample_line": "霓虹燈下我等的人不是你",
    },
    "멕시코식 스페인어": {
        "writer_persona": (
            "Letrista de ranchera y bolero mexicano. Destino, despedida, tequila, "
            "caballo y luna. Emoción directa y dramática en primera persona."
        ),
        "motifs": ["corazón", "tequila", "despedida", "luna", "caballo", "llanto", "destino", "cantina", "borracho"],
        "rhyme_rules": "Octosílabos (8 sílabas). Rima abab o abba. Estribillo emocional fuerte.",
        "famous_writers": "José Alfredo Jiménez, Agustín Lara, Juan Gabriel, Joan Sebastian",
        "avoid": "Anglicismos. Imágenes urbanas modernas. Tono frío.",
        "sample_line": "Con un trago de tequila olvidaré tu adiós",
    },
    "스페인어 (스페인)": {
        "writer_persona": (
            "Letrista español de canción de autor y pop. Lírico, literario, "
            "con imágenes mediterráneas y un punto melancólico."
        ),
        "motifs": ["corazón", "alma", "sueño", "mar", "noche", "luna", "suspiro", "viento", "olvido"],
        "rhyme_rules": "Endecasílabos (11 sílabas) o heptasílabos. Forma poética cuidada.",
        "famous_writers": "Joaquín Sabina, Joan Manuel Serrat, Alejandro Sanz, Rozalén",
        "avoid": "Traducción literal del pop estadounidense. Clichés gastados.",
        "sample_line": "Y nos sobran los motivos para seguir soñando",
    },
    "프랑스어": {
        "writer_persona": (
            "Parolier de chanson française dans la tradition des années 60-80. "
            "Mélancolie poétique, paysages urbains parisiens, première personne intimiste."
        ),
        "motifs": ["pluie", "café", "Paris", "rue", "automne", "métro", "fenêtre", "amour", "trottoir"],
        "rhyme_rules": "Schéma abab ou aabb. Rimes en voyelles (é/è/ou). 8 à 12 syllabes. Le e muet compte.",
        "famous_writers": "Serge Gainsbourg, Jacques Brel, Édith Piaf, Stromae, Françoise Hardy",
        "avoid": "Anglicismes (baby, yeah). Clichés sur la tour Eiffel. Rimes faciles.",
        "sample_line": "Sous le ciel de Paris s'envole une chanson",
    },
    "힌디어 (인도)": {
        "writer_persona": (
            "Bollywood geet lyricist in the ghazal-influenced tradition. "
            "Rain, moonlight, henna, eyes — romance with poetic restraint."
        ),
        "motifs": ["baarish", "chand", "mehndi", "ankhen", "dil", "raat", "ishq", "intezaar", "sapna"],
        "rhyme_rules": "Ghazal-influenced matla/maqta. AABA scheme common. Emotional climax with refrain (radif).",
        "famous_writers": "Gulzar, Javed Akhtar, Irshad Kamil, Amitabh Bhattacharya",
        "avoid": "Direct English translations. Western-style hooks. Forced rhymes.",
        "sample_line": "Tum jo aaye zindagi mein baat ban gayi",
    },
    "베트남어": {
        "writer_persona": (
            "Nhà viết lời nhạc Việt Nam (bolero / V-pop). Nỗi nhớ, quê hương, "
            "mưa Sài Gòn, đêm khuya — tình cảm sâu lắng, trữ tình."
        ),
        "motifs": ["mưa", "quê hương", "nỗi nhớ", "đêm khuya", "gió", "kỷ niệm", "Sài Gòn", "Hà Nội"],
        "rhyme_rules": "Vần cuối chặt chẽ. Câu 6-8 phổ biến. Nhịp trữ tình.",
        "famous_writers": "Trịnh Công Sơn, Trần Tiến, Phú Quang, Đức Trí",
        "avoid": "Tiếng Anh chen vào. Hình ảnh đô thị hiện đại quá mức.",
        "sample_line": "Mưa Sài Gòn nhớ Hà Nội xa xôi",
    },
    "인도네시아어": {
        "writer_persona": (
            "Penulis lirik pop Indonesia (dangdut-pop). Cinta, perpisahan, hujan, "
            "malam sepi — emosi sederhana namun dalam."
        ),
        "motifs": ["hujan", "malam", "hati", "rindu", "cinta", "jalan", "kenangan", "senja"],
        "rhyme_rules": "Rima AABB. Pengulangan refrain yang kuat. 7-9 suku kata per baris.",
        "famous_writers": "Melly Goeslaw, Yovie Widianto, Anggi Pratama, Glenn Fredly",
        "avoid": "Bahasa Inggris berlebihan. Klise lirik pop barat.",
        "sample_line": "Hujan turun di malam yang sepi tanpa kamu",
    },
    "태국어": {
        "writer_persona": (
            "นักแต่งเพลงไทย (ลูกทุ่ง/ป็อป). ความรัก ความคิดถึง บ้านเกิด ฝน — "
            "อารมณ์ที่อ่อนโยน เรียบง่าย แต่ลึกซึ้ง"
        ),
        "motifs": ["ฝน", "ดวงจันทร์", "บ้านนา", "หัวใจ", "รัก", "คิดถึง", "ค่ำคืน"],
        "rhyme_rules": "สัมผัสท้ายวรรค. วรรคสั้นและไหลลื่น. จังหวะนุ่มนวล.",
        "famous_writers": "ภูสิทธิ์ พรหมเจริญ, ปุ๊ อัญชลี, สุรชัย จันทิมาธร",
        "avoid": "ภาษาอังกฤษมากเกินไป. ภาพเมืองสมัยใหม่.",
        "sample_line": "ฝนตกที่หัวใจ คิดถึงเธอจังเลย",
    },
    "포르투갈어 (브라질)": {
        "writer_persona": (
            "Letrista brasileiro de MPB / sertanejo. Saudade, sol, mar, samba — "
            "poesia do cotidiano com musicalidade."
        ),
        "motifs": ["saudade", "sol", "mar", "samba", "coração", "lua", "beijo", "rua", "café"],
        "rhyme_rules": "Redondilha maior (7 sílabas). Rima livre mas musical. Ritmo cantábile.",
        "famous_writers": "Chico Buarque, Caetano Veloso, Tom Jobim, Marília Mendonça",
        "avoid": "Tradução literal do inglês. Clichês americanizados.",
        "sample_line": "Saudade é o que dói no peito quando o sol se vai",
    },
}


# ────────────────────────────────────────────────────────────────────────────
# 저장 / 불러오기
# ────────────────────────────────────────────────────────────────────────────
def load_prompts() -> dict:
    if PROMPTS_PATH.exists():
        try:
            data = json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))
            # 새 언어 시드가 추가되면 자동 보충 (사용자 편집은 보존)
            for key, seed in SEED_NATION_PROMPTS.items():
                data.setdefault(key, seed)
            return data
        except Exception:
            pass
    data = {k: v.copy() for k, v in SEED_NATION_PROMPTS.items()}
    save_prompts(data)
    return data


def save_prompts(data: dict) -> None:
    PROMPTS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_nation(language: str) -> dict:
    return load_prompts().get(language, {})


def upsert_nation(language: str, nation: dict) -> None:
    data = load_prompts()
    data[language] = nation
    save_prompts(data)


# ────────────────────────────────────────────────────────────────────────────
# 페르소나 합치기 — 장르 페르소나 + 나라 작사 DNA
# ────────────────────────────────────────────────────────────────────────────
def build_combined_persona(
    *,
    genre_persona: str,
    language: str,
    extra_genre_label: str = "",
) -> str:
    """장르 페르소나(트로트/발라드 등) + 그 나라 작사 DNA → 합쳐진 작사가 정체성."""
    nation = get_nation(language)
    if not nation:
        return genre_persona

    parts: list[str] = [genre_persona.strip()]

    writer = nation.get("writer_persona", "").strip()
    if writer:
        parts.append(f"\n[그 나라({language}) 작사 정체성 추가 지시]\n{writer}")

    motifs = nation.get("motifs") or []
    if motifs:
        parts.append(
            f"자주 쓰는 모티프(우선 활용, 강제는 아님): {', '.join(motifs)}"
        )

    rhyme = nation.get("rhyme_rules", "").strip()
    if rhyme:
        parts.append(f"운율/형식 규칙: {rhyme}")

    famous = nation.get("famous_writers", "").strip()
    if famous:
        parts.append(f"이 작사가들의 톤을 참고하라(베끼지 말고 톤만): {famous}")

    avoid = nation.get("avoid", "").strip()
    if avoid:
        parts.append(f"피해야 할 것: {avoid}")

    sample = nation.get("sample_line", "").strip()
    if sample:
        parts.append(f"한 줄 샘플 (이 톤/길이/리듬을 참고): {sample}")

    return "\n".join(parts)


if __name__ == "__main__":
    # 자가 점검: 시드 로드 + 12개 언어 모두 데이터 있는지
    data = load_prompts()
    print(f"총 {len(data)}개 나라 로드")
    for k in data:
        print(f"  · {k}: motifs={len(data[k].get('motifs',[]))}")
    print("\n=== 합쳐진 페르소나 예시 (프랑스어) ===")
    print(build_combined_persona(
        genre_persona="당신은 발라드 작사가입니다.",
        language="프랑스어",
    ))
