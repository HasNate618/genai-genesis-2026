// ── VS Code API bridge ────────────────────────────────────────────
const vscode = acquireVsCodeApi();

// ── State ─────────────────────────────────────────────────────────
let currentJobId = null;
let logEntries = [];
let pendingHitL1 = false;
let pendingHitL2 = false;
let isGeminiSet = false;
let isMoorchehSet = false;
let lastArtifactSignature = '';
let currentWorkspacePath = '';

// ── DOM refs ──────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);

// Tabs
const tabBtns = document.querySelectorAll('.tab-btn');
const panels = document.querySelectorAll('.panel');

// Settings
const geminiInput = $('gemini-key');
const moorchehInput = $('moorcheh-key');
const savedKeysSection = $('saved-keys-section');
const savedKeysList = $('saved-keys-list');

// Goal
const goalInput = $('goal-input');
const coderSlider = $('coder-count');
const coderDisplay = $('coder-count-display');
const launchBtn = $('launch-btn');
const jobInfo = $('job-info');
const jobIdDisplay = $('job-id-display');

// Review Panel
const reviewWaiting = $('review-waiting');
const planReviewContent = $('plan-review-content');
const resultReviewContent = $('result-review-content');
const reviewDone = $('review-done');
const planText = $('plan-text');
const planFeedback = $('plan-feedback');
const resultFeedback = $('result-feedback');

// Log
const logOutput = $('log-output');
const logCount = $('log-count');

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

// ── Repo path ─────────────────────────────────────────────────────
const repoPathDisplay = $('repo-path-display');
const browseRepoBtn = $('browse-repo-btn');

function setRepoPath(p) {
  currentWorkspacePath = p || '';
  if (currentWorkspacePath) {
    repoPathDisplay.textContent = currentWorkspacePath;
    repoPathDisplay.title = currentWorkspacePath;
    repoPathDisplay.classList.remove('unset');
  } else {
    repoPathDisplay.textContent = 'No workspace open';
    repoPathDisplay.title = '';
    repoPathDisplay.classList.add('unset');
  }
}

browseRepoBtn.addEventListener('click', () => {
  vscode.postMessage({ command: 'browseFolder' });
});

// ── Goal ──────────────────────────────────────────────────────────
coderSlider.addEventListener('input', () => {
  coderDisplay.textContent = coderSlider.value;
});

launchBtn.addEventListener('click', () => {
  const goal = goalInput.value.trim();
  if (!goal) { showNotification('Please enter a goal.', 'error'); return; }
  if (!currentWorkspacePath) { showNotification('Select a target repo first.', 'error'); return; }
  launchBtn.disabled = true;
  launchBtn.textContent = 'Launching…';
  vscode.postMessage({
    command: 'startRun',
    goal,
    coderCount: parseInt(coderSlider.value, 10),
    workspacePath: currentWorkspacePath,
  });
});

function resetLaunchButton() {
  launchBtn.disabled = false;
  launchBtn.textContent = '🚀 Launch Agents';
}

// ── Review (HitL Gates) ───────────────────────────────────────────
// Plan Review (HitL 1)
$('approve-plan-btn').addEventListener('click', () => {
  vscode.postMessage({ command: 'reviewPlan', approved: true, feedback: planFeedback.value });
  planReviewContent.classList.add('hidden');
  reviewDone.classList.remove('hidden');
  pendingHitL1 = false;
});

$('deny-plan-btn').addEventListener('click', () => {
  vscode.postMessage({ command: 'reviewPlan', approved: false, feedback: planFeedback.value });
  planReviewContent.classList.add('hidden');
  reviewWaiting.classList.remove('hidden');
  pendingHitL1 = false;
  appendLog('⟳ Plan revision requested…', 'warn');
});

// Result Review (HitL 2)
$('approve-result-btn').addEventListener('click', () => {
  vscode.postMessage({ command: 'reviewResult', approved: true, feedback: resultFeedback.value });
  resultReviewContent.classList.add('hidden');
  reviewDone.classList.remove('hidden');
  pendingHitL2 = false;
});

