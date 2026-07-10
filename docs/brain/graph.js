"use strict";

const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
}[ch]));

const COLOR = {
  agent: "#38bdf8", workflow: "#a78bfa", topic: "#22d3ee", skill: "#34d399",
  tool: "#c084fc", knowledge: "#67e8f9", "memory-file": "#fb7185", rule: "#fbbf24",
  domain: "#6ee7b7", "test-suite": "#facc15", "validation-gate": "#f59e0b",
  "failure-pattern": "#f87171", "successful-pattern": "#4ade80",
  "directory-brain": "#2dd4bf", artifact: "#e879f9", "source-file": "#64748b",
  directory: "#10b981", capsule: "#818cf8", manifest: "#f472b6",
  "code-module": "#34d399", unknown: "#64748b",
  feature: "#f97316",   // orange â€” feature rollups from git history
  bug: "#ef4444",       // red â€” bug fix rollups from git history
};

const IMPORTANT_TYPES = new Set([
  "agent", "workflow", "topic", "domain", "validation-gate", "knowledge", "memory-file", "artifact",
  "feature", "bug",
]);
const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

let Graph = null;
let graphRaw = null;
let graphNodes = [];
let graphLinks = [];
let visibleNodes = [];
let visibleLinks = [];
let nodeById = new Map();
let adjacency = new Map();
let degreeMap = new Map();
let typeCounts = new Map();
let typeVisible = new Map();
let searchMatchIds = new Set();
let highlightIds = new Set();
let selectedId = null;
let hoveredNode = null;
let systemHealth = null;
let autoRotate = false;
let lastPointer = null;
let toastTimer = null;
let voiceEnabled = false;
let voiceUnlocked = false;
let voiceQueue = [];
let voiceSpeaking = false;
let selectedVoice = null;
let activeAudio = null;
let fallbackSvg = null;

const dom = {};

document.addEventListener("DOMContentLoaded", () => {
  cacheDom();
  // Ensure panels start closed regardless of cached HTML state
  setCommandPanelOpen(false);
  setInspectorPanelOpen(false);
  closeAskPanel();
  bindUi();
  updateVoiceUi();
  setStatus("Booting Citadel...");
  Promise.allSettled([loadSystemHealth(), loadGraph()]).then(() => {
    setStatus("Online");
  });
});

function cacheDom() {
  Object.assign(dom, {
    body: document.body,
    graph: $("graph3d"),
    commandPanel: $("command-panel"),
    inspectorPanel: $("inspector-panel"),
    search: $("search"),
    searchResults: $("search-results"),
    stats: $("stats"),
    health: $("health"),
    healthPill: $("health-pill"),
    healthPillText: $("health-pill-text"),
    details: $("details"),
    neighbors: $("neighbors"),
    tooltip: $("tooltip"),
    toast: $("toast"),
    status: $("status"),
    hoverStatus: $("hover-status"),
    viewStatus: $("view-status"),
    legend: $("legend"),
    askPanel: $("ask-citadel-panel"),
    askBtn: $("ask-citadel-btn"),
    askClose: $("ask-close-btn"),
    askClear: $("ask-clear-btn"),
    askInput: $("ask-input"),
    askSend: $("ask-send-btn"),
    askHistory: $("ask-history"),
    askLoading: $("ask-loading"),
    askLoadingMsg: $("ask-loading-msg"),
    askSourceBadge: $("ask-source-badge"),
    askModelBadge: $("ask-model-badge"),
    askModeButtons: document.querySelectorAll(".ask-mode-btn"),
    voiceBtn: $("voice-btn"),
    voiceMode: $("voice-mode"),
    voiceEngine: $("voice-engine"),
    depth: $("depth"),
    labels: $("labels"),
    sizeScale: $("size-scale"),
    perfMode: $("perf-mode")
  });
}

function bindUi() {
  // Command panel toggle (topbar button + health pill click)
  bind("command-toggle", "click", () => setCommandPanelOpen(!dom.commandPanel?.classList.contains("open")));
  bind("command-close",  "click", () => setCommandPanelOpen(false));
  bind("health-pill",    "click", () => setCommandPanelOpen(true));

  // Inspector panel close
  bind("inspector-close", "click", () => setInspectorPanelOpen(false));

  // Graph control buttons
  bind("reset-btn",       "click", resetCamera);
  bind("fit-btn",         "click", fitGraph);
  bind("fit-btn2",        "click", fitGraph);
  bind("focus-btn",       "click", focusSelected);
  bind("focus-btn2",      "click", focusSelected);
  bind("clear-btn",       "click", clearSelection);
  bind("reload-btn",      "click", reloadAll);
  bind("export-btn",      "click", exportPng);
  bind("rotate-btn",      "click", toggleRotate);
  bind("types-all-btn",   "click", () => setAllTypes(true));
  bind("types-clear-btn", "click", () => setAllTypes(false));
  bind("health-reload-btn","click", () => loadSystemHealth(true));
  bind("voice-btn",       "click", toggleVoice);
  bind("workspace-btn",   "click", () => { location.href = "/brain/workspace.html"; });
  bind("tasks-btn",       "click", () => { location.href = "/brain/tasks.html"; });

  [dom.depth, dom.labels, dom.sizeScale, dom.perfMode].forEach((el) => {
    if (!el) return;
    el.addEventListener("input", () => {
      if (el === dom.perfMode) notify("Quality mode updated");
      refreshGraphVisuals();
    });
  });

  if (dom.voiceMode)   dom.voiceMode.addEventListener("change",   () => localStorage.setItem("citadelVoiceMode", dom.voiceMode.value));
  if (dom.voiceEngine) dom.voiceEngine.addEventListener("change", () => localStorage.setItem("citadelVoiceEngine", dom.voiceEngine.value));

  dom.search?.addEventListener("input", onSearchInput);
  dom.search?.addEventListener("keydown", (e) => { if (e.key === "Escape") clearSearch(); });

  bindAskPanel();
  bindGraphPointer();

  window.addEventListener("resize", debounce(() => {
    if (Graph && dom.graph) Graph.width(dom.graph.clientWidth).height(dom.graph.clientHeight);
    if (fallbackSvg) drawFallback2d();
  }, 120));

  document.addEventListener("keydown", (e) => {
    const target = e.target;
    const typing = target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
    if (e.key === "Escape") {
      closeAskPanel();
      clearSelection();
      setCommandPanelOpen(false);
      setInspectorPanelOpen(false);
      return;
    }
    if (typing) return;
    if (e.key === "/")               { e.preventDefault(); dom.search?.focus(); }
    if (e.key.toLowerCase() === "f") fitGraph();
    if (e.key.toLowerCase() === "r") toggleRotate();
  });
}

function bind(id, event, handler) {
  const el = $(id);
  if (el) el.addEventListener(event, handler);
}

/* ---- Panel state helpers ---- */

function setCommandPanelOpen(open) {
  if (!dom.commandPanel) return;
  dom.commandPanel.classList.toggle("open", open);
  dom.commandPanel.setAttribute("aria-hidden", open ? "false" : "true");
}

function setInspectorPanelOpen(open) {
  if (!dom.inspectorPanel) return;
  dom.inspectorPanel.classList.toggle("open", open);
  dom.inspectorPanel.setAttribute("aria-hidden", open ? "false" : "true");
}

function bindAskPanel() {
  dom.askBtn?.addEventListener("click", toggleAskPanel);
  dom.askClose?.addEventListener("click", closeAskPanel);
  dom.askClear?.addEventListener("click", () => {
    if (dom.askHistory) dom.askHistory.innerHTML = "";
    setAskBadge("local", "Local answer first");
  });
  dom.askSend?.addEventListener("click", askCitadel);
  dom.askInput?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); askCitadel(); }
  });
  document.querySelectorAll(".ask-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      if (dom.askInput) dom.askInput.value = chip.dataset.q || chip.textContent.trim();
      askCitadel();
    });
  });

  // Wire the Local / Citadel mode buttons.
  dom.askModeButtons?.forEach((btn) => {
    btn.addEventListener("click", () => {
      dom.askModeButtons.forEach((b) => {
        const on = b === btn;
        b.classList.toggle("active", on);
        b.setAttribute("aria-pressed", String(on));
      });
      const claude = btn.dataset.mode === "citadel";
      setAskModelBadge(claude ? "model" : "muted", claude ? "Claude CLI" : "Local first");
      setAskBadge("local", "Local answer first");
    });
  });

  // Initialise the model badge from /api/health (non-blocking).
  fetch("/api/health")
    .then((r) => r.json())
    .then((h) => {
      const enabled = h?.config?.allow_model_fallback;
      setAskModelBadge(enabled ? "model" : "muted", enabled ? "Claude CLI ready" : "Local only");
    })
    .catch(() => setAskModelBadge("muted", "Provider unknown"));
}

function bindGraphPointer() {
  if (!dom.graph) return;
  dom.graph.addEventListener("pointermove", (e) => {
    lastPointer = { x: e.clientX, y: e.clientY, t: Date.now() };
    moveTooltip(e.clientX, e.clientY);
  });
  dom.graph.addEventListener("pointerleave", () => {
    lastPointer = null;
    hideTooltip();
    dom.graph.classList.remove("dragging");
  });
  dom.graph.addEventListener("pointerdown", () => {
    dom.graph.classList.add("dragging");
  });
  dom.graph.addEventListener("pointerup", () => {
    dom.graph.classList.remove("dragging");
  });
  dom.graph.addEventListener("pointercancel", () => {
    dom.graph.classList.remove("dragging");
  });
}

