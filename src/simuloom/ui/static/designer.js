"use strict";

const designer = {
  simulationId: "",
  scenarioId: "",
  scenarios: [],
  operations: [],
  definition: null,
  stateIndex: 0,
  handlerIndex: 0,
  diagnostics: [],
  revision: null,
  etag: null,
  savedSnapshot: null,
  releases: [],
};

const svgNamespace = "http://www.w3.org/2000/svg";

function svgElement(name, attributes = {}, text = null) {
  const element = document.createElementNS(svgNamespace, name);
  Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
  if (text !== null) element.textContent = text;
  return element;
}

function refreshDesignerSimulations() {
  const select = $("#designer-simulation");
  if (!select) return;
  const selected = designer.simulationId;
  select.innerHTML = '<option value="">Select a simulation</option>' + state.simulations
    .map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join("");
  select.value = selected;
}

async function chooseDesignerSimulation(simulationId) {
  if (!confirmDesignerDiscard()) {
    $("#designer-simulation").value = designer.simulationId;
    return;
  }
  designer.simulationId = simulationId;
  designer.scenarioId = "";
  designer.definition = null;
  if (!simulationId) {
    designer.scenarios = [];
    designer.operations = [];
    renderDesignerScenarioList();
    renderDesignerEmpty();
    return;
  }
  try {
    [designer.scenarios, designer.operations] = await Promise.all([
      api(`/simulations/${simulationId}/scenarios`),
      api(`/simulations/${simulationId}/operations`),
    ]);
    renderDesignerScenarioList();
    renderDesignerEmpty();
  } catch (error) {
    notify(error.message, true);
  }
}

function renderDesignerScenarioList() {
  const list = $("#designer-scenario-list");
  list.innerHTML = designer.scenarios.map((scenario) => `<button data-designer-scenario="${escapeHtml(scenario.scenario_id)}" class="${scenario.scenario_id === designer.scenarioId ? "active" : ""}"><strong>${escapeHtml(scenario.name)}</strong><small>${scenario.state_count} states · ${scenario.handler_count} handlers${scenario.warning_count ? ` · ${scenario.warning_count} warnings` : ""}</small></button>`).join("");
  $$('[data-designer-scenario]', list).forEach((button) => button.addEventListener("click", () => loadScenario(button.dataset.designerScenario)));
}

function renderDesignerEmpty() {
  $("#designer-workspace").innerHTML = '<div class="detail-empty"><span>↗</span><h2>Choose a scenario</h2><p>Select a simulation and scenario, or create a new visual workflow.</p></div>';
}

async function loadScenario(scenarioId, force = false) {
  if (!force && scenarioId !== designer.scenarioId && !confirmDesignerDiscard()) return;
  try {
    const [view, diagnostics, releases] = await Promise.all([
      api(`/simulations/${designer.simulationId}/scenarios/${scenarioId}`),
      api(`/simulations/${designer.simulationId}/scenarios/${scenarioId}/diagnostics`),
      api(`/simulations/${designer.simulationId}/scenarios/${scenarioId}/releases`),
    ]);
    designer.scenarioId = scenarioId;
    designer.definition = structuredClone(view.definition);
    designer.stateIndex = 0;
    designer.handlerIndex = 0;
    designer.diagnostics = diagnostics;
    designer.revision = view.revision;
    designer.etag = view.etag;
    designer.savedSnapshot = JSON.stringify(view.definition);
    designer.releases = releases;
    renderDesignerScenarioList();
    renderDesigner();
  } catch (error) {
    notify(error.message, true);
  }
}

function defaultHandler(operation, index = 1) {
  const responseCode = operation?.response_codes.find((code) => /^2\d\d$/.test(code))
    || operation?.response_codes.find((code) => /^\d{3}$/.test(code)) || "200";
  const path = (operation?.path || "/resource").replace(/\{[^}]+\}/g, "SYNTHETIC-ID");
  return {
    name: `handler ${index}`,
    request: { method: operation?.method || "GET", path, query_parameters: {}, headers: {}, json_body: null },
    response: { status: Number(responseCode), headers: {}, json_body: { synthetic: true } },
    new_state: null,
  };
}

