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
  cores: document.querySelector("#demo-slots"),
  reserveOne: document.querySelector("#demo-reserve-one"),
  coreCountLabel: document.querySelector("#core-count-label"),
  coreHint: document.querySelector("#core-hint"),
  startDemoLabel: document.querySelector("#start-demo-label"),
  demoStateLabel: document.querySelector("#demo-state-label"),
  clusterStateLabel: document.querySelector("#cluster-state-label"),
  clusterStart: document.querySelector("#cluster-start"),
  clusterEnd: document.querySelector("#cluster-end"),
  clusterChunkSize: document.querySelector("#cluster-chunk-size"),
  clusterSlots: document.querySelector("#cluster-slots"),
  clusterReserveOne: document.querySelector("#cluster-reserve-one"),
  startClusterJob: document.querySelector("#start-cluster-job"),
  startClusterLabel: document.querySelector("#start-cluster-label"),
  clusterHelper: document.querySelector("#cluster-helper"),
  nodeStatusList: document.querySelector("#node-status-list"),
  nodeCapacityLabel: document.querySelector("#node-capacity-label"),
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

function frequencyText(value) {
  return value === null || value === undefined ? "— MHz" : `${Math.round(Number(value))} MHz`;
}

function throttleTone(throttle) {
  if (!throttle?.available) return "unavailable";
  if (throttle.active) return "active";
  if (throttle.occurred) return "history";
  return "ok";
}

function throttleText(throttle) {
  if (!throttle) return "STATUS UTILGJENGELIG";
  return `${throttle.summary}${throttle.available ? ` · ${throttle.raw}` : ""}`;
}

function renderNodeStatus(payload) {
  const nodes = Array.isArray(payload.nodes) ? payload.nodes : [];
  const fragment = document.createDocumentFragment();
  nodes.forEach((node) => {
    const row = element("article", `node-status-row ${node.online ? "online" : "offline"}`);
    const head = element("div", "node-status-head");
    const identity = element("strong", "", node.name || node.id || "Ukjent node");
    const state = element("span", node.online ? "online" : "offline", node.online ? "ONLINE" : "OFFLINE");
    head.append(identity, state);
    const metrics = element("div", "node-status-metrics");
    metrics.append(
      element("span", "", `CPU ${number(node.cpu, "%")}`),
      element("span", "", `RAM ${number(node.ram, "%")}`),
      element("span", "", `TEMP ${number(node.temp, "°C")}`),
      element("span", "", frequencyText(node.frequency_mhz)),
      element("span", "", `${Number(node.cores || 0)} CORES`),
    );
    const throttle = element("small", `node-throttle ${throttleTone(node.throttle)}`, throttleText(node.throttle));
    row.append(head, metrics, throttle);
    fragment.append(row);
  });
  if (!nodes.length) fragment.append(element("p", "helper-text", "Ingen registrerte noder."));
  ui.nodeStatusList.replaceChildren(fragment);
  const capacity = payload.cluster?.capacity || {};
  ui.nodeCapacityLabel.textContent = `${Number(capacity.total_slots || 0)} SLOTS`;
}

function systemHealthStrip(system, compact = false) {
  const throttle = system.throttle;
  const strip = element("div", `system-health ${throttleTone(throttle)}${compact ? " compact" : ""}`);
  const clock = element("span", "system-clock");
  clock.append(element("small", "", "CPU CLOCK"), element("strong", "", frequencyText(system.frequency_mhz)));
  strip.append(clock, element("span", "throttle-message", throttleText(throttle)));
  return strip;
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
  fragment.append(hero, metrics, systemHealthStrip(payload.system), footer);
  ui.screenContent.replaceChildren(fragment);
}

function nodeCard(node, index) {
  const card = element("article", node.online ? "cluster-node online" : "cluster-node offline");
  if (node.throttle?.active) card.classList.add("throttled");
  card.title = [node.model, node.ip, throttleText(node.throttle)].filter(Boolean).join(" · ");
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
    [node.model, node.ip, node.cores ? `${node.cores} CORES` : null, node.frequency_mhz ? frequencyText(node.frequency_mhz) : null].filter(Boolean).join(" · ") || "RASPBERRY PI",
  );

  const cpuLine = element("div", "cluster-metric-line");
  cpuLine.append(element("span", "", "CPU"), bar(node.cpu, true), element("b", "", number(node.cpu, "%")));
  const ramLine = element("div", "cluster-metric-line");
  ramLine.append(element("span", "", "RAM"), bar(node.ram, true), element("b", "", number(node.ram, "%")));

  const foot = element("div", "cluster-node-foot");
  const role = node.mock ? "DEMO" : node.kind === "local" ? "LOCAL" : "REMOTE";
  const statusText = node.throttle?.active ? "THROTTLE" : node.throttle?.occurred ? "HISTORY" : role;
  const statusClass = node.throttle?.active ? "warning" : node.throttle?.occurred ? "history" : node.kind || "remote";
  foot.append(
    element("span", "", node.online ? number(node.temp, "°C") : "NO SIGNAL"),
    element("span", `node-role-chip ${statusClass}`, statusText),
  );
  card.append(head, meta, cpuLine, ramLine, foot);
  return card;
}

