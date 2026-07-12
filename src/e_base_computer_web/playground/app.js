const staticOnlyHost = window.location.protocol === "file:" || (window.location.hostname || "").endsWith(".github.io");
let samples = window.EBaseStaticRuntime.samples();
let engineMode = staticOnlyHost ? "static" : "server";
const editor = document.getElementById("sourceEditor");
const sampleSelect = document.getElementById("sampleSelect");
const languageSelect = document.getElementById("languageSelect");
const precisionInput = document.getElementById("precisionInput");
const runButton = document.getElementById("runButton");
const copyLinkButton = document.getElementById("copyLinkButton");
const challengeButton = document.getElementById("challengeButton");
const challengeSuiteSelect = document.getElementById("challengeSuiteSelect");
const copyChallengeButton = document.getElementById("copyChallengeButton");
const metrics = document.getElementById("metrics");
const outputView = document.getElementById("outputView");
const assemblyView = document.getElementById("assemblyView");
const challengeStatus = document.getElementById("challengeStatus");
const challengeView = document.getElementById("challengeView");
const shareStatus = document.getElementById("shareStatus");
const engineStatus = document.getElementById("engineStatus");
const eventList = document.getElementById("eventList");
const registerLadder = document.getElementById("registerLadder");
const fieldMap = document.getElementById("fieldMap");
const canvas = document.getElementById("timelineCanvas");
const timelineScrubber = document.getElementById("timelineScrubber");
const timelineStatus = document.getElementById("timelineStatus");
const stepDetail = document.getElementById("stepDetail");
const operationProfile = document.getElementById("operationProfile");
const sampleDescription = document.getElementById("sampleDescription");
let lastChallengePayload = null;
let lastTimeline = [];
let selectedTimelineIndex = -1;

sampleSelect.addEventListener("change", () => loadSample(sampleSelect.value));
editor.addEventListener("input", () => {
  markCustomSource("Custom program");
  shareStatus.textContent = "not shared";
});
runButton.addEventListener("click", runProgram);
copyLinkButton.addEventListener("click", copyShareLink);
challengeButton.addEventListener("click", runChallengeSuite);
copyChallengeButton.addEventListener("click", copyChallengeJson);
timelineScrubber.addEventListener("input", () => selectTimelineIndex(Number(timelineScrubber.value)));
canvas.addEventListener("click", selectTimelineFromCanvas);
window.addEventListener("hashchange", () => {
  if (loadSharedState()) {
    runProgram();
  }
});
initialize();

async function initialize() {
  updateEngineStatus();
  samples = await fetchSamples();
  renderSampleOptions();
  if (!loadSharedState()) {
    loadSample(samples[0].slug);
  }
  runProgram();
}

async function fetchSamples() {
  if (staticOnlyHost) {
    return window.EBaseStaticRuntime.samples();
  }
  try {
    const response = await fetch("/api/samples");
    const payload = await response.json();
    if (payload.ok && Array.isArray(payload.samples) && payload.samples.length) {
      return payload.samples;
    }
  } catch (error) {
    console.warn("using fallback samples", error);
  }
  engineMode = "static";
  updateEngineStatus();
  return window.EBaseStaticRuntime.samples();
}

function renderSampleOptions() {
  sampleSelect.innerHTML = "";
  for (const sample of samples) {
    const option = document.createElement("option");
    option.value = sample.slug;
    option.textContent = sample.title;
    sampleSelect.appendChild(option);
  }
}

function loadSample(slug) {
  const sample = samples.find((item) => item.slug === slug) || samples[0];
  editor.value = sample.source;
  languageSelect.value = sample.language;
  sampleDescription.textContent = sample.description || sample.title;
  shareStatus.textContent = "not shared";
}