$('deny-result-btn').addEventListener('click', () => {
  vscode.postMessage({ command: 'reviewResult', approved: false, feedback: resultFeedback.value });
  resultReviewContent.classList.add('hidden');
  reviewWaiting.classList.remove('hidden');
  pendingHitL2 = false;
  appendLog('⟳ Result revision requested…', 'warn');
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
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
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
  planner: 'agent-planner', 
  coordinator_conflict: 'agent-coordinator-conflict',
  coder: 'agent-coder', 
  merger: 'agent-merger'
};

const STAGE_AGENT = {
  planning: 'planner', 
  awaiting_plan_approval: 'planner',
  coordinating: 'coordinator_conflict', 
  coding: 'coder', 
  verifying: 'merger', 
  review_ready: 'merger'
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

function applyStatus(status, planPayload) {
  $('pipeline-stage').textContent =
    status.status.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

  const active = STAGE_AGENT[status.status];
  if (active) {
    const order = ['planner', 'coordinator_conflict', 'coder', 'merger'];
    const idx = order.indexOf(active);
    order.forEach((a, i) => setAgentState(a, i < idx ? 'done' : i === idx ? 'running' : 'idle'));
  }

  if (status.agentStates) {
    Object.entries(status.agentStates).forEach(([a, s]) => setAgentState(a, s));
  }

  // HitL 1: Plan Approval
  if (status.status === 'awaiting_plan_approval' && planPayload && !pendingHitL1) {
    pendingHitL1 = true;
    planText.innerHTML = planPayload.replace(/\\n/g, '<br/>');
    reviewWaiting.classList.add('hidden');
    planReviewContent.classList.remove('hidden');
    resultReviewContent.classList.add('hidden');
    reviewDone.classList.add('hidden');
    switchTab('review');
    showNotification('📋 Plan ready — review and approve.', 'success', 2500);
  } else if (status.status !== 'awaiting_plan_approval') {
    pendingHitL1 = false;
  }

  // HitL 2: Result Approval
  if (status.status === 'review_ready' && !pendingHitL2) {
    pendingHitL2 = true;
    reviewWaiting.classList.add('hidden');
    planReviewContent.classList.add('hidden');
    resultReviewContent.classList.remove('hidden');
    reviewDone.classList.add('hidden');
    switchTab('review');
    showNotification('🚀 PR ready — review and approve.', 'success', 2500);
  } else if (status.status !== 'review_ready') {
    pendingHitL2 = false;
  }

  if (status.status === 'done') {
    resetAgents(); setAgentState('merger', 'done');
    const artifacts = status.artifacts || {};
    const changed = Array.isArray(artifacts.changed_files) ? artifacts.changed_files : [];
    const commit = artifacts.merged_commit || '';
    const signature = `${commit}|${changed.join(',')}`;
    if (signature && signature !== lastArtifactSignature) {
      if (commit) {
        appendLog(`Merged commit: ${commit}`, 'success');
      }
      if (changed.length) {
        appendLog(`Changed files: ${changed.join(', ')}`, 'info');
      }
      lastArtifactSignature = signature;
    }
    appendLog('✅ Pipeline complete!', 'success');
    resetLaunchButton();
  }
  if (status.status === 'failed') {
    appendLog('❌ Pipeline failed.', 'error');
    resetLaunchButton();
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

    case 'workspacePath':
      setRepoPath(msg.path);
      break;

    case 'notification':
      showNotification(msg.text, msg.type); break;

    case 'runStarted':
      currentJobId = msg.jobId;
      lastArtifactSignature = '';
      jobIdDisplay.textContent = msg.jobId;
      jobInfo.classList.remove('hidden');
      resetAgents(); setAgentState('planner', 'running');
      appendLog(`🚀 Run started: ${msg.jobId}`, 'success');
      switchTab('logs');
      launchBtn.textContent = '⏳ Running…';

      reviewWaiting.classList.remove('hidden');
      planReviewContent.classList.add('hidden');
      resultReviewContent.classList.add('hidden');
      reviewDone.classList.add('hidden');
      pendingHitL1 = false;
      pendingHitL2 = false;

      $('backend-status').className = 'online';
      $('backend-status-text').textContent = 'Online';
      break;

    case 'runStartFailed':
      resetLaunchButton();
      break;

    case 'statusUpdate':
      applyStatus(msg.status, msg.plan); break;
  }
});

// ── Init ──────────────────────────────────────────────────────────
switchTab('settings');
setRepoPath(window.__WORKSPACE_PATH__ || '');
