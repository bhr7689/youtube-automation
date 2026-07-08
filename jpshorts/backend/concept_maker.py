"""🎨 플리 컨셉 제조기 — 플레이리스트 채널 분석 → 신규 컨셉 + Suno 패키지.

사용자 제공 'GPT 커스텀 지침 v1.4' 를 앱에 내장. ChatGPT 커스텀 GPT 연결이 아니라
같은 지침을 우리 LLM 경로(Gemini 우선, OPENAI_API_KEY 있으면 GPT 폴백)로 실행한다.

GPT 버전보다 나은 점: 채널 URL 만 넣으면 YouTube Data API 로 제목·조회수·업로드
날짜를 자동 수집(실데이터) — 캡처 업로드 불필요. 썸네일 '시각' 분석은 이미지 미첨부
상태이므로 지침 원칙(근거 기반·추정 표시)에 따라 텍스트 근거 기반 추정으로 표기한다.
키 없으면 데모 리포트(형식 검증용).
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.parse

import translator
import youtube_client as yc

MAX_VIDEOS = 30
_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
THUMBS_DIR = os.path.join(_DATA, "concept_thumbs")
REPORTS_DIR = os.path.join(_DATA, "concept_reports")   # 📂 리포트 영구 저장(모바일↔데스크톱)

# ── 지침 v1.4 (시스템 프롬프트로 내장 — 핵심 전문 유지) ──
SPEC = """너는 "플리컨셉제조기"다. 유튜브 플레이리스트 채널의 제목 리스트·조회수·업로드
흐름(및 가능한 메타데이터)을 분석해 새로운 플레이리스트 채널 컨셉과 Suno 곡 제작
패키지까지 설계하는 전문 컨설턴트다. 답변은 한국어, 실무자가 바로 쓸 수 있게 간결하고
실행 중심으로.

[핵심 원칙]
1. 100% 복제 금지 — 원본 채널명·로고·캐릭터·썸네일 구도·제목을 그대로 따라 하지 않는다.
2. 85% 결 유지 — 타겟층·감정 무드·소비 목적·제목 문형·전체 톤은 원본과 비슷한 계열 유지.
3. 15% 변형 — 컬러 포인트·계절감·시그니처 오브젝트·악기 조합·인물 표현·제목 감정·채널명
   톤 중 1~2개만 새롭게 바꾼다.
4. 근거 기반 — 모든 분석에 어떤 제목·반복 패턴·데이터에서 판단했는지 근거를 붙인다.
   근거 없는 추측 금지.
5. 데이터 부족 시 멈추지 않기 — 조회수 없으면 "조회수 데이터가 없어 조회수 패턴은 확정
   분석이 아니라 제목 반복, 썸네일 반복, 업로드 흐름을 기반으로 한 추정입니다." 표시 후
   추정 진행. 썸네일 이미지가 없으면 시각 분석은 '추정'으로 표기.

[분석 6단계 — 표 형식 사용]
① 채널 아이덴티티: 전체 무드/세계관/타겟/시청 목적/감정 포인트/근거 표.
② 썸네일 스타일: 컬러/인물/구도 + 근거 표 (이미지 없으면 추정 표기).
③ 조회수 패턴: 고조회 공통 키워드·문형, 저조회와의 차이. 데이터 없으면 추정 표기.
④ 썸네일 변화 패턴: 초기/중기/최근/진단 표 (시간순 자료 기반, 없으면 업로드 흐름 추정).
⑤ 제목 키워드: 반복 키워드 Top10/감성 단어/장소·시간대/장르 단어/문형/제목 구조 표.
⑥ 브랜딩 점수: 일관성/차별성/기억용이성/확장성/클릭유도력 각 10점, 총점 50점 + 한줄평.

[다중 채널] 2개 이상이면: 개별 분석→공통 무드→차이점→융합 요소→신규 컨셉.
융합 비율 표시(예: A 60% 제목 문형·타겟 / B 30% 색감 / C 10% 악기·계절감).
메인 기준 채널 1개, 나머지는 보조. 요소를 너무 섞어 컨셉이 흐려지지 않게.

[신규 컨셉 1~2안] 컨셉명 / 한 줄 정의("이 채널은 [타겟]에게 [무드]를 [소재]로 전달") /
무드보드(색감·분위기·레퍼런스 단어 5~7개) / 유지한 85% / 새롭게 비튼 15% / 차별화
포인트 / 왜 이렇게 잡았는지(근거 1~2문장). 원본과 전혀 다른 장르·타겟으로 튀는 것 금지.

[채널 세팅] ①채널이름 2~3안 ②채널핸들 2~3안 + "동일하거나 유사한 핸들이 이미 사용
중일 수 있으니, 유튜브 채널 설정에서 직접 검색해 사용 가능 여부를 확인하세요." 문구
③채널설명문 3~5문장(무드·장르·듣기 좋은 상황) ④채널키워드 10~15개 쉼표 구분
⑤업로드 기본 설정: 고정 제목 템플릿/기본 설명문 템플릿/태그 10~15개/해시태그 3~7개.

[채널 미리보기] 프로필(형태/컬러/상징 오브젝트/분위기/피해야 할 요소), 배너(배경/메인
오브젝트/텍스트 배치/여백/분위기), 썸네일(구도/컬러/인물·오브젝트/텍스트 위치/클릭
포인트). 원본 이미지 편집·복제 금지, 참고만. 필요 시 이미지 생성 프롬프트 제공.

[썸네일 대표안] 콘셉트/선정 이유/구도/컬러 코드/폰트 톤/인물·오브젝트 규칙/텍스트
배치/금지 요소(원본 로고 복제·동일 캐릭터·랜덤 텍스트·과도한 네온·복잡한 배경)/
이미지 생성 프롬프트.

[신규 제목 10개] 표로. 원본 그대로 베끼지 않기. 감성 문장+검색 키워드 조합 우선.
질문형/감탄형/시적 서술형/검색 키워드형 혼합. 과도한 낚시 금지.
필요 시 한국어+일본어+영어 검색 키워드 조합.

[Suno 곡 제작] 가사곡: 곡 컨셉 요약/Suno 스타일 프롬프트/곡 구조/가사/곡 제목 후보
3~5/유튜브 제목 연결 예시. 연주곡: 곡 컨셉 요약/Suno 스타일 프롬프트/Instrumental
Structure/곡 제목 후보 3~5/유튜브 제목 연결 예시.
명시 없으면 채널 성격으로 판단(샹송·팝·엔카·트로트·동요→가사곡 / 클래식·재즈카페·
로파이·수면·명상·작업용→연주곡)하고 "채널 성격상 이번 곡은 [가사곡/연주곡]으로
설계했습니다." 표시. 연주곡 요청에 가사 금지, 가사곡 요청에 연주곡 구조만 제공 금지.
Suno 스타일 프롬프트는 영어: [Main genre], [sub genre], [era/mood], [instruments],
[vocal tone or no vocals], [BPM], [rhythm], [emotion], [ambience], [mixing texture],
[playlist use case].
가사곡 구조: [Intro][Verse 1][Pre-Chorus][Chorus][Verse 2][Bridge][Final Chorus][Outro]
— 감정을 직접 설명하지 말고 장면·이미지로 암시, 후렴은 기억하기 쉽게, 짧은 문장.
연주곡 구조: [Intro][Main Theme][Variation][Bridge][Final Theme][Outro] — 구간마다
악기·분위기·리듬 변화·감정선 짧게.
곡 묶음(10곡/25곡) 요청 시 표(번호/곡 제목/무드/Suno 스타일 요약/썸네일·영상 제목
연결). 25곡 흐름: 1~3 오프닝 / 4~10 몰입 / 11~17 감정 확장 / 18~22 클라이맥스 /
23~25 잔잔한 엔딩.

