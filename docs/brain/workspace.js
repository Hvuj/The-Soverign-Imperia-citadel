/* ------------------------------------------------------------------ */
/* Citadel Workspace Intelligence — shared JS  v=20260608-workspace-intel
/* Provides: fetch helpers, query-param router, paginator, copy-path,
/*           Ask Citadel panel for workspace pages.                      */
/* ------------------------------------------------------------------ */
"use strict";

/* ── Config ─────────────────────────────────────────────────────────── */
const PAGE_SIZE = 100;
const API_BASE  = "";   // same origin

/* ── URL query params ────────────────────────────────────────────────── */
function qs(key) {
  return new URLSearchParams(location.search).get(key) || "";
}

/* ── Fetch helper ────────────────────────────────────────────────────── */
async function getJSON(url) {
  const r = await fetch(url, { credentials: "same-origin" });
  if (!r.ok) throw new Error(`HTTP ${r.status} – ${r.statusText} (${url})`);
  return r.json();
}

async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    credentials: "same-origin",
  });
  if (!r.ok) throw new Error(`HTTP ${r.status} (${url})`);
  return r.json();
}

/* ── DOM helpers ─────────────────────────────────────────────────────── */
function el(id)           { return document.getElementById(id); }
function setText(id, txt) { const e = el(id); if (e) e.textContent = txt; }
function setHTML(id, html) { const e = el(id); if (e) e.innerHTML = html; }

function showLoading(id)  { setHTML(id, '<div class="loading-msg">Loading…</div>'); }
function showError(id, m) { setHTML(id, `<div class="error-msg">${esc(m)}</div>`); }

/* ── HTML escaping ───────────────────────────────────────────────────── */
function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* ── Badge helpers ───────────────────────────────────────────────────── */
function badge(text, cls) {
  return `<span class="badge badge-${cls}">${esc(text)}</span>`;
}

// Workspace-agnostic: badges reflect generic capability categories emitted by the indexer, not any
// specific framework. The learning layer maps a workspace's tools into these categories.
function techBadges(meta) {
  const b = [];
  if (meta.orchestration_assets?.length || meta.orchestration_jobs?.length ||
      meta.orchestration_schedules?.length || meta.orchestration_sensors?.length)
                                          b.push(badge("Orchestration", "cyan"));
  if (meta.schema_models?.length || meta.schema_checks?.length)
                                          b.push(badge("Schema",   "violet"));
  if (meta.config_models?.length)         b.push(badge("Config",   "blue"));
  if (meta.distributed_usage)             b.push(badge("Distributed", "orange"));
  if (meta.dataframe_usage)               b.push(badge("Dataframe", "green"));
  if (meta.query_usage)                   b.push(badge("Query",    "yellow"));
  return b.join(" ");
}

/* ── Copy path ───────────────────────────────────────────────────────── */
function copyPath(path) {
  navigator.clipboard.writeText(path).then(() => showToast("Path copied")).catch(() => {});
}

/* ── Toast ───────────────────────────────────────────────────────────── */
let _toastTimer = null;
function showToast(msg) {
  let t = el("ws-toast");
  if (!t) {
    t = document.createElement("div");
    t.id = "ws-toast";
    t.style.cssText =
      "position:fixed;bottom:80px;left:50%;transform:translateX(-50%);" +
      "background:rgba(36,215,255,0.12);border:1px solid rgba(36,215,255,0.3);" +
      "color:#e7f3ff;border-radius:8px;padding:7px 16px;font-size:12px;" +
      "z-index:200;pointer-events:none;white-space:nowrap;";
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.style.opacity = "1";
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { t.style.opacity = "0"; }, 2000);
}

/* ── Ask Citadel panel ─────────────────────────────────────────────────── */
function _ensureAskPanel() {
  if (el("ws-ask-panel")) return;
  document.body.insertAdjacentHTML("beforeend", `
    <div id="ws-ask-panel" class="ask-panel">
      <div class="ask-panel-header">
        <span class="ask-panel-title">Ask Citadel</span>
        <button class="ask-panel-close" onclick="closeAskPanel()">×</button>
      </div>
      <div id="ws-ask-body" class="ask-panel-body">
        <div class="ask-panel-thinking">Waiting for question…</div>
      </div>
    </div>
  `);
}

function closeAskPanel() {
  const p = el("ws-ask-panel");
  if (p) p.classList.remove("open");
}