function createScenarioDraft(metadata) {
  const operation = designer.operations[0];
  designer.scenarioId = metadata.scenario_id;
  designer.definition = {
    name: metadata.name,
    description: metadata.description,
    initial_state: "STARTED",
    states: [{ name: "STARTED", handlers: [defaultHandler(operation)] }],
    reset: { target_state: "STARTED" },
  };
  designer.stateIndex = 0;
  designer.handlerIndex = 0;
  designer.diagnostics = [];
  designer.revision = null;
  designer.etag = null;
  designer.savedSnapshot = null;
  designer.releases = [];
  renderDesignerScenarioList();
  renderDesigner();
}

function localDiagnostics() {
  if (!designer.definition) return [];
  const definition = designer.definition;
  const byName = new Map(definition.states.map((item) => [item.name, item]));
  const reachable = new Set([definition.initial_state]);
  const queue = [definition.initial_state];
  while (queue.length) {
    const current = byName.get(queue.shift());
    if (!current) continue;
    current.handlers.forEach((handler) => {
      if (handler.new_state && !reachable.has(handler.new_state)) {
        reachable.add(handler.new_state); queue.push(handler.new_state);
      }
    });
  }
  const result = [];
  definition.states.forEach((scenarioState) => {
    if (!reachable.has(scenarioState.name)) result.push({ severity: "warning", code: "unreachable-state", state: scenarioState.name, message: `State '${scenarioState.name}' is unreachable from the initial state` });
    const transitions = scenarioState.handlers.filter((handler) => handler.new_state);
    if (!transitions.length) result.push({ severity: "info", code: "terminal-state", state: scenarioState.name, message: `State '${scenarioState.name}' has no outgoing transitions` });
    transitions.filter((handler) => handler.new_state === scenarioState.name).forEach((handler) => result.push({ severity: "info", code: "self-transition", state: scenarioState.name, handler: handler.name, message: `Handler '${handler.name}' transitions back to '${scenarioState.name}'` }));
  });
  return result;
}

function renderDesigner() {
  if (!designer.definition) return renderDesignerEmpty();
  const definition = designer.definition;
  const readOnly = state.role === "viewer";
  $("#designer-workspace").innerHTML = `<div class="designer-toolbar">
    <div class="designer-toolbar-title"><p class="eyebrow">${escapeHtml(designer.scenarioId)}${designer.revision ? ` · revision ${designer.revision}` : " · unsaved"}${designer.releases.length ? ` · release ${designer.releases[0].release_number} runs revision ${designer.releases[0].revision}` : " · not deployed"}${designerIsDirty() ? " · modified" : ""}${readOnly ? " · read only" : ""}</p><h2>${escapeHtml(definition.name)}</h2></div>
    <button class="button ghost" data-designer-action="history">History</button>
    <button class="button ghost" data-designer-action="releases">Releases</button>
    <button class="button ghost" data-designer-action="export">Export</button>
    <button class="button" data-designer-action="save" data-designer-mutate>Save</button>
    <button class="button" data-designer-action="compile" data-designer-mutate>Compile</button>
    <button class="button primary" data-designer-action="deploy" data-designer-mutate>Deploy</button>
    <button class="button ghost" data-designer-action="runtime">Live state</button>
    <button class="button ghost" data-designer-action="reset" data-designer-mutate>Reset</button>
  </div><div class="designer-body"><div class="graph-pane"><div class="graph-heading"><h3>State graph</h3><div class="graph-legend"><span><i class="initial"></i>Initial</span><span><i></i>State</span></div></div><div class="graph-scroll"><svg id="scenario-graph" class="scenario-graph" viewBox="0 0 760 410" role="img" aria-label="Scenario state transition graph"></svg></div><div id="designer-diagnostics" class="diagnostic-list"></div><div id="designer-result" class="result-drawer" hidden><strong>Result</strong><pre></pre></div></div><aside id="designer-inspector" class="inspector"></aside></div>`;
  $$('[data-designer-action]').forEach((button) => button.addEventListener("click", () => runDesignerAction(button)));
  if (readOnly) $$('[data-designer-mutate]').forEach((button) => { button.disabled = true; button.title = "Operator role required"; });
  renderGraph();
  renderInspector();
}

