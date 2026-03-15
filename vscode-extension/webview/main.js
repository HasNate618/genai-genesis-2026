const vscode = acquireVsCodeApi();

let currentJobId = null;
let currentOutputPath = "";
let logEntries = [];
let pendingHitL1 = false;
let pendingHitL2 = false;
let isGeminiSet = false;
let isMoorchehSet = false;
let lastPipelineStatus = '';
let backendLogCount = 0;
const rawDetailsOpenState = {};

const AGENT_ORDER = [
  'planner',
  'task_coordinator',
  'conflict_analyst',
  'user_agents',
  'merge_agent',
  'qa_agent',
];

const AGENT_KEY_ALIASES = {
  conflict_manager: 'conflict_analyst',
  coder: 'user_agents',
  verification: 'qa_agent',
};

const AGENT_DOM_SUFFIX = {
  planner: 'planner',
  task_coordinator: 'task-coordinator',
  conflict_analyst: 'conflict-analyst',
  user_agents: 'user-agents',
  merge_agent: 'merge-agent',
  qa_agent: 'qa-agent',
};

const STAGE_AGENT = {
  planning: 'planner',
  awaiting_plan_approval: 'planner',
  coordinating: 'task_coordinator',
  analyzing_conflicts: 'conflict_analyst',
  coding: 'user_agents',
  merging: 'merge_agent',
  verifying: 'qa_agent',
  review_ready: 'qa_agent',
};

const expandedAgents = AGENT_ORDER.reduce((acc, key) => {
  acc[key] = false;
  return acc;
}, {});

const $ = (id) => document.getElementById(id);

const tabBtns = document.querySelectorAll('.tab-btn');
const panels = document.querySelectorAll('.panel');

const geminiInput = $('gemini-key');
const moorchehInput = $('moorcheh-key');
const savedKeysSection = $('saved-keys-section');
const savedKeysList = $('saved-keys-list');

const goalInput = $('goal-input');
const coderSlider = $('coder-count');
const coderDisplay = $('coder-count-display');
const launchBtn = $('launch-btn');
const jobInfo = $('job-info');
const jobIdDisplay = $('job-id-display');

const reviewWaiting = $('review-waiting');
const planReviewContent = $('plan-review-content');
const resultReviewContent = $('result-review-content');
const reviewDone = $('review-done');
const planText = $('plan-text');
const planFeedback = $('plan-feedback');
const resultFeedback = $('result-feedback');

const logOutput = $('log-output');
const logCount = $('log-count');
const finalOutputPath = $('final-output-path');
const copyOutputPathBtn = $('copy-output-path-btn');
const openOutputFolderBtn = $('open-output-folder-btn');

function switchTab(tabId) {
  tabBtns.forEach(b => b.classList.toggle('active', b.dataset.tab === tabId));
  panels.forEach(p => p.classList.toggle('active', p.id === `panel-${tabId}`));
}

tabBtns.forEach(btn => btn.addEventListener('click', () => switchTab(btn.dataset.tab)));

function showNotification(text, type = 'success', ms = 1500) {
  const el = $('notification');
  el.textContent = text;
  el.className = `notification ${type}`;
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.className = 'notification hidden'; }, ms);
}

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

  if (!g && !m) return;

  vscode.postMessage({ command: 'saveKeys', geminiKey: g, moorchehKey: m });

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

coderSlider.addEventListener('input', () => {
  coderDisplay.textContent = coderSlider.value;
});

launchBtn.addEventListener('click', () => {
  const goal = goalInput.value.trim();
  if (!goal) { showNotification('Please enter a goal.', 'error'); return; }
  launchBtn.disabled = true;
  launchBtn.textContent = 'Launching…';
  vscode.postMessage({
    command: 'startRun',
    goal,
    coderCount: parseInt(coderSlider.value, 10),
  });
});

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

Object.values(AGENT_DOM_SUFFIX).forEach(domKey => {
  const header = $(`agent-header-${domKey}`);
  if (!header) return;
  header.addEventListener('click', () => {
    const key = Object.keys(AGENT_DOM_SUFFIX).find((agentKey) => AGENT_DOM_SUFFIX[agentKey] === domKey);
    if (!key) return;
    toggleAgentAccordion(key, domKey);
  });
});

