/**
 * controls.js — Dashboard button wiring, phase machine, progress display.
 * Implements strict phase gating: BOOT → LAYOUT_READY → ROADS_READY →
 * RISK_READY → SIM_READY → RUNNING → DONE
 */

class Controls {

  constructor() {
    this.phase        = 'BOOT';
    this.execRunning  = false;
    this.tickCount    = 0;
    this._pollTimer   = null;
    this._clockInterval = null;
    this._onStateChange = null;
    this._gridRenderer  = null;
  }

  /** Phases in execution order — used to determine button availability */
  static PHASE_ORDER = [
    'BOOT', 'SOLVING_LAYOUT', 'LAYOUT_READY',
    'SOLVING_ROADS', 'ROADS_READY',
    'SOLVING_RISK', 'RISK_READY',
    'SOLVING_AMBULANCE', 'SIM_READY',
    'RUNNING', 'DONE',
  ];

  /** Which action each button triggers */
  static ACTION_MAP = {
    'c1':       { requires: ['BOOT'],                                    label: 'Challenge 1 (CSP)' },
    'c2':       { requires: ['LAYOUT_READY'],                            label: 'Challenge 2 (MST)' },
    'c3':       { requires: ['ROADS_READY','RISK_READY','SIM_READY','DONE'], label: 'Challenge 3 (GA)' },

    'c5':       { requires: ['LAYOUT_READY','ROADS_READY','RISK_READY','SIM_READY','RUNNING','DONE'], label: 'Challenge 5 (ML)' },
    'sim-tick': { requires: ['SIM_READY','RUNNING'],                     label: 'Run Sim Step' },
    'reset':    { requires: '*',                                         label: 'Reset City' },
    'home':     { requires: '*',                                         label: 'Back to Home' },
    'flood-clear': { requires: '*',                                      label: 'Clear All Floods' },
  };