function graphPositions(count) {
  const columns = Math.min(3, Math.max(1, count));
  return Array.from({ length: count }, (_, index) => ({
    x: 130 + (index % columns) * (500 / Math.max(1, columns - 1)),
    y: 90 + Math.floor(index / columns) * 145,
  }));
}

function renderGraph() {
  const svg = $("#scenario-graph");
  const definition = designer.definition;
  designer.diagnostics = localDiagnostics();
  const graphHeight = Math.max(410, Math.ceil(definition.states.length / 3) * 145 + 90);
  svg.setAttribute("viewBox", `0 0 760 ${graphHeight}`);
  svg.style.height = `${graphHeight}px`;
  svg.replaceChildren();
  const defs = svgElement("defs");
  const marker = svgElement("marker", { id: "arrowhead", markerWidth: "8", markerHeight: "6", refX: "7", refY: "3", orient: "auto" });
  marker.append(svgElement("path", { d: "M0,0 L8,3 L0,6 Z", fill: "#526782" }));
  defs.append(marker); svg.append(defs);
  const positions = graphPositions(definition.states.length);
  const indexByName = new Map(definition.states.map((item, index) => [item.name, index]));
  definition.states.forEach((scenarioState, sourceIndex) => {
    scenarioState.handlers.filter((handler) => handler.new_state && indexByName.has(handler.new_state)).forEach((handler) => {
      const targetIndex = indexByName.get(handler.new_state);
      const source = positions[sourceIndex]; const target = positions[targetIndex];
      if (sourceIndex === targetIndex) {
        svg.append(svgElement("path", { class: "graph-edge self", d: `M${source.x + 66},${source.y - 18} C${source.x + 145},${source.y - 90} ${source.x - 145},${source.y - 90} ${source.x - 66},${source.y - 18}` }));
        svg.append(svgElement("text", { class: "graph-edge-label", x: source.x, y: source.y - 72, "text-anchor": "middle" }, handler.name));
      } else {
        const midX = (source.x + target.x) / 2; const midY = (source.y + target.y) / 2;
        svg.append(svgElement("path", { class: "graph-edge", d: `M${source.x},${source.y} Q${midX},${midY - 34} ${target.x},${target.y}` }));
        svg.append(svgElement("text", { class: "graph-edge-label", x: midX, y: midY - 19, "text-anchor": "middle" }, handler.name));
      }
    });
  });
  definition.states.forEach((scenarioState, index) => {
    const position = positions[index];
    const warning = designer.diagnostics.some((item) => item.state === scenarioState.name && item.severity === "warning");
    const classes = ["graph-node", index === designer.stateIndex ? "selected" : "", scenarioState.name === definition.initial_state ? "initial" : "", warning ? "warning" : ""].filter(Boolean).join(" ");
    const group = svgElement("g", { class: classes, transform: `translate(${position.x - 72},${position.y - 30})`, tabindex: "0", role: "button", "aria-label": `Select state ${scenarioState.name}` });
    group.append(svgElement("rect", { width: "144", height: "60" }));
    group.append(svgElement("text", { x: "72", y: "25", "text-anchor": "middle" }, scenarioState.name));
    group.append(svgElement("text", { class: "node-meta", x: "72", y: "43", "text-anchor": "middle" }, `${scenarioState.handlers.length} handlers`));
    const selectNode = () => { designer.stateIndex = index; designer.handlerIndex = 0; renderGraph(); renderInspector(); };
    group.addEventListener("click", selectNode);
    group.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") selectNode(); });
    svg.append(group);
  });
  renderDiagnostics();
}

