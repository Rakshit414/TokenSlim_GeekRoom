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
    const emptyMsg = document.getElementById('stale-empty-msg');
    if (emptyMsg) emptyMsg.style.display = 'none';

    const classification = (detection.classification || 'UNCERTAIN').toUpperCase();
    const badgeClass = classification === 'STALE' ? 'badge-stale' :
                       classification === 'CURRENT' ? 'badge-current' : 'badge-uncertain';

    const simBadge = detection.is_simulated ?
      '<span class="badge-status badge-uncertain" style="font-size: 10px; padding: 2px 6px;">[OFFLINE SIMULATION]</span>' :
      '<span class="badge-status badge-current" style="font-size: 10px; padding: 2px 6px;">[LIVE TAVILY]</span>';

    const card = document.createElement('div');
    card.className = 'panel';
    card.style.marginBottom = '12px';
    card.style.border = '1px solid var(--cream-border)';

    let correctionHtml = '';
    if (detection.recommended_correction) {
      correctionHtml += `
        <div style="margin-top: 8px; padding: 8px; background-color: var(--coral-subtle); border-left: 3px solid var(--coral); border-radius: 4px;">
          <strong style="color: var(--coral);">Recommended Correction:</strong>
          <p style="margin-top: 2px; font-size: 12px;">${escapeHtml(detection.recommended_correction)}</p>
        </div>
      `;
    }
    if (detection.suggested_patch) {
      correctionHtml += `
        <div style="margin-top: 6px;">
          <small style="color: var(--cream-text-muted); font-weight: 600;">Suggested Patch:</small>
          <pre style="margin-top: 4px; padding: 6px 8px; background: #0d1629; color: #a8ff60; font-family: var(--font-mono); font-size: 11px; border-radius: 4px; overflow-x: auto;">${escapeHtml(detection.suggested_patch)}</pre>
        </div>
      `;
    }

    const techLabel = detection.technology ? `${detection.technology}${detection.version ? ' ' + detection.version : ''}` : (detection.library || 'General API');
    const timeLabel = detection.created_at || new Date().toLocaleTimeString();
    const sourceLink = detection.source_url ? `<a href="${escapeHtml(detection.source_url)}" target="_blank" style="color: var(--navy); font-weight: 500; text-decoration: underline;">${escapeHtml(detection.source_title || detection.source_url)}</a>` : 'Documentation reference';

    card.innerHTML = `
      <div class="panel-header" style="padding: 8px 12px; display: flex; justify-content: space-between; align-items: center;">
        <div style="display: flex; gap: 8px; align-items: center;">
          <span class="badge-status ${badgeClass}">${classification}</span>
          <span style="font-size: 12px; font-family: var(--font-mono); font-weight: 600; color: var(--navy);">${escapeHtml(techLabel)}</span>
        </div>
        <div style="display: flex; gap: 6px; align-items: center;">
          ${simBadge}
          <span style="font-size: 10px; color: var(--cream-text-muted);">${escapeHtml(timeLabel)}</span>
        </div>
      </div>
      <div class="panel-body" style="padding: 10px 12px; font-size: 12px;">
        <p><strong>Claim:</strong> <code>${escapeHtml(detection.claim_text || detection.claim || '')}</code></p>
        <p style="margin-top: 6px;"><strong>Evidence:</strong> ${escapeHtml(detection.reasoning || detection.evidence || 'Evidence retrieved via Tavily')}</p>
        <p style="margin-top: 4px;"><small style="color: var(--cream-text-muted);">Source: ${sourceLink}</small></p>
        ${correctionHtml}
      </div>
    `;
    staleContainer.prepend(card);
  }

  // On-demand verification button
  const btnVerify = document.getElementById('btn-verify-claim');
  btnVerify?.addEventListener('click', async () => {
    const claimInput = document.getElementById('input-verify-claim');
    const techInput = document.getElementById('input-verify-tech');
    const claimText = claimInput?.value?.trim();
    const tech = techInput?.value?.trim() || 'general';

    if (!claimText) return;

    btnVerify.disabled = true;
    btnVerify.textContent = 'Verifying...';

    try {
      const resp = await fetch('/api/stale-detection/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task: `Verify claim: ${claimText}`,
          claims: [{ claim_text: claimText, technology: tech }]
        })
      });

      if (!resp.ok) throw new Error(`Verification failed: ${resp.statusText}`);
      const data = await resp.json();

      if (data.claims && data.claims.length > 0) {
        data.claims.forEach(c => renderStaleDetection(c));
      }
    } catch (e) {
      appendTerminalLine('ERROR', `Stale check failed: ${e.message}`, true);
    } finally {
      btnVerify.disabled = false;
      btnVerify.textContent = 'Verify';
    }
  });

  // Fetch and render benchmark results
  async function loadBenchmarkData() {
    try {
      const resp = await fetch('/api/benchmarks');
      if (!resp.ok) return;
      const data = await resp.json();
      if (!data.configurations) return;

      const cfgs = data.configurations;
      if (cfgs.naive_baseline) {
        document.getElementById('kpi-a-tokens').textContent = cfgs.naive_baseline.total_tokens_spent.toLocaleString();
        document.getElementById('kpi-a-context').textContent = cfgs.naive_baseline.total_context_tokens.toLocaleString();
        document.getElementById('kpi-a-pass').textContent = `${cfgs.naive_baseline.pass_rate_pct}%`;
      }
      if (cfgs.leancode) {
        document.getElementById('kpi-b-tokens').textContent = cfgs.leancode.total_tokens_spent.toLocaleString();
        document.getElementById('kpi-b-context').textContent = cfgs.leancode.total_context_tokens.toLocaleString();
        document.getElementById('kpi-b-pass').textContent = `${cfgs.leancode.pass_rate_pct}%`;
        document.getElementById('kpi-b-reduction').textContent = `-${cfgs.leancode.context_reduction_pct}% Context`;
      }
      if (cfgs.leancode_tavily) {
        document.getElementById('kpi-c-tokens').textContent = cfgs.leancode_tavily.total_tokens_spent.toLocaleString();
        document.getElementById('kpi-c-pass').textContent = `${cfgs.leancode_tavily.pass_rate_pct}%`;
        document.getElementById('kpi-c-reduction').textContent = `-${cfgs.leancode_tavily.context_reduction_pct}% Context`;
        document.getElementById('kpi-c-stale').textContent = cfgs.leancode_tavily.stale_detections;
        document.getElementById('kpi-c-tavily').textContent = cfgs.leancode_tavily.tavily_searches;
      }

      const tbody = document.getElementById('benchmark-table-body');
      if (tbody && data.task_results) {
        tbody.innerHTML = '';
        data.task_results.forEach(tr => {
          const row = document.createElement('tr');
          row.style.borderBottom = '1px solid var(--cream-border)';
          const configBadge = tr.configuration === 'leancode_tavily' ? 'badge-current' :
                              tr.configuration === 'leancode' ? 'badge-current' : 'badge-uncertain';
          row.innerHTML = `
            <td style="padding: 6px 10px; font-family: var(--font-mono); font-size: 11px;">${escapeHtml(tr.task_id)}</td>
            <td style="padding: 6px 10px;"><span class="badge-status ${configBadge}">${escapeHtml(tr.configuration)}</span></td>
            <td style="padding: 6px 10px; color: ${tr.passed ? 'green' : 'var(--coral)'}; font-weight: 600;">${tr.passed ? 'PASSED' : 'FAILED'}</td>
            <td style="padding: 6px 10px; font-family: var(--font-mono);">${tr.estimated_context_tokens.toLocaleString()}</td>
            <td style="padding: 6px 10px; font-family: var(--font-mono); font-weight: 600;">${tr.total_tokens_spent.toLocaleString()}</td>
            <td style="padding: 6px 10px;">${tr.stale_detections_count} / ${tr.tavily_searches_count}</td>
          `;
          tbody.appendChild(row);
        });
      }
    } catch (e) {
      console.warn('Failed to load benchmark data:', e);
    }
  }

  document.getElementById('btn-refresh-benchmarks')?.addEventListener('click', loadBenchmarkData);
  loadBenchmarkData();

  // Navigation tab interaction
  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', (e) => {
      document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
      item.classList.add('active');
    });
  });
});