/* ---- Data fetching ---- */

async function fetchJson(urls) {
  let lastError = null;
  for (const url of urls) {
    try {
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      return await res.json();
    } catch (err) {
      lastError = err;
    }
  }
  throw lastError || new Error("No URL candidates provided");
}

/* ---- Health payload helpers ---- */

function isValidHealth(h) {
  return !!(h && typeof h === "object" &&
    (h.overall_status || Array.isArray(h.checks) || h.summary));
}

function normalizeHealthPayload(payload) {
  if (!payload || typeof payload !== "object") return null;
  // check each possible wrapping shape, most-specific first
  const candidates = [
    payload.health,                                                                          // wrapped: payload.health.*
    (payload.status && typeof payload.status === "object") ? payload.status.health : null,  // status wrapper
    (payload.data   && typeof payload.data   === "object") ? payload.data.health   : null,  // data wrapper
    payload,                                                                                 // raw system-status shape
  ];
  for (const c of candidates) {
    if (isValidHealth(c)) return c;
  }
  return null;
}

async function loadSystemHealth(refresh = false) {
  const apiUrl      = refresh ? "/api/health?refresh=1" : "/api/health";
  const fallbackUrls = ["system-status.json", "/brain/system-status.json"];
  // 1. try /api/health; normalize; fall back if no usable health object
  try {
    const payload = await fetchJson([apiUrl]);
    const health  = normalizeHealthPayload(payload);
    if (!health) throw new Error("/api/health returned no usable health object");
    systemHealth = health;
    renderHealth(systemHealth);
    return systemHealth;
  } catch (_errApi) {
    // 2. fall back to static system-status.json
    try {
      const payload = await fetchJson(fallbackUrls);
      const health  = normalizeHealthPayload(payload);
      if (!health) throw new Error("system-status.json returned no usable health object");
      systemHealth = health;
      renderHealth(systemHealth);
      return systemHealth;
    } catch (errFile) {
      systemHealth = null;
      renderHealthError(errFile);
      return null;
    }
  }
}

async function loadGraph() {
  try {
    setStatus("Loading graph...");
    graphRaw = await fetchJson(["graph.json", "/brain/graph.json"]);
    await _mergeRepoPointers(graphRaw);
    normalizeGraph(graphRaw);
    buildGraphIndexes();
    renderStats();
    renderLegend();
    renderGraph();
    setStatus(`${graphNodes.length}/${graphLinks.length} loaded`);
    notify("Graph loaded");
  } catch (err) {
    setStatus("Graph failed to load");
    notify("Graph load failed");
    if (dom.graph) dom.graph.innerHTML = `<div class="empty-state"><span>!</span><p>graph.json failed to load: ${esc(err.message)}</p></div>`;
  }
}

// Merge per-repo pointer nodes (from the sharded O(1) graph) so every workspace repo
// appears as a node; the full per-repo shard is lazy-loaded only on drill-in (see
// _loadRepoShard). Optional â€” silently skips if repos-graph.json is absent.
async function _mergeRepoPointers(raw) {
  let repos;
  try {
    repos = await fetchJson(["repos-graph.json", "/brain/repos-graph.json"]);
  } catch (_) {
    return;
  }
  if (!repos || !Array.isArray(repos.nodes) || !repos.nodes.length) return;
  raw.nodes = raw.nodes || [];
  raw.links = raw.links || [];
  const existing = new Set(raw.nodes.map((n) => String(n.id)));
  const ROOT_ID = "workspace:root";
  if (!existing.has(ROOT_ID)) {
    raw.nodes.push({ id: ROOT_ID, title: "Workspace", type: "workspace", tags: [] });
    existing.add(ROOT_ID);
  }
  for (const rn of repos.nodes) {
    const id = String(rn.id);
    if (!existing.has(id)) {
      raw.nodes.push({
        id, type: "repo", tags: [],
        title: `${rn.repo || id} (${rn.node_count || 0})`,
        graph_ref: rn.graph_ref || "", node_count: rn.node_count || 0
      });
      existing.add(id);
    }
    raw.links.push({ source: ROOT_ID, target: id, type: "contains" });
  }
}

function normalizeGraph(raw) {
  graphNodes = (raw.nodes || []).map((node) => ({
    id: String(node.id),
    title: String(node.title || node.label || node.id),
    type: String(node.type || "unknown"),
    path: node.path || "",
    tags: Array.isArray(node.tags) ? node.tags : [],
    files: Array.isArray(node.files) ? node.files : [],
    graph_ref: node.graph_ref || "",
    node_count: node.node_count || 0
  }));
  const ids = new Set(graphNodes.map((n) => n.id));
  graphLinks = (raw.links || []).map((link, index) => {
    const source = typeof link.source === "object" ? String(link.source.id) : String(link.source);
    const target = typeof link.target === "object" ? String(link.target.id) : String(link.target);
    return { id: `l-${index}`, source, target, type: link.type || "related_to" };
  }).filter((link) => ids.has(link.source) && ids.has(link.target));
}

function buildGraphIndexes() {
  nodeById  = new Map(graphNodes.map((n) => [n.id, n]));
  adjacency = new Map(graphNodes.map((n) => [n.id, new Set()]));
  degreeMap = new Map(graphNodes.map((n) => [n.id, 0]));
  typeCounts = new Map();

  for (const node of graphNodes) typeCounts.set(node.type, (typeCounts.get(node.type) || 0) + 1);
  for (const link of graphLinks) {
    adjacency.get(link.source)?.add(link.target);
    adjacency.get(link.target)?.add(link.source);
    degreeMap.set(link.source, (degreeMap.get(link.source) || 0) + 1);
    degreeMap.set(link.target, (degreeMap.get(link.target) || 0) + 1);
  }
  typeVisible = new Map([...typeCounts.keys()].sort().map((t) => [t, true]));
  applyVisibility();
}

function applyVisibility() {
  const visibleIds = new Set(graphNodes.filter((n) => typeVisible.get(n.type) !== false).map((n) => n.id));
  visibleNodes = graphNodes.filter((n) => visibleIds.has(n.id));
  visibleLinks = graphLinks.filter((l) => {
    const src = typeof l.source === "object" ? l.source.id : l.source;
    const tgt = typeof l.target === "object" ? l.target.id : l.target;
    return visibleIds.has(src) && visibleIds.has(tgt);
  });
}

/* ---- Graph rendering ---- */

function renderGraph() {
  if (window.ForceGraph3D && window.THREE && dom.graph) {
    render3dGraph();
  } else {
    renderFallback2d();
  }
}

function render3dGraph() {
  if (!dom.graph) return;
  dom.graph.innerHTML = "";
  fallbackSvg = null;
  Graph = ForceGraph3D({
    controlType: "orbit",
    rendererConfig: { antialias: true, alpha: true, preserveDrawingBuffer: true }
  })(dom.graph);

  Graph
    .backgroundColor("rgba(0,0,0,0)")
    .width(dom.graph.clientWidth)
    .height(dom.graph.clientHeight)
    .nodeId("id")
    .nodeVal((node) => nodeSize(node))
    .nodeColor((node) => nodeColor(node))
    .nodeLabel(() => "")
    .linkColor((link) => linkColor(link))
    .linkWidth((link) => linkWidth(link))
    .linkOpacity(0.48)
    .linkDirectionalParticles(() => (selectedId ? 1 : 0))
    .linkDirectionalParticleWidth(1.2)
    .linkDirectionalParticleSpeed(0.004)
    .nodeThreeObjectExtend(true)
    .nodeThreeObject((node) => makeNodeLabel(node))
    .onNodeHover((node) => onNodeHover(node))
    .onNodeClick((node, event) => onNodeClick(node, event))
    .onNodeRightClick((node, event) => onNodeClick(node, event))
    .onNodeDragEnd((node) => { node.fx = node.x; node.fy = node.y; node.fz = node.z; })
    .graphData({ nodes: visibleNodes, links: visibleLinks });

  try {
    Graph.d3Force("charge").strength(-55).distanceMax(180);
    Graph.d3Force("link").distance(30).strength(0.65);
    Graph.d3VelocityDecay(0.42);
    Graph.cooldownTicks(120);
    Graph.warmupTicks(80);
  } catch (_) {
    // ForceGraph version differences are non-fatal.
  }

  if (Graph.controls()) {
    Graph.controls().enableDamping = true;
    Graph.controls().dampingFactor = 0.08;
  }

  if (dom.viewStatus) dom.viewStatus.textContent = "3D mode";
  setTimeout(() => focusCore(),            1300);
  setTimeout(() => refreshGraphVisuals(),  1600);
}

function renderFallback2d() {
  Graph = null;
  if (dom.viewStatus) dom.viewStatus.textContent = "2D fallback";
  if (!dom.graph) return;
  dom.graph.innerHTML = `<div class="fallback-2d"><svg id="fallback-svg" role="img" aria-label="2D graph fallback"></svg></div>`;
  fallbackSvg = $("fallback-svg");
  drawFallback2d();
  notify("3D engine unavailable. Fallback mode engaged.");
}