function renderDiagnostics() {
  const target = $("#designer-diagnostics");
  target.innerHTML = designer.diagnostics.length
    ? designer.diagnostics.map((item) => `<div class="diagnostic ${item.severity}"><b>${escapeHtml(item.severity)}</b><span>${escapeHtml(item.message)}</span></div>`).join("")
    : '<div class="diagnostic info"><b>Ready</b><span>Every declared state is reachable.</span></div>';
}

function operationForHandler(handler) {
  return designer.operations.find((operation) => operation.method === handler.request.method && operation.path.replace(/\{[^}]+\}/g, "SYNTHETIC-ID") === handler.request.path) || designer.operations[0];
}

function renderInspector() {
  const target = $("#designer-inspector");
  const definition = designer.definition;
  const scenarioState = definition.states[designer.stateIndex];
  if (!scenarioState) return;
  const handler = scenarioState.handlers[designer.handlerIndex] || null;
  const stateOptions = definition.states.map((item) => `<option value="${escapeHtml(item.name)}">${escapeHtml(item.name)}</option>`).join("");
  const operationOptions = designer.operations.map((operation) => `<option value="${escapeHtml(operation.operation_id)}">${escapeHtml(operation.method)} ${escapeHtml(operation.path)}</option>`).join("");
  target.innerHTML = `<section class="inspector-section"><div class="inspector-heading"><h3>Scenario</h3></div>
    <label>Name<input id="designer-name" value="${escapeHtml(definition.name)}"></label><label>Description<textarea id="designer-description">${escapeHtml(definition.description)}</textarea></label>
    <label>Initial state<select id="designer-initial">${stateOptions}</select></label><label>Reset state<select id="designer-reset">${stateOptions}</select></label></section>
    <section class="inspector-section"><div class="inspector-heading"><h3>States</h3><button class="mini-button" id="add-state" data-designer-mutate>+ Add state</button></div><div class="item-list">${definition.states.map((item, index) => `<div class="item-row"><button data-state-index="${index}" class="${index === designer.stateIndex ? "active" : ""}">${escapeHtml(item.name)}</button><button class="remove-button" data-remove-state="${index}" data-designer-mutate aria-label="Remove ${escapeHtml(item.name)}">×</button></div>`).join("")}</div><label>Selected state name<input id="selected-state-name" value="${escapeHtml(scenarioState.name)}"></label></section>
    <section class="inspector-section"><div class="inspector-heading"><h3>Handlers</h3><button class="mini-button" id="add-handler" data-designer-mutate>+ Add handler</button></div><div class="item-list">${scenarioState.handlers.map((item, index) => `<div class="item-row"><button data-handler-index="${index}" class="${index === designer.handlerIndex ? "active" : ""}">${escapeHtml(item.name)}</button><button class="remove-button" data-remove-handler="${index}" data-designer-mutate aria-label="Remove ${escapeHtml(item.name)}">×</button></div>`).join("")}</div></section>
    ${handler ? `<section class="inspector-section"><div class="inspector-heading"><h3>Handler details</h3></div><label>Name<input id="handler-name" value="${escapeHtml(handler.name)}"></label><label>Contract operation<select id="handler-operation">${operationOptions}</select></label><label>Response status<select id="handler-status"></select></label><label>Next state<select id="handler-next"><option value="">No transition</option>${stateOptions}</select></label><label>Query matchers (JSON object)<textarea id="handler-query">${escapeHtml(JSON.stringify(handler.request.query_parameters || {}, null, 2))}</textarea></label><label>Request headers (JSON object)<textarea id="handler-request-headers">${escapeHtml(JSON.stringify(handler.request.headers || {}, null, 2))}</textarea></label><label>Request JSON body<textarea id="handler-request-body">${handler.request.json_body === null ? "" : escapeHtml(JSON.stringify(handler.request.json_body, null, 2))}</textarea></label><label>Response headers (JSON object)<textarea id="handler-response-headers">${escapeHtml(JSON.stringify(handler.response.headers || {}, null, 2))}</textarea></label><label>Response JSON body<textarea id="handler-response-body">${escapeHtml(JSON.stringify(handler.response.json_body, null, 2))}</textarea></label></section>` : '<div class="designer-placeholder">Add a handler to make this state executable.</div>'}`;
  $("#designer-initial").value = definition.initial_state;
  $("#designer-reset").value = definition.reset?.target_state || definition.initial_state;
  if (handler) configureHandlerFields(handler);
  bindInspectorEvents();
  if (state.role === "viewer") $$('[data-designer-mutate], input, textarea, select', target).forEach((control) => { control.disabled = true; });
}

