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
const sampleDescription = document.getElementById("sampleDescription");
let lastChallengePayload = null;

sampleSelect.addEventListener("change", () => loadSample(sampleSelect.value));
editor.addEventListener("input", () => {
  markCustomSource("Custom program");
  shareStatus.textContent = "not shared";
});
runButton.addEventListener("click", runProgram);
copyLinkButton.addEventListener("click", copyShareLink);
challengeButton.addEventListener("click", runChallengeSuite);
copyChallengeButton.addEventListener("click", copyChallengeJson);
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
  challengeView.className = "";
  try {
    const payload = engineMode === "static" ? window.EBaseStaticRuntime.runChallengeSuite() : await fetchChallengeSuite();
    if (!payload.ok) {
      throw new Error(payload.error || "challenge failed");
    }
    lastChallengePayload = payload;
    renderChallenge(payload);
  } catch (error) {
    try {
      engineMode = "static";
      updateEngineStatus();
      const payload = window.EBaseStaticRuntime.runChallengeSuite();
      lastChallengePayload = payload;
      renderChallenge(payload);
    } catch (fallbackError) {
      lastChallengePayload = null;
      copyChallengeButton.disabled = true;
      challengeStatus.textContent = "error";
      challengeView.className = "error";
      challengeView.textContent = `${error}\n\nStatic fallback also failed:\n${fallbackError}`;
    }
  } finally {
    challengeButton.disabled = false;
  }
}

async function fetchChallengeSuite() {
  const response = await fetch("/api/challenge");
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
  outputView.className = "";
  outputView.textContent = JSON.stringify(payload.output, null, 2);
  assemblyView.textContent = payload.assembly;
  renderEvents(payload.timeline);
  renderRegisters(payload.snapshot);
  renderFields(payload.snapshot);
  drawTimeline(payload.timeline);
}

function renderChallenge(payload) {
  const results = Array.isArray(payload.results) ? payload.results : [];
  const staticDemo = Boolean(payload.static_fallback);
  challengeStatus.textContent = staticDemo
    ? `demo only correct=${payload.correct} score=${payload.total_score}`
    : `official correct=${payload.correct} score=${payload.total_score}`;
  copyChallengeButton.disabled = staticDemo;
  challengeView.textContent = JSON.stringify({
    official_submission: !staticDemo,
    demo_only: staticDemo,
    correct: payload.correct,
    total_score: payload.total_score,
    results: results.map((result) => ({
      slug: result.slug,
      correct: result.correct,
      score: result.score.score,
      steps: result.steps,
      assembly_lines: result.assembly_lines,
      degraded_events: result.score.degraded_events
    }))
  }, null, 2);
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
  drawTimeline([]);
}

function renderEvents(timeline) {
  eventList.innerHTML = "";
  for (const event of timeline) {
    const node = document.createElement("div");
    node.className = "event";
    node.innerHTML = `<span>#${event.tick}</span><strong>${event.op}</strong><span>${event.flags.join(", ")}</span>`;
    eventList.appendChild(node);
  }
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

function drawTimeline(timeline) {
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
  context.fillStyle = "#15201c";
  context.font = "13px Segoe UI";
  context.fillText(`max temperature ${max.toFixed(3)}`, 14, 20);
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
