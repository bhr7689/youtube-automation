"""metadata_studio.html 생성기 — 엔진(metadata_team)이 뽑은 데이터를 그대로 화면에 주입.
JS 로직 중복 없이 파이썬 엔진이 단일 진실. 실행: python3 build_studio.py"""
import json
from pathlib import Path

import metadata_engine as ME
import metadata_team as MT

COUNTRIES = {
    "KR": {"label": "🇰🇷 한국", "concepts": list(ME.CONCEPTS.keys())},
    "JP": {"label": "🇯🇵 일본", "concepts": list(ME.CONCEPTS_JP.keys())},
    "US": {"label": "🇺🇸 미국", "concepts": list(ME.CONCEPTS_US.keys())},
}


def concept_label(country, key):
    d = {"KR": ME.CONCEPTS, "JP": ME.CONCEPTS_JP, "US": ME.CONCEPTS_US}[country]
    emoji = d.get(key, {}).get("emoji", "🎵")
    return f"{key} {emoji}"


DATA = {}
for co, meta in COUNTRIES.items():
    DATA[co] = {"label": meta["label"], "concepts": {}}
    for key in meta["concepts"]:
        pkg = MT.produce_package(co, concept=key)
        DATA[co]["concepts"][key] = {"label": concept_label(co, key), "pkg": pkg}

data_json = json.dumps(DATA, ensure_ascii=False)