function drawFallback2d() {
  if (!fallbackSvg || !dom.graph) return;
  applyVisibility();
  const w = dom.graph.clientWidth || 800;
  const h = dom.graph.clientHeight || 600;
  const cx = w / 2, cy = h / 2;
  const radius = Math.min(w, h) * 0.36;
  const nodes = visibleNodes.map((node, i) => {
    const angle = i * 2.39996323;
    const r = radius * Math.sqrt((i + 1) / Math.max(1, visibleNodes.length));
    return { ...node, x: cx + Math.cos(angle) * r, y: cy + Math.sin(angle) * r };
  });
  const pos = new Map(nodes.map((n) => [n.id, n]));
  const links = visibleLinks.filter((l) => pos.has(l.source) && pos.has(l.target));
  fallbackSvg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  fallbackSvg.innerHTML = `${links.map((l) => {
    const s = pos.get(l.source), t = pos.get(l.target);
    return `<line class="fallback-link" x1="${s.x}" y1="${s.y}" x2="${t.x}" y2="${t.y}"/>`;
  }).join("")}${nodes.map((node) => `
    <g class="fallback-node" data-id="${esc(node.id)}" transform="translate(${node.x},${node.y})">
      <circle r="${nodeSize(node) + 2}" fill="${nodeColor(node)}"></circle>
      ${shouldShowLabel(node) ? `<text class="fallback-label" x="9" y="4">${esc(node.title)}</text>` : ""}
    </g>`).join("")}`;
  fallbackSvg.querySelectorAll(".fallback-node").forEach((el) => {
    el.addEventListener("click", (e) => {
      const node = nodeById.get(el.dataset.id);
      onNodeClick(node, e);
    });
  });
}

/* ---- Node rendering helpers ---- */

function makeNodeLabel(node) {
  if (!window.SpriteText || !shouldShowLabel(node)) return null;
  const label = new window.SpriteText(node.title || node.id);
  label.textHeight = selectedId === node.id ? 5.8 : 4.1;
  label.color = selectedId === node.id ? "#ffffff" : "#bcd2e8";
  label.backgroundColor = selectedId === node.id ? "rgba(8,15,32,0.58)" : "rgba(8,15,32,0.18)";
  label.padding = 2;
  label.borderRadius = 4;
  label.position.y = nodeSize(node) + 5;
  return label;
}

function nodeSize(node) {
  const scale = Number(dom.sizeScale?.value || 115) / 100;
  return Math.max(3, (3.2 + Math.sqrt(degreeMap.get(node.id) || 0) * 1.15) * scale);
}

function nodeColor(node) {
  const base = COLOR[node.type] || COLOR.unknown;
  if (selectedId === node.id) return "#ffffff";
  if (searchMatchIds.size && searchMatchIds.has(node.id)) return "#34d399";
  if (highlightIds.size && highlightIds.has(node.id)) return base;
  if (highlightIds.size || searchMatchIds.size) return "#1f2937";
  return base;
}

function linkColor(link) {
  const src = typeof link.source === "object" ? link.source.id : link.source;
  const tgt = typeof link.target === "object" ? link.target.id : link.target;
  if (selectedId && (src === selectedId || tgt === selectedId)) return "rgba(36,215,255,0.92)";
  if (highlightIds.size && (highlightIds.has(src) || highlightIds.has(tgt))) return "rgba(36,215,255,0.35)";
  if (searchMatchIds.size && searchMatchIds.has(src) && searchMatchIds.has(tgt)) return "rgba(54,211,153,0.72)";
  if (highlightIds.size || searchMatchIds.size) return "rgba(36,52,78,0.18)";
  return "rgba(80,140,190,0.30)";
}

function linkWidth(link) {
  const src = typeof link.source === "object" ? link.source.id : link.source;
  const tgt = typeof link.target === "object" ? link.target.id : link.target;
  if (selectedId && (src === selectedId || tgt === selectedId)) return 2.1;
  if (highlightIds.size && (highlightIds.has(src) || highlightIds.has(tgt))) return 1.1;
  return 0.45;
}

function shouldShowLabel(node) {
  const mode = dom.labels?.value || "important";
  if (mode === "none") return false;
  if (mode === "all") return true;
  if (mode === "selected") return selectedId === node.id;
  return IMPORTANT_TYPES.has(node.type) || (degreeMap.get(node.id) || 0) >= 10 || selectedId === node.id;
}

function refreshGraphVisuals() {
  applyVisibility();
  if (Graph) {
    Graph
      .graphData({ nodes: visibleNodes, links: visibleLinks })
      .nodeVal((node) => nodeSize(node))
      .nodeColor((node) => nodeColor(node))
      .linkColor((link) => linkColor(link))
      .linkWidth((link) => linkWidth(link))
      .nodeThreeObject((node) => makeNodeLabel(node));
  } else if (fallbackSvg) {
    drawFallback2d();
  }
  renderStats();
}

/* ---- Node interaction ---- */

function onNodeClick(node, event) {
  if (!node) return;
  const now = Date.now();
  selectedId = node.id;
  const depth = Number(dom.depth?.value || 1);
  highlightIds = getNeighborhood(node.id, depth);
  renderDetails(node);
  renderNeighbors(node);
  refreshGraphVisuals();
  focusNode(node);
  const point = eventPoint(event) || lastPointer || projectedPoint(node);
  if (point) triggerClickWave(point.x, point.y, node.title || node.id);
  setInspectorPanelOpen(true);
  if (dom.hoverStatus) dom.hoverStatus.textContent = node.title || node.id;
  if (now - (onNodeClick.lastSpeak || 0) > 900) {
    speakNodeName(node.title || node.id);
    onNodeClick.lastSpeak = now;
  }
}

function onNodeHover(node) {
  hoveredNode = node || null;
  if (dom.graph) dom.graph.classList.toggle("hovering-node", Boolean(node));
  if (!node) {
    hideTooltip();
    if (!selectedId && dom.hoverStatus) dom.hoverStatus.textContent = "No node selected";
    return;
  }
  if (dom.hoverStatus) dom.hoverStatus.textContent = node.title || node.id;
  showTooltip(node);
}

function projectedPoint(node) {
  if (!Graph || typeof Graph.graph2ScreenCoords !== "function" || !Number.isFinite(node.x)) return null;
  const p = Graph.graph2ScreenCoords(node.x, node.y, node.z);
  return p && Number.isFinite(p.x) ? { x: p.x, y: p.y } : null;
}

function eventPoint(event) {
  const e = event?.srcEvent || event?.originalEvent || event;
  if (e && Number.isFinite(e.clientX) && Number.isFinite(e.clientY)) return { x: e.clientX, y: e.clientY };
  return null;
}

/* ---- Click wave ---- */

function triggerClickWave(x, y, label) {
  if (!Number.isFinite(x) || !Number.isFinite(y)) return;
  let layer = document.querySelector(".click-wave-layer");
  if (!layer) {
    layer = document.createElement("div");
    layer.className = "click-wave-layer";
    layer.setAttribute("aria-hidden", "true");
    document.body.appendChild(layer);
  }
  const wave = document.createElement("div");
  wave.className = "click-wave";
  wave.style.left = `${x}px`;
  wave.style.top  = `${y}px`;
  layer.appendChild(wave);
  wave.addEventListener("animationend", () => wave.remove(), { once: true });

  if (label && !REDUCED_MOTION) {
    const labelEl = document.createElement("div");
    labelEl.className = "click-wave-label";
    labelEl.style.left = `${x}px`;
    labelEl.style.top  = `${y}px`;
    labelEl.textContent = label;
    layer.appendChild(labelEl);
    labelEl.addEventListener("animationend", () => labelEl.remove(), { once: true });
  }
}

/* ---- Graph traversal ---- */

function getNeighborhood(id, depth) {
  const visited = new Set([id]);
  let frontier = new Set([id]);
  for (let step = 0; step < depth; step++) {
    const next = new Set();
    for (const cur of frontier) {
      for (const nb of adjacency.get(cur) || []) {
        if (!visited.has(nb)) { visited.add(nb); next.add(nb); }
      }
    }
    frontier = next;
    if (!frontier.size) break;
  }
  return visited;
}

/* ---- Inspector rendering ---- */

