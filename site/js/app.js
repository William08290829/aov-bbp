// Draft page UI: loads data.json, keeps board state, renders suggestions.
import { createEngine } from "./engine.js";
import { LANES, assignLanes } from "./matching.js";
import {
  SLOTS, emptyDraft, engineState, fillError, getSlot, nextEmptySlot, other,
  sameSlot, sanitizeDraft, sanitizeSlot, setSlot, slotLabel,
} from "./draft.js";

const CLASSES = ["坦克", "戰士", "刺客", "法師", "射手", "輔助"];
const CLASS_COLORS = {
  坦克: "#3f6fb5", 戰士: "#b5652a", 刺客: "#7b45b0", 法師: "#1f8fa3", 射手: "#b53d3d", 輔助: "#3a8a52",
};
const STORAGE_KEY = "bbp-draft-v1";
const VISIBLE_REASONS = 2;

let engine = null;
let defaultOrder = [];
let avatarVersion = "";

const ui = {
  side: "blue",
  draft: emptyDraft(),
  active: null,            // slot object; null = follow the next empty slot
  manualActive: false,     // true after the user clicked a slot
  sort: "score",
  filters: { cls: "", lane: "", q: "" },
  expanded: new Set(),
};

const $ = (id) => document.getElementById(id);

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

const slotKey = (s) => `${s.kind}:${s.team}:${s.index}`;
function parseSlotKey(key) {
  const [kind, team, index] = key.split(":");
  return sanitizeSlot({ kind, team, index });
}

// ---------------------------------------------------------------- persistence

function save() {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
      side: ui.side, draft: ui.draft, active: ui.manualActive ? ui.active : null, sort: ui.sort,
    }));
  } catch (_) { /* storage unavailable: state just won't survive a reload */ }
}

function restore() {
  let raw = null;
  try {
    raw = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "null");
  } catch (_) { raw = null; }
  if (!raw || typeof raw !== "object") return;
  ui.side = raw.side === "red" ? "red" : "blue";
  ui.draft = sanitizeDraft(raw.draft, engine.heroes);
  ui.sort = raw.sort === "default" ? "default" : "score";
  const active = sanitizeSlot(raw.active);
  if (active) {
    ui.active = active;
    ui.manualActive = true;
  }
}

// ---------------------------------------------------------------- helpers

function hero(name) {
  return engine.heroes.get(name);
}

function classLabel(h) {
  return h.sub_class ? `${h.main_class}/${h.sub_class}` : (h.main_class || "未分類");
}

function avatar(h, extra = "") {
  if (h.avatar) {
    const src = `./avatars/${encodeURIComponent(h.avatar)}${avatarVersion}`;
    return `<img class="av ${extra}" src="${esc(src)}" alt="" loading="lazy" data-ph="${esc(h.name)}">`;
  }
  return placeholder(h, extra);
}

function placeholder(h, extra = "") {
  const color = CLASS_COLORS[h.main_class] || "#666";
  return `<span class="av av-ph ${extra}" style="--c:${color}" aria-hidden="true">${esc(h.name.slice(0, 1))}</span>`;
}

function formatScore(v) {
  const abs = Math.abs(v).toFixed(1);
  if (abs === "0.0") return { text: "0.0", cls: "zero" };
  return v > 0 ? { text: `+${abs}`, cls: "pos" } : { text: `−${abs}`, cls: "neg" };
}

function currentActive() {
  if (ui.active) return ui.active;
  return nextEmptySlot(ui.draft);
}

function matchesFilters(name) {
  const h = hero(name);
  const { cls, lane, q } = ui.filters;
  if (cls && h.main_class !== cls && h.sub_class !== cls) return false;
  if (lane && !(lane in (h.lanes || {}))) return false;
  if (q && !h.name.toLowerCase().includes(q.toLowerCase())) return false;
  return true;
}

let toastTimer = null;
function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 2800);
}

// ---------------------------------------------------------------- actions

function fill(name) {
  const slot = currentActive();
  if (!slot) {
    toast("所有格子都已填滿；點選任一格可以更換。");
    return;
  }
  const error = fillError(ui.draft, slot, name, engine);
  if (error) {
    toast(error);
    return;
  }
  ui.draft = setSlot(ui.draft, slot, name);
  ui.active = null;
  ui.manualActive = false;
  update();
}

function selectSlot(slot) {
  ui.active = slot;
  ui.manualActive = true;
  update();
}