  /** Called once on dashboard init */
  init(gridRenderer) {
    this._gridRenderer = gridRenderer;

    // Action buttons
    document.querySelectorAll('.cmd-btn[data-action], .text-btn[data-action]').forEach(btn => {
      btn.addEventListener('click', () => {
        const action = btn.dataset.action;
        if (action === 'c1')      this._runC1();
        else if (action === 'c2') this._runC2();
        else if (action === 'c3') this._runC3();
        else if (action === 'c5') this._runC5();
        else if (action === 'sim-tick') this._runSimTick();
        else if (action === 'reset')    this._runAction(API.reset);
        else if (action === 'home')     this._goHome();
        else if (action === 'flood-clear') this._runAction(API.floodClear);
      });
    });

    // Toggle buttons
    document.querySelectorAll('.tgl-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const toggle = btn.dataset.toggle;
        const opts = this._gridRenderer.options;
        const map = { mst: 'showMst', aug: 'showAug', labels: 'showLabels', amb: 'showAmb', crime: 'showCrime' };
        if (map[toggle] !== undefined) {
          opts[map[toggle]] = !opts[map[toggle]];
          btn.classList.toggle('active', opts[map[toggle]]);
          this._gridRenderer.setOptions(opts);
        }
      });
    });

    // Grid click → node select or flood tool
    gridRenderer.onNodeClick((nid) => {
      const g = gridRenderer.state;
      if (!g) return;

      if (gridRenderer.floodFirst === null) {
        gridRenderer.floodFirst   = nid;
        gridRenderer.selectedNode = nid;
      } else {
        const a = gridRenderer.floodFirst;
        const b = nid;
        const edge = g.edges.find(e =>
          (e.from === a && e.to === b) || (e.from === b && e.to === a));
        if (edge) {
          API.flood(a, b).then(state => {
            if (this._onStateChange) this._onStateChange(state);
          });
        }
        gridRenderer.floodFirst   = null;
        gridRenderer.selectedNode = nid;
      }
      gridRenderer.dirty = true;
      this._updateNodeInfo(nid);
    });

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
      if (document.getElementById('dashboard-page').style.display === 'none') return;
      const opts = this._gridRenderer.options;
      const key = e.key.toLowerCase();
      if (key === 'm') { opts.showMst = !opts.showMst; this._syncToggleUI('mst', opts.showMst); }
      if (key === 'u') { opts.showAug = !opts.showAug; this._syncToggleUI('aug', opts.showAug); }
      if (key === 'l') { opts.showLabels = !opts.showLabels; this._syncToggleUI('labels', opts.showLabels); }
      if (key === 'a') { opts.showAmb = !opts.showAmb; this._syncToggleUI('amb', opts.showAmb); }
      if (key === 'c') { opts.showCrime = !opts.showCrime; this._syncToggleUI('crime', opts.showCrime); }
      if (key === 'r') { this._runAction(API.reset); }
      if (key === 'escape') { this._goHome(); }
      this._gridRenderer.setOptions(opts);
    });

    // Clock
    this._clockInterval = setInterval(() => {
      document.getElementById('header-clock').textContent =
        new Date().toTimeString().slice(0, 8);
    }, 1000);
  }

  /** Called when full state updates arrive */
  updateState(state) {
    const prevPhase = this.phase;
    this.phase = state.phase;
    this.execRunning = state.exec_running;
    this.tickCount++;
    document.getElementById('header-tick').textContent = String(this.tickCount).padStart(5, '0');
    this._updateStatusBadge(state);
    this._updateProgressBar(state);
    this._updateButtonStates();
    this._updateNodeCounts(state);
    this._updateMetrics(state);

    // Start or stop polling based on exec_running
    if (state.exec_running && !this._pollTimer) {
      this._startPolling();
    } else if (!state.exec_running && this._pollTimer) {
      this._stopPolling();
    }
  }

  onStateChange(fn) {
    this._onStateChange = fn;
  }

  // ── Background execution + polling ──

  async _runC1() { await this._runAsync(API.runC1); }
  async _runC2() { await this._runAsync(API.runC2); }
  async _runC3() { await this._runAsync(API.runC3); }
  async _runC5() { await this._runAsync(API.runC5); }

  async _runAsync(apiFn) {
    try {
      const state = await apiFn();
      if (this._onStateChange) this._onStateChange(state);
      // If execution is running, start polling
      if (state.exec_running) {
        this._startPolling();
      }
    } catch (err) {
      showToast('API error: ' + err.message, 'error');
    }
  }

  async _runSimTick() {
    try {
      const state = await API.simTick();
      if (this._onStateChange) this._onStateChange(state);
    } catch (err) {
      showToast('API error: ' + err.message, 'error');
    }
  }

  async _runAction(apiFn) {
    try {
      const state = await apiFn();
      if (this._onStateChange) this._onStateChange(state);
    } catch (err) {
      showToast('API error: ' + err.message, 'error');
    }
  }

  _startPolling() {
    if (this._pollTimer) return;
    this._pollTimer = setInterval(async () => {
      try {
        const state = await API.getState();
        if (this._onStateChange) this._onStateChange(state);
        if (!state.exec_running) {
          this._stopPolling();
        }
      } catch (e) {
        this._stopPolling();
      }
    }, 150);
  }

  _stopPolling() {
    if (this._pollTimer) {
      clearInterval(this._pollTimer);
      this._pollTimer = null;
    }
  }

  _goHome() {
    const dashboard = document.getElementById('dashboard-page');
    const landing = document.getElementById('landing-page');
    this._stopPolling();
    dashboard.style.display = 'none';
    landing.style.display = 'flex';
    landing.style.opacity = '1';
    landing.style.transform = 'scale(1)';
    landing.style.filter = '';
  }

  // ── UI Updates ──

  _updateStatusBadge(state) {
    const badge = document.getElementById('status-badge');
    const label = state.phase_label || state.phase;
    badge.textContent = label;

    // Phase dot color
    const dot = document.getElementById('phase-dot');
    if (dot) {
      dot.className = 'phase-dot';
      const p = state.phase;
      if (p === 'BOOT') dot.classList.add('idle');
      else if (p.startsWith('SOLVING_')) dot.classList.add('busy');
      else if (p.endsWith('_READY')) dot.classList.add('ready');
      else if (p === 'RUNNING') dot.classList.add('busy');
      else if (p === 'DONE') dot.classList.add('done');
    }

    // Phase indicator text
    const indicator = document.getElementById('phase-indicator');
    if (indicator) {
      indicator.textContent = state.phase_label || state.phase;
    }

    // Hub state
    const hubState = document.getElementById('hub-state');
    if (hubState) {
      hubState.textContent = state.phase_label || state.phase;
    }
  }

  _updateProgressBar(state) {
    const bar = document.getElementById('progress-container');
    const fill = document.getElementById('progress-fill');
    const lbl  = document.getElementById('progress-label');

    if (!bar || !fill || !lbl) return;

    if (state.exec_running || state.phase.startsWith('SOLVING_')) {
      bar.style.display = 'flex';
      const pct = state.progress_total > 0
        ? (state.progress_current / state.progress_total) * 100 : 0;
      fill.style.width = Math.min(100, Math.max(0, pct)) + '%';
      lbl.textContent = state.progress_label || 'Processing…';
    } else {
      bar.style.display = 'none';
    }
  }

  _updateButtonStates() {
    const solving = this.phase.startsWith('SOLVING_') || this.execRunning;

    document.querySelectorAll('.cmd-btn[data-action]').forEach(btn => {
      const action = btn.dataset.action;
      const cfg = Controls.ACTION_MAP[action];
      if (!cfg) return;

      if (solving) {
        btn.disabled = true;
        return;
      }

      if (cfg.requires === '*') {
        btn.disabled = false;
      } else if (Array.isArray(cfg.requires)) {
        btn.disabled = !cfg.requires.includes(this.phase);
      }
    });
  }

  _updateNodeCounts(state) {
    const container = document.getElementById('node-counts');
    if (!state.node_counts) { container.innerHTML = ''; return; }

    const counts = state.node_counts;
    const required = {
      'Residential': 60, 'Hospital': 2, 'School': 3,
      'Industrial': 4, 'PowerPlant': 2, 'AmbulanceDepot': 1,
    };
    const syms = { 'Residential': 'R', 'Hospital': 'H', 'School': 'S',
                   'Industrial': 'I', 'PowerPlant': 'P', 'AmbulanceDepot': 'A' };

    container.innerHTML = Object.entries(required).map(([type, req]) => {
      const c = counts[type] || 0;
      const pct = Math.min(100, (c / req) * 100);
      const nodeColor = GridRenderer.CELL_COLORS[type] || '#5B6B85';
      const textColor = c >= req ? '#4ADE80' : (c > 0 ? '#FFB020' : '#94A3B8');
      return `<div class="count-row">
        <span class="count-sym" style="color:${nodeColor}">${syms[type]}</span>
        <span class="count-type">${type}</span>
        <span class="count-val" style="color:${textColor}">${c}/${req}</span>
        <span class="count-bar-bg"><span class="count-bar-fill" style="width:${pct}%;background:${nodeColor}"></span></span>
      </div>`;
    }).join('');
  }

  _updateNodeInfo(nid) {
    const panel = document.getElementById('node-info');
    const content = document.getElementById('node-info-content');
    const g = this._gridRenderer.state;
    if (!g) return;
    const n = g.nodes[nid];
    if (!n) return;

    const crimeColors = { High: 'var(--err)', Medium: 'var(--warn)', Low: 'var(--ok)' };
    panel.style.display = 'block';
    content.innerHTML = `
      <div class="ni-kv"><span class="ni-key">ID:</span><span class="ni-val">${n.id}</span></div>
      <div class="ni-kv"><span class="ni-key">Type:</span><span class="ni-val" style="color:${GridRenderer.CELL_COLORS[n.type] || 'var(--white)'}">${n.type}</span></div>
      <div class="ni-kv"><span class="ni-key">Pos:</span><span class="ni-val">(${n.row},${n.col})</span></div>
      <div class="ni-kv"><span class="ni-key">Crime:</span><span class="ni-val" style="color:${crimeColors[n.crime_risk] || 'var(--white)'}">${n.crime_risk}</span></div>
      <div class="ni-kv"><span class="ni-key">Access:</span><span class="ni-val" style="color:${n.accessible ? 'var(--ok)' : 'var(--err)'}">${n.accessible ? 'YES' : 'NO'}</span></div>
    `;
  }

  _updateMetrics(state) {
    const setMetric = (id, value, pct) => {
      const valEl = document.getElementById('met-val-' + id);
      const ringEl = document.getElementById('met-ring-' + id);
      if (valEl) valEl.textContent = value;
      if (ringEl) ringEl.style.transform = 'rotate(' + (Math.min(100, Math.max(0, pct)) * 3.6) + 'deg)';
    };

    const g = this._gridRenderer ? this._gridRenderer.state : null;

    // Response Time
    if (state.simulation && state.simulation.running) {
      setMetric('response', 'Step ' + state.simulation.step + '/20', (state.simulation.step / 20) * 100);
    } else {
      setMetric('response', '--', 0);
    }

    // Total Crimes
    const highCrime = g ? g.nodes.filter(n => n.crime_risk === 'High').length : 0;
    const medCrime = g ? g.nodes.filter(n => n.crime_risk === 'Medium').length : 0;
    const totalCrime = highCrime + medCrime;
    setMetric('crimes', String(totalCrime), Math.min(100, (totalCrime / 72) * 100));

    // Road Efficiency
    const mstEdges = g ? (g.mst_edges ? g.mst_edges.length : 0) : 0;
    const totalEdges = g ? (g.edges ? g.edges.length : 0) : 0;
    const effPct = totalEdges > 0 ? (mstEdges / totalEdges) * 100 : 0;
    setMetric('efficiency', Math.round(effPct) + '%', effPct);

    // Units Deployed
    const ambCount = g ? (g.ambulance_positions ? g.ambulance_positions.length : 0) : 0;
    setMetric('units', String(ambCount), Math.min(100, (ambCount / 10) * 100));

    // Coverage
    const accessibleNodes = g ? g.nodes.filter(n => n.accessible).length : 0;
    const covPct = g ? (accessibleNodes / g.nodes.length) * 100 : 0;
    setMetric('coverage', Math.round(covPct) + '%', covPct);

    // System Load
    let loadLabel, loadPct;
    if (state.exec_running) {
      loadLabel = 'ACTIVE'; loadPct = 75;
    } else if (state.phase === 'BOOT') {
      loadLabel = 'IDLE'; loadPct = 10;
    } else if (state.phase.startsWith('SOLVING_')) {
      loadLabel = 'COMPUTE'; loadPct = 60;
    } else {
      loadLabel = 'STANDBY'; loadPct = 30;
    }
    setMetric('load', loadLabel, loadPct);
  }

  _syncToggleUI(toggle, state) {
    const btn = document.querySelector(`[data-toggle="${toggle}"]`);
    if (!btn) return;
    btn.classList.toggle('active', state);
  }
}