function toggleAgentAccordion(agentKey, domKey) {
  const body = $(`agent-result-${domKey}`);
  const chevron = $(`chevron-${domKey}`);
  if (!body || !chevron) return;

  const isExpanded = expandedAgents[agentKey];

  if (isExpanded) {
    body.classList.add('hidden');
    chevron.classList.remove('expanded');
    expandedAgents[agentKey] = false;
  } else {
    body.classList.remove('hidden');
    chevron.classList.add('expanded');
    expandedAgents[agentKey] = true;
  }
}

function updateOutputPathControls(outputPath) {
  currentOutputPath = typeof outputPath === 'string' ? outputPath : '';
  if (finalOutputPath) {
    finalOutputPath.textContent = currentOutputPath || 'Not available yet';
  }
  const disabled = !currentOutputPath;
  if (copyOutputPathBtn) copyOutputPathBtn.disabled = disabled;
  if (openOutputFolderBtn) openOutputFolderBtn.disabled = disabled;
}

if (copyOutputPathBtn) {
  copyOutputPathBtn.addEventListener('click', () => {
    if (!currentOutputPath) return;
    vscode.postMessage({ command: 'copyOutputPath', outputPath: currentOutputPath });
  });
}

if (openOutputFolderBtn) {
  openOutputFolderBtn.addEventListener('click', () => {
    if (!currentOutputPath) return;
    vscode.postMessage({ command: 'openOutputFolder', outputPath: currentOutputPath });
  });
}