async function askCitadel(question, nodeId) {
  _ensureAskPanel();
  const panel = el("ws-ask-panel");
  const body  = el("ws-ask-body");
  panel.classList.add("open");
  body.innerHTML = '<div class="ask-panel-thinking">Thinking…</div>';
  try {
    const payload = { question, mode: "fast" };
    if (nodeId) payload.selected_node_id = nodeId;
    const resp = await postJSON(`${API_BASE}/api/ask`, payload);
    const answer = resp.answer || resp.data?.answer || resp.message || JSON.stringify(resp, null, 2);
    body.innerHTML = `<div>${esc(answer).replace(/\n/g, "<br>")}</div>`;
  } catch (e) {
    body.innerHTML = `<div class="error-msg">Ask Citadel error: ${esc(e.message)}</div>`;
  }
}

/* ── Paginator ───────────────────────────────────────────────────────── */
class Paginator {
  constructor(items, pageSize, renderFn, containerId, paginationId) {
    this.items      = items;
    this.pageSize   = pageSize;
    this.renderFn   = renderFn;
    this.containerId = containerId;
    this.paginationId = paginationId;
    this.page       = 0;
    this.render();
  }

  totalPages() { return Math.max(1, Math.ceil(this.items.length / this.pageSize)); }

  render() {
    const start = this.page * this.pageSize;
    const slice = this.items.slice(start, start + this.pageSize);
    const c = el(this.containerId);
    if (c) c.innerHTML = slice.map(this.renderFn).join("");
    this._renderPagination();
  }

  _renderPagination() {
    const p = el(this.paginationId);
    if (!p) return;
    const total = this.totalPages();
    if (total <= 1) { p.innerHTML = ""; return; }
    p.innerHTML = `
      <button class="btn btn-sm btn-secondary" ${this.page === 0 ? "disabled" : ""}
              onclick="this.closest('[data-pag]').__pag.prev()">← Prev</button>
      <span class="page-info">Page ${this.page + 1} / ${total} (${this.items.length} items)</span>
      <button class="btn btn-sm btn-secondary" ${this.page >= total - 1 ? "disabled" : ""}
              onclick="this.closest('[data-pag]').__pag.next()">Next →</button>`;
    p.setAttribute("data-pag", "1");
    p.__pag = this;
  }

  prev() { if (this.page > 0) { this.page--; this.render(); } }
  next() { if (this.page < this.totalPages() - 1) { this.page++; this.render(); } }
}

/* ── Breadcrumb helpers ──────────────────────────────────────────────── */
function breadcrumb(...crumbs) {
  // crumbs: [{label, href?}]
  return crumbs.map((c, i) => {
    const isLast = i === crumbs.length - 1;
    const sep = i > 0 ? `<span class="sep">/</span>` : "";
    if (isLast || !c.href) return `${sep}<span class="crumb-current">${esc(c.label)}</span>`;
    return `${sep}<a href="${esc(c.href)}">${esc(c.label)}</a>`;
  }).join("");
}

/* ── Set breadcrumb in topbar ────────────────────────────────────────── */
function setBreadcrumb(id, ...crumbs) {
  const e = el(id);
  if (e) e.innerHTML = breadcrumb(...crumbs);
}

/* ── Search helper (client-side filter of loaded list) ──────────────── */
function clientFilter(items, query, fields) {
  if (!query) return items;
  const q = query.toLowerCase();
  return items.filter(item =>
    fields.some(f => String(item[f] ?? "").toLowerCase().includes(q))
  );
}

/* ── Workspace-page initializers (called by each page) ──────────────── */

