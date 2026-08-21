"use strict";

// Denne filen er bare en renderer: den tegner state som kommer fra Python-API-et.
const POLL_INTERVAL_MS = 1000;
const DEVICE_WIDTH = 540;
const DEVICE_HEIGHT = 380;
const MAX_DEVICE_SCALE = 2;
const DEVICE_BOTTOM_RESERVE = 112;
const UPDATE_STATUS_POLL_MS = 5000;
const UPDATE_CHECK_INTERVAL_MS = 30 * 60 * 1000;

const ui = {
  screenContent: document.querySelector("#screen-content"),
  deviceFit: document.querySelector("#device-fit"),
  deviceScale: document.querySelector("#device-scale"),
  connectionBadge: document.querySelector("#connection-badge"),
  connectionText: document.querySelector("#connection-text"),
  screenButtons: [...document.querySelectorAll(".screen-button")],
  startDemo: document.querySelector("#start-demo"),
  iterations: document.querySelector("#iterations"),
  startDemoLabel: document.querySelector("#start-demo-label"),
  demoStateLabel: document.querySelector("#demo-state-label"),
  lastUpdate: document.querySelector("#last-update"),
  rawPayload: document.querySelector("#raw-payload"),
  updateStatus: document.querySelector("#update-status"),
  updateVersion: document.querySelector("#update-version"),
  checkUpdate: document.querySelector("#check-update"),
  updateLink: document.querySelector("#update-link"),
};

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function number(value, suffix = "") {
  return value === null || value === undefined ? "—" : `${Number(value).toFixed(1)}${suffix}`;
}

function clampPercent(value) {
  if (value === null || value === undefined) return 0;
  return Math.min(100, Math.max(0, Number(value)));
}

function bar(value, compact = false) {
  const track = element("div", compact ? "meter-track compact" : "meter-track");
  const fill = element("span", "meter-fill");
  fill.style.width = `${clampPercent(value)}%`;
  if (Number(value) >= 80) fill.classList.add("hot");
  track.append(fill);
  return track;
}

function screenHeader(label, time, online = true) {
  const header = element("header", "display-header");
  const brand = element("div", "display-brand");
  brand.append(element("span", online ? "display-led online" : "display-led"));
  brand.append(element("span", "", label));
  header.append(brand, element("time", "display-clock", time));
  return header;
}

function metricCard(label, value, suffix, accent = "") {
  const card = element("div", `metric-card ${accent}`.trim());
  card.append(element("span", "metric-label", label));
  const reading = element("strong", "metric-value", number(value));
  reading.append(element("small", "", value === null || value === undefined ? "" : suffix));
  card.append(reading, bar(value));
  return card;
}

function renderHome(payload) {
  const fragment = document.createDocumentFragment();
  fragment.append(screenHeader("PI STATUS", payload.time, payload.network.online));

  const hero = element("section", "home-hero");
  const identity = element("div", "node-identity");
  identity.append(
    element("span", "screen-overline", "PRIMARY NODE"),
    element("strong", "node-name", payload.nodes[0].name),
    element("span", "node-address", payload.network.ip),
  );
  const network = element("div", payload.network.online ? "network-chip online" : "network-chip");
  network.append(
    element("span", "network-icon", payload.network.online ? "●" : "○"),
    element("span", "", payload.network.online ? "NETWORK ONLINE" : "OFFLINE"),
  );
  hero.append(identity, network);

  const metrics = element("section", "metrics-grid");
  metrics.append(
    metricCard("CPU LOAD", payload.system.cpu, "%", "cyan"),
    metricCard("CPU TEMP", payload.system.temp, "°C", "amber"),
    metricCard("MEMORY", payload.system.ram, "%", "violet"),
  );

  const footer = element("footer", "display-footer");
  footer.append(
    element("span", "", payload.backend),
    element("span", "footer-message", payload.message.toUpperCase()),
  );
  fragment.append(hero, metrics, footer);
  ui.screenContent.replaceChildren(fragment);
}

