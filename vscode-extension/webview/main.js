// ── VS Code API bridge ────────────────────────────────────────────
const vscode = acquireVsCodeApi();

// ── State ─────────────────────────────────────────────────────────
let currentJobId = null;
let logEntries = [];
let approvalPending = false;
let isGeminiSet = false;
let isMoorchehSet = false;

// ── DOM refs ──────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);

// Tabs
const tabBtns = document.querySelectorAll('.tab-btn');
const panels  = document.querySelectorAll('.panel');

// Settings
const geminiInput    = $('gemini-key');
const moorchehInput  = $('moorcheh-key');
const savedKeysSection = $('saved-keys-section');
const savedKeysList    = $('saved-keys-list');

// Goal
const goalInput         = $('goal-input');
const coderSlider       = $('coder-count');
const coderDisplay      = $('coder-count-display');
const launchBtn         = $('launch-btn');
const jobInfo           = $('job-info');
const jobIdDisplay      = $('job-id-display');

// Approval
const approvalWaiting  = $('approval-waiting');
const approvalContent  = $('approval-content');
const approvalDone     = $('approval-done');
const planText         = $('plan-text');

// Log
const logOutput = $('log-output');
const logCount  = $('log-count');

// ── Tab switching ─────────────────────────────────────────────────
function switchTab(tabId) {
  tabBtns.forEach(b => b.classList.toggle('active', b.dataset.tab === tabId));
  panels.forEach(p => p.classList.toggle('active', p.id === `panel-${tabId}`));
}
tabBtns.forEach(btn => btn.addEventListener('click', () => switchTab(btn.dataset.tab)));

// ── Notification ──────────────────────────────────────────────────
function showNotification(text, type = 'success', ms = 1500) {
  const el = $('notification');
  el.textContent = text;
  el.className = `notification ${type}`;
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.className = 'notification hidden'; }, ms);
}

// ── Settings ──────────────────────────────────────────────────────
function makeToggle(btnId, inputId) {
  $(btnId).addEventListener('click', (e) => {
    const inp = $(inputId);
    const isPass = inp.type === 'password';
    inp.type = isPass ? 'text' : 'password';
    e.currentTarget.classList.toggle('active', isPass);
  });
}
makeToggle('toggle-gemini', 'gemini-key');
makeToggle('toggle-moorcheh', 'moorcheh-key');

// Scope segmented control
document.querySelectorAll('.seg-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    btn.closest('.seg-control').querySelectorAll('.seg-btn')
      .forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
  });
});

$('save-keys-btn').addEventListener('click', () => {
  const g = geminiInput.value.trim();
  const m = moorchehInput.value.trim();
  
  // If nothing was entered, just do nothing (no popup, no save)
  if (!g && !m) return;
  
  vscode.postMessage({ command: 'saveKeys', geminiKey: g, moorchehKey: m });
  
  // Clear inputs after save so they only show in saved keys list
  if (g) geminiInput.value = '';
  if (m) moorchehInput.value = '';
});

function updateSavedKeysList(geminiSet, moorchehSet) {
  isGeminiSet = geminiSet;
  isMoorchehSet = moorchehSet;
  
  savedKeysList.innerHTML = '';
  
  if (!geminiSet && !moorchehSet) {
    savedKeysSection.classList.add('hidden');
    return;
  }
  
  savedKeysSection.classList.remove('hidden');
  
  if (geminiSet) {
    savedKeysList.appendChild(createKeyItem('Gemini', 'gemini'));
  }
  if (moorchehSet) {
    savedKeysList.appendChild(createKeyItem('Moorcheh', 'moorcheh'));
  }
}

function createKeyItem(name, keyId) {
  const div = document.createElement('div');
  div.className = 'saved-key-item';
  div.innerHTML = `
    <div><span class="saved-key-name">${name}</span> <span class="saved-key-val ml-4">•••••••••••••</span></div>
    <button class="saved-key-del" title="Delete ${name}">🗑</button>
  `;
  div.querySelector('button').addEventListener('click', () => {
    vscode.postMessage({ command: 'deleteKey', key: keyId });
  });
  return div;
}

// ── Goal ──────────────────────────────────────────────────────────
coderSlider.addEventListener('input', () => {
  coderDisplay.textContent = coderSlider.value;
});

launchBtn.addEventListener('click', () => {
  const goal = goalInput.value.trim();
  if (!goal) { showNotification('Please enter a goal.', 'error'); return; }
  launchBtn.disabled = true;
  launchBtn.textContent = '⏳ Launching…';
  vscode.postMessage({
    command: 'startRun',
    goal,
    coderCount: parseInt(coderSlider.value, 10),
  });
});

// ── Approval ──────────────────────────────────────────────────────
$('approve-btn').addEventListener('click', () => {
  vscode.postMessage({ command: 'approve' });
  approvalContent.classList.add('hidden');
  approvalDone.classList.remove('hidden');
  approvalPending = false;
});