function configureHandlerFields(handler) {
  const operation = operationForHandler(handler);
  if (operation) $("#handler-operation").value = operation.operation_id;
  const status = $("#handler-status");
  status.innerHTML = (operation?.response_codes || [String(handler.response.status)]).filter((code) => /^\d{3}$/.test(code)).map((code) => `<option value="${code}">${code}</option>`).join("");
  if (![...status.options].some((option) => Number(option.value) === handler.response.status)) status.add(new Option(String(handler.response.status), String(handler.response.status)));
  status.value = String(handler.response.status);
  $("#handler-next").value = handler.new_state || "";
}

function bindInspectorEvents() {
  const definition = designer.definition;
  const scenarioState = definition.states[designer.stateIndex];
  const handler = scenarioState.handlers[designer.handlerIndex] || null;
  $("#designer-name").addEventListener("input", (event) => { definition.name = event.target.value; });
  $("#designer-description").addEventListener("input", (event) => { definition.description = event.target.value; });
  $("#designer-initial").addEventListener("change", (event) => { definition.initial_state = event.target.value; renderGraph(); });
  $("#designer-reset").addEventListener("change", (event) => { definition.reset = { target_state: event.target.value }; });
  $("#selected-state-name").addEventListener("change", (event) => renameState(scenarioState.name, event.target.value.trim()));
  $("#add-state").addEventListener("click", addState);
  $("#add-handler").addEventListener("click", addHandler);
  $$('[data-state-index]').forEach((button) => button.addEventListener("click", () => { designer.stateIndex = Number(button.dataset.stateIndex); designer.handlerIndex = 0; renderGraph(); renderInspector(); }));
  $$('[data-handler-index]').forEach((button) => button.addEventListener("click", () => { designer.handlerIndex = Number(button.dataset.handlerIndex); renderInspector(); }));
  $$('[data-remove-state]').forEach((button) => button.addEventListener("click", () => removeState(Number(button.dataset.removeState))));
  $$('[data-remove-handler]').forEach((button) => button.addEventListener("click", () => removeHandler(Number(button.dataset.removeHandler))));
  if (!handler) return;
  $("#handler-name").addEventListener("input", (event) => { handler.name = event.target.value; renderGraph(); });
  $("#handler-operation").addEventListener("change", (event) => changeHandlerOperation(handler, event.target.value));
  $("#handler-status").addEventListener("change", (event) => { handler.response.status = Number(event.target.value); });
  $("#handler-next").addEventListener("change", (event) => { handler.new_state = event.target.value || null; renderGraph(); });
  $("#handler-query").addEventListener("change", (event) => updateJsonObject(handler.request, "query_parameters", event.target.value));
  $("#handler-request-headers").addEventListener("change", (event) => updateJsonObject(handler.request, "headers", event.target.value));
  $("#handler-request-body").addEventListener("change", (event) => updateJsonField(handler.request, "json_body", event.target.value, true));
  $("#handler-response-headers").addEventListener("change", (event) => updateJsonObject(handler.response, "headers", event.target.value));
  $("#handler-response-body").addEventListener("change", (event) => updateJsonField(handler.response, "json_body", event.target.value, false));
}

function renameState(oldName, newName) {
  if (!newName || designer.definition.states.some((item) => item.name === newName && item.name !== oldName)) return notify("State names must be unique and non-empty", true);
  const definition = designer.definition;
  definition.states[designer.stateIndex].name = newName;
  if (definition.initial_state === oldName) definition.initial_state = newName;
  if (definition.reset?.target_state === oldName) definition.reset.target_state = newName;
  definition.states.forEach((item) => item.handlers.forEach((handler) => { if (handler.new_state === oldName) handler.new_state = newName; }));
  renderDesigner();
}