function loadSharedState() {
  const rawHash = window.location.hash.replace(/^#/, "");
  if (!rawHash) {
    return false;
  }
  const params = new URLSearchParams(rawHash);
  const source = params.get("source");
  const language = params.get("lang");
  const precision = params.get("precision");
  if (!source || !["c", "asm"].includes(language || "")) {
    return false;
  }
  editor.value = source;
  languageSelect.value = language;
  if (precision !== null && precision !== "") {
    precisionInput.value = precision;
  }
  markCustomSource("Shared program");
  shareStatus.textContent = "shared link";
  return true;
}

async function runProgram() {
  runButton.disabled = true;
  try {
    const request = {
      source: editor.value,
      language: languageSelect.value,
      precision: Number(precisionInput.value || 8),
      maxSteps: 10000
    };
    const payload = engineMode === "static" ? runStaticProgram(request) : await runServerProgram(request);
    renderPayload(payload);
  } catch (error) {
    if (engineMode !== "static") {
      try {
        engineMode = "static";
        updateEngineStatus();
        renderPayload(runStaticProgram({
          source: editor.value,
          language: languageSelect.value,
          precision: Number(precisionInput.value || 8),
          maxSteps: 10000
        }));
      } catch (fallbackError) {
        showError(`${error}\n\nStatic fallback also failed:\n${fallbackError}`);
      }
    } else {
      showError(String(error));
    }
  } finally {
    runButton.disabled = false;
  }
}

async function runServerProgram(request) {
  const response = await fetch("/api/run", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(request)
  });
  const payload = await response.json();
  if (!payload.ok) {
    throw new Error(payload.error || "unknown error");
  }
  engineMode = "server";
  updateEngineStatus();
  return payload;
}

function runStaticProgram(request) {
  const payload = window.EBaseStaticRuntime.run(request);
  engineMode = "static";
  updateEngineStatus();
  return payload;
}

async function runChallengeSuite() {
  challengeButton.disabled = true;
  challengeStatus.textContent = "running";
  challengeView.className = "challengeView";
  try {
    const suite = challengeSuiteSelect.value;
    const payload = engineMode === "static"
      ? window.EBaseStaticRuntime.runChallengeSuite(suite)
      : await fetchChallengeSuite(suite);
    if (!payload.ok) {
      throw new Error(payload.error || "challenge failed");
    }
    lastChallengePayload = payload;
    renderChallenge(payload);
  } catch (error) {
    try {
      engineMode = "static";
      updateEngineStatus();
      const payload = window.EBaseStaticRuntime.runChallengeSuite(challengeSuiteSelect.value);
      lastChallengePayload = payload;
      renderChallenge(payload);
    } catch (fallbackError) {
      lastChallengePayload = null;
      copyChallengeButton.disabled = true;
      challengeStatus.textContent = "error";
      challengeView.className = "challengeView error";
      challengeView.textContent = `${error}\n\nStatic fallback also failed:\n${fallbackError}`;
    }
  } finally {
    challengeButton.disabled = false;
  }
}

async function fetchChallengeSuite(suite) {
  const response = await fetch(`/api/challenge?suite=${encodeURIComponent(suite)}`);
  const payload = await response.json();
  if (payload.ok) {
    engineMode = "server";
    updateEngineStatus();
  }
  return payload;
}

async function copyChallengeJson() {
  if (!lastChallengePayload) {
    return;
  }
  const text = JSON.stringify(lastChallengePayload, null, 2);
  try {
    await navigator.clipboard.writeText(text);
    challengeStatus.textContent = "copied";
  } catch (error) {
    challengeStatus.textContent = "copy unavailable";
    challengeView.textContent = text;
  }
}

async function copyShareLink() {
  const url = buildShareUrl();
  if (url.length > 7800) {
    shareStatus.textContent = "link too long";
    return;
  }
  history.replaceState(null, "", url);
  try {
    await navigator.clipboard.writeText(url);
    shareStatus.textContent = "link copied";
  } catch (error) {
    shareStatus.textContent = "address bar updated";
  }
}

function buildShareUrl() {
  const params = new URLSearchParams();
  params.set("lang", languageSelect.value);
  params.set("precision", String(Number(precisionInput.value || 8)));
  params.set("source", editor.value);
  const url = new URL(window.location.href);
  url.hash = params.toString();
  return url.toString();
}

function markCustomSource(label) {
  const customValue = "__custom__";
  let option = sampleSelect.querySelector(`option[value="${customValue}"]`);
  if (!option) {
    option = document.createElement("option");
    option.value = customValue;
    sampleSelect.appendChild(option);
  }
  option.textContent = label;
  sampleSelect.value = customValue;
  sampleDescription.textContent = label;
}