function drawMonteCarlo(canvas, points) {
  const size = 360;
  const center = size / 2;
  const radius = 160;
  canvas.width = size;
  canvas.height = size;
  const context = canvas.getContext("2d");

  context.fillStyle = "#071219";
  context.fillRect(0, 0, size, size);
  context.strokeStyle = "rgba(63, 96, 108, 0.18)";
  context.lineWidth = 1;
  for (let position = 20; position <= 340; position += 40) {
    context.beginPath();
    context.moveTo(position, 20);
    context.lineTo(position, 340);
    context.moveTo(20, position);
    context.lineTo(340, position);
    context.stroke();
  }

  context.beginPath();
  context.arc(center, center, radius, 0, Math.PI * 2);
  context.fillStyle = "rgba(40, 225, 209, 0.025)";
  context.fill();
  context.strokeStyle = "rgba(40, 225, 209, 0.75)";
  context.lineWidth = 2.5;
  context.stroke();

  (points || []).forEach((point, index) => {
    const x = center + Number(point[0]) * radius;
    const y = center - Number(point[1]) * radius;
    const inside = Number(point[2]) === 1;
    context.beginPath();
    context.arc(x, y, index === points.length - 1 ? 3.8 : 2.7, 0, Math.PI * 2);
    context.fillStyle = inside ? "rgba(40, 225, 209, 0.88)" : "rgba(167, 139, 250, 0.9)";
    context.fill();
  });

  if (points?.length) {
    const last = points[points.length - 1];
    context.beginPath();
    context.arc(center + Number(last[0]) * radius, center - Number(last[1]) * radius, 8, 0, Math.PI * 2);
    context.strokeStyle = "rgba(255, 255, 255, 0.72)";
    context.lineWidth = 1.5;
    context.stroke();
  }
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

function renderNodeCluster(payload) {
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

function clusterSummary(label, value, tone) {
  const card = element("div", `cluster-job-summary ${tone}`);
  card.append(element("span", "", label), element("strong", "", String(value || 0)));
  return card;
}

function clusterJobRow(job) {
  const row = element("article", `cluster-job-row ${job.viewStatus}`);
  const identity = element("div", "cluster-job-id");
  const typeLabel = job.job_type === "monte_carlo" ? "MONTE" : "PRIME";
  identity.append(
    element("span", "", `B${String(job.batch_id || 0).padStart(3, "0")} · J${String(job.job_id).padStart(3, "0")} · ${typeLabel}`),
    element("strong", "", job.viewStatus.toUpperCase()),
  );
  const worker = element("div", "cluster-job-worker");
  worker.append(element("span", "", "WORKER"), element("strong", "", job.worker || "VENTER"));
  const range = element("div", "cluster-job-range");
  const isMonteCarlo = job.job_type === "monte_carlo";
  range.append(
    element("span", "", isMonteCarlo ? "SAMPLES" : "RANGE"),
    element("strong", "", isMonteCarlo
      ? Number(job.samples || 0).toLocaleString("nb-NO")
      : `${Number(job.start).toLocaleString("nb-NO")}–${Number(job.end).toLocaleString("nb-NO")}`),
  );
  const result = element("div", "cluster-job-result");
  result.append(
    element("span", "", "RESULTAT"),
    element("strong", "", isMonteCarlo
      ? (job.inside === undefined ? "—" : `${Number(job.inside).toLocaleString("nb-NO")} INNE`)
      : (job.prime_count === undefined ? "—" : Number(job.prime_count).toLocaleString("nb-NO"))),
  );
  row.append(identity, worker, range, result);
  return row;
}

function renderCluster(payload) {
  const cluster = payload.cluster || { enabled: false };
  if (!cluster.enabled) {
    renderNodeCluster(payload);
    return;
  }

  const fragment = document.createDocumentFragment();
  fragment.append(
    screenHeader(
      `CLUSTER JOBS · ${cluster.available ? "ONLINE" : "OFFLINE"}`,
      payload.time,
      cluster.available,
    ),
  );

  const overview = element("section", "cluster-job-overview");
  const summaries = element("div", "cluster-job-summaries");
  summaries.append(
    clusterSummary("QUEUED", cluster.queued, "queued"),
    clusterSummary("RUNNING", cluster.running, "running"),
    clusterSummary("COMPLETED", cluster.completed, "completed"),
  );
  const roster = element("div", "cluster-node-roster");
  payload.nodes.slice(0, 4).forEach((node) => {
    const chip = element("span", node.online ? "online" : "");
    chip.append(element("i", ""), document.createTextNode(node.name));
    roster.append(chip);
  });
  overview.append(summaries, roster);

  const list = element("section", "cluster-job-list");
  const running = (cluster.running_jobs || []).map((job) => ({ ...job, viewStatus: "running" }));
  const completed = [...(cluster.results || [])]
    .reverse()
    .map((job) => ({ ...job, viewStatus: "completed" }));
  const queued = (cluster.queued_jobs || []).map((job) => ({ ...job, viewStatus: "queued" }));
  const jobs = [...running, ...completed, ...queued].slice(0, 3);

  if (jobs.length) {
    jobs.forEach((job) => list.append(clusterJobRow(job)));
  } else {
    const empty = element("div", "cluster-job-empty");
    empty.append(
      element("strong", "", cluster.available ? "INGEN JOBBER ENNÅ" : "COORDINATOR UTILGJENGELIG"),
      element("span", "", cluster.message || "Start en primtallsjobb fra kontrollpanelet"),
    );
    list.append(empty);
  }

  fragment.append(overview, list);
  ui.screenContent.replaceChildren(fragment);
}

function renderNerd(payload) {
  const demo = payload.demo;
  const fragment = document.createDocumentFragment();
  fragment.append(screenHeader("NERD LAB · MONTE CARLO", payload.time, demo.status !== "error"));

  const body = element("section", "nerd-layout");
  const visual = element("div", "monte-visual");
  visual.append(element("span", "screen-overline", "TREFF / BOM"));
  const canvas = element("canvas", "monte-canvas");
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", "Tilfeldige punkter i en sirkel inni et kvadrat");
  const legend = element("div", "monte-legend");
  const hits = element("span", "legend-hit", `${Number(demo.inside || 0).toLocaleString("nb-NO")} TREFF`);
  const misses = element("span", "legend-miss", `${Number(demo.outside || 0).toLocaleString("nb-NO")} BOM`);
  legend.append(hits, misses);
  visual.append(canvas, legend);

  const stats = element("div", "demo-stats");
  const stateText = {
    idle: "READY TO RUN",
    running: "CALCULATING",
    finished: "COMPLETE",
    error: "ERROR",
  }[demo.status] || demo.status.toUpperCase();
  const stateLine = element("div", "demo-state-line");
  stateLine.append(element("span", demo.status === "running" ? "pulse-dot active" : "pulse-dot"), element("strong", "", stateText));

  const result = element("div", "pi-reading");
  result.append(
    element("span", "pi-symbol", "π"),
    element("strong", "pi-value", demo.estimate === null ? "3.———" : Number(demo.estimate).toFixed(6)),
    element("span", "pi-target", "MÅL 3.141593"),
  );

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
  const runtimeValue = element("div", "");
  runtimeValue.append(element("span", "", "RUNTIME"), element("strong", "", `${Number(demo.runtime_seconds).toFixed(2)} s`));
  const workersValue = element("div", "");
  workersValue.append(element("span", "", "WORKERS"), element("strong", "", String(demo.worker_count || 1)));
  const clockValue = element("div", "");
  clockValue.append(element("span", "", "CLOCK"), element("strong", "", frequencyText(payload.system.frequency_mhz).replace(" MHz", "")));
  runtime.append(runtimeValue, workersValue, clockValue);
  stats.append(
    stateLine,
    result,
    progressHeading,
    progressBar,
    runtime,
    systemHealthStrip(payload.system, true),
    element("p", "demo-hint", demo.status === "idle" ? "Velg kjerner og start jobben →" : payload.message),
  );
  body.append(visual, stats);
  fragment.append(body);
  ui.screenContent.replaceChildren(fragment);
  drawMonteCarlo(canvas, demo.points || []);
}

function fillSlotOptions(select, available) {
  const previous = Number(select.value || 1);
  const preferred = [1, 2, 4, 6, 8].filter((value) => value <= available);
  if (available > 0 && !preferred.includes(available)) preferred.push(available);
  preferred.sort((a, b) => a - b);
  select.replaceChildren(...preferred.map((value) => {
    const option = element("option", "", `${value} ${value === 1 ? "slot" : "slots"}`);
    option.value = String(value);
    return option;
  }));
  const selected = preferred.includes(previous) ? previous : preferred[preferred.length - 1];
  if (selected !== undefined) select.value = String(selected);
}

function updateCoreControls(payload) {
  const capacity = payload.cluster?.capacity || {};
  const total = Number(capacity.total_slots || 0);
  const reserved = Number(capacity.reserved_slots || 0);
  const demoAvailable = ui.reserveOne.checked ? reserved : total;
  const primeAvailable = ui.clusterReserveOne.checked ? reserved : total;
  fillSlotOptions(ui.cores, demoAvailable);
  fillSlotOptions(ui.clusterSlots, primeAvailable);
  ui.coreCountLabel.textContent = `${demoAvailable} av ${total} tilgjengelig`;
  const running = payload.demo.status === "running";
  const clusterReady = payload.cluster?.enabled && payload.cluster?.available;
  ui.reserveOne.disabled = running || total === 0;
  ui.cores.disabled = running || demoAvailable === 0;
  ui.startDemo.disabled = running || demoAvailable === 0 || !clusterReady;
  ui.clusterReserveOne.disabled = total === 0;
  ui.clusterSlots.disabled = primeAvailable === 0;
  const selected = Number(ui.cores.value || 0);
  ui.coreHint.textContent = demoAvailable
    ? `Bruker inntil ${selected} cluster-slot${selected === 1 ? "" : "s"}. Controlleren regner ikke.`
    : "Ingen online compute-workers er tilgjengelige.";
}

function updateClusterControls(payload) {
  const cluster = payload.cluster || { enabled: false, available: false };
  const ready = cluster.enabled && cluster.available;
  const capacity = cluster.capacity || {};
  const available = ui.clusterReserveOne.checked
    ? Number(capacity.reserved_slots || 0)
    : Number(capacity.total_slots || 0);
  ui.startClusterJob.disabled = !ready || available === 0;
  ui.clusterStateLabel.textContent = !cluster.enabled ? "AV" : cluster.available ? "ONLINE" : "OFFLINE";
  ui.clusterStateLabel.classList.toggle("online", ready);
  ui.clusterHelper.textContent = !cluster.enabled
    ? "Aktiver clusteret i config.local.json først."
    : cluster.available
      ? `${Number(cluster.queued || 0)} i kø · ${Number(cluster.running || 0)} kjører · ${Number(cluster.completed || 0)} ferdig`
      : "Coordinatoren svarer ikke. Resten av appen kjører normalt.";
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
  renderNodeStatus(payload);
  updateCoreControls(payload);
  updateClusterControls(payload);
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
    await postJson("/api/demo/start", {
      samples: Number(ui.iterations.value),
      slot_limit: Number(ui.cores.value),
      reserve_one: ui.reserveOne.checked,
    });
    await fetchState();
  } catch (error) {
    ui.connectionText.textContent = error.message;
    ui.startDemo.disabled = false;
  }
});

ui.startClusterJob.addEventListener("click", async () => {
  ui.startClusterJob.disabled = true;
  ui.startClusterLabel.textContent = "Oppretter …";
  try {
    const result = await postJson("/api/cluster/start", {
      start: Number(ui.clusterStart.value),
      end: Number(ui.clusterEnd.value),
      chunk_size: Number(ui.clusterChunkSize.value),
      slot_limit: Number(ui.clusterSlots.value),
      reserve_one: ui.clusterReserveOne.checked,
    });
    ui.clusterHelper.textContent = `${Number(result.created || 0)} deljobber opprettet.`;
    await fetchState();
  } catch (error) {
    ui.clusterHelper.textContent = error.message;
  } finally {
    ui.startClusterLabel.textContent = "Start cluster-jobb";
  }
});

ui.checkUpdate.addEventListener("click", checkForUpdate);
ui.cores.addEventListener("change", () => fetchState());
ui.reserveOne.addEventListener("change", () => fetchState());
ui.clusterSlots.addEventListener("change", () => fetchState());
ui.clusterReserveOne.addEventListener("change", () => fetchState());

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