function nodeCard(node, index) {
  const card = element("article", node.online ? "cluster-node online" : "cluster-node offline");
  card.title = [node.model, node.ip].filter(Boolean).join(" · ");
  const head = element("div", "cluster-node-head");
  const title = element("div", "cluster-node-title");
  title.append(
    element("span", node.online ? "node-dot online" : "node-dot"),
    element("strong", "", node.name),
  );
  head.append(title, element("span", "node-index", `N${String(index + 1).padStart(2, "0")}`));

  const meta = element(
    "div",
    "cluster-node-meta",
    [node.model, node.ip].filter(Boolean).join(" · ") || "RASPBERRY PI",
  );

  const cpuLine = element("div", "cluster-metric-line");
  cpuLine.append(element("span", "", "CPU"), bar(node.cpu, true), element("b", "", number(node.cpu, "%")));
  const ramLine = element("div", "cluster-metric-line");
  ramLine.append(element("span", "", "RAM"), bar(node.ram, true), element("b", "", number(node.ram, "%")));

  const foot = element("div", "cluster-node-foot");
  const role = node.mock ? "DEMO" : node.kind === "local" ? "LOCAL" : "REMOTE";
  foot.append(
    element("span", "", node.online ? number(node.temp, "°C") : "NO SIGNAL"),
    element("span", `node-role-chip ${node.kind || "remote"}`, role),
  );
  card.append(head, meta, cpuLine, ramLine, foot);
  return card;
}

function emptyClusterCard(count) {
  const card = element("article", "cluster-empty");
  card.append(
    element("span", "empty-node-icon", "+"),
    element("strong", "", `${count} ${count === 1 ? "LEDIG NODEPLASS" : "LEDIGE NODEPLASSER"}`),
    element("span", "", "VENTER PÅ HEARTBEAT FRA NODE_AGENT.PY"),
  );
  return card;
}

function renderCluster(payload) {
  const fragment = document.createDocumentFragment();
  const onlineCount = payload.nodes.filter((node) => node.online).length;
  fragment.append(screenHeader(`CLUSTER · ${onlineCount}/${payload.nodes.length} ONLINE`, payload.time, onlineCount > 0));
  const grid = element("section", "cluster-grid");
  const visibleNodes = payload.nodes.slice(0, 4);
  visibleNodes.forEach((node, index) => grid.append(nodeCard(node, index)));
  if (visibleNodes.length < 4) grid.append(emptyClusterCard(4 - visibleNodes.length));
  fragment.append(grid);
  ui.screenContent.replaceChildren(fragment);
}

function renderNerd(payload) {
  const demo = payload.demo;
  const fragment = document.createDocumentFragment();
  fragment.append(screenHeader("NERD LAB · MONTE CARLO", payload.time, demo.status !== "error"));

  const body = element("section", "nerd-layout");
  const result = element("div", "pi-result");
  result.append(
    element("span", "screen-overline", "ESTIMATED VALUE"),
    element("span", "pi-symbol", "π"),
    element("strong", "pi-value", demo.estimate === null ? "3.———" : Number(demo.estimate).toFixed(6)),
    element("span", "pi-target", "target 3.141593"),
  );

  const stats = element("div", "demo-stats");
  const stateText = {
    idle: "READY TO RUN",
    running: "CALCULATING",
    finished: "COMPLETE",
    error: "ERROR",
  }[demo.status] || demo.status.toUpperCase();
  const stateLine = element("div", "demo-state-line");
  stateLine.append(element("span", demo.status === "running" ? "pulse-dot active" : "pulse-dot"), element("strong", "", stateText));

  const progressHeading = element("div", "progress-heading");
  progressHeading.append(
    element("span", "", `${Number(demo.samples_done).toLocaleString("nb-NO")} PUNKTER`),
    element("b", "", `${Number(demo.progress).toFixed(1)}%`),
  );
  const progressBar = element("div", "demo-progress");
  const progressFill = element("span", "");
  progressFill.style.width = `${clampPercent(demo.progress)}%`;
  progressBar.append(progressFill);

  const runtime = element("div", "runtime-box");
  runtime.append(element("span", "", "RUNTIME"), element("strong", "", `${Number(demo.runtime_seconds).toFixed(2)} s`));
  stats.append(stateLine, progressHeading, progressBar, runtime, element("p", "demo-hint", demo.status === "idle" ? "Start jobben i kontrollpanelet →" : payload.message));
  body.append(result, stats);
  fragment.append(body);
  ui.screenContent.replaceChildren(fragment);
}

