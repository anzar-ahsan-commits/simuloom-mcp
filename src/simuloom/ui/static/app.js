"use strict";

const state = {
  apiKey: sessionStorage.getItem("simuloom-api-key") || "",
  simulations: [],
  selectedId: null,
  role: "viewer",
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"]/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;",
}[character]));

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.apiKey) headers.set("Authorization", `Bearer ${state.apiKey}`);
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(`/api/v1${path}`, { ...options, headers });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof payload === "object" ? payload.detail || JSON.stringify(payload) : payload;
    throw new Error(message || `Request failed with ${response.status}`);
  }
  return payload;
}

function notify(message, error = false) {
  const notice = $("#notice");
  notice.textContent = message;
  notice.classList.toggle("error", error);
  notice.hidden = false;
  clearTimeout(notify.timer);
  notify.timer = setTimeout(() => { notice.hidden = true; }, 5000);
}

function setBusy(button, busy) {
  if (!button) return;
  if (busy) button.dataset.label = button.textContent;
  button.disabled = busy;
  button.textContent = busy ? "Working…" : button.dataset.label || button.textContent;
}

function showResult(title, payload) {
  const drawer = $("#result-drawer");
  if (!drawer) return;
  $("strong", drawer).textContent = title;
  $("pre", drawer).textContent = JSON.stringify(payload, null, 2);
  drawer.hidden = false;
  drawer.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function switchView(name) {
  $$(".view").forEach((view) => view.classList.toggle("active", view.id === `${name}-view`));
  $$(".nav-item[data-view]").forEach((item) => item.classList.toggle("active", item.dataset.view === name));
  $("#page-title").textContent = name === "overview" ? "Operational overview" : "Simulation workspace";
}

async function loadDashboard() {
  try {
    const [health, capabilities, simulations, session] = await Promise.all([
      api("/health"), api("/runtime"), api("/simulations"), api("/session"),
    ]);
    state.simulations = simulations;
    state.role = session.role;
    $("#auth-button").textContent = `${session.role} session`;
    $("#new-simulation-button").disabled = session.role === "viewer";
    $("#empty-create-button").disabled = session.role === "viewer";
    $("#runtime-name").textContent = capabilities.runtime;
    $("#runtime-storage").textContent = capabilities.persistent
      ? `${capabilities.storage} · durable`
      : `${capabilities.storage} · ephemeral`;
    $("#runtime-health").textContent = health.runtimeReady ? "Ready" : "Unavailable";
    $("#runtime-detail").textContent = health.runtimeReady ? "Adapter responding" : "Check runtime connection";
    $("#sidebar-runtime").textContent = `${capabilities.runtime} ${health.runtimeReady ? "ready" : "offline"}`;
    $("#sidebar-runtime-dot").classList.toggle("ready", health.runtimeReady);
    $("#simulation-count").textContent = simulations.length;
    $("#report-count").textContent = simulations.filter((item) => item.has_report).length;
    renderSimulations();
  } catch (error) {
    notify(error.message, true);
    if (/valid Bearer|Authentication required/i.test(error.message)) $("#auth-dialog").showModal();
  }
}

function simulationCard(item) {
  return `<button class="simulation-card" data-simulation="${escapeHtml(item.id)}">
    <div class="simulation-card-top"><div><p>${escapeHtml(item.active_profile)} profile</p><h3>${escapeHtml(item.name)}</h3></div><span class="status">${escapeHtml(item.status)}</span></div>
    <p>${escapeHtml(item.id)}</p>
    <div class="card-stats"><span><b>${item.operation_count}</b>operations</span><span><b>${item.scenario_count}</b>scenarios</span><span><b>${item.has_report ? "Yes" : "—"}</b>evidence</span></div>
  </button>`;
}

function renderSimulations() {
  const grid = $("#simulation-grid");
  grid.innerHTML = state.simulations.map(simulationCard).join("");
  $("#empty-state").hidden = state.simulations.length > 0;
  const list = $("#simulation-list");
  list.innerHTML = state.simulations.map((item) => `<button data-simulation="${escapeHtml(item.id)}" class="${item.id === state.selectedId ? "active" : ""}"><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.status)} · ${item.operation_count} operations</small></button>`).join("");
  $$('[data-simulation]').forEach((button) => button.addEventListener("click", () => selectSimulation(button.dataset.simulation)));
}

function detailTemplate(item) {
  return `<div class="detail-header"><p class="eyebrow">${escapeHtml(item.status)} · ${escapeHtml(item.active_profile)} profile</p><h2>${escapeHtml(item.name)}</h2><code>${escapeHtml(item.id)} · ${escapeHtml(item.fingerprint)}</code></div>
  <div class="workflow">
    <section class="workflow-section"><h3>1. Synthetic data</h3><p>Create reproducible contract-derived requests for compilation and validation.</p><label>Records<input id="record-count" type="number" min="1" max="10000" value="25"></label><div class="workflow-actions"><button class="button" data-action="generate">Generate data</button><button class="button ghost" data-action="dataset">Inspect data</button></div></section>
    <section class="workflow-section"><h3>2. Runtime bundle</h3><p>Compile portable mappings, then deploy them to the selected runtime adapter.</p><div class="workflow-actions"><button class="button" data-action="compile">Compile</button><button class="button primary" data-action="deploy">Deploy</button></div></section>
    <section class="workflow-section"><h3>3. Behavior</h3><p>Activate a deterministic normal, slow, unavailable, or intermittent profile.</p><label>Profile<select id="profile-select"><option>normal</option><option>slow</option><option>unavailable</option><option>intermittent</option></select></label><div class="workflow-actions"><button class="button" data-action="profile">Activate profile</button></div></section>
    <section class="workflow-section"><h3>4. Validation</h3><p>Preview or execute contract, boundary, negative, pairwise, and scenario cases.</p><label><input id="edge-cases" type="checkbox"> Boundary and negative cases</label><label><input id="pairwise-cases" type="checkbox"> Pairwise cases</label><div class="workflow-actions"><button class="button" data-action="plan">Preview plan</button><button class="button primary" data-action="validate">Run validation</button></div></section>
    <section class="workflow-section"><h3>5. Evidence</h3><p>Inspect machine-readable coverage or download the human-readable report.</p><div class="workflow-actions"><button class="button" data-action="report">Latest evidence</button><button class="button ghost" data-action="report-html">Download HTML report</button><button class="button ghost" data-action="export">Export bundle</button></div></section>
    <section class="workflow-section"><h3>6. Scenario state</h3><p>Inspect or reset a configured scenario by its stable scenario ID.</p><label>Scenario ID<input id="scenario-id" placeholder="order-lifecycle" pattern="[a-z0-9][a-z0-9-]*"></label><div class="workflow-actions"><button class="button" data-action="scenario-state">Inspect state</button><button class="button ghost" data-action="scenario-reset">Reset</button></div></section>
  </div>
  <div id="result-drawer" class="result-drawer" hidden><strong>Result</strong><pre></pre></div>`;
}

function selectSimulation(id) {
  const item = state.simulations.find((candidate) => candidate.id === id);
  if (!item) return;
  state.selectedId = id;
  switchView("simulations");
  renderSimulations();
  $("#simulation-detail").innerHTML = detailTemplate(item);
  if (state.role === "viewer") {
    $$('[data-action="generate"], [data-action="compile"], [data-action="deploy"], [data-action="profile"], [data-action="validate"], [data-action="scenario-reset"]', $("#simulation-detail"))
      .forEach((button) => { button.disabled = true; button.title = "Operator role required"; });
  }
  $$('[data-action]', $("#simulation-detail")).forEach((button) => button.addEventListener("click", () => runAction(button)));
}

function validationPayload(execute = false) {
  const edge = $("#edge-cases").checked;
  return {
    max_dataset_cases: 3,
    ...(execute ? { reset_runtime_state: true } : {}),
    include_boundary_cases: edge,
    include_negative_cases: edge,
    max_edge_cases_per_operation: 12,
    include_pairwise_cases: $("#pairwise-cases").checked,
    max_pairwise_cases_per_operation: 25,
  };
}

async function openArtifact(path, downloadName = null) {
  const headers = new Headers();
  if (state.apiKey) headers.set("Authorization", `Bearer ${state.apiKey}`);
  const response = await fetch(`/api/v1${path}`, { headers });
  if (!response.ok) {
    let message = `Request failed with ${response.status}`;
    try { message = (await response.json()).detail || message; } catch { /* non-JSON error */ }
    throw new Error(message);
  }
  const url = URL.createObjectURL(await response.blob());
  if (downloadName) {
    const link = document.createElement("a");
    link.href = url; link.download = downloadName; link.click();
  } else {
    window.open(url, "_blank", "noopener");
  }
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}

async function runAction(button) {
  const id = state.selectedId;
  const action = button.dataset.action;
  const scenarioId = $("#scenario-id")?.value.trim();
  const actions = {
    generate: () => api(`/simulations/${id}/data`, { method: "POST", body: JSON.stringify({ records: Number($("#record-count").value), seed: 1207 }) }),
    dataset: () => api(`/simulations/${id}/data`),
    compile: () => api(`/simulations/${id}/compile`, { method: "POST" }),
    deploy: () => api(`/simulations/${id}/deploy`, { method: "POST", body: JSON.stringify({ reset_existing: false }) }),
    profile: () => api(`/simulations/${id}/profiles/${$("#profile-select").value}`, { method: "PUT", body: JSON.stringify({ fixed_delay_ms: 2000, failure_status: 503 }) }),
    plan: () => api(`/simulations/${id}/validation/plan`, { method: "POST", body: JSON.stringify(validationPayload()) }),
    validate: () => api(`/simulations/${id}/validate`, { method: "POST", body: JSON.stringify(validationPayload(true)) }),
    report: () => api(`/simulations/${id}/reports/latest`),
    "scenario-state": () => scenarioId ? api(`/simulations/${id}/scenarios/${scenarioId}/state`) : Promise.reject(new Error("Enter a scenario ID")),
    "scenario-reset": () => scenarioId ? api(`/simulations/${id}/scenarios/${scenarioId}/reset`, { method: "POST" }) : Promise.reject(new Error("Enter a scenario ID")),
  };
  if (action === "report-html") {
    try { await openArtifact(`/simulations/${id}/reports/latest/html`, `${id}-evidence.html`); } catch (error) { notify(error.message, true); }
    return;
  }
  if (action === "export") {
    try { await openArtifact(`/simulations/${id}/export/bundle`, `${id}.simuloom.zip`); } catch (error) { notify(error.message, true); }
    return;
  }
  setBusy(button, true);
  try {
    const result = await actions[action]();
    showResult(button.dataset.label || button.textContent, result);
    notify(`${button.dataset.label || "Operation"} completed`);
    await loadDashboard();
  } catch (error) {
    notify(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function createSimulation(event) {
  event.preventDefault();
  const submit = $('button[type="submit"]', event.currentTarget);
  setBusy(submit, true);
  try {
    const result = await api("/simulations/from-contract", { method: "POST", body: new FormData(event.currentTarget) });
    $("#create-dialog").close();
    event.currentTarget.reset();
    await loadDashboard();
    selectSimulation(result.id);
    notify("Simulation workspace created");
  } catch (error) {
    notify(error.message, true);
  } finally {
    setBusy(submit, false);
  }
}

function initialize() {
  $$(".nav-item[data-view]").forEach((item) => item.addEventListener("click", () => switchView(item.dataset.view)));
  ["#new-simulation-button", "#empty-create-button"].forEach((selector) => $(selector).addEventListener("click", () => $("#create-dialog").showModal()));
  $("#auth-button").addEventListener("click", () => { $("#api-key-input").value = state.apiKey; $("#auth-dialog").showModal(); });
  $("#refresh-button").addEventListener("click", loadDashboard);
  $("#create-form").addEventListener("submit", createSimulation);
  $("#auth-form").addEventListener("submit", (event) => {
    event.preventDefault();
    state.apiKey = $("#api-key-input").value.trim();
    if (state.apiKey) sessionStorage.setItem("simuloom-api-key", state.apiKey);
    else sessionStorage.removeItem("simuloom-api-key");
    $("#auth-dialog").close();
    loadDashboard();
  });
  $("#clear-key-button").addEventListener("click", () => {
    state.apiKey = ""; sessionStorage.removeItem("simuloom-api-key"); $("#api-key-input").value = "";
  });
  $$('[data-close]').forEach((button) => button.addEventListener("click", () => $(`#${button.dataset.close}`).close()));
  loadDashboard();
}

document.addEventListener("DOMContentLoaded", initialize);