function renderDetails(node) {
  if (!dom.details) return;
  const files = node.files || [], tags = node.tags || [];
  const nodeTitle = node.title || node.id;

  dom.details.innerHTML = `
    <h3 id="node-title">${esc(nodeTitle)}</h3>
    <div id="node-id">${esc(node.id)}</div>
    <span class="type-badge" style="color:${esc(COLOR[node.type] || COLOR.unknown)}">${esc(node.type)}</span>
    <div class="detail-row"><span class="detail-key">Degree</span><span class="detail-val">${degreeMap.get(node.id) || 0}</span></div>
    ${node.path ? `<div class="detail-row"><span class="detail-key">Path</span><span class="detail-val">${esc(node.path)}</span></div>` : ""}
    ${tags.length ? `<div class="section-title">Tags</div><div>${tags.map((t) => `<span class="type-badge" style="color:#a78bfa">${esc(t)}</span>`).join(" ")}</div>` : ""}
    ${files.length ? `<div class="section-title">Files</div>${files.slice(0, 8).map((f) => `<a class="file-link" href="#" title="${esc(f)}">${esc(f)}</a>`).join("")}` : ""}
    <div class="section-title" style="margin-top:14px">Ask Citadel</div>
    <div class="inspector-actions">
      <button class="ask-chip" type="button" data-ask-tpl="What does {t} do?">What does this do?</button>
      <button class="ask-chip" type="button" data-ask-tpl="What is {t} in charge of?">What is it in charge of?</button>
      <button class="ask-chip" type="button" data-ask-tpl="What is connected to {t}?">Show connections</button>
      <button class="ask-chip" type="button" data-ask-tpl="What files does {t} reference?">Show referenced files</button>
      <button class="ask-chip" type="button" data-ask-tpl="What workflows are related to {t}?">Find related workflows</button>
      <button class="ask-chip" type="button" data-ask-tpl="What agents are related to {t}?">Find related agents</button>
      <button class="ask-chip" type="button" data-ask-tpl="What knowledge is related to {t}?">Find related knowledge</button>
      <button class="ask-chip" type="button" data-ask-tpl="Tell me about {t}">Ask Citadel about this node</button>
      <button class="ask-chip" type="button" data-copy-node-id="1">Copy node ID</button>
      <button class="ask-chip" type="button" data-focus-node="1">Focus graph here</button>
    </div>
  `;

  // Wire inspector action chips
  dom.details.querySelectorAll("[data-ask-tpl]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const q = btn.dataset.askTpl.replace(/\{t\}/g, nodeTitle);
      if (dom.askInput) dom.askInput.value = q;
      setAskPanelOpen(true);
      askCitadel();
    });
  });
  dom.details.querySelector("[data-copy-node-id]")?.addEventListener("click", () => {
    navigator.clipboard?.writeText(node.id).then(() => notify("Node ID copied"));
  });
  dom.details.querySelector("[data-focus-node]")?.addEventListener("click", () => {
    focusNode(node);
  });

  // Lazy-load commit history for feature/bug nodes (O(1) via commit-index.json)
  if ((node.type === "feature" || node.type === "bug") && node.path) {
    _loadCommitHistory(node);
  }

  // Lazy-load a repo's shard graph only when its pointer node is opened (O(1) via graph_ref).
  if (node.type === "repo" && node.graph_ref) {
    _loadRepoShard(node);
  }
}

let shardStack = []; // holds the workspace-level {nodes,links} while a shard is open