HTML = r"""<!DOCTYPE html>
<html lang="ko"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🌐 국가별 메타데이터 스튜디오 · 쇼츠헌터</title>
<style>
  :root{--red:#e11d2a;--red-d:#b3121d;--ink:#1f2430;--sub:#8b94a3;--line:#eceef2;--bg:#f6f7f9;--ok:#16a34a;--warn:#d97706;}
  *{box-sizing:border-box;}
  body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Malgun Gothic",sans-serif;background:var(--bg);color:var(--ink);}
  .topbar{background:#fff;border-bottom:1px solid var(--line);position:sticky;top:0;z-index:20;}
  .tb-in{max-width:1120px;margin:0 auto;display:flex;align-items:center;gap:14px;padding:12px 20px;}
  .logo{display:flex;align-items:center;gap:7px;font-weight:900;color:var(--red);font-size:18px;}
  .logo .mark{display:inline-flex;gap:2px;align-items:flex-end;}
  .logo .mark i{width:4px;border-radius:2px;background:var(--red);display:inline-block;}
  .logo .mark i:nth-child(1){height:9px;}.logo .mark i:nth-child(2){height:15px;}.logo .mark i:nth-child(3){height:11px;opacity:.6;}
  .tb-title{font-size:14px;color:#5a6270;font-weight:700;}
  .wrap{max-width:1120px;margin:0 auto;padding:22px 20px 60px;}
  .h1{font-size:22px;font-weight:900;margin:4px 0 2px;}
  .lead{color:var(--sub);font-size:13.5px;line-height:1.7;margin-bottom:18px;}
  .demo-chip{display:inline-block;background:#fff7ed;border:1px solid #fdba74;color:#9a3412;font-size:12px;font-weight:700;padding:4px 11px;border-radius:999px;margin-bottom:16px;}
  .ctl{background:#fff;border:1px solid var(--line);border-radius:16px;padding:16px;margin-bottom:18px;box-shadow:0 2px 12px rgba(20,25,40,.04);}
  .ctl-lbl{font-size:12px;font-weight:800;color:#5a6270;margin:2px 0 8px;}
  .tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px;}
  .tab{border:1.5px solid #e3e6ec;background:#fff;border-radius:11px;padding:9px 16px;font-weight:800;font-size:14px;cursor:pointer;color:#3b424f;}
  .tab.on{background:var(--red);color:#fff;border-color:var(--red);}
  .chips{display:flex;gap:7px;flex-wrap:wrap;}
  .chip{border:1.5px solid #e3e6ec;background:#fff;border-radius:999px;padding:7px 13px;font-size:13px;font-weight:700;cursor:pointer;color:#3b424f;}
  .chip.on{background:#fee2e2;color:var(--red-d);border-color:#fca5a5;}
  .sec{background:#fff;border:1px solid var(--line);border-radius:16px;padding:16px 18px;margin-bottom:14px;box-shadow:0 2px 12px rgba(20,25,40,.04);}
  .sec-h{font-size:13px;font-weight:900;margin-bottom:10px;display:flex;align-items:center;gap:8px;color:#3b424f;}
  .sec-h .sp{flex:1;}
  .copybtn{border:1.5px solid #e3e6ec;background:#fff;border-radius:9px;padding:5px 11px;font-size:12px;font-weight:800;cursor:pointer;color:#3b424f;}
  .copybtn:hover{border-color:var(--red);color:var(--red);}
  .reco{border:1.5px solid #fecaca;background:linear-gradient(180deg,#fff5f5,#fff);border-radius:14px;padding:14px 16px;font-size:16px;font-weight:800;line-height:1.5;display:flex;gap:10px;align-items:flex-start;}
  .reco .t{flex:1;}
  .list{display:flex;flex-direction:column;gap:8px;}
  .row{display:flex;gap:9px;align-items:flex-start;background:#fafbfc;border:1px solid var(--line);border-radius:10px;padding:10px 12px;font-size:13.5px;line-height:1.5;}
  .row .t{flex:1;word-break:break-word;}
  .mini{border:none;background:#f1f3f6;color:#475063;border-radius:7px;padding:4px 8px;font-size:11.5px;font-weight:800;cursor:pointer;flex:0 0 auto;}
  .mini:hover{background:#fee2e2;color:var(--red-d);}
  pre.blk{background:#0f1220;color:#e7e9f3;border-radius:11px;padding:13px 15px;font-size:12.5px;line-height:1.6;overflow-x:auto;white-space:pre-wrap;margin:0;}
  .tagwrap{display:flex;flex-wrap:wrap;gap:6px;}
  .tg{background:#f1f3f6;border-radius:7px;padding:4px 9px;font-size:12px;color:#475063;}
  .qa{display:flex;gap:10px;flex-wrap:wrap;align-items:center;}
  .qbadge{font-size:20px;font-weight:900;padding:6px 14px;border-radius:12px;}
  .qbadge.g{background:#dcfce7;color:#166534;}.qbadge.y{background:#fef9c3;color:#854d0e;}
  .met{font-size:12px;color:var(--sub);}
  .flag{font-size:12px;color:var(--warn);}
  .team{display:flex;flex-direction:column;gap:6px;}
  .tm{display:flex;gap:10px;font-size:12.5px;background:#fafbfc;border:1px solid var(--line);border-radius:9px;padding:8px 11px;}
  .tm b{color:#3b424f;flex:0 0 auto;}
  .tm span{color:#5a6270;}
  .thumb{display:flex;gap:14px;align-items:center;flex-wrap:wrap;}
  .thumb .sq{width:150px;height:84px;border-radius:10px;background:linear-gradient(135deg,#e11d2a,#f59e0b);display:flex;align-items:center;justify-content:center;color:#fff;font-weight:900;text-align:center;padding:8px;font-size:14px;line-height:1.3;flex:0 0 auto;}
  .thumb .info{font-size:12.5px;color:#5a6270;line-height:1.7;}
  #toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#1f2430;color:#fff;padding:11px 20px;border-radius:999px;font-size:13px;opacity:0;transition:.25s;pointer-events:none;z-index:99;}
  @media(max-width:560px){.h1{font-size:19px;}}
</style></head><body>
<div class="topbar"><div class="tb-in">
  <div class="logo"><span class="mark"><i></i><i></i><i></i></span>쇼츠헌터</div>
  <div class="tb-title">🌐 국가별 메타데이터 스튜디오</div>
</div></div>
<div class="wrap">
  <div class="h1">🌐 국가별 메타데이터 스튜디오</div>
  <p class="lead">곡 컨셉을 고르면 <b>전문가 10명 + 편집장</b>이 그 나라 검색 문법으로 <b>제목·설명·태그·해시태그·썸네일 문구</b>를 뽑아 줍니다.<br>검색어 밀도형 제목이 1순위 — 고조회 영상과 <b>연관 동영상으로 묶이게</b> 최적화. 모든 블록은 📋로 바로 복사.</p>
  <span class="demo-chip">🎬 규칙기반 데모 — 키 연결 시 각 전문가가 LLM으로 심화 + SERP 실검증(PC)</span>

  <div class="ctl">
    <div class="ctl-lbl">1. 나라 선택</div>
    <div class="tabs" id="tabs"></div>
    <div class="ctl-lbl">2. 곡 컨셉 / 테마 선택 <span style="font-weight:400;color:#8b94a3;">— 알고리즘 변화에 맞춰 과일·카페·비 등 자유 전환</span></div>
    <div class="chips" id="chips"></div>
  </div>

  <div id="out"></div>
</div>
<div id="toast"></div>
<script>
const DATA = __DATA__;
let CO = "KR", CC = null;

function toast(m){const t=document.getElementById('toast');t.textContent=m;t.style.opacity='1';clearTimeout(t._h);t._h=setTimeout(()=>t.style.opacity='0',1600);}
function copy(txt,msg){navigator.clipboard.writeText(txt).then(()=>toast(msg||'📋 복사됨'),()=>toast('복사 실패'));}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}

function renderTabs(){
  document.getElementById('tabs').innerHTML = Object.keys(DATA).map(co=>
    `<button class="tab ${co===CO?'on':''}" onclick="selCountry('${co}')">${DATA[co].label}</button>`).join('');
}
function renderChips(){
  const cs = DATA[CO].concepts;
  document.getElementById('chips').innerHTML = Object.keys(cs).map(k=>
    `<button class="chip ${k===CC?'on':''}" onclick="selConcept('${k}')">${esc(cs[k].label)}</button>`).join('');
}
function selCountry(co){CO=co;const ks=Object.keys(DATA[co].concepts);CC=ks.includes(CC)?CC:ks[0];renderTabs();renderChips();render();}
function selConcept(k){CC=k;renderChips();render();}

function block(title, bodyHtml, copyText, copyMsg){
  const btn = copyText!=null ? `<button class="copybtn" onclick='copy(${JSON.stringify(copyText)}, ${JSON.stringify(copyMsg||"📋 복사됨")})'>📋 복사</button>` : '';
  return `<div class="sec"><div class="sec-h">${title}<span class="sp"></span>${btn}</div>${bodyHtml}</div>`;
}
function titleRows(arr){
  return `<div class="list">`+arr.map(t=>
    `<div class="row"><div class="t">${esc(t)}</div><button class="mini" onclick='copy(${JSON.stringify(t)},"📋 제목 복사")'>복사</button></div>`).join('')+`</div>`;
}

function render(){
  const p = DATA[CO].concepts[CC].pkg;
  const qcls = p.qa.total>=27?'g':'y';
  const th = p.thumbnail;
  let html = '';

  html += `<div class="sec"><div class="sec-h">⭐ 추천 제목 (검색어 밀도형 · 1순위)<span class="sp"></span>
    <button class="copybtn" onclick='copy(${JSON.stringify(p.title_recommended)},"📋 추천 제목 복사")'>📋 복사</button></div>
    <div class="reco"><div class="t">${esc(p.title_recommended)}</div></div></div>`;

  html += block('🔎 검색형 제목 (밀도형)', titleRows(p.titles_search),
                p.titles_search.join('\n'), '📋 검색형 제목 전체 복사');
  html += block('💫 감성형 제목 (보조)', titleRows(p.titles_emotion),
                p.titles_emotion.join('\n'), '📋 감성형 제목 전체 복사');

  html += block('📄 설명글 (4단 · 복사용)', `<pre class="blk">${esc(p.description)}</pre>`,
                p.description, '📋 설명글 복사');

  html += block('🏷️ 태그', `<div class="tagwrap">`+p.tags.map(t=>`<span class="tg">${esc(t)}</span>`).join('')+`</div>`,
                p.tags.join(', '), '📋 태그 복사');
  html += block('#️⃣ 해시태그', `<div style="font-size:13.5px;color:#3b424f;">${esc(p.hashtags)}</div>`,
                p.hashtags, '📋 해시태그 복사');

  html += block('🖼️ 썸네일 (제목과 소재 일치)',
    `<div class="thumb"><div class="sq">${esc(th.thumb_text)}</div>
      <div class="info"><b>씬</b> · ${esc(th.scene)}<br><b>가독성</b> · ${esc(th.readability)}<br><b>일치</b> · ${esc(th.match)}</div></div>`,
    th.thumb_text, '📋 썸네일 문구 복사');

  const flags = (p.qa.flags&&p.qa.flags.length)?`<span class="flag">⚠️ ${p.qa.flags.map(esc).join(' · ')}</span>`:'<span class="met">플래그 없음</span>';
  html += block('🏆 품질 평가(QA)',
    `<div class="qa"><span class="qbadge ${qcls}">${p.qa.total}/30</span>
      <span class="met">제목 ${p.qa.scores.title} · 태그 ${p.qa.scores.tags} · 설명 ${p.qa.scores.description}</span>${flags}</div>`);

  html += block('👥 전문가 10명 리포트',
    `<div class="team">`+p.team_report.map(r=>`<div class="tm"><b>${esc(r.role)}</b><span>${esc(r.summary)}</span></div>`).join('')+`</div>`);

  document.getElementById('out').innerHTML = html;
}

renderTabs(); selCountry('KR');
</script>
</body></html>"""

out = HTML.replace("__DATA__", data_json)
Path("japan_shorts_app/metadata_studio.html").write_text(out, encoding="utf-8")
print("✅ japan_shorts_app/metadata_studio.html 생성 —",
      sum(len(v["concepts"]) for v in DATA.values()), "개 컨셉 패키지 임베드")