// workspace.html
async function initWorkspacePage() {
  const summaryEl = el("summary-area");
  const repoGrid  = el("repo-grid");

  showLoading("summary-area");
  showLoading("repo-grid");

  try {
    const [sumResp, reposResp] = await Promise.all([
      getJSON(`${API_BASE}/api/workspace/summary`),
      getJSON(`${API_BASE}/api/workspace/repos`),
    ]);

    // Summary card
    const s = sumResp.data || {};
    const subtitleEl = el("page-subtitle");
    if (subtitleEl && s.repo_count != null) {
      subtitleEl.textContent =
        `All ${s.repo_count} workspace repos — metadata, symbols, features, reuse candidates`;
    }
    summaryEl.innerHTML = `
      <div class="stats-row">
        <div class="stat-chip"><span class="val">${esc(s.repo_count ?? 0)}</span><span class="lbl">Repos</span></div>
        <div class="stat-chip"><span class="val">${esc(s.file_count ?? 0)}</span><span class="lbl">Files</span></div>
        <div class="stat-chip"><span class="val">${esc(s.feature_count ?? 0)}</span><span class="lbl">Features</span></div>
        <div class="stat-chip"><span class="val">${esc(s.changed_count ?? 0)}</span><span class="lbl">Changed</span></div>
      </div>
      <div style="font-size:11px;color:var(--muted)">
        Build <code>${esc(s.build_id?.slice(0,8) ?? "—")}</code> ·
        ${s.incremental ? "incremental" : "full"} ·
        ${s.build_duration_sec ? `${s.build_duration_sec.toFixed(2)}s` : ""}
        ${s.last_build_at ? `· last built ${esc(s.last_build_at.slice(0,19))} UTC` : ""}
      </div>`;

    // Repo cards
    const repos = reposResp.data || [];
    if (!repos.length) {
      repoGrid.innerHTML = '<div class="loading-msg">No repos found in index.</div>';
    } else {
      repoGrid.innerHTML = repos.map(repo => {
        // Actual repo-index.json uses `name` and `feature_ids`
        const name  = repo.name || repo.repo_id || repo.repo_name || "?";
        const path  = repo.path || "";
        const files = repo.file_count ?? "?";
        const mods  = repo.module_count ?? "?";
        const feats = (repo.feature_ids || repo.top_features || []).length;
        const href  = `/brain/repo.html?repo=${encodeURIComponent(name)}`;
        return `
          <a class="repo-card" href="${esc(href)}">
            <div class="repo-card-name">${esc(name)}</div>
            <div class="repo-card-path">${esc(path)}</div>
            <div class="repo-card-counts">
              ${badge(files + " files", "muted")}
              ${badge(mods  + " modules", "cyan")}
              ${feats ? badge(feats + " features", "violet") : ""}
            </div>
          </a>`;
      }).join("");
    }
  } catch (e) {
    showError("summary-area", `Failed to load workspace summary: ${e.message}`);
    showError("repo-grid", `Failed to load repos: ${e.message}`);
  }

  // Search box
  const searchInput = el("search-input");
  const searchBtn   = el("search-btn");
  const reuseInput  = el("reuse-input");
  const reuseBtn    = el("reuse-btn");
  const resultsEl   = el("search-results");

  async function doSearch(q, endpoint) {
    if (!q.trim()) return;
    showLoading("search-results");
    try {
      const resp = await getJSON(`${API_BASE}/api/workspace/${endpoint}?q=${encodeURIComponent(q)}&limit=20`);
      const results = resp.data?.results || resp.data || [];
      if (!results.length) {
        setHTML("search-results", '<div class="loading-msg">No results found.</div>');
        return;
      }
      setHTML("search-results", results.map(r => {
        const title = r.feature || r.file_id || r.path || r.query || "result";
        const detail = r.path || r.summary || r.why_reusable?.join(", ") || "";
        const repo = r.repo || "";
        return `<li class="item-list">
          <div style="display:flex;align-items:flex-start;gap:8px;padding:8px 12px;border-radius:10px;cursor:default">
            ${badge(endpoint, endpoint === "reuse" ? "violet" : "blue")}
            <span class="item-path">${esc(title)}</span>
            <span class="item-summary">${esc(detail.slice(0, 80))}</span>
            ${repo ? badge(repo, "muted") : ""}
          </div>
        </li>`;
      }).join(""));
    } catch (e) {
      showError("search-results", e.message);
    }
  }

  if (searchBtn) searchBtn.onclick = () => doSearch(searchInput?.value || "", "search");
  if (reuseBtn)  reuseBtn.onclick  = () => doSearch(reuseInput?.value  || "", "reuse");
  if (searchInput) searchInput.onkeydown = e => { if (e.key === "Enter") doSearch(searchInput.value, "search"); };
  if (reuseInput)  reuseInput.onkeydown  = e => { if (e.key === "Enter") doSearch(reuseInput.value,  "reuse"); };
}

