/**
 * event_log.js — Scrollable event log panel.
 * Appends new entries without rebuilding the entire list.
 */

class EventLog {

  constructor(containerEl) {
    this.el = containerEl;
    this.maxEntries = 100;
    this._lastCount = 0;
  }

  /**
   * Update the log. Only appends new entries since last call.
   * Rebuilds full list only when count decreases (reset) or
   * when first loading.
   */
  update(logEntries) {
    const entries = logEntries.slice(-this.maxEntries);

    // If count went down (reset happened), rebuild from scratch
    if (entries.length < this._lastCount) {
      this._rebuild(entries);
      return;
    }

    // On first load, rebuild
    if (this._lastCount === 0 && entries.length > 0) {
      this._rebuild(entries);
      return;
    }

    // Only append new entries
    const newEntries = entries.slice(this._lastCount);
    if (newEntries.length === 0) return;

    for (const msg of newEntries) {
      this._append(msg);
    }

    // Trim if over max
    while (this.el.children.length > this.maxEntries) {
      this.el.firstChild.remove();
    }

    this._lastCount = entries.length;
    this._scrollBottom();
  }

  _rebuild(entries) {
    // Clear empty state message if present
    const emptyEl = this.el.querySelector('.log-empty');
    if (emptyEl) emptyEl.remove();

    // Remove existing entries
    this.el.querySelectorAll('.log-entry').forEach(e => e.remove());

    for (const msg of entries) {
      this._append(msg);
    }

    this._lastCount = entries.length;
    if (entries.length === 0) {
      this.el.innerHTML = '<p class="log-empty">Awaiting events…</p>';
    }
    this._scrollBottom();
  }

  _append(msg) {
    // Determine icon and CSS class based on event content
    let icon = '◆'; // ◆ info
    let cls = 'log-info';

    if (msg.includes('FLOOD') || msg.includes('✗') || msg.includes('BLOCKED') || msg.includes('flood')) {
      icon = '⚠'; // ⚠ flood
      cls = 'log-flood';
    } else if (msg.includes('✓') || msg.includes('ready') || msg.includes('complete') || msg.includes('solved') || msg.includes('SUCCESS')) {
      icon = '✓'; // ✓ ok
      cls = 'log-ok';
    } else if (msg.includes('▶') || msg.includes('starting') || msg.includes('Generating') || msg.includes('Analyzing') || msg.includes('Evolving') || msg.includes('Starting') || msg.includes('Running')) {
      icon = '▶'; // ▶ warn
      cls = 'log-warn';
    } else if (msg.includes('ROUTE') || msg.includes('A*') || msg.includes('path') || msg.includes('ambulance') || msg.includes('AMB')) {
      icon = '◉'; // ◉ route
      cls = 'log-route';
    }

    const ts = new Date().toTimeString().slice(0, 8);

    const div = document.createElement('div');
    div.className = 'log-entry ' + cls;

    const timeSpan = document.createElement('span');
    timeSpan.className = 'log-time';
    timeSpan.textContent = ts;

    const iconSpan = document.createElement('span');
    iconSpan.className = 'log-icon';
    iconSpan.textContent = icon;

    const msgSpan = document.createElement('span');
    msgSpan.className = 'log-msg';
    msgSpan.textContent = msg;

    div.appendChild(timeSpan);
    div.appendChild(iconSpan);
    div.appendChild(msgSpan);
    this.el.appendChild(div);
  }

  _scrollBottom() {
    this.el.scrollTop = this.el.scrollHeight;
  }
}