function render(payload) {
  const renderers = { home: renderHome, cluster: renderCluster, nerd: renderNerd };
  (renderers[payload.screen] || renderHome)(payload);

  ui.screenButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.screen === payload.screen);
  });

  const running = payload.demo.status === "running";
  ui.startDemo.disabled = running;
  ui.startDemoLabel.textContent = running ? "Beregner …" : "Start beregning";
  ui.demoStateLabel.textContent = running ? `${payload.demo.progress.toFixed(0)}%` : payload.demo.status.toUpperCase();
  ui.rawPayload.textContent = JSON.stringify(payload, null, 2);
  ui.lastUpdate.textContent = `${payload.time} · ${payload.mock_mode ? "mock" : "live"}`;
}

async function fetchState() {
  try {
    const response = await fetch("/api/state", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    render(payload);
    ui.connectionBadge.classList.remove("offline");
    ui.connectionText.textContent = "Live forbindelse";
  } catch (error) {
    ui.connectionBadge.classList.add("offline");
    ui.connectionText.textContent = "Ingen forbindelse";
    console.error("Kunne ikke hente state:", error);
  }
}

async function postJson(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
  return result;
}

function renderUpdateStatus(status) {
  const labels = {
    idle: "IKKE SJEKKET",
    checking: "SJEKKER …",
    current: "OPPDATERT",
    available: "NY VERSJON · SSH",
    error: "SJEKK FEILET",
  };
  const busy = status.status === "checking";
  const versions = [status.current_commit, status.available_commit].filter(Boolean);
  ui.updateStatus.textContent = labels[status.status] || status.status.toUpperCase();
  ui.updateStatus.title = status.message || "";
  ui.updateVersion.textContent = versions.length > 1 ? `${versions[0]} → ${versions[1]}` : versions[0] || "Ukjent versjon";
  ui.checkUpdate.disabled = busy;
  ui.updateLink.hidden = !status.commit_url;
  ui.updateLink.href = status.commit_url || "";
}

async function fetchUpdateStatus() {
  try {
    const response = await fetch("/api/update/status", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderUpdateStatus(await response.json());
  } catch (error) {
    ui.updateStatus.textContent = "STATUS UTILGJENGELIG";
    ui.updateStatus.title = error.message;
  }
}

async function checkForUpdate() {
  try {
    const response = await fetch("/api/update/check", { method: "POST" });
    if (!response.ok && response.status !== 409) throw new Error(`HTTP ${response.status}`);
    await fetchUpdateStatus();
  } catch (error) {
    ui.updateStatus.textContent = "SJEKK FEILET";
    ui.updateStatus.title = error.message;
  }
}

ui.screenButtons.forEach((button) => {
  button.addEventListener("click", async () => {
    try {
      await postJson("/api/screen", { screen: button.dataset.screen });
      await fetchState();
    } catch (error) {
      ui.connectionText.textContent = error.message;
    }
  });
});

ui.startDemo.addEventListener("click", async () => {
  ui.startDemo.disabled = true;
  try {
    await postJson("/api/demo/start", { iterations: Number(ui.iterations.value) });
    await fetchState();
  } catch (error) {
    ui.connectionText.textContent = error.message;
    ui.startDemo.disabled = false;
  }
});

ui.checkUpdate.addEventListener("click", checkForUpdate);

function fitDevice() {
  const availableWidth = ui.deviceFit.clientWidth;
  const deviceTop = ui.deviceFit.getBoundingClientRect().top;
  const availableHeight = Math.max(
    DEVICE_HEIGHT,
    window.innerHeight - deviceTop - DEVICE_BOTTOM_RESERVE,
  );
  const scale = Math.min(
    MAX_DEVICE_SCALE,
    availableWidth / DEVICE_WIDTH,
    availableHeight / DEVICE_HEIGHT,
  );
  ui.deviceScale.style.transform = `scale(${scale})`;
  ui.deviceFit.style.height = `${DEVICE_HEIGHT * scale}px`;
}

if ("ResizeObserver" in window) {
  new ResizeObserver(fitDevice).observe(ui.deviceFit);
}
window.addEventListener("resize", fitDevice);

fitDevice();
fetchState();
fetchUpdateStatus();
window.setTimeout(checkForUpdate, 1500);
window.setInterval(fetchState, POLL_INTERVAL_MS);
window.setInterval(fetchUpdateStatus, UPDATE_STATUS_POLL_MS);
window.setInterval(checkForUpdate, UPDATE_CHECK_INTERVAL_MS);