function clearSlot(slot) {
  ui.draft = setSlot(ui.draft, slot, null);
  ui.active = slot;
  ui.manualActive = true;
  update();
}

function update() {
  save();
  render();
}

// ---------------------------------------------------------------- rendering

function render() {
  const active = currentActive();
  const state = engineState(ui.draft, ui.side);
  const isBan = active?.kind === "ban";
  const result = isBan ? engine.banSuggestions(state) : engine.pickSuggestions(state);
  const open = result.openLanes || engine.openLanes(state);

  document.body.dataset.side = ui.side;
  renderTop(active);
  renderBans(active);
  renderTeam("us", ui.side, active, open.us);
  renderTeam("them", other(ui.side), active, open.them);
  renderSuggestions(result, active);
  renderGrid(result, active, state);
}

function renderTop(active) {
  for (const btn of document.querySelectorAll(".side-btn")) {
    btn.setAttribute("aria-pressed", String(btn.dataset.side === ui.side));
  }
  for (const btn of document.querySelectorAll(".sort-toggle button")) {
    btn.setAttribute("aria-pressed", String(btn.dataset.sort === ui.sort));
  }
  $("phase").textContent = !active ? "已完成" : active.kind === "ban" ? "禁用階段" : "選角階段";
  $("active-hint").textContent = active ? `目前：${slotLabel(active, ui.side)}` : "點選任一格可更換";
}

function slotHtml(slot, active, inner, extraClass) {
  const name = getSlot(ui.draft, slot);
  const isActive = sameSlot(slot, active);
  const label = slotLabel(slot, ui.side);
  return `
    <div class="slot ${extraClass} ${name ? "filled" : "empty"} ${isActive ? "active" : ""}">
      <button type="button" class="slot-main" data-slot="${slotKey(slot)}"
              aria-label="${esc(label)}${name ? `：${esc(name)}` : "：空"}"${isActive ? ' aria-current="true"' : ""}>
        ${inner}
      </button>
      ${name ? `<button type="button" class="slot-clear" data-clear="${slotKey(slot)}" aria-label="清除${esc(label)}">×</button>` : ""}
    </div>`;
}

function renderBans(active) {
  for (const [el, team] of [[$("bans-us"), ui.side], [$("bans-them"), other(ui.side)]]) {
    el.className = `bans bans-${team === ui.side ? "us" : "them"} team-${team}`;
    el.innerHTML = Array.from({ length: SLOTS }, (_, index) => {
      const slot = { kind: "ban", team, index };
      const name = getSlot(ui.draft, slot);
      const inner = name
        ? `${avatar(hero(name), "av-ban")}<span class="ban-name">${esc(name)}</span>`
        : `<span class="ban-empty">禁${index + 1}</span>`;
      return slotHtml(slot, active, inner, "ban-slot");
    }).join("");
  }
}

function renderTeam(who, team, active, openLanes) {
  const el = $(`team-${who}`);
  el.className = `team team-${who} team-${team}`;
  const names = ui.draft.picks[team];
  const filled = names.map((n, i) => [n, i]).filter(([n]) => n);
  const lanes = assignLanes(filled.map(([n]) => (engine.hasLaneData(n) ? engine.lanesOf(n) : [])));
  const laneOf = new Map(filled.map(([n], k) => [n, engine.hasLaneData(n) ? lanes[k] : null]));

  const title = `${who === "us" ? "我方" : "敵方"}（${team === "blue" ? "藍" : "紅"}）`;
  const openText = openLanes.length ? openLanes.join("、") : "—";
  const rows = Array.from({ length: SLOTS }, (_, index) => {
    const slot = { kind: "pick", team, index };
    const name = names[index];
    const h = name && hero(name);
    const lane = name ? (laneOf.get(name) || (engine.hasLaneData(name) ? "撞路" : "分路未填")) : "";
    const inner = `
      ${h ? avatar(h, "av-pick") : '<span class="av av-empty" aria-hidden="true"></span>'}
      <span class="pick-text">
        <span class="pick-name">${h ? esc(name) : "點此填入"}</span>
        <span class="pick-sub">${esc(slotLabel(slot, ui.side))}</span>
        ${lane ? `<span class="pick-lane">${esc(lane)}</span>` : ""}
      </span>`;
    return slotHtml(slot, active, inner, "pick-slot");
  });
  el.innerHTML = `
    <div class="team-head"><span class="team-title">${title}</span>
      <span class="team-open" title="仍可補的分路">可補：${esc(openText)}</span></div>
    ${rows.join("")}`;
}