function addState() {
  const names = new Set(designer.definition.states.map((item) => item.name));
  let index = designer.definition.states.length + 1; let name = `STATE_${index}`;
  while (names.has(name)) { index += 1; name = `STATE_${index}`; }
  designer.definition.states.push({ name, handlers: [defaultHandler(designer.operations[0])] });
  designer.stateIndex = designer.definition.states.length - 1; designer.handlerIndex = 0; renderDesigner();
}

function removeState(index) {
  const definition = designer.definition;
  if (definition.states.length === 1) return notify("A scenario requires at least one state", true);
  const removed = definition.states[index].name;
  definition.states.splice(index, 1);
  definition.states.forEach((item) => item.handlers.forEach((handler) => { if (handler.new_state === removed) handler.new_state = null; }));
  if (definition.initial_state === removed) definition.initial_state = definition.states[0].name;
  if (definition.reset?.target_state === removed) definition.reset.target_state = definition.initial_state;
  designer.stateIndex = Math.min(index, definition.states.length - 1); designer.handlerIndex = 0; renderDesigner();
}

function addHandler() {
  const handlers = designer.definition.states[designer.stateIndex].handlers;
  handlers.push(defaultHandler(designer.operations[0], handlers.length + 1));
  designer.handlerIndex = handlers.length - 1; renderDesigner();
}

function removeHandler(index) {
  const handlers = designer.definition.states[designer.stateIndex].handlers;
  handlers.splice(index, 1); designer.handlerIndex = Math.max(0, Math.min(index, handlers.length - 1)); renderDesigner();
}

function changeHandlerOperation(handler, operationId) {
  const operation = designer.operations.find((item) => item.operation_id === operationId);
  if (!operation) return;
  handler.request.method = operation.method;
  handler.request.path = operation.path.replace(/\{[^}]+\}/g, "SYNTHETIC-ID");
  const code = operation.response_codes.find((item) => /^2\d\d$/.test(item)) || operation.response_codes.find((item) => /^\d{3}$/.test(item));
  if (code) handler.response.status = Number(code);
  renderInspector();
}

function updateJsonField(target, field, value, allowEmpty) {
  if (!value.trim() && allowEmpty) { target[field] = null; return; }
  try { target[field] = JSON.parse(value || "null"); notify("JSON updated"); }
  catch (error) { notify(`Invalid JSON: ${error.message}`, true); }
}

function updateJsonObject(target, field, value) {
  try {
    const parsed = JSON.parse(value || "{}");
    if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error("Value must be a JSON object");
    target[field] = parsed; notify("JSON object updated");
  } catch (error) { notify(`Invalid JSON object: ${error.message}`, true); }
}

async function runDesignerAction(button) {
  const base = `/simulations/${designer.simulationId}/scenarios/${designer.scenarioId}`;
  const action = button.dataset.designerAction;
  if (action === "export") return exportScenario();
  setBusy(button, true);
  try {
    let result;
    if (action === "save") result = await saveDesignerScenario(base);
    if (action === "history") return await showScenarioHistory(base);
    if (action === "releases") return await showScenarioReleases(base);
    if (action === "compile") result = await api(`${base}/compile`, { method: "POST" });
    if (action === "deploy") result = await api(`${base}/deploy`, { method: "POST" });
    if (action === "runtime") result = await api(`${base}/state`);
    if (action === "reset") result = await api(`${base}/reset`, { method: "POST" });
    const drawer = $("#designer-result");
    $("strong", drawer).textContent = `${action} result`;
    $("pre", drawer).textContent = JSON.stringify(result, null, 2);
    drawer.hidden = false;
    notify(`Scenario ${action} completed`);
    if (action === "save") {
      designer.revision = result.revision;
      designer.etag = result.etag;
      designer.savedSnapshot = JSON.stringify(result.definition);
      designer.diagnostics = await api(`${base}/diagnostics`);
      designer.scenarios = await api(`/simulations/${designer.simulationId}/scenarios`);
      renderDesignerScenarioList(); renderDesigner();
    }
    if (action === "deploy") {
      designer.releases = await api(`${base}/releases`);
      renderDesigner();
    }
  } catch (error) {
    if (action === "save" && error.status === 409) await resolveDesignerConflict(base, error);
    else notify(error.message, true);
  }
  finally { setBusy(button, false); }
}