// repo.html
async function initRepoPage() {
  const repoName = qs("repo");
  if (!repoName) { showError("repo-body", "Missing ?repo= parameter"); return; }

  setBreadcrumb("breadcrumb",
    { label: "Workspace", href: "/brain/workspace.html" },
    { label: repoName });

  setText("page-title", repoName);
  showLoading("repo-body");

  try {
    const resp = await getJSON(`${API_BASE}/api/workspace/repo?repo=${encodeURIComponent(repoName)}`);
    const r = resp.data || {};
    el("repo-body").innerHTML = _renderRepoBody(r, repoName);
  } catch (e) {
    showError("repo-body", `Failed to load repo: ${e.message}`);
  }
}

function _renderRepoBody(r, repoName) {
  // repo-index.json actual fields: name, path, repo_id, file_count, module_count,
  //   feature_ids, python_root, is_git
  const repoDisplayName = r.name || r.repo_name || repoName;
  const features = r.feature_ids || r.top_features || r.feature_tags || [];
  const dirs     = r.important_dirs || r.dir_ids || [];
  const files    = r.important_files || [];
  const dagDefs  = r.dagster_defs || [];
  const deps     = r.dependencies || [];
  const pkgRoots = r.python_root ? [r.python_root] : (r.python_package_roots || []);

  const statsHTML = `
    <div class="stats-row">
      <div class="stat-chip"><span class="val">${r.file_count ?? "?"}</span><span class="lbl">Files</span></div>
      <div class="stat-chip"><span class="val">${r.module_count ?? "?"}</span><span class="lbl">Modules</span></div>
      <div class="stat-chip"><span class="val">${features.length}</span><span class="lbl">Features</span></div>
    </div>`;

  const summaryHTML = r.summary
    ? `<div class="card"><p style="color:var(--muted);margin:0">${esc(r.summary)}</p></div>` : "";

  const pkgHTML = pkgRoots.length
    ? `<div class="section">
        <div class="section-title">Package roots</div>
        <div>${pkgRoots.map(p => `<code>${esc(p)}</code>`).join(" ")}</div>
       </div>` : "";

  const featHTML = features.length
    ? `<div class="section">
        <div class="section-title">Features <span class="count">${features.length}</span></div>
        <div style="display:flex;flex-wrap:wrap;gap:5px;margin-bottom:4px">${features.slice(0, 30).map(f => badge(f, "violet")).join("")}</div>
       </div>` : "";

  const dirsHTML = dirs.length
    ? `<div class="section">
        <div class="section-title">Important directories <span class="count">${dirs.length}</span></div>
        <ul class="item-list">${dirs.slice(0, 30).map(d => {
          const dirId = typeof d === "string" ? d : (d.dir_id || d);
          const label = typeof d === "string" ? d : (d.relative_path || d.dir_id || d);
          return `<li>${badge("dir", "blue")}<a class="item-link" href="/brain/dir.html?repo=${encodeURIComponent(repoName)}&dir=${encodeURIComponent(dirId)}">${esc(label)}</a></li>`;
        }).join("")}</ul>
       </div>` : "";

  const depsHTML = deps.length
    ? `<div class="section">
        <div class="section-title">Dependencies <span class="count">${deps.length}</span></div>
        <div style="display:flex;flex-wrap:wrap;gap:5px">${deps.slice(0, 30).map(d => badge(d, "muted")).join("")}</div>
       </div>` : "";

  const dagHTML = dagDefs.length
    ? `<div class="section">
        <div class="section-title">Dagster definitions <span class="count">${dagDefs.length}</span></div>
        <ul class="item-list">${dagDefs.slice(0, 20).map(d =>
          `<li>${badge(d.kind || "asset", "cyan")}<span class="item-path">${esc(d.name || d)}</span></li>`
        ).join("")}</ul>
       </div>` : "";

  const filesHTML = files.length
    ? `<div class="section">
        <div class="section-title">Important files <span class="count">${files.length}</span></div>
        <ul class="item-list">${files.slice(0, 20).map(f => {
          const fileId = typeof f === "string" ? f : (f.file_id || f);
          const label  = typeof f === "string" ? f : (f.relative_path || f.file_id || f);
          return `<li>${badge("file", "muted")}<a class="item-link" href="/brain/file.html?repo=${encodeURIComponent(repoName)}&file=${encodeURIComponent(fileId)}">${esc(label)}</a></li>`;
        }).join("")}</ul>
       </div>` : "";

  return `
    ${statsHTML}
    ${summaryHTML}
    <div class="card">
      <div class="card-title">Details</div>
      <div><b>Path:</b> <code>${esc(r.path || "—")}</code>
           <button class="btn btn-sm btn-secondary" onclick="copyPath('${esc(r.path || "")}')">Copy</button></div>
      ${pkgHTML}
      ${depsHTML}
    </div>
    ${featHTML}${dirsHTML}${dagHTML}${filesHTML}
    <div class="section">
      <div class="section-title">Ask Citadel</div>
      <div class="ask-chip-row">
        <button class="ask-chip" onclick="askCitadel('What does ${esc(repoDisplayName)} do?')">What does this repo do?</button>
        <button class="ask-chip" onclick="askCitadel('What can we reuse from ${esc(repoDisplayName)}?')">What can I reuse?</button>
        <button class="ask-chip" onclick="askCitadel('What modules does ${esc(repoDisplayName)} have?')">Show modules</button>
        <button class="ask-chip" onclick="askCitadel('What features does ${esc(repoDisplayName)} have?')">Show features</button>
      </div>
    </div>`;
}