function renderPayload(payload) {
  const score = payload.score;
  metrics.innerHTML = "";
  addMetric("engine", payload.static_fallback ? "static" : "server");
  addMetric("score", score.score);
  addMetric("steps", score.steps);
  addMetric("max temp", score.max_temperature);
  addMetric("observations", score.observations);
  addMetric("degraded", score.degraded_events);
  addMetric("refreshes", score.refresh_events);
  addMetric("memory cells", score.memory_cells);
  outputView.className = "";
  outputView.textContent = JSON.stringify(payload.output, null, 2);
  assemblyView.textContent = payload.assembly;
  lastTimeline = Array.isArray(payload.timeline) ? payload.timeline : [];
  renderEvents(lastTimeline);
  renderOperationProfile(lastTimeline);
  timelineScrubber.max = String(Math.max(0, lastTimeline.length - 1));
  timelineScrubber.disabled = !lastTimeline.length;
  selectTimelineIndex(lastTimeline.length - 1, payload.snapshot);
}

function renderChallenge(payload) {
  const results = Array.isArray(payload.results) ? payload.results : [];
  const staticDemo = Boolean(payload.static_fallback);
  const suite = payload.suite || challengeSuiteSelect.value;
  challengeStatus.textContent = staticDemo
    ? `demo ${suite} correct=${payload.correct} score=${payload.total_score}`
    : `${suite} correct=${payload.correct} score=${payload.total_score}`;
  copyChallengeButton.disabled = staticDemo;
  challengeView.innerHTML = "";
  const table = document.createElement("table");
  table.className = "challengeTable";
  const numerical = suite === "numerical";
  const headings = numerical
    ? ["kernel", "ok", "digits", "error", "steps", "perf", "total"]
    : ["challenge", "ok", "steps", "temp", "degraded", "score"];
  const head = document.createElement("tr");
  headings.forEach((label) => {
    const cell = document.createElement("th");
    cell.textContent = label;
    head.appendChild(cell);
  });
  table.appendChild(head);
  results.forEach((result) => {
    const values = numerical
      ? [result.slug, result.correct, result.accuracy_digits, result.relative_error, result.steps, result.score.score, result.numerical_score]
      : [result.slug, result.correct, result.steps, result.score.max_temperature, result.score.degraded_events, result.score.score];
    const row = document.createElement("tr");
    values.forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = String(value);
      row.appendChild(cell);
    });
    table.appendChild(row);
  });
  challengeView.appendChild(table);
}

function updateEngineStatus() {
  engineStatus.textContent = engineMode === "static" ? "static fallback" : "server";
  engineStatus.className = engineMode === "static" ? "engineStatus static" : "engineStatus";
}

function addMetric(label, value) {
  const node = document.createElement("div");
  node.className = "metric";
  node.innerHTML = `<span>${label}</span><strong>${value}</strong>`;
  metrics.appendChild(node);
}

function showError(message) {
  metrics.innerHTML = "";
  outputView.className = "error";
  outputView.textContent = message;
  assemblyView.textContent = "";
  eventList.innerHTML = "";
  registerLadder.innerHTML = "";
  fieldMap.innerHTML = "";
  operationProfile.innerHTML = "";
  stepDetail.textContent = "";
  lastTimeline = [];
  drawTimeline([]);
}

function renderEvents(timeline) {
  eventList.innerHTML = "";
  timeline.forEach((event, index) => {
    const node = document.createElement("button");
    node.type = "button";
    node.className = "event";
    node.innerHTML = `<span>#${event.tick}</span><strong>${event.op}</strong><span>${event.flags.join(", ")}</span>`;
    node.addEventListener("click", () => selectTimelineIndex(index));
    eventList.appendChild(node);
  });
}