function reasonHtml(item, kind) {
  if (kind === "con" && item.value === 0) {
    return `<li class="reason note">· ${esc(item.text)}</li>`;
  }
  const s = formatScore(item.value);
  return `<li class="reason ${kind}"><span class="sign">${kind === "pro" ? "+" : "−"}</span> ${esc(item.text)} <span class="rv">${s.text}</span></li>`;
}

function renderSuggestions(result, active) {
  const isBan = active?.kind === "ban";
  const enemyPick = active?.kind === "pick" && active.team !== ui.side;
  $("suggest-title").textContent = isBan ? "禁用建議"
    : enemyPick ? "敵方選角中（以下為我方下一手參考）" : "選角建議";

  const all = result.suggestions;
  const available = all.filter((s) => !s.blocked).length;
  const shown = all.filter((s) => matchesFilters(s.name));
  $("suggest-count").textContent = shown.length === all.length
    ? `共 ${available} 隻可選` : `共 ${available} 隻可選（篩選後 ${shown.length} 隻）`;

  const rank = new Map(all.map((s, i) => [s.name, i + 1]));
  $("suggest-list").innerHTML = shown.length ? shown.map((s) => {
    const h = hero(s.name);
    const r = rank.get(s.name);
    const score = formatScore(s.score);
    const open = ui.expanded.has(s.name);
    const pros = s.pros.map((p) => reasonHtml(p, "pro"));
    const cons = s.cons.map((c) => reasonHtml(c, "con"));
    const hidden = Math.max(0, pros.length - VISIBLE_REASONS) + Math.max(0, cons.length - VISIBLE_REASONS);
    const visible = open ? [...pros, ...cons]
      : [...pros.slice(0, VISIBLE_REASONS), ...cons.slice(0, VISIBLE_REASONS)];
    const lanes = s.lanes.length ? s.lanes.join("/") : (isBan ? "分路未填" : "撞路");
    return `
      <li class="sg ${r <= 3 && !s.blocked ? "top" : ""} ${s.blocked ? "blocked" : ""}">
        <button type="button" class="sg-main" data-hero="${esc(s.name)}">
          <span class="rank">${r}</span>
          ${avatar(h, "av-sg")}
          <span class="sg-name">${esc(s.name)}</span>
          <span class="sg-meta">${esc(classLabel(h))} · ${esc(lanes)}</span>
          <span class="score ${score.cls}">${score.text}</span>
        </button>
        ${visible.length || hidden ? `<ul class="reasons">${visible.join("")}</ul>` : ""}
        ${hidden ? `<button type="button" class="more" data-more="${esc(s.name)}" aria-expanded="${open}">${open ? "收合" : `更多（+${hidden}）`}</button>` : ""}
      </li>`;
  }).join("") : '<li class="empty-msg">沒有符合篩選條件的英雄</li>';
}

function renderGrid(result, active, state) {
  const rank = new Map(result.suggestions.filter((s) => !s.blocked).map((s, i) => [s.name, i + 1]));
  let names = defaultOrder;
  if (ui.sort === "score") {
    const ranked = result.suggestions.map((s) => s.name);
    const inRanked = new Set(ranked);
    names = [...ranked, ...defaultOrder.filter((n) => !inRanked.has(n))];
  }
  const banned = new Set([...state.bansUs, ...state.bansThem]);
  const ours = new Set(state.picksUs);
  const theirs = new Set(state.picksThem);
  const pickActive = active?.kind === "pick";

  const cells = names.filter(matchesFilters).map((name) => {
    const h = hero(name);
    let status = "";
    let disabled = false;
    if (banned.has(name)) { status = "已禁"; disabled = true; }
    else if (ours.has(name)) { status = "我方"; disabled = true; }
    else if (theirs.has(name)) { status = "敵方"; disabled = true; }
    else if (!engine.isPickable(name, state)) { status = "型態已選"; disabled = pickActive || !active; }
    const r = rank.get(name);
    const top = ui.sort === "score" && r && r <= 3 && !status;
    return `
      <button type="button" class="cell ${status ? "taken" : ""} ${top ? "top" : ""}" data-hero="${esc(name)}"
              ${disabled ? "disabled" : ""} title="${esc(`${name}（${classLabel(h)}）`)}">
        ${avatar(h, "av-cell")}
        <span class="cell-name">${esc(name)}</span>
        ${status ? `<span class="cell-badge">${status}</span>` : top ? '<span class="cell-badge rec">推薦</span>' : ""}
      </button>`;
  });
  $("hero-grid").innerHTML = cells.join("") || '<p class="empty-msg">沒有符合篩選條件的英雄</p>';
}