function renderMarkdown(md) {
  if (!md || md.trim() === '') return '<span class="agent-result-empty">No results yet.</span>';

  let html = escHtml(md);

  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
  html = html.replace(/((?:<li>.*<\/li>\n?)+)/g, '<ul>$1</ul>');
  html = html.replace(/\n{2,}/g, '</p><p>');
  html = html.replace(/\n/g, '<br/>');
  html = html.replace(/<p><\/p>/g, '');
  html = html.replace(/<br\/><h/g, '<h');
  html = html.replace(/<\/h(\d)><br\/>/g, '</h$1>');
  html = html.replace(/<br\/><ul>/g, '<ul>');
  html = html.replace(/<\/ul><br\/>/g, '</ul>');

  return html;
}

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
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function stateLabel(state) {
  const label = String(state || 'idle').replace(/_/g, ' ');
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function normalizeAgentKey(key) {
  return AGENT_KEY_ALIASES[key] || key;
}

function setAgentState(key, state) {
  const normalized = normalizeAgentKey(key);
  const domSuffix = AGENT_DOM_SUFFIX[normalized];
  if (!domSuffix) return;

  const card = $(`agent-${domSuffix}`);
  if (!card) return;

  card.className = `agent-card ${state}`;
  const badge = card.querySelector('.badge');
  if (!badge) return;
  badge.className = `badge badge-${state}`;
  badge.textContent = stateLabel(state);
}

function setAgentResult(key, markdown) {
  const normalized = normalizeAgentKey(key);
  const domSuffix = AGENT_DOM_SUFFIX[normalized];
  if (!domSuffix) return;

  const contentEl = $(`agent-result-content-${domSuffix}`);
  if (!contentEl) return;
  contentEl.innerHTML = renderMarkdown(markdown);
}

function resetAgents() {
  AGENT_ORDER.forEach((key) => setAgentState(key, 'idle'));
}

function stageFallback(statusName) {
  const active = STAGE_AGENT[statusName];
  if (!active) return;
  const idx = AGENT_ORDER.indexOf(active);
  AGENT_ORDER.forEach((agent, i) => {
    setAgentState(agent, i < idx ? 'done' : i === idx ? 'running' : 'idle');
  });
}

function renderSummaryAndRaw(containerId, summaryLines, payload) {
  const el = $(containerId);
  if (!el) return;

  const existingDetails = el.querySelector('details.workflow-raw');
  const wasOpen = existingDetails ? existingDetails.open : !!rawDetailsOpenState[containerId];

  const summaryHtml = summaryLines.length
    ? `<ul>${summaryLines.map((line) => `<li>${escHtml(line)}</li>`).join('')}</ul>`
    : '<span class="agent-result-empty">No summary available.</span>';

  if (!payload) {
    el.innerHTML = summaryLines.length ? summaryHtml : '<span class="agent-result-empty">No data yet.</span>';
    rawDetailsOpenState[containerId] = false;
    return;
  }

  const rawJson = escHtml(JSON.stringify(payload, null, 2));
  el.innerHTML = `${summaryHtml}<details class="workflow-raw"><summary>Raw JSON</summary><pre>${rawJson}</pre></details>`;

  const details = el.querySelector('details.workflow-raw');
  if (details) {
    details.open = wasOpen;
    rawDetailsOpenState[containerId] = details.open;
    details.addEventListener('toggle', () => {
      rawDetailsOpenState[containerId] = details.open;
    });
  }
}

function renderFinalOutput(status) {
  const outputs = Array.isArray(status.userAgentOutputs) ? status.userAgentOutputs : [];
  const changedFiles = new Set();
  outputs.forEach((output) => {
    const files = Array.isArray(output?.changed_files)
      ? output.changed_files
      : (Array.isArray(output?.changedFiles) ? output.changedFiles : []);
    files.forEach((file) => changedFiles.add(file));
  });

  const writtenFiles = Array.isArray(status.writtenFiles) ? status.writtenFiles : [];
  const finalProjectFiles = Array.isArray(status.finalProjectFiles) ? status.finalProjectFiles : [];
  const outputPath = typeof status.outputPath === 'string' ? status.outputPath : '';
  const finalProjectPath = typeof status.finalProjectPath === 'string' ? status.finalProjectPath : '';
  const primaryPath = finalProjectPath || outputPath;
  updateOutputPathControls(primaryPath);

  const merge = status.mergeResult || null;
  const qa = status.qaResult || null;
  const mergeFilesTouched = Number(merge?.summary?.files_touched ?? 0);
  const changedFilesCount = changedFiles.size > 0
    ? changedFiles.size
    : (finalProjectFiles.length > 0 ? finalProjectFiles.length : (writtenFiles.length > 0 ? writtenFiles.length : mergeFilesTouched));

  const summary = [
    `Pipeline status: ${status.status}`,
    `Mode: ${status.simulationMode ? 'Simulation (test key)' : 'Live model runtime'}`,
    `Coding outputs: ${outputs.length}`,
    `Changed files: ${changedFilesCount}${changedFiles.size === 0 && writtenFiles.length > 0 ? ' (written artifacts)' : (changedFiles.size === 0 && mergeFilesTouched > 0 ? ' (from merge summary)' : '')}`,
    `Final project path: ${finalProjectPath || 'Not available yet'}`,
    `Output artifacts path: ${outputPath || 'Not available yet'}`,
    `Written files on disk: ${writtenFiles.length}`,
    `Final project files: ${finalProjectFiles.length}`,
    `Merge: ${merge?.status ?? 'n/a'}${merge ? (merge?.mergeable ? ' (mergeable)' : ' (not mergeable)') : ''}`,
    `QA: ${qa?.status ?? 'n/a'}${qa ? (qa?.qa_passed ? ' (passed)' : ' (not passed)') : ''}`,
  ];

  if (changedFiles.size === 0 && mergeFilesTouched === 0 && outputs.length > 0 && writtenFiles.length === 0) {
    summary.push('Changed file paths were not reported by coding agents for this run.');
  }
  if (merge?.next_action_reason) {
    summary.push(`Merge note: ${merge.next_action_reason}`);
  }
  if (qa?.next_action_reason) {
    summary.push(`QA note: ${qa.next_action_reason}`);
  }
  if (status.simulationMode) {
    summary.push('Simulation mode returns synthetic code artifacts. Use a valid Gemini key for model-generated project files.');
  }

  const hasFinalPayload = outputs.length > 0 || !!merge || !!qa || writtenFiles.length > 0 || finalProjectFiles.length > 0 || !!outputPath || !!finalProjectPath || ['review_ready', 'done', 'failed'].includes(status.status);
  const payload = hasFinalPayload
    ? {
        status: status.status,
        simulationMode: !!status.simulationMode,
        planningRound: status.planningRound ?? null,
        coordinationRound: status.coordinationRound ?? null,
        executionRound: status.executionRound ?? null,
        changedFilesCount,
        changedFiles: Array.from(changedFiles),
        writtenFiles,
        outputPath,
        finalProjectPath,
        finalProjectFiles,
        userAgentOutputs: outputs,
        mergeResult: merge,
        qaResult: qa,
      }
    : null;

  if (!hasFinalPayload) {
    renderSummaryAndRaw('detail-final-output', ['Final output will appear after coding, merge, and QA complete.'], null);
    return;
  }

  renderSummaryAndRaw('detail-final-output', summary, payload);
}

function renderWorkflowDetails(status) {
  $('round-planning').textContent = String(status.planningRound ?? 0);
  $('round-coordination').textContent = String(status.coordinationRound ?? 0);
  $('round-execution').textContent = String(status.executionRound ?? 0);

  const context = status.workflowContext || null;
  const contextSummary = [];
  if (context?.replan_reason) contextSummary.push(`Replan reason: ${context.replan_reason}`);
  if (context?.coordinator_feedback?.reason) contextSummary.push(`Coordinator feedback: ${context.coordinator_feedback.reason}`);
  if (context?.execution_feedback?.reason) contextSummary.push(`Execution feedback: ${context.execution_feedback.reason}`);
  renderSummaryAndRaw('detail-workflow-context', contextSummary, context);

  const taskDist = status.taskDistribution || null;
  const assignmentCount = Array.isArray(taskDist?.assignments) ? taskDist.assignments.length : 0;
  const taskSummary = [
    `Assignments: ${assignmentCount}`,
    `Coordination round: ${taskDist?.coordination_round ?? 'n/a'}`,
  ];
  if (taskDist?.context_reason) taskSummary.push(`Context: ${taskDist.context_reason}`);
  renderSummaryAndRaw('detail-task-distribution', taskSummary, taskDist);

  const conflict = status.conflictReport || null;
  const conflictSummary = [
    `Score: ${conflict?.overall_conflict_score ?? 'n/a'}%`,
    `Threshold: ${conflict?.threshold_percent ?? 'n/a'}%`,
    `Breached: ${conflict?.threshold_breached ? 'Yes' : 'No'}`,
  ];
  if (conflict?.next_action_reason) conflictSummary.push(`Reason: ${conflict.next_action_reason}`);
  renderSummaryAndRaw('detail-conflict-report', conflictSummary, conflict);

  const merge = status.mergeResult || null;
  const mergeSummary = [
    `Status: ${merge?.status ?? 'n/a'}`,
    `Mergeable: ${merge?.mergeable ? 'Yes' : 'No'}`,
    `Conflicts detected: ${merge?.summary?.conflicts_detected ?? 0}`,
  ];
  if (merge?.next_action_reason) mergeSummary.push(`Reason: ${merge.next_action_reason}`);
  renderSummaryAndRaw('detail-merge-result', mergeSummary, merge);

  const qa = status.qaResult || null;
  const qaSummary = [
    `Status: ${qa?.status ?? 'n/a'}`,
    `QA passed: ${qa?.qa_passed ? 'Yes' : 'No'}`,
    `Commands failed: ${qa?.summary?.commands_failed ?? 0}`,
  ];
  if (qa?.next_action_reason) qaSummary.push(`Reason: ${qa.next_action_reason}`);
  renderSummaryAndRaw('detail-qa-result', qaSummary, qa);

  renderFinalOutput(status);
}

$('clear-logs-btn').addEventListener('click', () => {
  logEntries = [];
  logOutput.innerHTML = '<span class="log-placeholder">Logs cleared.</span>';
  logCount.textContent = '';
});

$('scroll-bottom-btn').addEventListener('click', () => {
  logOutput.scrollTop = logOutput.scrollHeight;
});

function applyStatus(status, planPayload) {
  $('pipeline-stage').textContent = status.status.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

  stageFallback(status.status);

  const statePayload = status.logicalAgentStates || status.agentStates;
  if (statePayload) {
    Object.entries(statePayload).forEach(([key, state]) => {
      setAgentState(key, state);
    });
  }

  if (status.agentResults) {
    Object.entries(status.agentResults).forEach(([key, md]) => {
      if (md) setAgentResult(key, md);
    });
  }

  renderWorkflowDetails(status);

  if (status.status === 'awaiting_plan_approval' && planPayload && !pendingHitL1) {
    pendingHitL1 = true;
    planText.innerHTML = renderMarkdown(planPayload);
    reviewWaiting.classList.add('hidden');
    planReviewContent.classList.remove('hidden');
    resultReviewContent.classList.add('hidden');
    reviewDone.classList.add('hidden');
    switchTab('review');
    showNotification('📋 Plan ready — review and approve.', 'success', 2500);
  } else if (status.status !== 'awaiting_plan_approval') {
    pendingHitL1 = false;
  }

  if (status.status === 'review_ready' && !pendingHitL2) {
    pendingHitL2 = true;
    reviewWaiting.classList.add('hidden');
    planReviewContent.classList.add('hidden');
    resultReviewContent.classList.remove('hidden');
    reviewDone.classList.add('hidden');
    switchTab('review');
    showNotification('🚀 Final output ready — review and approve.', 'success', 2500);
  } else if (status.status !== 'review_ready') {
    pendingHitL2 = false;
  }

  const backendLogs = Array.isArray(status.logs) ? status.logs : [];
  if (backendLogs.length > backendLogCount) {
    backendLogs.slice(backendLogCount).forEach(line => appendLog(line));
    backendLogCount = backendLogs.length;
  }

  if (status.status === 'done' && lastPipelineStatus !== 'done') {
    AGENT_ORDER.forEach((agent) => setAgentState(agent, 'done'));
    appendLog('✅ Pipeline complete!', 'success');
    launchBtn.disabled = false;
    launchBtn.textContent = '🚀 Launch Agents';
  }

  if (status.status === 'failed' && lastPipelineStatus !== 'failed') {
    appendLog('❌ Pipeline failed.', 'error');
    const backendFailure = backendLogs.length ? backendLogs[backendLogs.length - 1] : '';
    if (backendFailure) {
      appendLog(`Failure reason: ${backendFailure}`, 'error');
    }
    showNotification('Pipeline failed — check Logs for failure reason.', 'error', 3500);
    launchBtn.disabled = false;
    launchBtn.textContent = '🚀 Launch Agents';
  }

  lastPipelineStatus = status.status;
}

window.addEventListener('message', ({ data: msg }) => {
  switch (msg.command) {
    case 'switchTab':
      switchTab(msg.tab);
      break;

    case 'keysLoaded':
      updateSavedKeysList(msg.geminiKeySet, msg.moorchehKeySet);
      break;

    case 'notification':
      showNotification(msg.text, msg.type);
      break;

    case 'runStarted':
      currentJobId = msg.jobId;
      jobIdDisplay.textContent = msg.jobId;
      jobInfo.classList.remove('hidden');
      resetAgents();
      setAgentState('planner', 'running');
      appendLog(`🚀 Run started: ${msg.jobId}`, 'success');
      switchTab('logs');
      launchBtn.textContent = '⏳ Running…';
      lastPipelineStatus = '';
      backendLogCount = 0;

      reviewWaiting.classList.remove('hidden');
      planReviewContent.classList.add('hidden');
      resultReviewContent.classList.add('hidden');
      reviewDone.classList.add('hidden');
      pendingHitL1 = false;
      pendingHitL2 = false;
      updateOutputPathControls('');

      $('backend-status').className = 'online';
      $('backend-status-text').textContent = 'Online';
      break;

    case 'statusUpdate':
      applyStatus(msg.status, msg.plan);
      break;
  }
});

switchTab('settings');