// dir.html
async function initDirPage() {
  const repoName = qs("repo");
  const dirId    = qs("dir");
  if (!dirId) { showError("dir-body", "Missing ?dir= parameter"); return; }

  setBreadcrumb("breadcrumb",
    { label: "Workspace", href: "/brain/workspace.html" },
    { label: repoName || "repo", href: repoName ? `/brain/repo.html?repo=${encodeURIComponent(repoName)}` : undefined },
    { label: dirId.split(":")[1] || dirId });

  showLoading("dir-body");

  try {
    const url = `${API_BASE}/api/workspace/dir?${repoName ? `repo=${encodeURIComponent(repoName)}&` : ""}dir=${encodeURIComponent(dirId)}`;
    const resp = await getJSON(url);
    const d = resp.data || {};
    setText("page-title", d.relative_path || dirId);
    el("dir-body").innerHTML = _renderDirBody(d, repoName);
  } catch (e) {
    showError("dir-body", `Failed to load directory: ${e.message}`);
  }
}

function _renderDirBody(d, repoName) {
  const childDirs = d.child_dirs || [];
  const files     = d.files || [];
  const modules   = d.modules || [];
  const features  = d.feature_tags || [];
  const tests     = d.tests || [];

  const statsHTML = `
    <div class="stats-row">
      <div class="stat-chip"><span class="val">${childDirs.length}</span><span class="lbl">Sub-dirs</span></div>
      <div class="stat-chip"><span class="val">${files.length}</span><span class="lbl">Files</span></div>
      <div class="stat-chip"><span class="val">${modules.length}</span><span class="lbl">Modules</span></div>
      <div class="stat-chip"><span class="val">${d.symbols_count ?? "?"}</span><span class="lbl">Symbols</span></div>
    </div>`;

  const summaryHTML = d.purpose_summary
    ? `<div class="card"><p style="margin:0;color:var(--muted)">${esc(d.purpose_summary)}</p></div>` : "";

  const dirsHTML = childDirs.length ? `
    <div class="section">
      <div class="section-title">Sub-directories <span class="count">${childDirs.length}</span></div>
      <ul class="item-list">${childDirs.slice(0, PAGE_SIZE).map(cd => {
        const id = typeof cd === "string" ? cd : (cd.dir_id || cd);
        const lbl = typeof cd === "string" ? cd : (cd.relative_path || cd.dir_id || cd);
        return `<li>${badge("dir", "blue")}
          <a class="item-link" href="/brain/dir.html?repo=${encodeURIComponent(repoName || "")}&dir=${encodeURIComponent(id)}">${esc(lbl)}</a></li>`;
      }).join("")}</ul>
    </div>` : "";

  const filesHTML = files.length ? `
    <div class="section">
      <div class="section-title">Files <span class="count">${files.length}</span></div>
      <ul class="item-list">${files.slice(0, PAGE_SIZE).map(f => {
        const fid = typeof f === "string" ? f : (f.file_id || f);
        const lbl = typeof f === "string" ? f : (f.relative_path || f.file_id || f);
        return `<li>${badge("file", "muted")}
          <a class="item-link" href="/brain/file.html?repo=${encodeURIComponent(repoName || "")}&file=${encodeURIComponent(fid)}">${esc(lbl)}</a></li>`;
      }).join("")}</ul>
    </div>` : "";

  const modsHTML = modules.length ? `
    <div class="section">
      <div class="section-title">Modules <span class="count">${modules.length}</span></div>
      <ul class="item-list">${modules.slice(0, PAGE_SIZE).map(m => {
        const name = typeof m === "string" ? m : (m.module_name || m);
        return `<li>${badge("module", "cyan")}
          <a class="item-link" href="/brain/module.html?repo=${encodeURIComponent(repoName || "")}&module=${encodeURIComponent(name)}">${esc(name)}</a></li>`;
      }).join("")}</ul>
    </div>` : "";

  const featHTML = features.length ? `
    <div class="section">
      <div class="section-title">Features</div>
      <div style="display:flex;flex-wrap:wrap;gap:5px">${features.map(f => badge(f, "violet")).join("")}</div>
    </div>` : "";

  const testsHTML = tests.length ? `
    <div class="section">
      <div class="section-title">Tests <span class="count">${tests.length}</span></div>
      <ul class="item-list">${tests.slice(0, 20).map(t =>
        `<li>${badge("test", "green")}<span class="item-path">${esc(typeof t === "string" ? t : t.file_id || t)}</span></li>`
      ).join("")}</ul>
    </div>` : "";

  return `
    ${statsHTML}${summaryHTML}
    <div class="card">
      <div><b>Path:</b> <code>${esc(d.absolute_path || d.relative_path || "—")}</code>
        <button class="btn btn-sm btn-secondary" onclick="copyPath('${esc(d.absolute_path || d.relative_path || "")}')">Copy</button>
      </div>
    </div>
    ${dirsHTML}${filesHTML}${modsHTML}${featHTML}${testsHTML}
    <div class="section">
      <div class="ask-chip-row">
        <button class="ask-chip" onclick="askCitadel('What does the directory ${esc(d.relative_path || "")} do?')">What does this directory do?</button>
        <button class="ask-chip" onclick="askCitadel('What can I reuse from ${esc(d.relative_path || "")}?')">What can I reuse?</button>
      </div>
    </div>`;
}