function selectTimelineIndex(index, fallbackSnapshot) {
  if (!lastTimeline.length) {
    selectedTimelineIndex = -1;
    timelineStatus.textContent = "no trace";
    renderRegisters(fallbackSnapshot || {er: {}});
    renderFields(fallbackSnapshot || {fields: {}});
    drawTimeline([]);
    return;
  }
  selectedTimelineIndex = Math.max(0, Math.min(lastTimeline.length - 1, index));
  timelineScrubber.value = String(selectedTimelineIndex);
  const event = lastTimeline[selectedTimelineIndex];
  const snapshot = event.after || fallbackSnapshot || {};
  timelineStatus.textContent = `tick ${event.tick} / ${lastTimeline.length} · ${event.op}`;
  stepDetail.textContent = formatEventDetail(event, snapshot);
  renderRegisters(snapshot);
  renderFields(snapshot);
  drawTimeline(lastTimeline, selectedTimelineIndex);
  Array.from(eventList.children).forEach((node, nodeIndex) => {
    node.classList.toggle("selected", nodeIndex === selectedTimelineIndex);
  });
}

function formatEventDetail(event, snapshot) {
  const lines = [`tick=${event.tick} op=${event.op}`];
  if (event.source) lines.push(`source: ${event.source}`);
  if (Array.isArray(event.args) && event.args.length) lines.push(`args: ${event.args.join(", ")}`);
  if (Array.isArray(event.targets) && event.targets.length) lines.push(`targets: ${event.targets.join(", ")}`);
  if (Array.isArray(event.flags) && event.flags.length) lines.push(`flags: ${event.flags.join(", ")}`);
  const precision = snapshotPrecision(snapshot);
  lines.push(`max_temperature=${maxTemp({after: snapshot}).toFixed(4)} q_max=${precision.qMax} current_partition=${precision.current}`);
  return lines.join("\n");
}

function selectTimelineFromCanvas(event) {
  if (!lastTimeline.length) return;
  const rect = canvas.getBoundingClientRect();
  const ratio = (event.clientX - rect.left) / Math.max(1, rect.width);
  selectTimelineIndex(Math.round(ratio * (lastTimeline.length - 1)));
}

function renderRegisters(snapshot) {
  registerLadder.innerHTML = "";
  const registers = Object.entries(snapshot.er || {})
    .filter(([, value]) => Math.abs(Number(value.real || 0)) > 1e-12 || Number(value.temperature || 0) > 0);
  if (!registers.length) {
    registerLadder.textContent = "No active E registers";
    return;
  }
  for (const [name, value] of registers) {
    const row = document.createElement("div");
    row.className = "registerRow";
    const digits = (value.digits || []).map((digit) => {
      const width = Math.max(3, Math.min(100, Number(digit.digit || 0) / Math.E * 100));
      return `<div class="digit"><span>e^${digit.exponent}</span><div class="bar" style="width:${width}%"></div><span>${Number(digit.digit).toFixed(3)}</span></div>`;
    }).join("") || `<div class="digit"><span>zero</span><div class="bar" style="width:3%"></div><span>0.000</span></div>`;
    row.innerHTML = `
      <div class="registerHead">
        <strong>${name}</strong>
        <span>${value.mode} real=${Number(value.real || 0).toFixed(6)} temp=${Number(value.temperature || 0).toFixed(3)}</span>
      </div>
      <div class="digits">${digits}</div>
    `;
    registerLadder.appendChild(row);
  }
}

function renderFields(snapshot) {
  fieldMap.innerHTML = "";
  const fields = Object.entries(snapshot.fields || {});
  if (!fields.length) {
    fieldMap.textContent = "No allocated E fields";
    return;
  }
  for (const [name, field] of fields) {
    const row = document.createElement("div");
    row.className = "fieldRow";
    const cells = (field.cells || []).map((cell) => {
      const heat = Math.max(0, Math.min(1, Number(cell.temperature || 0) / 3));
      const red = Math.round(232 + heat * 23);
      const green = Math.round(241 - heat * 110);
      const blue = Math.round(237 - heat * 120);
      return `<div class="cell" style="background:rgb(${red},${green},${blue})">${Number(cell.value || 0).toFixed(2)}</div>`;
    }).join("");
    row.innerHTML = `
      <div class="fieldHead">
        <strong>${name} @ ${field.bank_id}</strong>
        <span>${field.mode} q=${field.current_partition}/${field.q_max} temp=${Number(field.temperature || 0).toFixed(3)}</span>
      </div>
      <div class="cells">${cells}</div>
    `;
    fieldMap.appendChild(row);
  }
}