function designerIsDirty() {
  return Boolean(designer.definition) && JSON.stringify(designer.definition) !== designer.savedSnapshot;
}

function confirmDesignerDiscard() {
  return !designerIsDirty() || window.confirm("Discard your unsaved scenario changes?");
}

async function saveDesignerScenario(base, force = false) {
  const headers = {};
  if (designer.etag && !force) headers["If-Match"] = `"${designer.etag}"`;
  return api(base, { method: "PUT", headers, body: JSON.stringify(designer.definition) });
}

async function resolveDesignerConflict(base, error) {
  const revision = error.detail?.current_revision;
  const overwrite = window.confirm(`This scenario changed on the server${revision ? ` (revision ${revision})` : ""}.\n\nOK: overwrite it with your draft.\nCancel: reload the latest version.`);
  if (overwrite) {
    const result = await saveDesignerScenario(base, true);
    designer.revision = result.revision;
    designer.etag = result.etag;
    designer.definition = structuredClone(result.definition);
    designer.savedSnapshot = JSON.stringify(result.definition);
    renderDesigner();
    notify("Conflict resolved by creating a new revision");
  } else {
    await loadScenario(designer.scenarioId, true);
    notify("Latest server revision loaded");
  }
}

async function showScenarioHistory(base) {
  const history = await api(`${base}/history`);
  const drawer = $("#designer-result");
  $("strong", drawer).textContent = "Revision history";
  $("pre", drawer).textContent = history.map((item) => `Revision ${item.revision} · ${item.created_by} · ${new Date(item.created_at).toLocaleString()} · ${item.state_count} states`).join("\n");
  drawer.hidden = false;
  if (history.length > 1) {
    const requested = window.prompt("Optional: enter 'compare 1 2', 'deploy 1', or 'restore 1'.");
    const [action, first, second] = (requested || "").trim().split(/\s+/);
    if (action === "compare") await compareDesignerRevisions(base, Number(first), Number(second));
    if (state.role !== "viewer" && action === "deploy") await deployDesignerRevision(base, Number(first));
    if (state.role !== "viewer" && action === "restore") await restoreDesignerRevision(base, Number(first));
  }
  return history;
}

async function compareDesignerRevisions(base, fromRevision, toRevision) {
  if (![fromRevision, toRevision].every((value) => Number.isInteger(value) && value > 0)) return notify("Comparison requires two positive revision numbers", true);
  const comparison = await api(`${base}/history/compare?from_revision=${fromRevision}&to_revision=${toRevision}`);
  const drawer = $("#designer-result");
  $("strong", drawer).textContent = `Revision ${fromRevision} → ${toRevision}`;
  $("pre", drawer).textContent = comparison.changes.map((change) => `${change.breaking ? "BREAKING " : ""}${change.kind.toUpperCase()} ${change.path}`).join("\n") || "No changes";
  drawer.hidden = false;
}

async function deployDesignerRevision(base, revision) {
  if (!Number.isInteger(revision) || revision < 1) return notify("Revision must be a positive number", true);
  if (!window.confirm(`Deploy immutable revision ${revision}?`)) return;
  const result = await api(`${base}/history/${revision}/deploy`, { method: "POST" });
  designer.releases = await api(`${base}/releases`);
  renderDesigner();
  notify(`Revision ${revision} deployed as release ${result.release_number}`);
}