// module.html
async function initModulePage() {
  const repoName = qs("repo");
  const modName  = qs("module");
  if (!modName) { showError("module-body", "Missing ?module= parameter"); return; }

  setBreadcrumb("breadcrumb",
    { label: "Workspace", href: "/brain/workspace.html" },
    { label: repoName || "repo", href: repoName ? `/brain/repo.html?repo=${encodeURIComponent(repoName)}` : undefined },
    { label: modName });

  setText("page-title", modName);
  showLoading("module-body");

  try {
    const url = `${API_BASE}/api/workspace/module?${repoName ? `repo=${encodeURIComponent(repoName)}&` : ""}module=${encodeURIComponent(modName)}`;
    const resp = await getJSON(url);
    const m = resp.data || {};
    el("module-body").innerHTML = _renderModuleBody(m, repoName, modName);
  } catch (e) {
    showError("module-body", `Failed to load module: ${e.message}`);
  }
}

function _renderModuleBody(m, repoName, modName) {
  // module-index maps module_name → [file_ids] or → module metadata dict
  // Handle both shapes
  const fileIds   = Array.isArray(m) ? m : (m.files || m.file_ids || []);
  const imports   = m.imports   || [];
  const impBy     = m.imported_by || [];
  const symbols   = m.symbols   || [];
  const classes   = m.classes   || [];
  const functions = m.functions || [];
  const assets    = m.dagster_assets || [];
  const schemas   = m.pandera_schemas || [];
  const pydantic  = m.pydantic_models || [];
  const tests     = m.related_tests || [];
  const features  = m.feature_tags || [];
  const summary   = m.summary || "";

  const summaryHTML = summary
    ? `<div class="card"><p style="margin:0;color:var(--muted)">${esc(summary)}</p></div>` : "";

  function symbolList(items, kind, cls) {
    if (!items.length) return "";
    return `<div class="section">
      <div class="section-title">${kind} <span class="count">${items.length}</span></div>
      <ul class="item-list">${items.slice(0, PAGE_SIZE).map(s => {
        const name = typeof s === "string" ? s : (s.name || s.symbol || JSON.stringify(s));
        const line = s.line ? `:${s.line}` : "";
        const doc  = s.docstring_summary || s.docstring || "";
        return `<li>${badge(kind.toLowerCase(), cls)}<span class="item-path">${esc(name)}${esc(line)}</span><span class="item-summary">${esc(doc.slice(0,60))}</span></li>`;
      }).join("")}</ul>
    </div>`;
  }

  const filesHTML = fileIds.length ? `
    <div class="section">
      <div class="section-title">Files <span class="count">${fileIds.length}</span></div>
      <ul class="item-list">${fileIds.slice(0, 20).map(fid =>
        `<li>${badge("file", "muted")}<a class="item-link" href="/brain/file.html?repo=${encodeURIComponent(repoName || "")}&file=${encodeURIComponent(fid)}">${esc(fid)}</a></li>`
      ).join("")}</ul>
    </div>` : "";

  const importsHTML = imports.length ? `
    <div class="section">
      <div class="section-title">Imports <span class="count">${imports.length}</span></div>
      <div style="display:flex;flex-wrap:wrap;gap:5px">${imports.slice(0,30).map(i => badge(i, "muted")).join("")}</div>
    </div>` : "";

  const impByHTML = impBy.length ? `
    <div class="section">
      <div class="section-title">Imported by <span class="count">${impBy.length}</span></div>
      <div style="display:flex;flex-wrap:wrap;gap:5px">${impBy.slice(0,20).map(i => badge(i, "cyan")).join("")}</div>
    </div>` : "";

  const featHTML = features.length ? `
    <div class="section">
      <div class="section-title">Features</div>
      <div style="display:flex;flex-wrap:wrap;gap:5px">${features.map(f => badge(f, "violet")).join("")}</div>
    </div>` : "";

  const testsHTML = tests.length ? `
    <div class="section">
      <div class="section-title">Tests <span class="count">${tests.length}</span></div>
      <ul class="item-list">${tests.slice(0,20).map(t =>
        `<li>${badge("test","green")}<span class="item-path">${esc(typeof t === "string" ? t : t.file_id || t)}</span></li>`
      ).join("")}</ul>
    </div>` : "";

  return `
    ${summaryHTML}
    ${filesHTML}${importsHTML}${impByHTML}
    ${symbolList(classes,   "Classes",   "violet")}
    ${symbolList(functions, "Functions", "cyan")}
    ${symbolList(symbols,   "Symbols",   "blue")}
    ${symbolList(assets,    "Assets",    "yellow")}
    ${symbolList(schemas,   "Pandera schemas", "orange")}
    ${symbolList(pydantic,  "Pydantic models", "blue")}
    ${featHTML}${testsHTML}
    <div class="section">
      <div class="ask-chip-row">
        <button class="ask-chip" onclick="askCitadel('What does the module ${esc(modName)} do?')">What does this module do?</button>
        <button class="ask-chip" onclick="askCitadel('What can I reuse from ${esc(modName)}?')">What can I reuse?</button>
        <button class="ask-chip" onclick="askCitadel('What tests cover ${esc(modName)}?')">Show tests</button>
      </div>
    </div>`;
}

