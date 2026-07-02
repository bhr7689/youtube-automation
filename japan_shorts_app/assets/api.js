/* jpshorts 공용 API 클라이언트 + 카드 렌더러
   FastAPI(main.py)가 이 정적 앱을 같은 포트에서 서빙하므로 API_BASE 는 상대경로. */

const API_BASE = "";

async function api(path, opts = {}) {
  const res = await fetch(API_BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
  return res.json();
}

/* ── 포맷 헬퍼 ─────────────────────────────────── */

function fmtViews(n) {
  n = Number(n) || 0;
  if (n >= 100000000) return `조회 ${(n / 100000000).toFixed(1)}억`;
  if (n >= 10000) return `조회 ${(n / 10000).toFixed(1)}만`;
  return `조회 ${n.toLocaleString()}`;
}

function fmtDuration(sec) {
  if (!sec) return "";
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
           : `${m}:${String(s).padStart(2, "0")}`;
}

function fmtAgo(iso) {
  const t = new Date(iso).getTime();
  if (!iso || isNaN(t)) return "";
  const d = (Date.now() - t) / 86400000;
  if (d < 1) return "오늘";
  if (d < 7) return `${Math.floor(d)}일 전`;
  if (d < 30) return `${Math.floor(d / 7)}주 전`;
  if (d < 365) return `${Math.floor(d / 30)}달 전`;
  return `${Math.floor(d / 365)}년 전`;
}

const AVATAR_COLORS = ["#92400e","#dc2626","#f59e0b","#be123c","#a855f7","#b45309","#0ea5e9","#9d174d","#047857","#db2777","#f97316","#475569","#ca8a04","#ea580c"];
function avatarColor(name) {
  let h = 0;
  for (const ch of name || "") h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return AVATAR_COLORS[h % AVATAR_COLORS.length];
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
}

/* ── 토스트 ────────────────────────────────────── */

function toast(msg) {
  let t = document.getElementById("toast");
  if (!t) {
    t = document.createElement("div");
    t.id = "toast";
    t.style.cssText = "position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#2b2440;color:#fff;padding:10px 20px;border-radius:20px;font-size:13px;z-index:999;opacity:0;transition:.3s;pointer-events:none;";
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.style.opacity = "1";
  clearTimeout(t._h);
  t._h = setTimeout(() => (t.style.opacity = "0"), 1800);
}

/* ── 데모 배너 ─────────────────────────────────── */

function showDemoBanner(isDemo) {
  let b = document.getElementById("demoBanner");
  if (!isDemo) { if (b) b.remove(); return; }
  if (b) return;
  b = document.createElement("div");
  b.id = "demoBanner";
  b.style.cssText = "background:#fff7ed;border:1.5px solid #fdba74;color:#9a3412;border-radius:12px;padding:10px 16px;font-size:13px;margin-bottom:14px;";
  b.innerHTML = "🔑 <b>데모 데이터 모드</b> — 저장소 루트 <code>.env</code> 에 <code>YOUTUBE_API_KEY</code> 를 넣고 서버를 재시작하면 실제 유튜브 검색이 작동해요.";
  const main = document.querySelector(".main");
  if (main) main.insertBefore(b, main.children[1] || null);
}

/* ── 카드 렌더러 ───────────────────────────────── */

function videoUrl(c) { return `https://www.youtube.com/watch?v=${c.video_id}`; }

function renderCard(c) {
  const reg = c.registered;
  const thumb = c.thumb
    ? `<img src="${esc(c.thumb)}" alt="" loading="lazy">`
    : `<div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-size:38px;background:linear-gradient(135deg,#41295a,#2F0743);">🎬</div>`;
  const sprout = c.channel_age_months !== undefined && c.channel_age_months < 900
    ? `<span class="sprout-tag">🌱 ${c.channel_age_months}개월</span>` : "";
  return `
  <div class="video-card ${reg ? "registered" : "new-add"}" data-vid="${esc(c.video_id)}" data-cid="${esc(c.channel_id)}">
    <div class="video-thumb" onclick="window.open('${videoUrl(c)}','_blank')" style="cursor:pointer;">
      ${thumb}
      ${c.is_short ? '<span class="shorts-tag">SHORTS</span>' : ""}
      ${c.multiplier && reg ? `<span class="multiplier-tag">×${c.multiplier}</span>` : ""}
      <span class="duration-tag">${fmtDuration(c.duration_sec)}</span>
      <div class="thumb-bookmark ${c.bookmarked ? "on" : ""}" onclick="event.stopPropagation();toggleBookmark(this)">${c.bookmarked ? "★" : "☆"}</div>
    </div>
    <div class="video-body">
      <div class="video-title" title="${esc(c.title)}">${esc(c.title)}</div>
      <div class="video-channel">
        <div class="channel-avatar" style="background:${avatarColor(c.channel_title)};"></div>
        <span class="channel-name">${esc(c.channel_title)}</span>
        ${reg
          ? '<span class="btn-registered" onclick="toggleChannel(this)">✓ 등록</span>'
          : '<button class="btn-add" onclick="toggleChannel(this)">+ 추가</button>'}
      </div>
      <div class="video-stats">
        <span>${fmtViews(c.views)}</span>
        <span>${fmtAgo(c.published_at)}</span>
      </div>
      ${sprout ? `<div style="margin-bottom:6px;">${sprout}</div>` : ""}
      <div class="video-actions">
        <div class="action-row">
          <span class="action-chip" onclick="window.open('https://downsub.com/?url=${encodeURIComponent(videoUrl(c))}','_blank')">📜 자막</span>
          <span class="action-dot">·</span>
          <span class="action-chip" onclick="window.open('${videoUrl(c)}','_blank')">⚪ 원본</span>
          <span class="action-dot">·</span>
          <span class="action-chip" onclick="location.href='search.html?q='+encodeURIComponent('${esc(c.title).slice(0, 40)}')">📰 유사</span>
        </div>
        <div class="action-row">
          <span class="action-chip" onclick="window.open('${videoUrl(c)}','_blank')">💬 댓글</span>
          <span class="action-chip" onclick="navigator.clipboard.writeText('${videoUrl(c)}').then(()=>toast('🔗 링크 복사됨'))">🔗 링크</span>
        </div>
      </div>
    </div>
  </div>`;
}

/* 카드 데이터 보관 (액션에서 payload 접근용) */
const CARD_STORE = {};

function renderGrid(el, cards) {
  cards.forEach(c => (CARD_STORE[c.video_id] = c));
  el.innerHTML = cards.length
    ? cards.map(renderCard).join("")
    : '<div style="grid-column:1/-1;text-align:center;color:#8a80a5;padding:60px 0;">결과가 없어요</div>';
}

/* ── 북마크 토글 (크로스 화면 공유) ─────────────── */

async function toggleBookmark(el) {
  const card = el.closest(".video-card");
  const vid = card.dataset.vid;
  const on = el.classList.contains("on");
  try {
    if (on) {
      await api(`/api/bookmarks/${vid}`, { method: "DELETE" });
      el.classList.remove("on");
      el.textContent = "☆";
      toast("북마크 해제");
      if (window.BOOKMARK_PAGE) card.remove();
    } else {
      await api("/api/bookmarks", { method: "POST", body: JSON.stringify({ card: CARD_STORE[vid] || { video_id: vid } }) });
      el.classList.add("on");
      el.textContent = "★";
      toast("⭐ 북마크 저장 — 북마크 패널에서 확인");
    }
  } catch (e) { toast("오류: " + e.message); }
}

/* ── 레퍼런스 채널 등록/해제 ────────────────────── */

async function toggleChannel(el) {
  const card = el.closest(".video-card");
  const cid = card.dataset.cid;
  const name = card.querySelector(".channel-name").textContent.trim();
  const isReg = el.classList.contains("btn-registered");
  try {
    if (isReg) {
      if (!confirm(`'${name}' 채널 등록을 해제할까요?`)) return;
      await api(`/api/channels/${cid}`, { method: "DELETE" });
      toast("채널 등록 해제");
    } else {
      const vid = card.dataset.vid;
      const c = CARD_STORE[vid] || {};
      await api("/api/channels", {
        method: "POST",
        body: JSON.stringify({ channel_id: cid, title: name, payload: { thumb: c.thumb || "", avg_views: c.channel_avg_views || 0, age_months: c.channel_age_months } }),
      });
      toast(`✓ '${name}' 레퍼런스 채널 등록`);
    }
    /* 같은 채널의 모든 카드 상태 갱신 */
    document.querySelectorAll(`.video-card[data-cid="${CSS.escape(cid)}"]`).forEach(cd => {
      cd.classList.toggle("registered", !isReg);
      cd.classList.toggle("new-add", isReg);
      const btn = cd.querySelector(".btn-add, .btn-registered");
      if (btn) btn.outerHTML = !isReg
        ? '<span class="btn-registered" onclick="toggleChannel(this)">✓ 등록</span>'
        : '<button class="btn-add" onclick="toggleChannel(this)">+ 추가</button>';
      const v = CARD_STORE[cd.dataset.vid];
      const mult = v && v.multiplier;
      const tag = cd.querySelector(".multiplier-tag");
      if (!isReg && mult && !tag) {
        cd.querySelector(".video-thumb").insertAdjacentHTML("beforeend", `<span class="multiplier-tag">×${mult}</span>`);
      } else if (isReg && tag) tag.remove();
    });
  } catch (e) { toast("오류: " + e.message); }
}

/* ── 결과 내 정렬/필터 (클라이언트) ──────────────── */

function applyLocalFilter(cards, { sort = "views", minMult = 0, minViews = 0, maxAgeMonths = 0 } = {}) {
  let out = cards.filter(c =>
    (!minMult || (c.multiplier || 0) >= minMult) &&
    (!minViews || c.views >= minViews) &&
    (!maxAgeMonths || (c.channel_age_months ?? 999) <= maxAgeMonths)
  );
  if (sort === "views") out.sort((a, b) => b.views - a.views);
  else if (sort === "mult") out.sort((a, b) => (b.multiplier || 0) - (a.multiplier || 0));
  else if (sort === "date") out.sort((a, b) => new Date(b.published_at) - new Date(a.published_at));
  return out;
}

/* ── 칩 그룹 헬퍼 (단일 선택) ───────────────────── */

function chipGroup(rootEl, { multi = false, onChange } = {}) {
  rootEl.addEventListener("click", e => {
    const chip = e.target.closest(".chip, .chip-check");
    if (!chip) return;
    if (multi) chip.classList.toggle("selected");
    else {
      rootEl.querySelectorAll(".selected").forEach(c => c.classList.remove("selected"));
      chip.classList.add("selected");
    }
    onChange && onChange(chip);
  });
}

function selectedValue(rootEl) {
  const c = rootEl.querySelector(".selected");
  return c ? c.dataset.v : undefined;
}