async function _loadRepoShard(node) {
  if (!dom.details) return;
  const rel = String(node.graph_ref).replace(/^docs\/brain\//, "");
  let shard;
  try {
    shard = await fetchJson([rel, "/brain/" + rel]);
  } catch (_) {
    return;
  }
  const nodes = Array.isArray(shard.nodes) ? shard.nodes : [];
  const links = Array.isArray(shard.links) ? shard.links : [];
  const byType = shard.by_type || {};
  const typeLine = Object.entries(byType).map(([k, v]) => `${esc(k)}: ${v}`).join(" Â· ");
  const items = nodes.slice(0, 25).map((n) =>
    `<li><span class="type-badge" style="color:${esc(COLOR[n.type] || COLOR.unknown)}">${esc(n.type)}</span> ${esc(n.title || n.id)}</li>`
  ).join("");
  const div = document.createElement("div");
  div.innerHTML =
    `<div class="section-title" style="margin-top:14px">Repo shard â€” ${esc(shard.node_count || nodes.length)} nodes, ${esc(shard.link_count ?? links.length)} links</div>`
    + (typeLine ? `<div class="muted" style="font-size:11px">${typeLine}</div>` : "")
    + (nodes.length ? `<button class="ask-chip" type="button" data-open-shard-graph="1" style="margin:6px 0">Open as graph</button>` : "")
    + `<ul style="font-size:12px;line-height:1.6;padding-left:14px">${items}</ul>`
    + (nodes.length > 25 ? `<div class="muted" style="font-size:11px">â€¦and ${nodes.length - 25} more (open as graph to see all)</div>` : "");
  dom.details.appendChild(div);

  div.querySelector("[data-open-shard-graph]")?.addEventListener("click", () => {
    _enterShardGraph(node, nodes, links);
  });
}

// Swap the live force-graph to a repo's real structural sub-graph (symbols, modules,
// commits, and their intra-file call/import edges â€” see build_sharded_brain_graph.py).
// This is a one-hop drill-in by design (the "1 + N repo graphs" the pointer graph
// links to), not a recursive tree, so shardStack only ever needs one saved level.
function _enterShardGraph(repoNode, shardNodes, shardLinks) {
  if (!shardStack.length) {
    shardStack.push({ nodes: graphNodes, links: graphLinks });
  }
  const normalizedNodes = shardNodes.map((n) => ({
    id: String(n.id),
    title: String(n.title || n.id),
    type: String(n.type || "unknown"),
    path: n.path || "",
    tags: [],
    files: [],
    graph_ref: "",
    node_count: 0
  }));
  const idSet = new Set(normalizedNodes.map((n) => n.id));
  const normalizedLinks = shardLinks
    .filter((l) => idSet.has(String(l.source)) && idSet.has(String(l.target)))
    .map((l, i) => ({ id: `shard-l-${i}`, source: String(l.source), target: String(l.target), type: l.type || "related_to" }));

  graphNodes = normalizedNodes;
  graphLinks = normalizedLinks;
  buildGraphIndexes();
  renderStats();
  renderLegend();
  renderGraph();
  _renderShardBackButton(repoNode);
  setStatus(`${graphNodes.length}/${graphLinks.length} loaded â€” ${repoNode.title || repoNode.id} shard`);
  notify(`Opened ${repoNode.title || repoNode.id} shard`);
}

function _exitShardGraph() {
  const root = shardStack.shift();
  if (!root) return;
  graphNodes = root.nodes;
  graphLinks = root.links;
  shardStack = [];
  buildGraphIndexes();
  renderStats();
  renderLegend();
  renderGraph();
  _removeShardBackButton();
  setStatus(`${graphNodes.length}/${graphLinks.length} loaded`);
}

function _renderShardBackButton(repoNode) {
  _removeShardBackButton();
  if (!dom.graph || !dom.graph.parentElement) return;
  const btn = document.createElement("button");
  btn.id = "shard-back-btn";
  btn.className = "ask-chip";
  btn.type = "button";
  btn.style.cssText = "position:absolute;top:10px;left:10px;z-index:20";
  btn.textContent = `â† Back to workspace (from ${repoNode.title || repoNode.id})`;
  btn.addEventListener("click", _exitShardGraph);
  dom.graph.parentElement.appendChild(btn);
}

function _removeShardBackButton() {
  document.getElementById("shard-back-btn")?.remove();
}

async function _loadCommitHistory(node) {
  if (!dom.details) return;
  // Append a placeholder section immediately (non-blocking)
  const historyEl = document.createElement("div");
  historyEl.id = "commit-history-section";
  historyEl.innerHTML = `<div class="section-title" style="margin-top:14px">Commit History</div><div class="muted" style="font-size:11px">Loadingâ€¦</div>`;
  dom.details.appendChild(historyEl);

  try {
    // Serve from docs/ static tree: docs/brain/nodes/features/â€¦ â†’ /brain/nodes/features/â€¦
    const mdUrl = "/" + node.path.replace(/^docs\//, "");
    const res = await fetch(mdUrl, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const text = await res.text();

    // Detect pointer file (has chunk links) vs direct rollup
    const chunkLinks = [...text.matchAll(/- \[([^\]]+)\]\(([^)]+)\)/g)];
    const commitLines = [...text.matchAll(/^- `([a-f0-9]{6,8})` \*\*([^*]+)\*\*[^\n]*/gm)];
    const commitCount = (text.match(/commit_count:\s*(\d+)/) || [])[1] || "";

    let html = `<div class="section-title" style="margin-top:14px">Commit History${commitCount ? " (" + commitCount + ")" : ""}</div>`;

    if (chunkLinks.length > 0 && commitLines.length === 0) {
      // Pointer file â€” render chunk links for lazy drill-down
      html += `<div class="muted" style="font-size:11px;margin-bottom:6px">Large feature â€” ${chunkLinks.length} chunk(s). Click to expand.</div>`;
      chunkLinks.slice(0, 10).forEach(([, label, path]) => {
        html += `<a class="file-link" href="#" data-chunk-md="${esc(path)}" title="${esc(label)}">${esc(label.split("/").pop())}</a>`;
      });
    } else {
      // Direct rollup â€” render commit list inline
      commitLines.slice(0, 40).forEach(([, sha, title]) => {
        html += `<div style="font-size:11px;margin:3px 0"><code style="color:${esc(COLOR.feature || "#f97316")}">${esc(sha)}</code> ${esc(title)}</div>`;
      });
      if (commitLines.length > 40) {
        html += `<div class="muted" style="font-size:11px">â€¦and ${commitLines.length - 40} more</div>`;
      }
      if (commitLines.length === 0) {
        html += `<div class="muted" style="font-size:11px">No commits listed in rollup.</div>`;
      }
    }

    historyEl.innerHTML = html;

    // Wire chunk link clicks â€” fetch chunk .md and render its commit list inline
    historyEl.querySelectorAll("[data-chunk-md]").forEach((el) => {
      el.addEventListener("click", async (e) => {
        e.preventDefault();
        el.textContent = "Loadingâ€¦";
        try {
          const cUrl = "/" + el.dataset.chunkMd.replace(/^docs\//, "");
          const cr = await fetch(cUrl, { cache: "no-store" });
          if (!cr.ok) throw new Error(`HTTP ${cr.status}`);
          const ct = await cr.text();
          const cls = [...ct.matchAll(/^- `([a-f0-9]{6,8})` \*\*([^*]+)\*\*[^\n]*/gm)];
          let inner = `<div class="section-title">Chunk commits</div>`;
          cls.slice(0, 50).forEach(([, sha, title]) => {
            inner += `<div style="font-size:11px;margin:3px 0"><code style="color:${esc(COLOR.feature || "#f97316")}">${esc(sha)}</code> ${esc(title)}</div>`;
          });
          if (cls.length === 0) inner += `<div class="muted" style="font-size:11px">No commits in chunk.</div>`;
          el.outerHTML = inner;
        } catch (err) {
          el.textContent = `Error: ${err.message}`;
        }
      });
    });
  } catch (err) {
    historyEl.innerHTML = `<div class="section-title" style="margin-top:14px">Commit History</div><div class="muted" style="font-size:11px">Could not load: ${esc(String(err))}</div>`;
  }
}

function renderNeighbors(node) {
  if (!dom.neighbors) return;
  const neighbors = [...(adjacency.get(node.id) || [])].map((id) => nodeById.get(id)).filter(Boolean)
    .sort((a, b) => (degreeMap.get(b.id) || 0) - (degreeMap.get(a.id) || 0));
  if (!neighbors.length) {
    dom.neighbors.innerHTML = `<div class="empty-state muted"><span>Â·Â·Â·</span><p>No connected nodes.</p></div>`;
    return;
  }
  dom.neighbors.innerHTML = neighbors.slice(0, 40).map((n) => `
    <button class="neighbor" type="button" data-id="${esc(n.id)}">
      <span>${esc(n.title || n.id)}</span>
      <span class="neighbor-type">${esc(n.type)}</span>
    </button>`).join("");
  dom.neighbors.querySelectorAll(".neighbor").forEach((el) => {
    el.addEventListener("click", () => onNodeClick(nodeById.get(el.dataset.id)));
  });
}

function clearSelection() {
  selectedId = null;
  setInspectorPanelOpen(false);
  highlightIds.clear();
  if (dom.details) dom.details.innerHTML = `<div class="empty-state"><span>â—Ž</span><p>Click any node to inspect it.</p></div>`;
  if (dom.neighbors) dom.neighbors.innerHTML = `<div class="empty-state muted"><span>Â·Â·Â·</span><p>No node selected.</p></div>`;
  if (dom.hoverStatus) dom.hoverStatus.textContent = "No node selected";
  refreshGraphVisuals();
}

/* ---- Stats & legend ---- */

function renderStats() {
  if (!dom.stats) return;
  const typeCount = typeCounts.size;
  const visibleTypeCount = [...typeVisible.values()].filter(Boolean).length;
  const maxDegreeNode = graphNodes.reduce(
    (best, node) => ((degreeMap.get(node.id) || 0) > (degreeMap.get(best?.id) || 0) ? node : best),
    graphNodes[0]
  );
  const agentCount = typeCounts.get("agent") || 0;
  dom.stats.innerHTML = `
    <div class="metric-card"><span class="metric-val">${visibleNodes.length}</span><span class="metric-label">Visible nodes</span></div>
    <div class="metric-card"><span class="metric-val">${visibleLinks.length}</span><span class="metric-label">Visible links</span></div>
    <div class="metric-card"><span class="metric-val">${graphNodes.length}</span><span class="metric-label">Total nodes</span></div>
    <div class="metric-card"><span class="metric-val">${agentCount}</span><span class="metric-label">Agents</span></div>
    <div class="metric-card"><span class="metric-val">${typeCount}</span><span class="metric-label">Node types</span></div>
    <div class="metric-card"><span class="metric-val">${visibleTypeCount}</span><span class="metric-label">Active types</span></div>
    <div class="metric-card full"><span class="metric-val">${esc(maxDegreeNode?.title || "-")}</span><span class="metric-label">Highest degree node</span></div>
  `;
}

function renderLegend() {
  if (!dom.legend) return;
  dom.legend.innerHTML = [...typeCounts.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([type, count]) => `
    <label class="legend-chip active" data-type="${esc(type)}">
      <input type="checkbox" checked aria-label="Toggle ${esc(type)} nodes">
      <span class="dot" style="background:${esc(COLOR[type] || COLOR.unknown)}"></span>
      <span>${esc(type)}</span>
      <span>${count}</span>
    </label>`).join("");
  dom.legend.querySelectorAll(".legend-chip").forEach((chip) => {
    chip.addEventListener("click", (event) => {
      event.preventDefault();
      const type = chip.dataset.type;
      const next = !typeVisible.get(type);
      typeVisible.set(type, next);
      chip.classList.toggle("active", next);
      chip.classList.toggle("inactive", !next);
      const input = chip.querySelector("input");
      if (input) input.checked = next;
      refreshGraphVisuals();
    });
  });
}

function setAllTypes(on) {
  for (const type of typeVisible.keys()) typeVisible.set(type, on);
  dom.legend?.querySelectorAll(".legend-chip").forEach((chip) => {
    chip.classList.toggle("active", on);
    chip.classList.toggle("inactive", !on);
    const input = chip.querySelector("input");
    if (input) input.checked = on;
  });
  refreshGraphVisuals();
}

/* ---- Search ---- */

function onSearchInput() {
  const query = dom.search?.value.trim().toLowerCase() || "";
  searchMatchIds.clear();
  if (!query) {
    if (dom.searchResults) dom.searchResults.style.display = "none";
    refreshGraphVisuals();
    return;
  }
  const matches = graphNodes.filter((n) => nodeText(n).includes(query)).slice(0, 24);
  matches.forEach((n) => searchMatchIds.add(n.id));
  renderSearchResults(matches);
  refreshGraphVisuals();
}

function nodeText(node) {
  return [node.id, node.title, node.type, node.path, ...(node.tags || []), ...(node.files || [])].join(" ").toLowerCase();
}

function renderSearchResults(matches) {
  if (!dom.searchResults) return;
  if (!matches.length) {
    dom.searchResults.innerHTML = `<div class="result-item"><span></span><div><div class="result-title">No results</div><div class="result-meta">Try another node, tag, file, or path.</div></div></div>`;
  } else {
    dom.searchResults.innerHTML = matches.map((node) => `
      <div class="result-item" role="option" data-id="${esc(node.id)}">
        <span class="result-dot" style="background:${esc(COLOR[node.type] || COLOR.unknown)}"></span>
        <div><div class="result-title">${esc(node.title)}</div><div class="result-meta">${esc(node.type)} Â· ${esc(node.id)}</div></div>
      </div>`).join("");
    dom.searchResults.querySelectorAll(".result-item[data-id]").forEach((item) => {
      item.addEventListener("click", () => {
        const node = nodeById.get(item.dataset.id);
        if (dom.searchResults) dom.searchResults.style.display = "none";
        if (node) onNodeClick(node);
      });
    });
  }
  dom.searchResults.style.display = "block";
}

function clearSearch() {
  if (dom.search) dom.search.value = "";
  searchMatchIds.clear();
  if (dom.searchResults) dom.searchResults.style.display = "none";
  refreshGraphVisuals();
}

/* ---- Health rendering ---- */

function renderHealth(health) {
  if (!dom.health || !dom.healthPill || !dom.healthPillText) return;
  const status  = String(health?.overall_status || "unknown").toLowerCase();
  const summary = health?.summary || {};
  const total   = Number(summary.green || 0) + Number(summary.yellow || 0) + Number(summary.red || 0);
  const checked = formatHealthTime(health);

  dom.healthPill.className = `health-pill is-${["green","yellow","red"].includes(status) ? status : "unknown"}`;
  dom.healthPillText.textContent = status === "green"
    ? `Green Â· ${summary.green || 0}/${total || 0}`
    : `${status.toUpperCase()} Â· ${summary.green || 0}/${total || 0}`;

  const icon = status === "green" ? "bi-check-circle-fill" : status === "red" ? "bi-x-circle-fill" : "bi-exclamation-triangle-fill";
  const checks = (health?.checks || []).map((c) => {
    const s = String(c.status || "unknown").toLowerCase();
    const i = s === "green" ? "bi-check-circle-fill" : s === "red" ? "bi-x-circle-fill" : "bi-exclamation-triangle-fill";
    return `<div class="health-check"><i class="bi ${i} ${esc(s)}"></i><div><strong>${esc(c.name)}</strong><br><span>${esc(c.details || c.evidence || "")}</span></div></div>`;
  }).join("");

  dom.health.innerHTML = `
    <div class="health-summary-card">
      <div class="health-status-line">
        <span class="status-chip ${esc(status)}"><i class="bi ${icon}"></i> ${esc(status)}</span>
        <span class="health-time" title="Browser timezone: ${esc(Intl.DateTimeFormat().resolvedOptions().timeZone || "local")}">${esc(checked)}</span>
      </div>
      <div class="health-counts">
        <span>Green ${summary.green || 0}</span>
        <span>Yellow ${summary.yellow || 0}</span>
        <span>Red ${summary.red || 0}</span>
      </div>
      <div class="health-checks">${checks || `<div class="health-check"><i class="bi bi-question-circle yellow"></i><div>No detailed checks available.</div></div>`}</div>
    </div>`;
}

function renderHealthError(err) {
  if (!dom.healthPill || !dom.healthPillText || !dom.health) return;
  dom.healthPill.className = "health-pill is-yellow";
  dom.healthPillText.textContent = "Health unavailable";
  dom.health.innerHTML = `<div class="health-summary-card"><div class="health-status-line"><span class="status-chip yellow"><i class="bi bi-exclamation-triangle-fill"></i> degraded</span></div><p>Health file unavailable: ${esc(err.message || err)}</p></div>`;
}

function formatHealthTime(health) {
  let dt = null;
  if (Number.isFinite(health?.epoch_ms))         dt = new Date(health.epoch_ms);
  else if (health?.created_at_local)             dt = new Date(health.created_at_local);
  else if (health?.created_at_utc)               dt = new Date(health.created_at_utc);
  else if (health?.created_at)                   dt = new Date(health.created_at);
  if (!dt || Number.isNaN(dt.getTime())) return "Checked time unknown";
  return `Checked ${dt.toLocaleString(undefined, { hour: "numeric", minute: "2-digit", second: "2-digit", year: "numeric", month: "short", day: "numeric" })}`;
}

/* ---- Tooltip ---- */

function showTooltip(node) {
  if (!dom.tooltip) return;
  dom.tooltip.innerHTML = `<div class="tooltip-title">${esc(node.title)}</div><div class="tooltip-meta"><span>${esc(node.type)}</span><span>${degreeMap.get(node.id) || 0} links</span></div>`;
  dom.tooltip.style.display = "block";
  dom.tooltip.setAttribute("aria-hidden", "false");
}

function moveTooltip(x, y) {
  if (!hoveredNode || !dom.tooltip) return;
  dom.tooltip.style.left = `${Math.min(x + 16, window.innerWidth - 300)}px`;
  dom.tooltip.style.top  = `${Math.min(y + 16, window.innerHeight - 110)}px`;
}

function hideTooltip() {
  if (!dom.tooltip) return;
  dom.tooltip.style.display = "none";
  dom.tooltip.setAttribute("aria-hidden", "true");
}

/* ---- Camera controls ---- */

function focusCore() {
  const core = visibleNodes.reduce(
    (best, node) => ((degreeMap.get(node.id) || 0) > (degreeMap.get(best?.id) || 0) ? node : best),
    visibleNodes[0]
  );
  if (core) focusNode(core, 560, false);
  else fitGraph();
}

function focusNode(node, distance = 430, select = true) {
  if (!node || !Graph || !Number.isFinite(node.x)) return;
  const distRatio = 1 + distance / Math.hypot(node.x || 1, node.y || 1, node.z || 1);
  Graph.cameraPosition(
    { x: node.x * distRatio, y: node.y * distRatio, z: (node.z || 0) * distRatio + distance },
    { x: node.x, y: node.y, z: node.z || 0 },
    REDUCED_MOTION ? 0 : 900
  );
  if (select) selectedId = node.id;
}

function fitGraph() {
  if (Graph && typeof Graph.zoomToFit === "function") Graph.zoomToFit(REDUCED_MOTION ? 0 : 900, 90);
  else if (fallbackSvg) drawFallback2d();
  notify("Graph fitted");
}

function focusSelected() {
  if (!selectedId) {
    focusCore();
    notify("Focused graph core");
    return;
  }
  const node = nodeById.get(selectedId);
  focusNode(node, 360, false);
  notify(`Focused ${node?.title || selectedId}`);
}

function resetCamera() {
  if (!Graph) return;
  Graph.cameraPosition({ x: 0, y: 0, z: 820 }, { x: 0, y: 0, z: 0 }, REDUCED_MOTION ? 0 : 900);
  notify("Camera reset");
}

function toggleRotate() {
  autoRotate = !autoRotate;
  const btn = $("rotate-btn");
  if (btn) btn.setAttribute("aria-pressed", String(autoRotate));
  if (Graph?.controls()) {
    Graph.controls().autoRotate = autoRotate;
    Graph.controls().autoRotateSpeed = 0.75;
  }
  notify(autoRotate ? "Orbital scan engaged" : "Orbital scan suspended");
  speakLine(autoRotate ? "Orbital scan engaged." : "Orbital scan suspended.");
}

function exportPng() {
  const canvas = dom.graph?.querySelector("canvas");
  if (!canvas) { notify("PNG export unavailable in fallback mode"); return; }
  const link = document.createElement("a");
  link.download = "citadel-graph.png";
  link.href = canvas.toDataURL("image/png");
  link.click();
  notify("Graph snapshot exported");
}

function reloadAll() {
  notify("Reloading graph and health");
  Promise.allSettled([loadSystemHealth(true), loadGraph()]).then(() => notify("Reload complete"));
}

/* ---- Status / toast ---- */

function setStatus(message) {
  if (dom.status) dom.status.textContent = message;
}

function notify(message) {
  if (!dom.toast) return;
  clearTimeout(toastTimer);
  dom.toast.textContent = message;
  dom.toast.classList.add("show");
  toastTimer = setTimeout(() => dom.toast.classList.remove("show"), 1700);
}

/* ---- Ask Citadel ---- */

function toggleAskPanel() {
  setAskPanelOpen(!dom.askPanel?.classList.contains("open"));
}

function closeAskPanel() { setAskPanelOpen(false); }

function setAskPanelOpen(open) {
  if (!dom.askPanel) return;
  dom.askPanel.classList.toggle("open", open);
  dom.askPanel.setAttribute("aria-hidden", open ? "false" : "true");
  dom.askBtn?.setAttribute("aria-pressed", String(open));
  if (open) setTimeout(() => dom.askInput?.focus(), 80);
}

async function askCitadel() {
  if (!dom.askInput) return;
  const question = dom.askInput.value.trim();
  if (!question) return;
  addAskMessage("user", question);
  dom.askInput.value = "";

  const askClaude =
    document.querySelector(".ask-mode-btn.active")?.dataset.mode === "citadel";
  const sseSupported = typeof EventSource !== "undefined";

  if (askClaude && sseSupported) {
    // Direct Claude path â€” stream via the CLI-backed SSE endpoint.
    // Do NOT silently fall back to local on failure; show the error instead.
    setAskLoading(true, "Asking Claude...");
    try {
      await askBackendSSE(question);
    } catch (err) {
      setAskLoading(false);
      setAskBadge("error", "Error");
      addAskMessage("citadel", `Claude unavailable: ${err?.message || "SSE error"}`, "Error");
    }
    return;
  }

  // Local-first path (toggle OFF or no SSE support) â€” original behaviour.
  setAskLoading(true, "Reading local status...");
  try {
    await delay(160);
    setAskLoading(true, "Checking graph context...");
    const backend = await askBackend(question).catch(() => null);
    if (backend?.answer) {
      const _BS = {
        "local":             { t: "local",  x: "Local" },
        "local_plus_claude": { t: "hybrid", x: "Local + Claude" },
        "claude_fallback":   { t: "model",  x: "Claude fallback" },
        "model":             { t: "model",  x: "Model answer" },
        "unavailable":       { t: "muted",  x: "Unavailable" },
      };
      const _bi = _BS[backend.source] || _BS["local"];
      setAskBadge(_bi.t, _bi.x);
      addCitadelResponse(backend);
    } else {
      await delay(160);
      const local = answerLocally(question);
      setAskBadge(local.source, local.badge);
      addAskMessage("citadel", local.answer, local.badge);
    }
  } catch (err) {
    setAskBadge("error", "Error");
    addAskMessage("citadel", `I could not answer that safely from local status. ${err.message || err}`, "Error");
  } finally {
    setAskLoading(false);
  }
}

async function askBackendSSE(question) {
  return new Promise((resolve, reject) => {
    const url = `/api/ask/stream?question=${encodeURIComponent(question)}`;
    const es = new EventSource(url);
    let msgEl = null;
    let accText = "";
    let gotChunk = false;

    function appendChunk(delta) {
      if (!dom.askHistory) return;
      if (!msgEl) {
        msgEl = document.createElement("div");
        msgEl.className = "ask-message citadel";
        msgEl.innerHTML = `<div class="msg-meta">The Sovereign Imperia Citadel Z Â· Streaming</div><p class="stream-text"></p><div class="ask-actions"><button type="button" data-copy="1"><i class="bi bi-copy"></i> Copy</button></div>`;
        dom.askHistory.appendChild(msgEl);
        msgEl.querySelector("[data-copy]")?.addEventListener("click", () => navigator.clipboard?.writeText(accText).then(() => notify("Answer copied")));
      }
      accText += delta;
      const p = msgEl.querySelector(".stream-text");
      if (p) p.textContent = accText;
      dom.askHistory.scrollTop = dom.askHistory.scrollHeight;
    }

    es.addEventListener("chunk", (e) => {
      try {
        const d = JSON.parse(e.data);
        if (d.delta) { appendChunk(d.delta); gotChunk = true; }
      } catch (_) {}
    });

    es.addEventListener("rejected", (e) => {
      es.close();
      setAskLoading(false);
      try {
        const d = JSON.parse(e.data);
        setAskBadge("muted", "CLI only");
        addAskMessage("citadel", d.message || "Mutation tasks require the CLI.", "CLI only");
      } catch (_) {}
      resolve();
    });

    es.addEventListener("error", (e) => {
      es.close();
      setAskLoading(false);
      if (gotChunk) {
        // Partial answer already rendered â€” treat as done.
        if (msgEl) { const meta = msgEl.querySelector(".msg-meta"); if (meta) meta.textContent = "The Sovereign Imperia Citadel Z"; }
        setAskBadge("model", "LEGION Z");
        resolve();
      } else {
        // No chunks yet â€” reject so the caller falls back to buffered path.
        reject(new Error("SSE error before first chunk"));
      }
    });

    es.addEventListener("done", () => {
      es.close();
      setAskLoading(false);
      if (msgEl) { const meta = msgEl.querySelector(".msg-meta"); if (meta) meta.textContent = "The Sovereign Imperia Citadel Z"; }
      setAskBadge("model", "LEGION Z");
      resolve();
    });

    // Timeout safety: if nothing arrives in 8 s, fall back.
    const timeout = setTimeout(() => {
      if (!gotChunk) { es.close(); reject(new Error("SSE timeout")); }
    }, 8000);
    es.addEventListener("done", () => clearTimeout(timeout));
    es.addEventListener("rejected", () => clearTimeout(timeout));
  });
}

async function askBackend(question) {
  const res = await fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, mode: "fast", selected_node_id: selectedId || null })
  });
  if (!res.ok) throw new Error("Ask backend unavailable");
  return res.json();
}