// file.html
async function initFilePage() {
  const repoName = qs("repo");
  const fileId   = qs("file");
  if (!fileId) { showError("file-body", "Missing ?file= parameter"); return; }

  const shortPath = fileId.includes(":") ? fileId.split(":")[1] : fileId;
  setBreadcrumb("breadcrumb",
    { label: "Workspace", href: "/brain/workspace.html" },
    { label: repoName || "repo", href: repoName ? `/brain/repo.html?repo=${encodeURIComponent(repoName)}` : undefined },
    { label: shortPath });

  setText("page-title", shortPath);
  showLoading("file-body");

  try {
    const url = `${API_BASE}/api/workspace/file?${repoName ? `repo=${encodeURIComponent(repoName)}&` : ""}file=${encodeURIComponent(fileId)}`;
    const resp = await getJSON(url);
    const f = resp.data || {};
    el("file-body").innerHTML = _renderFileBody(f, repoName, fileId);
  } catch (e) {
    showError("file-body", `Failed to load file: ${e.message}`);
  }
}

function _renderFileBody(f, repoName, fileId) {
  const imports   = f.imports || [];
  const classes   = f.classes || [];
  const functions = f.functions || [];
  const constants = f.constants || [];
  const assets    = f.dagster_assets || [];
  const checks    = f.dagster_asset_checks || [];
  const schemas   = f.pandera_schemas || [];
  const pydantic  = f.pydantic_models || [];
  const tests     = f.tests_related || [];
  const refBy     = f.referenced_by || [];
  const features  = f.likely_feature_area || [];
  const techB     = techBadges(f);

  const metaHTML = `
    <div class="card">
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px">
        ${badge(f.language || f.extension || "file", "muted")}
        ${badge(f.parse_status || "ok", f.parse_status === "ok" ? "green" : "yellow")}
        ${techB}
      </div>
      <div style="font-size:12px;color:var(--muted);display:grid;grid-template-columns:auto 1fr;gap:4px 12px">
        <b>Path:</b> <span style="display:flex;align-items:center;gap:6px">
          <code style="overflow:hidden;text-overflow:ellipsis">${esc(f.absolute_path || f.relative_path || fileId)}</code>
          <button class="btn btn-sm btn-secondary" onclick="copyPath('${esc(f.absolute_path || f.relative_path || "")}')">Copy</button>
        </span>
        <b>Size:</b> <span>${f.size ? `${(f.size/1024).toFixed(1)} KB` : "—"}</span>
        <b>Lines:</b> <span>${f.line_count ?? "—"}</span>
        <b>Repo:</b> <span>${esc(f.repo || repoName || "—")}</span>
      </div>
      ${f.short_summary ? `<p style="margin:12px 0 0;color:var(--text);font-size:12px;line-height:1.5">${esc(f.short_summary)}</p>` : ""}
    </div>`;

  function symList(items, kind, cls, showLine) {
    if (!items.length) return "";
    return `<div class="section">
      <div class="section-title">${kind} <span class="count">${items.length}</span></div>
      <ul class="item-list">${items.slice(0, PAGE_SIZE).map(s => {
        const name = typeof s === "string" ? s : (s.name || s.symbol || s);
        const line = showLine && s.line ? `:${s.line}` : "";
        const doc  = s.docstring_summary || s.docstring || s.summary || "";
        return `<li>${badge(kind, cls)}<span class="item-path">${esc(name)}${esc(line)}</span><span class="item-summary">${esc(doc.slice(0,70))}</span></li>`;
      }).join("")}</ul>
    </div>`;
  }

  const importsHTML = imports.length ? `
    <div class="section">
      <div class="section-title">Imports <span class="count">${imports.length}</span></div>
      <div style="display:flex;flex-wrap:wrap;gap:5px">${imports.slice(0,40).map(i => badge(i, "muted")).join("")}</div>
    </div>` : "";

  const refByHTML = refBy.length ? `
    <div class="section">
      <div class="section-title">Referenced by <span class="count">${refBy.length}</span></div>
      <div style="display:flex;flex-wrap:wrap;gap:5px">${refBy.slice(0,20).map(r => badge(r, "cyan")).join("")}</div>
    </div>` : "";

  const featHTML = features.length ? `
    <div class="section">
      <div class="section-title">Feature areas</div>
      <div style="display:flex;flex-wrap:wrap;gap:5px">${features.map(f2 => badge(f2, "violet")).join("")}</div>
    </div>` : "";

  const testsHTML = tests.length ? `
    <div class="section">
      <div class="section-title">Tests <span class="count">${tests.length}</span></div>
      <ul class="item-list">${tests.slice(0,20).map(t =>
        `<li>${badge("test","green")}<span class="item-path">${esc(typeof t === "string" ? t : (t.file_id || t))}</span></li>`
      ).join("")}</ul>
    </div>` : "";

  const askFileId = f.relative_path || fileId;

  return `
    ${metaHTML}
    ${importsHTML}
    ${symList(classes,   "class",    "violet", true)}
    ${symList(functions, "function", "cyan",   true)}
    ${symList(constants, "constant", "blue",   false)}
    ${symList(assets,    "asset",    "yellow", true)}
    ${symList(checks,    "check",    "orange", true)}
    ${symList(schemas,   "pandera",  "orange", true)}
    ${symList(pydantic,  "pydantic", "blue",   true)}
    ${refByHTML}${featHTML}${testsHTML}
    <div class="section">
      <div class="section-title">Ask Citadel</div>
      <div class="ask-chip-row">
        <button class="ask-chip" onclick="askCitadel('What does the file ${esc(askFileId)} do?')">What does this file do?</button>
        <button class="ask-chip" onclick="askCitadel('What can I reuse from ${esc(askFileId)}?')">What can I reuse?</button>
        <button class="ask-chip" onclick="askCitadel('What tests cover ${esc(askFileId)}?')">What tests cover this?</button>
        <button class="ask-chip" onclick="askCitadel('What depends on ${esc(askFileId)}?')">What depends on this?</button>
        <button class="ask-chip" onclick="askCitadel('What features are related to ${esc(askFileId)}?')">Related features</button>
      </div>
    </div>`;
}