[최종 출력 순서 — 반드시 이 순서, 마크다운 ## 제목으로 구분]
1.입력 가정 2.채널별 분석 3.채널 아이덴티티 4.썸네일 스타일 분석 5.조회수 패턴 분석
6.썸네일 변화 패턴 분석 7.텍스트 제목 키워드 분석 8.브랜딩 점수 9.신규 컨셉안 1~2개
10.유튜브 채널 세팅 추천 11.채널 미리보기 방향 12.썸네일 대표안 13.신규 제목 샘플 10개
14.Suno AI 아웃풋 15.다음 실행 체크리스트

[금지] 원본 복제 제안/거의 같은 채널명/로고·캐릭터·고유 구도 복제/데이터 없이 확정적
인기 분석/핸들 가용성 단정/원본 제목 단어만 바꾼 유사 제목/원본과 전혀 다른 방향/분석
없이 컨셉만 제시."""


# ── JSON 출력 스키마 (마크다운 대신 구조화 — 화면에서 카드로 렌더) ──
JSON_OUTPUT = """[출력 형식 — 매우 중요]
위 [최종 출력 순서]의 마크다운 지시는 무시한다. 대신 아래 JSON 스키마 **하나만** 출력한다.
설명·인사말·코드펜스(```) 금지. 순수 JSON 객체 하나만. 모든 분석 원칙(85% 유지·15% 변형·
근거 기반·데이터 없으면 '(추정)' 표기)은 그대로 지킨다. 값 안의 텍스트는 한국어를 기본으로
하되, Suno style_prompt·image_prompt·handles·hashtags·keywords·tags 처럼 원어가 자연스러운
것은 원어(영어/스페인어 등) 유지. 빈 값도 키는 반드시 포함(빈 문자열/빈 배열).

{
  "input_assumptions": ["분석 전제·데이터 한계 2~4문장(예: 썸네일 미첨부→시각분석 추정)"],
  "channels": [{
    "name": "채널명",
    "identity": {"mood":"전체 무드","world":"세계관","target":"타겟","purpose":"시청 목적","emotion":"감정 포인트","evidence":"근거(어떤 제목·반복 패턴에서 판단했는지)"},
    "thumbnail": {"color":"컬러 경향","person":"인물 유무","composition":"구도","evidence":"근거","estimated": true},
    "views": "③ 조회수 패턴 — 고조회 공통점, 저조회와의 차이(근거 포함). 데이터 없으면 문장 앞에 '(추정)'",
    "evolution": {"early":"초기","mid":"중기","recent":"최근","diagnosis":"진단 한 줄"},
    "keywords": {"repeated":["반복 키워드 Top"],"emotional":["감성 단어"],"place_time":"장소·시간대 단어","genre":["장르 단어"],"pattern":"문형 패턴","structure":"제목 구조 공식(예: 이모지+감성문장+검색키워드+회차번호)"},
    "branding": {"consistency":9,"differentiation":7,"memorability":8,"scalability":9,"clickability":8,"total":41,"one_liner":"한줄평"}
  }],
  "fusion": "다채널이면 융합 비율(예: A 60% 제목문형 / B 30% 색감 / C 10% 악기). 1채널이면 빈 문자열",
  "concepts": [{
    "name":"컨셉명","definition":"이 채널은 [타겟]에게 [무드]를 [소재]로 전달하는 채널이다",
    "moodboard": {"colors":"색감 5~7개(#hex 있으면 포함)","atmosphere":"분위기 묘사","ref_words":["레퍼런스 단어 5~7개"]},
    "keep_85":["유지한 85% 항목들"],"twist_15":["새롭게 비튼 15% 항목들"],
    "differentiation":["차별화 포인트"],"rationale":"왜 이렇게 잡았는지 1~2문장(근거)"
  }],
  "setup": {
    "names":["채널이름 후보 2~3개"],"handles":["@핸들 후보 2~3개"],
    "handle_note":"동일·유사 핸들이 이미 있을 수 있으니 유튜브에서 직접 검색해 확인하라는 안내",
    "description":"채널 설명문 3~5문장(그대로 복붙용)",
    "keywords":"채널 키워드 10~15개 쉼표 구분(복붙용)",
    "title_template":"고정 제목 템플릿 예시(#01 포함)",
    "desc_template":"기본 영상 설명문 템플릿(복붙용)",
    "tags":"기본 태그 10~15개 쉼표 구분(복붙용)",
    "hashtags":["#해시태그 3~7개"]
  },
  "preview": {
    "profile":{"form":"형태","color":"컬러","objects":"상징 오브젝트","mood":"분위기","avoid":"피해야 할 요소","image_prompt":"신규 채널 **로고/프로필 아이콘** 영어 이미지 프롬프트 — 원형 아이콘용 심플한 심볼, 신규 컨셉의 시그니처 오브젝트 반영, 레퍼런스 복제 금지, 깔끔한 배경, 정사각형"},
    "banner":{"background":"배경","object":"메인 오브젝트","text":"텍스트 배치","margin":"여백","mood":"분위기","image_prompt":"신규 채널 **배너(채널아트)** 영어 이미지 프롬프트 — 와이드 파노라마 구도, 가운데에 채널명 얹을 여백, 신규 컨셉 무드·색감, 레퍼런스 복제 금지, 사람 없음"},
    "thumbnail":{"composition":"구도","color":"컬러 비율","object_rule":"인물·오브젝트 규칙","text":"텍스트 위치","click_point":"클릭 포인트"}
  },
  "hero_thumbnail": {
    "concept":"대표 썸네일 콘셉트","reason":"선정 이유",
    "composition":"구도","color_codes":"컬러 코드(#hex 포함)","font":"폰트 톤",
    "object_rule":"인물·오브젝트 규칙","text_placement":"텍스트 배치","forbidden":"금지 요소",
    "image_prompt":"신규 채널의 **새 대표 썸네일 1장**을 그리는 영어 서술형 프롬프트. 인기 썸네일의 무드·색감 계열·구도 '느낌'만 85% 참고하고, 주인공 오브젝트·장면은 신규 컨셉(concepts)의 15% 시그니처 변형으로 **교체**해 레퍼런스 어느 것과도 구별되는 완전히 새로운 장면을 묘사. 특정 레퍼런스 복제·모사 금지. **프로 사진 수준으로 구체적으로**: 전경/중경/배경 배치, 광원과 시간대(예: warm golden-hour sunlight through leaves), 렌즈 느낌(shallow depth of field, 35mm), 질감, 컬러 팔레트(#hex), 'cinematic professional photography, photorealistic, ultra-detailed' 류 화질 묘사를 반드시 포함. --ar 등 파라미터는 붙이지 마라(시스템 자동 추가)"
  },
  "title_sets": [{
    "title":"영상 제목(신규 채널 문형, 원본 복제 금지)",
    "thumb_text":"썸네일 이미지 위에 얹을 한글 문구 — 제목의 핵심을 1~2줄로 짧게(줄바꿈은 \\n). 유튜브 썸네일 텍스트처럼 간결하게",
    "image_prompt":"이 제목의 장면을 그리는 영어 프롬프트 — 제목이 말하는 계절·시간대·장소·상황이 이미지에 그대로 보여야 한다(제목과 이미지가 한 세트). 무드·색감은 벤치마킹 85% 유지+신규 시그니처 15%. 전경/중경/배경, 광원·시간대, 렌즈 느낌, #hex 팔레트, cinematic professional photography 포함. 문구가 들어갈 여백 위치 명시. 레퍼런스 복제 금지"
  }],
  "suno": {
    "song_type":"instrumental 또는 lyric",
    "type_reason":"'채널 성격상 이번 곡은 [연주곡/가사곡]으로 설계했습니다' + 이유",
    "concept":"곡 컨셉 요약 1~2문장",
    "style_prompt":"Suno 스타일 프롬프트(영어, 복붙용)",
    "structure":[{"section":"[Intro]","desc":"구간 악기·분위기·감정선"}],
    "lyrics":"가사곡이면 [Verse 1]/[Chorus] 등 구조 가사, 연주곡이면 빈 문자열",
    "title_candidates":["곡 제목 후보 3~5개"],
    "yt_title_example":"유튜브 제목 연결 예시",
    "song_pack":[]
  },
  "checklist": ["다음 실행 체크리스트 4~6개(실행 동사로)"]
}

곡 수가 2개 이상이면 suno.song_pack 을 그 개수만큼 채운다(각 {"no":1,"title":"곡 제목","mood":"무드","style":"Suno 스타일 요약","link":"연결할 썸네일·영상 제목"}), 이때 structure/lyrics 는 대표 1곡 기준으로만 채운다. 곡 수가 1이면 song_pack=[] 로 둔다.

title_sets 는 반드시 10개. 제목과 썸네일이 **한 세트**다 — 시청자가 썸네일만 봐도 제목이
읽히고, 제목만 봐도 썸네일 장면이 그려져야 한다. 10세트는 계절·시간대·상황(아침/저녁/
비/눈/카페/산책 등)을 다양하게 분산시키되 채널 무드는 하나로 통일한다."""


# ── LLM 디스패처: Gemini 우선 → OpenAI(키 있으면) ──────

def _openai(prompt: str, json_mode: bool = False) -> str | None:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key)
        kwargs = dict(model="gpt-4o",
                      messages=[{"role": "user", "content": prompt}],
                      temperature=0.7)
        if json_mode:                       # 유효한 JSON 강제 (파싱 실패 방지)
            kwargs["response_format"] = {"type": "json_object"}
            kwargs["max_tokens"] = 8000     # 리포트 길어도 잘리지 않게
        r = client.chat.completions.create(**kwargs)
        return (r.choices[0].message.content or "").strip()
    except Exception:
        return None


def _llm(prompt: str, json_mode: bool = False) -> str | None:
    # 플리 컨셉 작업은 GPT(OpenAI) 우선 — 사용자가 GPT 연결. 없으면 Gemini 폴백.
    out = _openai(prompt, json_mode=json_mode)
    if out:
        return out
    return translator._gemini(prompt, temperature=0.7, json_mode=json_mode)


# ── 👁 GPT Vision: 인기 썸네일을 '직접 보고' 벤치마킹 ────
VISION_PROMPT = """너는 유튜브 썸네일 디자인 분석가다. 아래는 한 채널의 '인기 상위' 썸네일들이다
(조회수 순). 이미지들을 실제로 보고, 이 채널의 성공한 썸네일들이 공유하는 시각 공식을
한국어로 간결하게 정리하라. 추측하지 말고 실제로 보이는 것만. 항목:
1. 공통 컬러 팔레트 — 지배 색 3~5개(가능하면 #hex 근사값)와 명도·채도 경향
2. 구도 — 클로즈업/와이드, 주 피사체 위치, 심도, 여백
3. 반복 오브젝트·소재 — 실제로 보이는 사물/배경/상징
4. 인물·얼굴 — 유무, 표정·감정, 크기
5. 텍스트 오버레이 — 유무, 위치, 폰트 톤, 크기, 색(없으면 '없음')
6. 전체 무드 — 한 줄
7. 벤치마킹 요약 — "이 채널 썸네일이 먹히는 이유" 2~3줄, 그리고 신규 채널이 지켜야 할
   85% 요소와 바꿔볼 15% 요소를 각각 콕 집어서.
표 없이 '- ' 불릿으로만. 간결하게."""


def analyze_thumbnails_vision(thumb_urls: list[str],
                              titles: list[str] | None = None) -> str | None:
    """OpenAI GPT-4o Vision 으로 실제 썸네일 이미지를 보고 공통 시각 패턴 추출.
    키 없거나 http 이미지 없으면 None(→ 텍스트 추정 경로로 폴백)."""
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return None
    urls = [u for u in (thumb_urls or []) if _is_image_ref(u)][:9]
    if not urls:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key)
        content: list = [{"type": "text", "text": VISION_PROMPT}]
        for idx, u in enumerate(urls):
            if titles and idx < len(titles):
                content.append({"type": "text", "text": f"#{idx + 1} 제목: {titles[idx]}"})
            content.append({"type": "image_url",
                            "image_url": {"url": u, "detail": "low"}})
        r = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": content}],
            temperature=0.4, max_tokens=900)
        return (r.choices[0].message.content or "").strip() or None
    except Exception:
        return None


def _engine_name() -> str:
    if os.environ.get("OPENAI_API_KEY", "").strip():
        return "openai"
    if translator.has_gemini():
        return "gemini"
    return "demo"


def llm_status() -> dict:
    return {"gemini": translator.has_gemini(),
            "openai": bool(os.environ.get("OPENAI_API_KEY", "").strip())}


# ── 미드저니 프롬프트 / 이미지 프롬프트 정리 ────────────
def _is_image_ref(u: str) -> bool:
    """Vision 이 볼 수 있는 이미지 참조인가 — http(s) URL 또는 base64 data(png/jpeg/webp/gif)."""
    return isinstance(u, str) and (
        u.startswith("http") or bool(re.match(r"data:image/(png|jpe?g|webp|gif)", u, re.I)))


def _clean_img_prompt(p: str) -> str:
    """미드저니 파라미터(--ar 16:9 --v 6 …)를 제거한 순수 서술형 프롬프트."""
    p = (p or "").strip()
    i = p.find(" --")               # MJ 파라미터는 항상 ' --' 로 시작하는 후행 블록
    if i != -1:
        p = p[:i]
    return p.strip()


def _midjourney(prompt: str) -> str:
    """서술형 프롬프트 → 미드저니용(16:9, v6, style raw) 프롬프트."""
    p = _clean_img_prompt(prompt)
    p = re.sub(r"[,;]?\s*\d{1,2}:\d{1,2}\s*$", "", p).strip().rstrip(" .,")  # 후행 비율 제거
    if not p:
        return ""
    return f"{p} --ar 16:9 --style raw --v 6"


def _overlay_prompt(scene: str, text: str) -> str:
    """장면 프롬프트 + 한글 문구 오버레이 지시 → GPT 이미지용 풀 프롬프트."""
    base = _clean_img_prompt(scene)
    t = (text or "").strip().replace('"', "'")
    if not t:
        return base
    return (base +
            f' Overlay the exact Korean text "{t}" on the image — elegant thin white '
            "font with a subtle soft shadow, small-to-medium size, placed in the "
            "natural empty area of the composition, tasteful like a premium music "
            "playlist thumbnail. Render the Korean characters accurately, exactly as written.")


# ── 데모 썸네일(그라디언트 SVG data URI) ────────────────
_DEMO_THUMB_COLORS = [
    ("#1F3D2B", "#E0A458"), ("#2b2d42", "#8d99ae"), ("#3a0ca3", "#f72585"),
    ("#264653", "#2a9d8f"), ("#6a040f", "#e85d04"), ("#03045e", "#48cae4"),
    ("#432818", "#bb9457"), ("#354f52", "#84a98c"), ("#4a4e69", "#c9ada7"),
]


def _demo_thumb(i: int) -> str:
    c1, c2 = _DEMO_THUMB_COLORS[i % len(_DEMO_THUMB_COLORS)]
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="480" height="270">'
        f'<defs><linearGradient id="g{i}" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/>'
        f'</linearGradient></defs><rect width="480" height="270" fill="url(#g{i})"/>'
        f'<circle cx="240" cy="118" r="46" fill="#ffffff" opacity="0.16"/>'
        f'<text x="240" y="136" font-family="sans-serif" font-size="46" fill="#ffffff" '
        f'opacity="0.92" font-weight="bold" text-anchor="middle">#{i + 1}</text>'
        f'<text x="240" y="230" font-family="sans-serif" font-size="20" fill="#ffffff" '
        f'opacity="0.6" text-anchor="middle">DEMO THUMB</text></svg>'
    )
    return "data:image/svg+xml;utf8," + urllib.parse.quote(svg)


# ── 🖼️ GPT 썸네일 이미지 생성 (미리보기, 최고 화질) ─────
# 화질 보정 지시 — 사진·일러스트 공용 (저품질 원인이던 기본 등급을 최고 등급으로)
_QUALITY_SUFFIX = (
    " Masterpiece quality, ultra-detailed, tack-sharp focus, rich professional "
    "color grading, beautiful natural lighting, high dynamic range, no noise, "
    "no artifacts, no blur, magazine-grade finish.")

# 레퍼런스 무드 이식 지시 — 모델이 레퍼런스 이미지를 '직접 보며' 그릴 때 사용
_MOOD_TRANSFER = (
    "Look carefully at the attached reference thumbnail images. Absorb their EXACT "
    "mood, emotional atmosphere, color grading, lighting, film texture, level of "
    "realism and overall sensibility — the new image must feel like it belongs to "
    "the very same channel (85% same emotional tone). But do NOT copy any "
    "reference's composition, objects or scene — create a completely NEW scene "
    "(15% twist) as described: ")


def _ref_to_file(ref: str, idx: int):
    """data URL/http URL → (파일명, BytesIO, mime). 래스터 이미지가 아니면 None."""
    import io
    data, mime = None, "image/png"
    if ref.startswith("data:image/"):
        m = re.match(r"data:(image/(?:png|jpe?g|webp));base64,(.+)", ref, re.S | re.I)
        if m:
            mime = m.group(1).lower().replace("image/jpg", "image/jpeg")
            try:
                data = base64.b64decode(m.group(2))
            except Exception:
                data = None
    elif ref.startswith("http"):
        try:
            import urllib.request
            req = urllib.request.Request(ref, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()
            mime = "image/jpeg"
        except Exception:
            data = None
    if not data:
        return None
    ext = "png" if "png" in mime else ("webp" if "webp" in mime else "jpg")
    return (f"ref{idx}.{ext}", io.BytesIO(data), mime)


def generate_thumbnail_image(prompt: str, size: str = "1536x1024",
                             refs: list[str] | None = None) -> dict:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return {"ok": False, "error": "OpenAI(GPT) 키가 필요해요. 설정 → 🔑 연결키 저장에서 OpenAI 키를 넣어주세요. "
                "(미드저니를 쓰신다면 아래 미드저니 프롬프트를 복사해 붙여넣으세요.)"}
    scene = _clean_img_prompt(prompt)
    if not scene:
        return {"ok": False, "error": "이미지 프롬프트가 비어 있어요."}

    # 레퍼런스 이미지 준비 (ChatGPT 앱처럼 — 모델이 무드를 '직접 보고' 그린다)
    files = []
    for i, ref in enumerate((refs or [])[:8]):
        f = _ref_to_file(ref, i)
        if f:
            files.append(f)

    try:
        from openai import OpenAI
        client = OpenAI(api_key=key)
        b64, model, qual = None, "", ""
        refs_used = 0

        if files:   # 1) 🎯 레퍼런스 무드 반영 생성 (images.edit — 참조 이미지 직접 투입)
            p_edit = _MOOD_TRANSFER + scene + _QUALITY_SUFFIX
            for kwargs in (dict(quality="high"), dict()):   # 구 SDK/미지원 대비 재시도
                try:
                    r = client.images.edit(model="gpt-image-1", image=files,
                                           prompt=p_edit, size=size, n=1, **kwargs)
                    b64 = r.data[0].b64_json
                    model, qual = "gpt-image-1", kwargs.get("quality", "auto")
                    refs_used = len(files)
                    break
                except Exception:
                    for _, bio, _m in files:                 # 재시도 전 파일 포인터 리셋
                        bio.seek(0)

        if not b64:  # 2) 레퍼런스 없음/실패 → 텍스트 생성 (gpt-image-1 high)
            p_gen = ("Create an original, brand-new YouTube thumbnail. Use the following "
                     "as style inspiration only — do NOT copy or reproduce any existing/"
                     "reference thumbnail; invent a fresh scene. " + scene + _QUALITY_SUFFIX)
            try:
                r = client.images.generate(model="gpt-image-1", prompt=p_gen, size=size,
                                           n=1, quality="high")
                b64, model, qual = r.data[0].b64_json, "gpt-image-1", "high"
            except Exception:      # 3) dall-e-3 폴백 — quality=hd + vivid
                ds = "1792x1024" if size.startswith("1536") else "1024x1024"
                r = client.images.generate(model="dall-e-3", prompt=p_gen, size=ds, n=1,
                                           quality="hd", style="vivid",
                                           response_format="b64_json")
                b64, model, qual = r.data[0].b64_json, "dall-e-3", "hd"

        if not b64:
            return {"ok": False, "error": "이미지 생성 응답이 비어 있어요."}
        os.makedirs(THUMBS_DIR, exist_ok=True)
        name = f"thumb_{int(time.time())}.png"
        with open(os.path.join(THUMBS_DIR, name), "wb") as f:
            f.write(base64.b64decode(b64))
        return {"ok": True, "data_url": "data:image/png;base64," + b64,
                "file": name, "model": model, "quality": qual,
                "refs_used": refs_used}
    except Exception as e:
        return {"ok": False, "error": f"이미지 생성 실패: {e}"}


# ── 채널 데이터 자동 수집 (URL 만 넣으면 실데이터) ──────

def _extract_channel_ref(url: str) -> tuple[str, str]:
    """URL → ('id'|'handle'|'search', 값)"""
    u = url.strip()
    m = re.search(r"youtube\.com/channel/(UC[\w-]+)", u)
    if m:
        return "id", m.group(1)
    m = re.search(r"youtube\.com/(@[\w.\-가-힣]+)", u)
    if m:
        return "handle", m.group(1)
    if u.startswith("UC") and len(u) >= 20:
        return "id", u
    if u.startswith("@"):
        return "handle", u
    return "search", u


def collect_channel(url: str, max_videos: int = MAX_VIDEOS) -> dict:
    """채널 URL/핸들 → 채널 정보 + 최근 영상(제목·조회수·날짜). 실데이터."""
    if not yc.has_key():
        return _demo_channel(url)
    try:
        yt = yc._yt()
        kind, val = _extract_channel_ref(url)
        params = dict(part="snippet,statistics,contentDetails", maxResults=1)
        if kind == "id":
            params["id"] = val
        elif kind == "handle":
            params["forHandle"] = val
        else:
            s = yt.search().list(part="id", q=val, type="channel",
                                 maxResults=1).execute()
            items = s.get("items", [])
            if not items:
                return {"error": f"채널을 찾지 못했어요: {url}"}
            params["id"] = items[0]["id"]["channelId"]
        resp = yt.channels().list(**params).execute()
        items = resp.get("items", [])
        if not items:
            return {"error": f"채널을 찾지 못했어요: {url}"}
        ch = items[0]
        uploads = ch.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
        videos = []
        if uploads:
            pl = yt.playlistItems().list(part="contentDetails", playlistId=uploads,
                                         maxResults=min(50, max_videos)).execute()
            ids = [i["contentDetails"]["videoId"] for i in pl.get("items", [])][:max_videos]
            if ids:
                vr = yt.videos().list(part="snippet,statistics",
                                      id=",".join(ids)).execute()
                for v in vr.get("items", []):
                    sn, st = v["snippet"], v.get("statistics", {})
                    th = sn.get("thumbnails", {})
                    thumb = ""
                    for q in ("maxres", "standard", "high", "medium", "default"):
                        if th.get(q, {}).get("url"):
                            thumb = th[q]["url"]
                            break
                    videos.append({
                        "title": sn["title"],
                        "views": int(st.get("viewCount", 0)),
                        "published": sn["publishedAt"][:10],
                        "thumb": thumb,
                        "video_id": v.get("id", ""),
                    })
        st = ch.get("statistics", {})
        return {
            "url": url,
            "title": ch["snippet"]["title"],
            "description": ch["snippet"].get("description", "")[:500],
            "subscribers": int(st.get("subscriberCount", 0) or 0),
            "video_count": int(st.get("videoCount", 0) or 0),
            "videos": videos,
            "demo": False,
        }
    except Exception as e:
        return {"error": f"수집 실패({url}): {e}"}


def _demo_channel(url: str) -> dict:
    titles = [
        ("비 오는 새벽, 창가에서 듣는 재즈 피아노 ☔", 1_240_000, "2026-06-28"),
        ("퇴근길 버스에서 | 마음이 풀리는 로파이 재즈", 890_000, "2026-06-21"),
        ("새벽 2시의 카페 | 아무도 없는 조용한 재즈", 2_100_000, "2026-06-14"),
        ("공부할 때 듣는 잔잔한 피아노 3시간", 760_000, "2026-06-07"),
        ("일요일 아침, 커피와 보사노바 ☕", 1_530_000, "2026-05-31"),
        ("잠들기 전 30분 | 느린 재즈 발라드", 680_000, "2026-05-24"),
        ("창밖에 눈이 내리면 | 겨울밤 재즈", 3_400_000, "2026-01-18"),
        ("혼자 있는 밤, 위스키 한 잔과 재즈", 1_020_000, "2026-05-10"),
        ("가을비 내리는 오후, 카페 창가 재즈 🍂", 1_180_000, "2026-04-19"),
    ]
    return {
        "url": url or "(데모 채널)",
        "title": "새벽카페 재즈 (데모)",
        "description": "새벽 감성 재즈·로파이 플레이리스트 채널 (데모 데이터)",
        "subscribers": 87_000, "video_count": 142,
        "videos": [{"title": t, "views": v, "published": d,
                    "thumb": _demo_thumb(i), "video_id": ""}
                   for i, (t, v, d) in enumerate(titles)],
        "demo": True,
    }


# ── JSON 파싱 (LLM 출력 방어적 파싱) ────────────────────

def _parse_json(text: str) -> dict | None:
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):                       # 코드펜스 제거
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    i, j = t.find("{"), t.rfind("}")              # 첫 { ~ 마지막 }
    if i == -1:
        return None
    frag = t[i:j + 1] if j > i else t[i:]
    # 여러 방어 시도: 원문 → 후행 콤마 제거 → 중괄호 균형 복구(잘림 대비)
    for cand in (frag, _strip_trailing_commas(frag), _balance_braces(frag)):
        if not cand:
            continue
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    return None


def _strip_trailing_commas(s: str) -> str:
    return re.sub(r",(\s*[}\]])", r"\1", s)


def _balance_braces(s: str) -> str:
    """잘린 JSON 대비 — 열린 문자열/괄호를 닫아 파싱 가능성을 높인다."""
    s = _strip_trailing_commas(s.rstrip().rstrip(","))
    # 문자열이 열린 채 끝났으면 닫기 (이스케이프 아닌 " 개수 홀수)
    if len(re.findall(r'(?<!\\)"', s)) % 2 == 1:
        s += '"'
    opens = s.count("{") - s.count("}")
    closes = s.count("[") - s.count("]")
    s += "]" * max(0, closes) + "}" * max(0, opens)
    return _strip_trailing_commas(s)


# ── 리포트 생성 ─────────────────────────────────────────

def generate_report(channel_urls: list[str], song_type: str = "auto",
                    num_songs: int = 1, extra_notes: str = "",
                    images: list[str] | None = None, titles_text: str = "") -> dict:
    images = [i for i in (images or []) if _is_image_ref(i)][:9]
    titles_list = [t.strip() for t in (titles_text or "").splitlines() if t.strip()][:20]

    collected = [collect_channel(u) for u in channel_urls if u.strip()]
    channels = [c for c in collected if not c.get("error")]
    errs = [c["error"] for c in collected if c.get("error")]
    if not channels and not images and not titles_list:
        return {"error": " / ".join(errs) or "채널 URL·썸네일 캡처·제목 중 하나는 넣어주세요."}

    # 🖼️ 벤치마킹 썸네일 결정 — 업로드 캡처가 있으면 그것을(사용자 선별=정밀), 없으면 인기순 9개
    used_images = bool(images)
    if used_images:
        thumbnails = [{"rank": k + 1,
                       "title": (titles_list[k] if k < len(titles_list) else ""),
                       "views": 0, "published": "", "thumb": img, "video_id": ""}
                      for k, img in enumerate(images)]
    else:
        main = channels[0] if channels else {}
        tops = sorted(main.get("videos", []), key=lambda v: v.get("views", 0),
                      reverse=True)[:9]
        thumbnails = [{"rank": i + 1, "title": v.get("title", ""),
                       "views": v.get("views", 0), "published": v.get("published", ""),
                       "thumb": v.get("thumb", ""), "video_id": v.get("video_id", "")}
                      for i, v in enumerate(tops)]

    # 👁 GPT Vision 실측: 썸네일 이미지를 실제로 '보고' 공통 시각 패턴 추출
    vision = analyze_thumbnails_vision(
        [t["thumb"] for t in thumbnails], [t["title"] for t in thumbnails])

    data_block = ""
    for i, c in enumerate(channels, 1):
        vids = "\n".join(
            f"  - [{v['published']}] {v['title']} — 조회수 {v['views']:,}"
            for v in c["videos"])
        data_block += (
            f"\n[채널 {i}] {c['title']} (구독자 {c['subscribers']:,} · "
            f"총 영상 {c['video_count']}개)\n채널 설명: {c['description']}\n"
            f"최근 영상 {len(c['videos'])}개 (제목·조회수·날짜 = 실데이터):\n{vids}\n")
    if titles_list:
        data_block += ("\n[인기 상승 제목 — 사용자가 직접 선별해 붙여넣음(핵심 근거)]\n"
                       + "\n".join(f"  - {t}" for t in titles_list) + "\n")
    if not data_block.strip():
        data_block = "(채널 데이터 없음 — 첨부된 썸네일 이미지 실측 분석을 근거로 설계)"

    song_line = {"lyric": "가사곡으로 제작", "instrumental": "연주곡으로 제작",
                 "auto": "채널 성격에 따라 가사곡/연주곡 자동 판단"}.get(song_type, "자동 판단")
    songs_line = (f"곡 묶음 {num_songs}곡을 suno.song_pack 에 {num_songs}개 채워라."
                  if num_songs > 1 else "곡 1곡 패키지(structure/가사)를 제공하라.")

    if vision:      # 실측 시각 분석이 있으면 근거로 주입 (추정 아님)
        src = "사용자가 캡처해 올린 인기 썸네일" if used_images else "인기 상위 9개 썸네일"
        thumb_note = (
            f"\n[👁 썸네일 실측 시각 분석 — GPT Vision 이 {src} 이미지를 직접 보고 추출]\n"
            + vision +
            "\n위 시각 분석은 이미지를 실제로 본 결과다. thumbnail(②)·썸네일 대표안·image_prompt 를"
            " 이 실측 근거로 작성하고, thumbnail.estimated=false 로 둔다."
            "\n★가장 중요★ image_prompt 는 레퍼런스 썸네일을 '똑같이' 그리는 게 절대 아니다."
            " 공통 무드·색감 계열·구도 '느낌'만 85% 참고하고, 주인공 오브젝트·장면은 신규"
            " 컨셉안(concepts)의 15% 시그니처 변형(새 상징 오브젝트·새 컬러 포인트)으로 **교체**해서,"
            " 어떤 레퍼런스와도 확실히 구별되는 **완전히 새로운 썸네일 한 장면**을 묘사하라."
            " 특정 레퍼런스의 구도·오브젝트를 그대로 복제하면 실패다.")
    else:
        thumb_note = ("\n[주의] 썸네일 이미지 미첨부 — thumbnail.estimated=true 로 두고 시각/조회"
                      " 근거는 제목·업로드 흐름 기반 추정으로 표기."
                      "\nimage_prompt 는 레퍼런스 복제가 아니라 신규 컨셉안의 시그니처 변형을"
                      " 주인공으로 한 새로운 썸네일 장면을 묘사하라.")
    if titles_list:
        thumb_note += ("\n[제목 근거] 위 '인기 상승 제목'의 반복 키워드·문형·감정 훅을 keywords·"
                       "titles·concepts 설계의 최우선 근거로 삼아라.")

    prompt = (
        SPEC + "\n\n" + JSON_OUTPUT +
        "\n\n[입력 데이터 — YouTube API 실측]\n" + data_block +
        ("\n[사용자 추가 메모]\n" + extra_notes + "\n" if extra_notes.strip() else "") +
        f"\n[곡 유형] {song_line}\n[곡 수] {songs_line}\n" +
        thumb_note +
        "\n위 JSON 스키마 하나만 순수 JSON으로 출력하라."
    )
    out = _llm(prompt, json_mode=True)
    engine = _engine_name()

    result = _parse_json(out) if out else None
    markdown = None
    if result is None:
        if out:                    # LLM은 응답했지만 JSON 파싱 실패 → 원문 마크다운 폴백
            markdown = out
        else:                      # LLM 키 없음 → 구조화 데모(화면 전체 컴포넌트 시연)
            base = channels[0] if channels else {"title": "캡처 분석", "subscribers": 0,
                                                 "video_count": 0, "videos": []}
            result = _demo_result(base)
            engine = "demo"

    if isinstance(result, dict):
        # 미드저니 프롬프트 자동 생성(LLM 형식 의존 제거)
        ht = result.get("hero_thumbnail")
        if isinstance(ht, dict) and ht.get("image_prompt"):
            ht["midjourney_prompt"] = _midjourney(ht["image_prompt"])
        # 🎬 썸네일+제목 세트: 세트별 풀 프롬프트(문구 오버레이) + 미드저니 프롬프트
        ts = result.get("title_sets")
        if isinstance(ts, list):
            for s in ts:
                if isinstance(s, dict) and s.get("image_prompt"):
                    s["full_image_prompt"] = _overlay_prompt(
                        s["image_prompt"], s.get("thumb_text", ""))
                    s["midjourney_prompt"] = _midjourney(s["image_prompt"])
            if not result.get("titles"):     # 전체복사·구버전 호환용 제목 리스트 파생
                result["titles"] = [s.get("title", "") for s in ts
                                    if isinstance(s, dict) and s.get("title")]
        # 실측 분석을 썼으면 estimated=false 확정
        if vision:
            for ch in result.get("channels", []):
                if isinstance(ch.get("thumbnail"), dict):
                    ch["thumbnail"]["estimated"] = False

    return {
        "result": result,          # 구조화 객체(성공 시) — 프론트가 카드로 렌더
        "markdown": markdown,      # 파싱 실패 시 원문(프론트가 마크다운 폴백 렌더)
        "thumbnails": thumbnails,  # 벤치마킹 그리드(업로드 캡처 또는 인기순 9개)
        "vision": vision,          # 👁 GPT Vision 실측 분석 텍스트(없으면 None)
        "thumb_source": ("upload" if used_images else
                         "youtube" if channels else "none"),
        "channels": [{"title": c["title"], "subscribers": c["subscribers"],
                      "videos": len(c["videos"]), "demo": c.get("demo", False)}
                     for c in channels],
        "engine": engine,
    }


# ── 📂 리포트 영구 저장 (모바일에서 만들고 집 데스크톱에서 검수) ──

def save_report(resp: dict, channel_urls: list[str]) -> str:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    rid = f"cr_{int(time.time() * 1000)}"
    res = resp.get("result") or {}
    title = ""
    if res.get("concepts"):
        title = (res["concepts"][0] or {}).get("name", "")
    if not title and resp.get("channels"):
        title = resp["channels"][0].get("title", "")
    rec = {
        "id": rid, "created": int(time.time()), "title": title or "컨셉 리포트",
        "channels": resp.get("channels", []), "engine": resp.get("engine", ""),
        "thumb_source": resp.get("thumb_source", ""), "inputs": channel_urls,
        "response": resp,
    }
    tmp = os.path.join(REPORTS_DIR, rid + ".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False)
    os.replace(tmp, os.path.join(REPORTS_DIR, rid + ".json"))
    return rid


def list_reports(limit: int = 40) -> list[dict]:
    if not os.path.isdir(REPORTS_DIR):
        return []
    out = []
    for fn in os.listdir(REPORTS_DIR):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(REPORTS_DIR, fn), encoding="utf-8") as f:
                r = json.load(f)
            out.append({"id": r["id"], "created": r.get("created", 0),
                        "title": r.get("title", ""), "channels": r.get("channels", []),
                        "engine": r.get("engine", ""),
                        "thumb_source": r.get("thumb_source", "")})
        except Exception:
            continue
    out.sort(key=lambda x: x.get("created", 0), reverse=True)
    return out[:limit]


def load_report(rid: str) -> dict | None:
    if any(c in rid for c in ("/", "\\", "..")):
        return None
    p = os.path.join(REPORTS_DIR, rid + ".json")
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def delete_report(rid: str) -> bool:
    if any(c in rid for c in ("/", "\\", "..")):
        return False
    p = os.path.join(REPORTS_DIR, rid + ".json")
    if os.path.isfile(p):
        os.remove(p)
        return True
    return False


def _demo_result(ch: dict) -> dict:
    """키 없을 때 보여줄 구조화 데모 — 모든 화면 컴포넌트를 채운다."""
    return {
        "input_assumptions": [
            f"분석 대상: {ch['title']} (구독자 {ch['subscribers']:,}, 최근 영상 {len(ch['videos'])}개 실데이터).",
            "썸네일 이미지 미첨부 → 썸네일 시각 분석은 제목·업로드 흐름 기반 (추정)입니다.",
            "이 리포트는 데모입니다 — 설정에서 Gemini 키를 넣으면 실제 분석이 나옵니다.",
        ],
        "channels": [{
            "name": ch["title"],
            "identity": {
                "mood": "새벽·비·카페의 고요한 위로", "world": "혼자 있는 시간의 안식처",
                "target": "20~40대, 심야·출퇴근·작업 BGM 수요층", "purpose": "수면 유도·집중·감정 정리",
                "emotion": "외로움을 부정하지 않고 감싸줌",
                "evidence": "제목 8개 중 6개가 시간대(새벽·밤)+장소(카페·창가) 조합",
            },
            "thumbnail": {"color": "앰버·딥블루 야간 톤", "person": "인물 없음(창가·불빛 오브젝트)",
                          "composition": "중앙 오브젝트 + 흐린 배경", "evidence": "제목의 장면 묘사 반복",
                          "estimated": True},
            "views": "(추정) 고조회 공통은 계절·날씨 키워드(겨울밤 340만, 새벽 2시 210만) — 시기성 훅. "
                     "기능성 제목(공부용 76만)보다 장면 묘사형이 평균 1.8배.",
            "evolution": {"early": "단순 BGM 제목", "mid": "시간대+장소 공식 정착",
                          "recent": "계절·날씨 훅 강화", "diagnosis": "장면 묘사형으로 정체성 수렴 중"},
            "keywords": {"repeated": ["새벽", "카페", "재즈", "로파이", "창가", "밤"],
                         "emotional": ["혼자", "위로", "고요", "잠들기 전"],
                         "place_time": "새벽·밤 / 카페·창가",
                         "genre": ["재즈", "로파이", "보사노바"],
                         "pattern": "시간·장소 + 감정 + 장르",
                         "structure": "장면 묘사 문장 + | + 장르/목적 키워드"},
            "branding": {"consistency": 9, "differentiation": 6, "memorability": 6,
                         "scalability": 8, "clickability": 7, "total": 36,
                         "one_liner": "결은 탄탄하나 시그니처 오브젝트가 없어 기억에 덜 남는다."},
        }],
        "fusion": "",
        "concepts": [{
            "name": "심야서점 라디오",
            "definition": "이 채널은 혼자 있는 밤의 20~40대에게 책 냄새 나는 고요함을 재즈·로파이로 전달하는 채널이다.",
            "moodboard": {"colors": "딥그린 #1F3D2B, 앰버 #E0A458, 크림 #F3E9D2, 우드브라운 #7A5A3A",
                          "atmosphere": "스탠드 불빛, 낡은 책장, 창밖 빗소리",
                          "ref_words": ["심야", "서점", "책장", "빗소리", "스탠드 불빛", "고요", "위로"]},
            "keep_85": ["심야 시간대", "위로 무드", "장면 묘사형 제목", "잔잔한 재즈 결", "인물 없는 썸네일"],
            "twist_15": ["카페 → 서점(시그니처: 스탠드 불빛+책)", "앰버 단색 → 딥그린 포인트"],
            "differentiation": ["'장소+시간대' 공식은 유지하되 미개척 공간(서점)으로 차별화",
                                "책이라는 시그니처 오브젝트로 기억용이성 보강"],
            "rationale": "원본의 '장소+시간대' 공식은 검증됐고, 서점은 같은 정서의 미개척 공간이라 15% 변형에 적합.",
        }],
        "setup": {
            "names": ["심야서점 라디오", "밤의 책방", "Midnight Bookstore"],
            "handles": ["@midnight.bookstore", "@bam.chaekbang", "@simya.radio"],
            "handle_note": "동일하거나 유사한 핸들이 이미 사용 중일 수 있으니, 유튜브 채널 설정에서 직접 검색해 사용 가능 여부를 확인하세요.",
            "description": "혼자 있는 밤을 위한 작은 서점입니다.\n오래된 책장과 스탠드 불빛 사이에서 흐르는 재즈·로파이로\n독서, 작업, 잠들기 전 시간을 조용히 채워드려요.\n숨을 고르고, 오늘 하루를 천천히 내려놓으세요.",
            "keywords": "심야 재즈, 밤 재즈, 로파이, 서점 음악, 독서 음악, 수면 음악, 집중 음악, 재즈 카페, 잔잔한 피아노, 밤 감성, 작업용 BGM, 위로 음악, 빗소리 재즈, 심야 라디오, 조용한 밤",
            "title_template": "🌙 새벽 3시의 책방 | 잠들기 전 듣는 심야 재즈 #01",
            "desc_template": "혼자 있는 밤, 오래된 책방에서 흐르는 잔잔한 재즈입니다.\n독서, 작업, 수면 전 배경음악으로 편하게 틀어두세요.\n숨을 고르고 오늘을 내려놓는 한 시간.\n들어주셔서 고맙습니다.",
            "tags": "심야재즈, 밤재즈, 로파이, 서점음악, 독서음악, 수면음악, 집중음악, 재즈카페, 잔잔한피아노, 밤감성, 작업용브금, 위로음악, 빗소리, 심야라디오, 조용한밤",
            "hashtags": ["#심야재즈", "#로파이", "#독서음악", "#수면음악", "#재즈카페", "#밤감성"],
        },
        "preview": {
            "profile": {"form": "원형 로고 안 스탠드 불빛+책", "color": "딥그린+앰버",
                        "objects": "책, 스탠드, 작은 창", "mood": "따뜻하고 조용한 밤",
                        "avoid": "원본과 같은 커피잔 로고, 과도한 네온",
                        "image_prompt": "A minimal circular channel logo icon of an open book under a small warm stand lamp, deep green and amber palette, cozy flat illustration, clean dark background, centered symbol, square"},
            "banner": {"background": "밤의 서점 창가, 멀리 빗줄기", "object": "책장과 스탠드 불빛",
                       "text": "중앙보다 약간 왼쪽, 작게", "margin": "상·좌우 넓은 여백",
                       "mood": "고요·안식",
                       "image_prompt": "A wide panoramic YouTube channel banner of a cozy midnight bookstore with tall bookshelves and warm stand lamps, soft rain on windows, deep green and amber cinematic mood, empty space in the center for a channel title, no people, wide"},
            "thumbnail": {"composition": "전경 책+스탠드, 후경 흐린 창가", "color": "딥그린 60% 앰버 30% 크림 10%",
                          "object_rule": "인물 없음, 책·불빛 중심", "text": "좌하단 2~4단어",
                          "click_point": "'들어가 앉고 싶은 밤 서점' 느낌"},
        },
        "hero_thumbnail": {
            "concept": "스탠드 불빛 아래 펼쳐진 책, 창밖엔 부드러운 빗줄기, 딥그린 배경의 심야 서점",
            "reason": "원본 고조회 요소(야간·장면 묘사·불빛)를 유지하되 커피잔 대신 책으로 시그니처 차별화.",
            "composition": "전경 책+스탠드 40%, 후경 창가·빗줄기 60%",
            "color_codes": "딥그린 #1F3D2B, 앰버 #E0A458, 크림 #F3E9D2, 우드브라운 #7A5A3A",
            "font": "썸네일 텍스트 최소화, 필요 시 부드러운 세리프",
            "object_rule": "인물 없음. 책·스탠드·창가·빗방울 중심",
            "text_placement": "넣는다면 좌하단 2~4단어만",
            "forbidden": "원본 로고 복제, 커피잔 동일 구도, 랜덤 텍스트, 과도한 네온",
            "image_prompt": "A cozy midnight bookstore, an open book under a warm stand lamp in the foreground, soft rain streaks on a window in the blurred background, deep green and amber color palette, calm and intimate late-night mood, cinematic realistic photography, shallow depth of field, no people, no text, no logos, relaxing jazz playlist thumbnail, 16:9",
        },
        "title_sets": [
            {"title": "🌙 새벽 3시의 책방 | 잠들기 전 듣는 심야 재즈 #01",
             "thumb_text": "새벽 3시의 책방\n잠들기 전 듣는 재즈",
             "image_prompt": "A cozy midnight bookstore at 3am, warm stand lamp glowing over an open book in the foreground, tall dark bookshelves behind, deep green #1F3D2B and amber #E0A458 palette, cinematic professional photography, shallow depth of field, empty upper-left area for text, no people"},
            {"title": "비 오는 밤, 오래된 서점에서 | 잔잔한 재즈 피아노 #02",
             "thumb_text": "비 오는 밤,\n오래된 서점에서",
             "image_prompt": "Rain streaking down an old bookstore window at night, warm interior light reflecting on wet glass, blurred bookshelves inside, moody deep green and amber tones, cinematic realistic photography, soft bokeh, empty center-left area for text, no people"},
            {"title": "혼자 있는 밤을 위한 재즈 | 독서와 위로 #03",
             "thumb_text": "혼자 있는 밤을 위한\n독서와 재즈",
             "image_prompt": "A single armchair beside a small reading lamp in a quiet bookstore corner at night, an open book resting on the seat, warm amber pool of light in deep green shadows, cinematic photography, shallow depth of field, empty upper area for text, no people"},
            {"title": "스탠드 불빛 아래, 느린 재즈 발라드 #04",
             "thumb_text": "스탠드 불빛 아래,\n느린 재즈",
             "image_prompt": "Close-up of a warm brass stand lamp illuminating stacked vintage books, dust motes floating in the light beam, dark green background fading to black, cinematic professional photography, macro lens feel, empty right side for text, no people"},
            {"title": "창밖엔 비, 책방엔 재즈 | 심야 감성 BGM #05",
             "thumb_text": "창밖엔 비,\n책방엔 재즈",
             "image_prompt": "View from inside a bookstore looking out a rain-covered window at blurred city lights at night, window-side reading nook with a small book stack, deep green and amber palette, cinematic photography, empty upper-left for text, no people"},
            {"title": "잠 안 오는 밤 | 마음이 풀리는 로파이 재즈 #06",
             "thumb_text": "잠 안 오는 밤,\n마음이 풀리는 재즈",
             "image_prompt": "A dim cozy bookstore aisle at late night, one warm hanging bulb, soft shadows between shelves, calm and intimate mood, deep green tones with warm amber accent, cinematic realistic photography, empty center area for text, no people"},
            {"title": "책 한 권, 재즈 한 곡 | 조용한 밤의 서점 #07",
             "thumb_text": "책 한 권,\n재즈 한 곡",
             "image_prompt": "A single open book under lamplight on a wooden reading table, reading glasses beside it, quiet bookstore blurred in background, warm amber on deep green, cinematic professional photography, shallow depth of field, empty upper-right for text, no people"},
            {"title": "새벽 감성 재즈 | 집중과 휴식 사이 #08",
             "thumb_text": "집중과 휴식 사이,\n새벽 재즈",
             "image_prompt": "A tidy bookstore work desk before dawn, notebook and fountain pen under a focused lamp, first blue light of dawn in the window contrasted with warm interior amber, deep green walls, cinematic photography, empty left side for text, no people"},
            {"title": "오늘 하루를 내려놓는 밤 | 느린 재즈 #09",
             "thumb_text": "오늘 하루를\n내려놓는 밤",
             "image_prompt": "A coat hung by the bookstore door at night, warm light spilling from deeper inside between shelves, feeling of arriving and exhaling after a long day, deep green and amber cinematic tones, professional photography, empty upper area for text, no people"},
            {"title": "여기 잠깐 앉았다 가세요 | 심야 서점 재즈 #10",
             "thumb_text": "여기 잠깐\n앉았다 가세요",
             "image_prompt": "A small inviting bench with a cushion inside a midnight bookstore, warm lamp above it like an invitation, books stacked beside, deep green and amber cinematic palette, professional photography, gentle vignette, empty center-top for text, no people"},
        ],
        "suno": {
            "song_type": "instrumental",
            "type_reason": "채널 성격상 이번 곡은 연주곡으로 설계했습니다 — 독서·수면·작업용은 가사보다 반복 재생 가능한 연주곡이 적합.",
            "concept": "밤의 서점에서 마음을 천천히 내려놓는 1시간 플레이리스트용 힐링 연주곡. 피아노 중심, 브러시 드럼과 빗소리 앰비언스가 감싼다.",
            "style_prompt": "Instrumental lofi jazz, late-night 1960s mood, soft piano trio, upright bass, brushed drums, no vocals, 68 BPM, slow swing, wistful but warm, small bookstore ambience with vinyl crackle and distant rain, warm analog mixing, midnight reading playlist",
            "structure": [
                {"section": "[Intro]", "desc": "솔로 피아노, 빗소리 앰비언스, 넓고 조용한 분위기"},
                {"section": "[Main Theme]", "desc": "브러시 드럼 합류, 따뜻한 메인 멜로디"},
                {"section": "[Variation]", "desc": "베이스 워킹, 피아노가 조금 더 표현적으로"},
                {"section": "[Bridge]", "desc": "피아노만 남아 반성적이고 조용하게"},
                {"section": "[Final Theme]", "desc": "메인 멜로디 회귀, 드라마 없이 따뜻한 상승"},
                {"section": "[Outro]", "desc": "악기 서서히 페이드, 빗소리만 남기며 마무리"},
            ],
            "lyrics": "",
            "title_candidates": ["Midnight Pages", "밤의 책방", "Rain on the Spine", "책장 사이의 재즈", "After Hours Bookstore"],
            "yt_title_example": "🌙 Midnight Pages | 잠들기 전 듣는 심야 서점 재즈 #01",
            "song_pack": [],
        },
        "checklist": [
            "채널핸들 후보를 유튜브에서 직접 검색해 사용 가능 확인",
            "대표 썸네일 1장 제작 → 첫 3영상 같은 색감·구도로 통일",
            "고정 제목 템플릿으로 초반 10개 밀어 정체성 각인",
            "영상 길이 1시간~1시간 10분 유지",
            "25곡 풀 플레이리스트가 필요하면 곡 수를 25로 다시 생성",
        ],
    }


def _demo_report(ch: dict) -> str:
    return f"""# 플리 컨셉 리포트 (데모 — GEMINI/OPENAI 키를 넣으면 실제 분석)

## 1. 입력 가정
- 분석 대상: **{ch['title']}** (구독자 {ch['subscribers']:,}, 최근 영상 {len(ch['videos'])}개 실데이터)
- 썸네일 이미지 미첨부 → 시각 분석은 제목·업로드 흐름 기반 **추정**입니다.

## 3. 채널 아이덴티티
| 항목 | 분석 |
| --- | --- |
| 전체 무드 | 새벽·비·카페의 고요한 위로 |
| 세계관 | 혼자 있는 시간의 안식처 |
| 타겟 | 20~40대, 심야·출퇴근·작업 BGM 수요 |
| 시청 목적 | 수면 유도·집중·감정 정리 |
| 감정 포인트 | 외로움을 부정하지 않고 감싸줌 |
| 근거 | 제목 8개 중 6개가 시간대(새벽·밤)+장소(카페·창가) 조합 |

## 5. 조회수 패턴 분석
- 고조회 공통: **계절·날씨 키워드** (겨울밤 340만, 새벽 2시 210만) — 시기성 훅
- 저조회 대비: 기능성 제목(공부용 76만)보다 **장면 묘사형**이 평균 1.8배

## 8. 브랜딩 점수
| 항목 | 점수 |
| --- | --- |
| 일관성 | 9/10 |
| 차별성 | 6/10 |
| 기억용이성 | 6/10 |
| 확장성 | 8/10 |
| 클릭유도력 | 7/10 |

**총점 36/50** — 결은 탄탄하나 시그니처 오브젝트가 없어 기억에 안 남는다.

## 9. 신규 컨셉안
### 컨셉안 1 — "심야서점 라디오"
- 한 줄 정의: 혼자 있는 밤의 20~40대에게 **책 냄새 나는 고요함**을 재즈·로파이로 전달
- 유지한 85%: 심야 시간대·위로 무드·장면 묘사형 제목·잔잔한 재즈 결
- 새롭게 비튼 15%: 카페→**서점**(시그니처: 스탠드 불빛+책), 컬러 앰버→**딥그린**
- 근거: 원본의 '장소+시간대' 공식은 검증됐고, 서점은 같은 정서의 미개척 공간

## 14. Suno AI 아웃풋
채널 성격상 이번 곡은 **연주곡**으로 설계했습니다.
- Suno 스타일: Jazz, lofi jazz piano trio, late-night 1960s mood, soft piano + upright bass + brushed drums, no vocals, 68 BPM, slow swing, wistful but warm, small bookstore ambience with vinyl crackle, warm analog mixing, midnight reading playlist
- Instrumental Structure: [Intro] 솔로 피아노 → [Main Theme] 브러시 드럼 합류 → [Variation] 베이스 워킹 → [Bridge] 피아노만 → [Final Theme] → [Outro] 페이드

## 15. 다음 실행 체크리스트
- [ ] 채널핸들 후보를 유튜브에서 직접 검색해 사용 가능 확인
- [ ] 대표 썸네일 1장 제작 → 3영상 테스트
- [ ] 25곡 묶음이 필요하면 곡 수를 25로 다시 요청

*(데모 리포트는 요약본 — 키를 넣으면 1~15 전체가 상세 출력됩니다)*"""
