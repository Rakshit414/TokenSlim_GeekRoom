// TokenSlim Frontend Client Application
// Geek Room x HackCulture 2026

document.addEventListener('DOMContentLoaded', () => {
  console.log('TokenSlim Client Initialized.');

  // DOM Elements
  const btnRun = document.getElementById('btn-run');
  const btnCancel = document.getElementById('btn-cancel');
  const terminalTrace = document.getElementById('terminal-trace');
  const traceStatus = document.getElementById('trace-status');
  const topTokens = document.getElementById('top-tokens');
  const topReduction = document.getElementById('top-reduction');
  const topCalls = document.getElementById('top-calls');
  const topStaleCount = document.getElementById('top-stale-count');
  const staleContainer = document.getElementById('stale-evidence-container');
  const diffContent = document.getElementById('diff-content');

  let activeEventSource = null;
  let currentRunId = null;

  function appendTerminalLine(tag, text, isError = false) {
    const line = document.createElement('div');
    line.className = 'terminal-line';
    const timeStr = new Date().toLocaleTimeString();

    line.innerHTML = `
      <span class="terminal-timestamp">[${timeStr}]</span>
      <span class="terminal-tag" style="${isError ? 'color: var(--coral);' : ''}">[${tag}]</span>
      <span>${escapeHtml(text)}</span>
    `;
    terminalTrace.appendChild(line);
    terminalTrace.scrollTop = terminalTrace.scrollHeight;
  }

  function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // Handle run initiation
  btnRun?.addEventListener('click', async () => {
    const repo = document.getElementById('input-repo').value;
    const config = document.getElementById('select-config').value;
    const prompt = document.getElementById('input-prompt').value;
    const budget = parseInt(document.getElementById('input-budget').value, 10) || 15000;
    const isReplay = document.getElementById('check-replay').checked;

    appendTerminalLine('AGENT', `Starting task execution with config: ${config} (Replay: ${isReplay})...`);
    btnRun.disabled = true;
    btnCancel.disabled = false;
    traceStatus.textContent = 'Running';
    traceStatus.className = 'badge-status badge-stale';

    try {
      const response = await fetch('/api/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          repo_path: repo,
          configuration: config,
          prompt: prompt,
          token_budget: budget,
          replay: isReplay
        })
      });

      if (!response.ok) {
        throw new Error(`Failed to initiate run: ${response.statusText}`);
      }

      const data = await response.json();
      currentRunId = data.run_id;
      appendTerminalLine('SYSTEM', `Run created: ${currentRunId}. Streaming telemetry...`);
      connectEventStream(currentRunId);
    } catch (err) {
      appendTerminalLine('ERROR', err.message, true);
      btnRun.disabled = false;
      btnCancel.disabled = true;
      traceStatus.textContent = 'Error';
    }
  });

  function connectEventStream(runId) {
    if (activeEventSource) {
      activeEventSource.close();
    }

    activeEventSource = new EventSource(`/api/runs/${runId}/events`);

    activeEventSource.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        handleTraceEvent(payload);
      } catch (e) {
        console.error('Failed to parse event stream payload:', e);
      }
    };

    activeEventSource.onerror = () => {
      activeEventSource.close();
      btnRun.disabled = false;
      btnCancel.disabled = true;
      traceStatus.textContent = 'Finished';
      traceStatus.className = 'badge-status badge-current';
    };
  }

  function handleTraceEvent(event) {
    if (event.type === 'log') {
      appendTerminalLine(event.source || 'AGENT', event.message);
    } else if (event.type === 'metrics') {
      if (topTokens) topTokens.textContent = event.total_tokens || 0;
      if (topCalls) topCalls.textContent = event.llm_calls || 0;
      if (topReduction) topReduction.textContent = `${(event.reduction_pct || 0).toFixed(1)}%`;
    } else if (event.type === 'stale_detection') {
      renderStaleDetection(event.data);
    } else if (event.type === 'diff') {
      if (diffContent) diffContent.textContent = event.diff || '// No changes applied';
    }
  }

  function renderStaleDetection(detection) {
    if (!staleContainer) return;
    const badgeClass = detection.classification === 'STALE' ? 'badge-stale' :
                       detection.classification === 'CURRENT' ? 'badge-current' : 'badge-uncertain';

    const card = document.createElement('div');
    card.className = 'panel';
    card.style.marginBottom = '10px';
    card.innerHTML = `
      <div class="panel-header" style="padding: 8px 12px;">
        <span class="badge-status ${badgeClass}">${detection.classification}</span>
        <span style="font-size: 11px; font-family: var(--font-mono); color: var(--navy-text-muted);">${escapeHtml(detection.library || 'General API')}</span>
      </div>
      <div class="panel-body" style="padding: 10px 12px; font-size: 12px;">
        <p><strong>Claim:</strong> <code>${escapeHtml(detection.claim)}</code></p>
        <p style="margin-top: 4px;"><strong>Evidence:</strong> ${escapeHtml(detection.evidence)}</p>
        <p style="margin-top: 4px;"><small>Source: <a href="${escapeHtml(detection.source_url)}" target="_blank" style="color: var(--navy);">${escapeHtml(detection.source_title || detection.source_url)}</a></small></p>
      </div>
    `;
    staleContainer.prepend(card);
  }

  // Navigation tab interaction
  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', (e) => {
      document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
      item.classList.add('active');
    });
  });
});