async function showScenarioReleases(base) {
  designer.releases = await api(`${base}/releases`);
  const drawer = $("#designer-result");
  $("strong", drawer).textContent = "Deployment releases";
  $("pre", drawer).textContent = designer.releases.map((release) => `Release ${release.release_number} · revision ${release.revision} · ${release.deployed_by} · ${new Date(release.deployed_at).toLocaleString()}${release.source_release ? ` · rollback of ${release.source_release}` : ""}`).join("\n") || "No releases deployed";
  drawer.hidden = false;
  if (state.role !== "viewer" && designer.releases.length) {
    const requested = window.prompt("Enter a release number to roll back, or leave blank to inspect only:");
    if (requested) await rollbackDesignerRelease(base, Number(requested));
  }
  return designer.releases;
}

async function rollbackDesignerRelease(base, releaseNumber) {
  if (!Number.isInteger(releaseNumber) || releaseNumber < 1) return notify("Release must be a positive number", true);
  if (!window.confirm(`Roll back by redeploying release ${releaseNumber}?`)) return;
  const result = await api(`${base}/releases/${releaseNumber}/rollback`, { method: "POST" });
  designer.releases = await api(`${base}/releases`);
  renderDesigner();
  notify(`Rollback recorded as release ${result.release_number}`);
}

async function restoreDesignerRevision(base, revision) {
  if (!Number.isInteger(revision) || revision < 1) return notify("Revision must be a positive number", true);
  if (!window.confirm(`Restore revision ${revision} as a new revision?`)) return;
  const headers = designer.etag ? { "If-Match": `"${designer.etag}"` } : {};
  const result = await api(`${base}/history/${revision}/restore`, { method: "POST", headers });
  designer.revision = result.revision;
  designer.etag = result.etag;
  designer.definition = structuredClone(result.definition);
  designer.savedSnapshot = JSON.stringify(result.definition);
  renderDesigner();
  notify(`Revision ${revision} restored as revision ${result.revision}`);
}

function exportScenario() {
  const blob = new Blob([JSON.stringify(designer.definition, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob); const link = document.createElement("a");
  link.href = url; link.download = `${designer.scenarioId}.scenario.json`; link.click(); URL.revokeObjectURL(url);
}

async function importScenario(file) {
  if (!designer.simulationId) return notify("Select a simulation before importing", true);
  if (!confirmDesignerDiscard()) return;
  try {
    const definition = JSON.parse(await file.text());
    if (!definition.name || !Array.isArray(definition.states)) throw new Error("Scenario JSON must contain name and states");
    const id = file.name.replace(/\.scenario\.json$|\.json$/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 80);
    designer.scenarioId = id || "imported-scenario";
    designer.definition = definition; designer.revision = null; designer.etag = null;
    designer.savedSnapshot = null; designer.stateIndex = 0; designer.handlerIndex = 0; renderDesigner();
    notify("Scenario imported as an unsaved draft");
  } catch (error) { notify(`Import failed: ${error.message}`, true); }
}

window.addEventListener("beforeunload", (event) => {
  if (!designerIsDirty()) return;
  event.preventDefault();
  event.returnValue = "";
});

function initializeDesigner() {
  $("#designer-simulation").addEventListener("change", (event) => chooseDesignerSimulation(event.target.value));
  $("#new-scenario-button").addEventListener("click", () => {
    if (!designer.simulationId) return notify("Select a simulation first", true);
    if (state.role === "viewer") return notify("Operator role required", true);
    if (!confirmDesignerDiscard()) return;
    $("#scenario-metadata-dialog").showModal();
  });
  $("#import-scenario-button").addEventListener("click", () => $("#import-scenario-file").click());
  $("#import-scenario-file").addEventListener("change", (event) => { if (event.target.files[0]) importScenario(event.target.files[0]); event.target.value = ""; });
  $("#scenario-metadata-form").addEventListener("submit", (event) => {
    event.preventDefault(); const values = Object.fromEntries(new FormData(event.currentTarget));
    createScenarioDraft(values); $("#scenario-metadata-dialog").close(); event.currentTarget.reset();
  });
}
