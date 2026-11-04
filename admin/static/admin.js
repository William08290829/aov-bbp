// Client-side filtering and error toasts for the BBP admin.

function toast(message, isError = true) {
  const box = document.getElementById("toasts");
  if (!box) return;
  const el = document.createElement("div");
  el.className = "toast" + (isError ? " error" : "");
  el.textContent = message;
  box.appendChild(el);
  setTimeout(() => el.remove(), 6000);
}

function errorText(xhr) {
  const text = xhr.responseText || "";
  try {
    const data = JSON.parse(text);
    if (typeof data.detail === "string") return data.detail;
  } catch (_) { /* plain text */ }
  return text || `發生錯誤（HTTP ${xhr.status}）`;
}

document.addEventListener("htmx:responseError", (e) => toast(errorText(e.detail.xhr)));
document.addEventListener("htmx:sendError", () => toast("無法連線到後台，請確認 uvicorn 是否仍在執行"));

// ---- hero list filter (search + class / flag chips)

let listFilter = "";

function applyListFilter() {
  const q = (document.getElementById("list-search")?.value || "").trim().toLowerCase();
  for (const item of document.querySelectorAll("#hero-list .hero-item")) {
    let ok = !q || item.dataset.name.toLowerCase().includes(q);
    if (ok && listFilter.startsWith("class:")) {
      ok = item.dataset.classes.split(" ").includes(listFilter.slice(6));
    } else if (ok && listFilter.startsWith("flag:")) {
      ok = item.dataset.flags.split(" ").includes(listFilter.slice(5));
    }
    item.hidden = !ok;
  }
}

document.addEventListener("input", (e) => {
  if (e.target.id === "list-search") applyListFilter();
  if (e.target.closest(".rel-filters")) applyRelFilter();
});

document.addEventListener("change", (e) => {
  if (e.target.closest(".rel-filters")) applyRelFilter();
});

document.addEventListener("click", (e) => {
  const chip = e.target.closest("#list-filter .chip");
  if (!chip) return;
  listFilter = chip.dataset.filter;
  for (const c of document.querySelectorAll("#list-filter .chip")) c.classList.toggle("on", c === chip);
  applyListFilter();
});

// ---- relation grid filter

function applyRelFilter() {
  const q = (document.getElementById("rel-search")?.value || "").trim().toLowerCase();
  const cls = document.getElementById("rel-class")?.value || "";
  const lane = document.getElementById("rel-lane")?.value || "";
  const only = document.getElementById("rel-only")?.checked || false;
  for (const cell of document.querySelectorAll(".rel-grid .rel")) {
    cell.hidden = !(
      (!q || cell.dataset.name.toLowerCase().includes(q)) &&
      (!cls || cell.dataset.classes.split(" ").includes(cls)) &&
      (!lane || cell.dataset.lanes.split(" ").includes(lane)) &&
      (!only || cell.dataset.has === "1")
    );
  }
}

// ---- keep list highlight and filters after swaps

function markActive() {
  const m = location.pathname.match(/\/admin\/hero\/(\d+)/);
  const href = m ? `/admin/hero/${m[1]}` : null;
  for (const item of document.querySelectorAll("#hero-list .hero-item")) {
    item.classList.toggle("active", item.getAttribute("href") === href);
  }
}

document.addEventListener("htmx:afterSettle", (e) => {
  const target = e.detail.target;
  if (!target) return;
  if (target.id === "hero-list") applyListFilter();
  if (target.id === "editor") markActive();
});
window.addEventListener("popstate", () => setTimeout(markActive, 0));