function answerLocally(question) {
  const q = question.toLowerCase();
  const summary = systemHealth?.summary || {};
  const checks  = systemHealth?.checks  || [];
  const total   = Number(summary.green || 0) + Number(summary.yellow || 0) + Number(summary.red || 0);

  if (/permission|access|can you do|what can you access/.test(q)) {
    return {
      source: "local", badge: "Local answer",
      answer: "From this UI, I can read the local graph/status endpoints served to the browser, show graph metadata, system health, node details, and cached local context. I cannot edit files, run shell commands, access secrets, deploy code, or call external services from the browser UI. Model-backed Q&A is disabled unless the local backend explicitly enables it."
    };
  }
  if (/green|health|systems|status|all systems/.test(q)) {
    if (!systemHealth) return { source: "error", badge: "Unavailable", answer: "System health is unavailable. Reload health or regenerate system-status.json." };
    const status = systemHealth.overall_status || "unknown";
    const failed = checks.filter((c) => c.status !== "green").map((c) => `${c.name}: ${c.status}`);
    return {
      source: "local", badge: "Local answer",
      answer: status === "green"
        ? `Overall status is green. ${summary.green || 0}/${total || 0} checks are green. Checked in your local browser time: ${formatHealthTime(systemHealth)}.`
        : `Overall status is ${status}. Non-green checks: ${failed.length ? failed.join("; ") : "none listed"}. Checked in your local browser time: ${formatHealthTime(systemHealth)}.`
    };
  }
  if (/daemon|running|server/.test(q)) {
    const daemonChecks = checks.filter((c) => /daemon|server|scheduler/i.test(c.name));
    if (!daemonChecks.length) return { source: "local", badge: "Local answer", answer: "No daemon/server checks are available in system-status.json." };
    return { source: "local", badge: "Local answer", answer: daemonChecks.map((c) => `${c.name}: ${c.status} (${c.details || c.evidence || "no details"})`).join("\n") };
  }
  if (/graph/.test(q)) {
    return { source: "local", badge: "Local answer", answer: `Graph status: ${graphNodes.length} nodes, ${graphLinks.length} links, ${typeCounts.size} node types. Visible now: ${visibleNodes.length} nodes and ${visibleLinks.length} links.` };
  }
  return {
    source: "muted", badge: "Model disabled",
    answer: "I can answer local system/status questions from the graph and health JSON. Model-backed Q&A is not configured from this UI."
  };
}