$('deny-btn').addEventListener('click', () => {
  vscode.postMessage({ command: 'deny' });
  approvalContent.classList.add('hidden');
  approvalWaiting.classList.remove('hidden');
  approvalPending = false;
  appendLog('⟳ Plan revision requested…', 'warn');
});

// ── Log console ───────────────────────────────────────────────────
function appendLog(message, level = 'info') {
  const ts = new Date().toLocaleTimeString();
  logEntries.push({ ts, message, level });

  const ph = logOutput.querySelector('.log-placeholder');
  if (ph) ph.remove();

  const span = document.createElement('span');
  span.className = `log-entry ${level}`;
  span.innerHTML = `<span class="ts">[${ts}]</span>${escHtml(message)}`;
  logOutput.appendChild(span);
  logOutput.appendChild(document.createTextNode('\n'));

  logCount.textContent = `${logEntries.length} entries`;

  const atBottom = logOutput.scrollHeight - logOutput.scrollTop - logOutput.clientHeight < 60;
  if (atBottom) logOutput.scrollTop = logOutput.scrollHeight;
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

$('clear-logs-btn').addEventListener('click', () => {
  logEntries = [];
  logOutput.innerHTML = '<span class="log-placeholder">Logs cleared.</span>';
  logCount.textContent = '';
});

$('scroll-bottom-btn').addEventListener('click', () => {
  logOutput.scrollTop = logOutput.scrollHeight;
});

// ── Agent state helpers ───────────────────────────────────────────
const AGENT_MAP = {
  planner:'agent-planner', coordinator:'agent-coordinator',
  coder:'agent-coder', merger:'agent-merger', qa:'agent-qa', qa_tester:'agent-qa'
};

const STAGE_AGENT = {
  planning:'planner', awaiting_approval:'planner',
  coordinating:'coordinator', coding:'coder', merging:'merger', qa:'qa'
};

function setAgentState(key, state) {
  const card = $(AGENT_MAP[key]);
  if (!card) return;
  card.className = `agent-card ${state}`;
  const badge = card.querySelector('.badge');
  badge.className = `badge badge-${state}`;
  badge.textContent = state.charAt(0).toUpperCase() + state.slice(1);
}

function resetAgents() {
  Object.keys(AGENT_MAP).forEach(k => setAgentState(k, 'idle'));
}

function applyStatus(status) {
  $('pipeline-stage').textContent =
    status.status.replace(/_/g,' ').replace(/\b\w/g, c => c.toUpperCase());

  const active = STAGE_AGENT[status.status];
  if (active) {
    const order = ['planner','coordinator','coder','merger','qa'];
    const idx = order.indexOf(active);
    order.forEach((a, i) => setAgentState(a, i < idx ? 'done' : i === idx ? 'running' : 'idle'));
  }

  if (status.agentStates) {
    Object.entries(status.agentStates).forEach(([a, s]) => setAgentState(a, s));
  }

  if (status.status === 'awaiting_approval' && status.plan && !approvalPending) {
    approvalPending = true;
    planText.textContent = status.plan;
    approvalWaiting.classList.add('hidden');
    approvalContent.classList.remove('hidden');
    approvalDone.classList.add('hidden');
    switchTab('approval');
    showNotification('📋 Plan ready — review and approve.', 'success', 5000);
  }

  if (status.status === 'done') {
    resetAgents(); setAgentState('qa', 'done');
    appendLog('✅ Pipeline complete!', 'success');
    launchBtn.disabled = false; launchBtn.textContent = '🚀 Launch Agents';
  }
  if (status.status === 'failed') {
    appendLog('❌ Pipeline failed.', 'error');
    launchBtn.disabled = false; launchBtn.textContent = '🚀 Launch Agents';
  }

  if (status.logs?.length > logEntries.length) {
    status.logs.slice(logEntries.length).forEach(l => appendLog(l));
  }
}

// ── Message bus ───────────────────────────────────────────────────
window.addEventListener('message', ({ data: msg }) => {
  switch (msg.command) {
    case 'switchTab':
      switchTab(msg.tab); break;

    case 'keysLoaded':
      updateSavedKeysList(msg.geminiKeySet, msg.moorchehKeySet);
      break;

    case 'notification':
      showNotification(msg.text, msg.type); break;

    case 'runStarted':
      currentJobId = msg.jobId;
      jobIdDisplay.textContent = msg.jobId;
      jobInfo.classList.remove('hidden');
      resetAgents(); setAgentState('planner', 'running');
      appendLog(`🚀 Run started: ${msg.jobId}`, 'success');
      switchTab('logs');
      launchBtn.textContent = '⏳ Running…';

      approvalWaiting.classList.remove('hidden');
      approvalContent.classList.add('hidden');
      approvalDone.classList.add('hidden');
      approvalPending = false;

      $('backend-status').className = 'online';
      $('backend-status-text').textContent = 'Online';
      break;

    case 'statusUpdate':
      applyStatus(msg.status); break;
  }
});

// ── Init ──────────────────────────────────────────────────────────
switchTab('settings');