function drawTimeline(timeline, selectedIndex = -1) {
  const context = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  context.clearRect(0, 0, width, height);
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, width, height);
  context.strokeStyle = "#cdd8d3";
  context.lineWidth = 1;
  for (let y = 30; y < height; y += 40) {
    context.beginPath();
    context.moveTo(0, y);
    context.lineTo(width, y);
    context.stroke();
  }
  if (!timeline.length) {
    return;
  }
  const temps = timeline.map(maxTemp);
  const precisions = timeline.map((event) => snapshotPrecision(event.after || {}).qMax);
  const max = Math.max(0.1, ...temps);
  context.strokeStyle = "#c93324";
  context.lineWidth = 3;
  context.beginPath();
  temps.forEach((temp, index) => {
    const x = timeline.length === 1 ? 0 : (index / (timeline.length - 1)) * (width - 28) + 14;
    const y = height - 18 - (temp / max) * (height - 42);
    if (index === 0) {
      context.moveTo(x, y);
    } else {
      context.lineTo(x, y);
    }
  });
  context.stroke();
  context.strokeStyle = "#2367b1";
  context.lineWidth = 2;
  context.beginPath();
  precisions.forEach((partition, index) => {
    const x = timelineX(index, timeline.length, width);
    const y = height - 18 - (partition / 243) * (height - 42);
    if (index === 0) context.moveTo(x, y);
    else context.lineTo(x, y);
  });
  context.stroke();
  if (selectedIndex >= 0) {
    const x = timelineX(selectedIndex, timeline.length, width);
    context.strokeStyle = "#0e7c66";
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(x, 28);
    context.lineTo(x, height - 16);
    context.stroke();
  }
  context.fillStyle = "#15201c";
  context.font = "13px Segoe UI";
  context.fillText(`temperature ${max.toFixed(3)}`, 14, 20);
  context.fillStyle = "#2367b1";
  context.fillText("q_max 3–243", 180, 20);
}

function timelineX(index, count, width) {
  return count === 1 ? 14 : (index / (count - 1)) * (width - 28) + 14;
}

function snapshotPrecision(snapshot) {
  const values = [];
  for (const value of Object.values(snapshot.er || {})) {
    values.push({qMax: Number(value.q_max || 243), current: Number(value.current_partition || 243)});
  }
  for (const field of Object.values(snapshot.fields || {})) {
    values.push({qMax: Number(field.q_max || 243), current: Number(field.current_partition || 243)});
    for (const cell of field.cells || []) {
      values.push({qMax: Number(cell.q_max || 243), current: Number(cell.current_partition || 243)});
    }
  }
  if (!values.length) return {qMax: 243, current: 243};
  return {
    qMax: Math.min(...values.map((value) => value.qMax)),
    current: Math.min(...values.map((value) => value.current))
  };
}

function renderOperationProfile(timeline) {
  operationProfile.innerHTML = "";
  const counts = new Map();
  timeline.forEach((event) => counts.set(event.op, (counts.get(event.op) || 0) + 1));
  const rows = Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
  const maxCount = Math.max(1, ...rows.map(([, count]) => count));
  rows.forEach(([op, count]) => {
    const row = document.createElement("div");
    row.className = "profileRow";
    const label = document.createElement("span");
    label.textContent = op;
    const track = document.createElement("div");
    track.className = "profileBarTrack";
    const bar = document.createElement("div");
    bar.className = "profileBar";
    bar.style.width = `${(count / maxCount) * 100}%`;
    track.appendChild(bar);
    const value = document.createElement("strong");
    value.textContent = String(count);
    row.append(label, track, value);
    operationProfile.appendChild(row);
  });
}

function maxTemp(event) {
  const after = event.after || {};
  let max = 0;
  for (const value of Object.values(after.er || {})) {
    max = Math.max(max, Number(value.temperature || 0));
  }
  for (const field of Object.values(after.fields || {})) {
    max = Math.max(max, Number(field.temperature || 0));
    for (const cell of field.cells || []) {
      max = Math.max(max, Number(cell.temperature || 0));
    }
  }
  return max;
}