function addAskMessage(role, text, badge = "") {
  if (!dom.askHistory) return;
  const msg = document.createElement("div");
  msg.className = `ask-message ${role === "user" ? "user" : "citadel"}`;
  msg.innerHTML = `<div class="msg-meta">${role === "user" ? "You" : `Citadel${badge ? ` Â· ${esc(badge)}` : ""}`}</div><p>${esc(text)}</p>${role !== "user" ? `<div class="ask-actions"><button type="button" data-copy="1"><i class="bi bi-copy"></i> Copy</button></div>` : ""}`;
  dom.askHistory.appendChild(msg);
  msg.querySelector("[data-copy]")?.addEventListener("click", () => navigator.clipboard?.writeText(text).then(() => notify("Answer copied")));
  dom.askHistory.scrollTop = dom.askHistory.scrollHeight;
}

function addCitadelResponse(data) {
  if (!dom.askHistory) return;
  const src      = data.source      || "local";
  const conf     = data.confidence  || "medium";
  const cat      = data.category    || "";
  const evidence = Array.isArray(data.evidence)            ? data.evidence            : [];
  const suggests = Array.isArray(data.suggested_questions) ? data.suggested_questions : [];

  const _SRC = {
    "local":             { label: "Local",           cls: "local"   },
    "local_plus_claude": { label: "Local + Claude",  cls: "hybrid"  },
    "claude_fallback":   { label: "Claude fallback", cls: "model"   },
    "model":             { label: "Model answer",    cls: "model"   },
    "unavailable":       { label: "Unavailable",     cls: "muted"   },
  };
  const _si = _SRC[src] || _SRC["local"];
  const srcLabel = _si.label;
  const srcClass = _si.cls;

  const msg = document.createElement("div");
  msg.className = "ask-message citadel";

  // Badges row
  const badgesDiv = document.createElement("div");
  badgesDiv.className = "ask-badges-row";
  badgesDiv.innerHTML =
    `<span class="source-badge ${esc(srcClass)}">${esc(srcLabel)}</span>` +
    `<span class="conf-badge ${esc(conf)}">${esc(conf)}</span>` +
    (cat ? `<span class="cat-badge">${esc(cat)}</span>` : "");

  // Meta label
  const meta = document.createElement("div");
  meta.className = "msg-meta";
  meta.textContent = "Citadel";

  // Answer text
  const p = document.createElement("p");
  p.textContent = data.answer || "";

  // Evidence (collapsed details)
  let evidenceEl = null;
  if (evidence.length > 0) {
    evidenceEl = document.createElement("details");
    evidenceEl.className = "ask-evidence";
    const summary = document.createElement("summary");
    summary.textContent = `${evidence.length} source${evidence.length !== 1 ? "s" : ""}`;
    const list = document.createElement("div");
    list.className = "evidence-list";
    evidence.forEach((ev) => {
      const row = document.createElement("div");
      row.className = "evidence-row";
      const srcSpan = document.createElement("span");
      srcSpan.className = "evidence-src";
      srcSpan.textContent = ev.source || "";
      srcSpan.title = ev.source || "";
      const detSpan = document.createElement("span");
      detSpan.className = "evidence-detail";
      detSpan.textContent = ev.detail || "";
      // Make node-link evidence clickable
      const det = ev.detail || "";
      const idMatch = det.match(/â†’\s*([a-z0-9][a-z0-9\-]*[a-z0-9])/i);
      if (idMatch && nodeById?.has(idMatch[1])) {
        detSpan.style.cursor = "pointer";
        detSpan.style.textDecoration = "underline dotted";
        detSpan.title = `Select node ${idMatch[1]}`;
        detSpan.addEventListener("click", () => selectNodeById(idMatch[1]));
      }
      row.appendChild(srcSpan);
      row.appendChild(detSpan);
      list.appendChild(row);
    });
    evidenceEl.appendChild(summary);
    evidenceEl.appendChild(list);
  }

  // Copy + actions row
  const actions = document.createElement("div");
  actions.className = "ask-actions";
  const copyBtn = document.createElement("button");
  copyBtn.type = "button";
  copyBtn.dataset.copy = "1";
  copyBtn.innerHTML = `<i class="bi bi-copy"></i> Copy`;
  copyBtn.addEventListener("click", () =>
    navigator.clipboard?.writeText(data.answer || "").then(() => notify("Answer copied"))
  );
  actions.appendChild(copyBtn);

  // Assemble
  msg.appendChild(meta);
  msg.appendChild(badgesDiv);
  msg.appendChild(p);
  if (evidenceEl) msg.appendChild(evidenceEl);
  msg.appendChild(actions);
  dom.askHistory.appendChild(msg);
  dom.askHistory.scrollTop = dom.askHistory.scrollHeight;

  // Suggested follow-up chips (rendered as a separate row below the message)
  if (suggests.length > 0) {
    const sugDiv = document.createElement("div");
    sugDiv.className = "ask-suggestions";
    suggests.slice(0, 4).forEach((q) => {
      const btn = document.createElement("button");
      btn.className = "ask-chip";
      btn.type = "button";
      btn.textContent = q;
      btn.addEventListener("click", () => {
        if (dom.askInput) dom.askInput.value = q;
        askCitadel();
      });
      sugDiv.appendChild(btn);
    });
    dom.askHistory.appendChild(sugDiv);
    dom.askHistory.scrollTop = dom.askHistory.scrollHeight;
  }
}