function renderFilters() {
  $("class-tabs").innerHTML = ["", ...CLASSES].map((c) =>
    `<button type="button" role="tab" data-cls="${c}" aria-selected="${ui.filters.cls === c}">${c || "全部"}</button>`,
  ).join("");
  $("lane-filter").innerHTML = ['<option value="">全部分路</option>',
    ...LANES.map((l) => `<option value="${l}">${l}</option>`)].join("");
}

// ---------------------------------------------------------------- events

function bind() {
  document.addEventListener("click", (e) => {
    const t = e.target.closest("button");
    if (!t || t.disabled) return;
    if (t.dataset.clear) return clearSlot(parseSlotKey(t.dataset.clear));
    if (t.dataset.slot) return selectSlot(parseSlotKey(t.dataset.slot));
    if (t.dataset.hero) return fill(t.dataset.hero);
    if (t.dataset.more) {
      const name = t.dataset.more;
      if (ui.expanded.has(name)) ui.expanded.delete(name); else ui.expanded.add(name);
      return render();
    }
    if (t.dataset.side) {
      ui.side = t.dataset.side;
      return update();
    }
    if (t.dataset.sort) {
      ui.sort = t.dataset.sort;
      return update();
    }
    if (t.dataset.cls !== undefined && t.getAttribute("role") === "tab") {
      ui.filters.cls = t.dataset.cls;
      for (const tab of document.querySelectorAll("#class-tabs button")) {
        tab.setAttribute("aria-selected", String(tab === t));
      }
      return render();
    }
    if (t.id === "btn-clear") {
      if (!confirm("確定要清空所有禁用與選角嗎？")) return;
      ui.draft = emptyDraft();
      ui.active = null;
      ui.manualActive = false;
      ui.expanded.clear();
      return update();
    }
  });

  $("search").addEventListener("input", (e) => {
    ui.filters.q = e.target.value.trim();
    render();
  });
  $("lane-filter").addEventListener("change", (e) => {
    ui.filters.lane = e.target.value;
    render();
  });

  // Missing avatar file: fall back to the placeholder.
  document.addEventListener("error", (e) => {
    const img = e.target;
    if (!(img instanceof HTMLImageElement) || !img.dataset.ph) return;
    const h = hero(img.dataset.ph);
    if (h) img.outerHTML = placeholder(h, img.className.replace(/\bav\b/, ""));
  }, true);
}

// ---------------------------------------------------------------- startup

function showLoadError(err) {
  $("app").hidden = true;
  const el = $("load-error");
  el.hidden = false;
  el.innerHTML = `
    <h1>無法載入英雄資料</h1>
    <p>讀取 <code>data/data.json</code> 時發生錯誤：${esc(err?.message || err)}</p>
    <p>請重新整理頁面再試一次。若是在本機預覽，請用
      <code>python -m http.server 8080 --directory site</code> 開啟，不要直接以檔案開啟 index.html。</p>`;
}

function formatTime(iso) {
  if (!iso) return "未知";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat("zh-TW", {
    timeZone: "Asia/Taipei", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(d);
}

async function main() {
  try {
    const res = await fetch("./data/data.json", { cache: "no-cache" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!Array.isArray(data?.heroes)) throw new Error("資料格式不正確");
    engine = createEngine(data);
  } catch (err) {
    showLoadError(err);
    return;
  }
  const classIndex = (c) => (CLASSES.includes(c) ? CLASSES.indexOf(c) : CLASSES.length);
  defaultOrder = [...engine.heroes.values()]
    .sort((a, b) => classIndex(a.main_class) - classIndex(b.main_class) || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0))
    .map((h) => h.name);
  avatarVersion = engine.exportedAt ? `?v=${encodeURIComponent(engine.exportedAt)}` : "";
  $("data-time").textContent = `資料更新時間：${formatTime(engine.exportedAt)}`;

  restore();
  renderFilters();
  bind();
  render();
}

main();
