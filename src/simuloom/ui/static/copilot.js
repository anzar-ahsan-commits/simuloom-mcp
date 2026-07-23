"use strict";

const copilot = {
  threads: [],
  selectedId: sessionStorage.getItem("simuloom-copilot-thread") || null,
  settings: null,
};

function rememberCopilotThread(threadId) {
  copilot.selectedId = threadId || null;
  if (copilot.selectedId) sessionStorage.setItem("simuloom-copilot-thread", copilot.selectedId);
  else sessionStorage.removeItem("simuloom-copilot-thread");
}

function refreshCopilot() {
  const picker = $("#copilot-simulation");
  if (!picker) return;
  const selected = picker.value;
  picker.innerHTML = '<option value="">Select a simulation</option>' + state.simulations
    .map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`)
    .join("");
  picker.value = state.simulations.some((item) => item.id === selected) ? selected : "";
  loadCopilotThreads();
  loadCopilotSettings();
}

async function loadCopilotSettings() {
  try {
    copilot.settings = await api("/ai/settings");
    const status = $("#copilot-ai-status");
    status.textContent = copilot.settings.enabled ? `${copilot.settings.model} enabled` : "AI disabled";
    status.classList.toggle("disabled", !copilot.settings.enabled);
    const toggle = $("#copilot-ai-toggle");
    toggle.textContent = copilot.settings.enabled ? "Disable AI" : "Enable AI";
    toggle.disabled = state.role !== "admin";
    toggle.title = state.role === "admin" ? `${copilot.settings.provider} at ${copilot.settings.base_url}` : "Admin role required";
  } catch (error) { notify(error.message, true); }
}

async function toggleCopilotAI() {
  if (!copilot.settings || state.role !== "admin") return;
  const enabled = !copilot.settings.enabled;
  if (!window.confirm(`${enabled ? "Enable" : "Disable"} local AI for all users?`)) return;
  const button = $("#copilot-ai-toggle");
  setBusy(button, true);
  try {
    copilot.settings = await api("/ai/settings", {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    });
    notify(`Local AI ${enabled ? "enabled" : "disabled"}. ${enabled ? "Ollama must be reachable for chat responses." : "Existing conversations remain available."}`);
  } catch (error) { notify(error.message, true); }
  finally { setBusy(button, false); await loadCopilotSettings(); }
}

async function loadCopilotThreads() {
  try {
    copilot.threads = await api("/ai/chat/threads");
    if (!copilot.threads.some((thread) => thread.id === copilot.selectedId)) {
      rememberCopilotThread(copilot.threads[0]?.id || null);
    }
    const list = $("#copilot-thread-list");
    list.innerHTML = copilot.threads.length ? copilot.threads.map((thread) => `<button data-chat-thread="${escapeHtml(thread.id)}" class="${thread.id === copilot.selectedId ? "active" : ""}"><strong>${escapeHtml(thread.title)}</strong><small>${escapeHtml(thread.simulation_id)} · ${thread.messages.length} messages</small></button>`).join("") : '<div class="designer-placeholder">Choose a simulation and start a grounded conversation.</div>';
    $$('[data-chat-thread]', list).forEach((button) => button.addEventListener("click", () => selectCopilotThread(button.dataset.chatThread)));
    const selected = copilot.threads.find((thread) => thread.id === copilot.selectedId);
    if (selected) renderCopilotMessages(selected);
  } catch (error) { notify(error.message, true); }
}

async function createCopilotThread() {
  const simulationId = $("#copilot-simulation").value;
  if (!simulationId) { notify("Select a simulation first", true); return; }
  const simulation = state.simulations.find((item) => item.id === simulationId);
  try {
    const thread = await api("/ai/chat/threads", { method: "POST", body: JSON.stringify({ simulation_id: simulationId, title: `${simulation.name} assistant` }) });
    rememberCopilotThread(thread.id);
    await loadCopilotThreads();
    await selectCopilotThread(thread.id);
    $("#copilot-input").focus();
  } catch (error) { notify(error.message, true); }
}

function renderCopilotAction(action) {
  const canDecide = state.role !== "viewer" && action.status === "proposed";
  return `<article class="copilot-action ${escapeHtml(action.risk)}"><div><span>${escapeHtml(action.risk)} risk</span><strong>${escapeHtml(action.summary)}</strong><code>${escapeHtml(action.kind)}</code></div><div class="workflow-actions">${canDecide ? `<button class="button primary" data-ai-approve="${escapeHtml(action.id)}">Approve</button><button class="button ghost" data-ai-reject="${escapeHtml(action.id)}">Reject</button>` : `<span class="status">${escapeHtml(action.status)}</span>`}</div></article>`;
}

function renderCopilotMessages(thread) {
  $("#copilot-title").textContent = thread.title;
  const target = $("#copilot-messages");
  target.innerHTML = thread.messages.length ? thread.messages.map((message) => `<article class="copilot-message ${escapeHtml(message.role)}"><div class="copilot-avatar">${message.role === "assistant" ? "AI" : "You"}</div><div><p>${escapeHtml(message.content).replace(/\n/g, "<br>")}</p>${message.actions.map(renderCopilotAction).join("")}</div></article>`).join("") : '<div class="copilot-welcome"><span>AI</span><h3>Conversation ready</h3><p>Ask me to explain this simulation, examine its scenario design, or recommend a safe next operation.</p></div>';
  $$('[data-ai-approve]', target).forEach((button) => button.addEventListener("click", () => decideCopilotAction(button.dataset.aiApprove, true)));
  $$('[data-ai-reject]', target).forEach((button) => button.addEventListener("click", () => decideCopilotAction(button.dataset.aiReject, false)));
  target.scrollTop = target.scrollHeight;
}

async function selectCopilotThread(threadId) {
  rememberCopilotThread(threadId);
  try {
    const thread = await api(`/ai/chat/threads/${threadId}`);
    renderCopilotMessages(thread);
    await loadCopilotThreads();
  } catch (error) { notify(error.message, true); }
}

async function sendCopilotMessage(event) {
  event.preventDefault();
  const activeId = copilot.selectedId
    || $('[data-chat-thread].active')?.dataset.chatThread
    || sessionStorage.getItem("simuloom-copilot-thread");
  if (!activeId) { notify("Start or select a conversation first", true); return; }
  rememberCopilotThread(activeId);
  const input = $("#copilot-input");
  const button = $('button[type="submit"]', event.currentTarget);
  setBusy(button, true);
  try {
    await api(`/ai/chat/threads/${copilot.selectedId}/messages`, { method: "POST", body: JSON.stringify({ content: input.value.trim() }) });
    input.value = "";
    await selectCopilotThread(copilot.selectedId);
  } catch (error) { notify(error.message, true); }
  finally { setBusy(button, false); }
}

async function decideCopilotAction(actionId, approve) {
  const verb = approve ? "execute" : "reject";
  if (!window.confirm(`${approve ? "Approve and execute" : "Reject"} this AI proposal?`)) return;
  try {
    await api(`/ai/chat/actions/${actionId}/${approve ? "approve" : "reject"}`, { method: "POST" });
    notify(`AI proposal ${verb === "execute" ? "executed" : "rejected"}`);
    await selectCopilotThread(copilot.selectedId);
    await loadDashboard();
  } catch (error) { notify(error.message, true); }
}

function initializeCopilot() {
  $("#new-chat-button").addEventListener("click", createCopilotThread);
  $("#copilot-form").addEventListener("submit", sendCopilotMessage);
  $("#copilot-ai-toggle").addEventListener("click", toggleCopilotAI);
}