function selectNodeById(id) {
  const node = nodeById?.get(id);
  if (node) onNodeClick(node);
}

function setAskBadge(type, text) {
  if (!dom.askSourceBadge) return;
  dom.askSourceBadge.className = `source-badge ${type || "local"}`;
  dom.askSourceBadge.textContent = text || "Local answer";
}

function setAskModelBadge(type, text) {
  if (!dom.askModelBadge) return;
  dom.askModelBadge.className = `source-badge ${type || "muted"}`;
  dom.askModelBadge.textContent = text || "";
}

function setAskLoading(on, message = "Reading local status...") {
  if (!dom.askLoading || !dom.askLoadingMsg) return;
  dom.askLoading.hidden = !on;
  dom.askLoadingMsg.textContent = message;
}

/* ---- Voice ---- */

function toggleVoice() {
  voiceEnabled = !voiceEnabled;
  voiceUnlocked = voiceEnabled;
  updateVoiceUi();
  if (!voiceEnabled) {
    cancelSpeech();
    notify("Voice muted");
    return;
  }
  notify("Voice telemetry online");
  const status = systemHealth?.overall_status || "yellow";
  const lines = status === "green"
    ? ["Initializing Citadel.", "System checks completed.", "All systems are green.", "Welcome, User. We are The Sovereign Imperia Citadel Z, We Are Many. System awareness is online. What is your request?"]
    : status === "red"
      ? ["Initializing Citadel.", "System checks failed.", "Core systems require attention."]
      : ["Initializing Citadel.", "System checks completed with warnings.", "Open the health panel for details."];
  speakLines(lines);
}

function updateVoiceUi() {
  if (dom.voiceMode)   dom.voiceMode.value   = localStorage.getItem("citadelVoiceMode")   || "cinematic_ai";
  if (dom.voiceEngine) dom.voiceEngine.value = localStorage.getItem("citadelVoiceEngine") || "local";
  if (!dom.voiceBtn) return;
  dom.voiceBtn.setAttribute("aria-pressed", String(voiceEnabled));
  dom.voiceBtn.innerHTML = voiceEnabled
    ? `<i class="bi bi-mic-fill" aria-hidden="true"></i><span>Voice On</span>`
    : `<i class="bi bi-mic-mute" aria-hidden="true"></i><span>Voice Off</span>`;
}

function speakNodeName(name) {
  if (!voiceEnabled || !voiceUnlocked) return;
  speakLines([name]);
}

function speakLine(line) {
  if (!voiceEnabled || !voiceUnlocked) return;
  speakLines([line]);
}

function speakLines(lines) {
  if (!voiceEnabled || !("speechSynthesis" in window)) return;
  voiceQueue.push(...lines.filter(Boolean));
  drainSpeech();
}

function drainSpeech() {
  if (voiceSpeaking || !voiceQueue.length || !voiceEnabled) return;
  const text = voiceQueue.shift();
  voiceSpeaking = true;
  const preset = voicePreset();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate   = preset.rate;
  utterance.pitch  = preset.pitch;
  utterance.volume = preset.volume;
  const voice = selectedVoice || selectBestVoice();
  if (voice) utterance.voice = voice;
  utterance.onend = utterance.onerror = () => {
    voiceSpeaking = false;
    setTimeout(drainSpeech, preset.gap);
  };
  window.speechSynthesis.speak(utterance);
}

function voicePreset() {
  const mode = dom.voiceMode?.value || "cinematic_ai";
  const presets = {
    minimal:        { rate: 1,    pitch: 1,    volume: 0.72, gap: 90  },
    calm_ai:        { rate: 0.86, pitch: 0.82, volume: 0.9,  gap: 260 },
    cinematic_ai:   { rate: 0.78, pitch: 0.72, volume: 1,    gap: 420 },
    command_center: { rate: 0.9,  pitch: 0.65, volume: 1,    gap: 240 }
  };
  return presets[mode] || presets.cinematic_ai;
}

function selectBestVoice() {
  const voices = window.speechSynthesis?.getVoices?.() || [];
  const preferred = ["Samantha","Daniel","Alex","Google US English","Google UK English","Microsoft Aria","Microsoft Guy","Natural","Premium"];
  selectedVoice = preferred.map((name) => voices.find((v) => new RegExp(name, "i").test(v.name))).find(Boolean)
    || voices.find((v) => /^en[-_]/i.test(v.lang || ""))
    || voices[0] || null;
  return selectedVoice;
}

if ("speechSynthesis" in window) {
  window.speechSynthesis.onvoiceschanged = selectBestVoice;
  selectBestVoice();
}

function cancelSpeech() {
  voiceQueue = [];
  voiceSpeaking = false;
  if (activeAudio) {
    try { activeAudio.pause(); } catch (_) {}
    activeAudio = null;
  }
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
}

/* ---- Utilities ---- */

function delay(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }

function debounce(fn, wait) {
  let timer = null;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), wait); };
}

/* ---- Kinetic telemetry pulse layer (Phase 17) ---- */

// activePulses: Map<linkKey, {color, expiresAt}>
// linkKey: `${source_node}::${target_node}`
const activePulses = new Map();
const PULSE_FADE_MS = 2000;

function _pulseKey(src, tgt) { return `${src}::${tgt}`; }

function _applyPulseToGraph() {
  if (!graph) return;
  const now = Date.now();
  // Expire stale pulses.
  for (const [key, pulse] of activePulses.entries()) {
    if (now > pulse.expiresAt) activePulses.delete(key);
  }
  graph
    .linkColor((link) => {
      const src = typeof link.source === "object" ? link.source.id : link.source;
      const tgt = typeof link.target === "object" ? link.target.id : link.target;
      const pulse = activePulses.get(_pulseKey(src, tgt));
      if (pulse) return pulse.color;
      return linkColor(link);
    })
    .linkDirectionalParticleColor((link) => {
      const src = typeof link.source === "object" ? link.source.id : link.source;
      const tgt = typeof link.target === "object" ? link.target.id : link.target;
      const pulse = activePulses.get(_pulseKey(src, tgt));
      return pulse ? pulse.color : "#ffffff44";
    })
    .linkDirectionalParticles((link) => {
      const src = typeof link.source === "object" ? link.source.id : link.source;
      const tgt = typeof link.target === "object" ? link.target.id : link.target;
      return (selectedId || activePulses.has(_pulseKey(src, tgt))) ? 2 : 0;
    });
}

function _handleTelemetryEvent(evt) {
  const src = evt.source_node;
  const tgt = evt.target_node;
  const kind = evt.kind || "route";
  const colorMap = { cyan: "#00e5ff", green: "#69ff47", red: "#ff4444" };
  const color = colorMap[evt.color] || colorMap.cyan;
  if (!src || !tgt) return;
  activePulses.set(_pulseKey(src, tgt), { color, expiresAt: Date.now() + PULSE_FADE_MS });
  // Also add the reverse key so undirected edges pulse visually.
  activePulses.set(_pulseKey(tgt, src), { color, expiresAt: Date.now() + PULSE_FADE_MS });
  _applyPulseToGraph();
  // Schedule cleanup after fade.
  setTimeout(() => {
    activePulses.delete(_pulseKey(src, tgt));
    activePulses.delete(_pulseKey(tgt, src));
    _applyPulseToGraph();
  }, PULSE_FADE_MS + 100);
  console.debug(`[LEGION Z telemetry] ${kind}: ${src} â†’ ${tgt} (${evt.color})`);
}

function initTelemetryStream() {
  if (typeof EventSource === "undefined") return;
  const es = new EventSource("/api/telemetry/stream");

  es.addEventListener("ready", () => {
    console.debug("[LEGION Z telemetry] stream connected");
  });

  es.onmessage = (e) => {
    try { _handleTelemetryEvent(JSON.parse(e.data)); } catch (_) {}
  };

  // Named events emitted by the server also fire onmessage for unrecognized event types,
  // but for named ones we add explicit listeners too.
  for (const kind of ["route", "l5_pass", "l5_veto", "l6_pass", "l6_fail"]) {
    es.addEventListener(kind, (e) => {
      try { _handleTelemetryEvent(JSON.parse(e.data)); } catch (_) {}
    });
  }

  es.onerror = () => {
    // Reconnection is automatic with EventSource; no explicit handling needed.
    console.debug("[LEGION Z telemetry] stream error â€” will auto-reconnect");
  };
}

// Initialise the telemetry stream after a short delay to let the graph render first.
setTimeout(initTelemetryStream, 1500);
