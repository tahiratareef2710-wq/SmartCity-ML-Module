/**
 * dashboard.js — Dashboard orchestrator.
 * Connects API responses to grid renderer, event log, and controls.
 */

const Dashboard = {

  gridRenderer: null,
  eventLog:     null,
  controls:     null,
  initialized:  false,

  /** Called after the landing→dashboard transition completes */
  init() {
    if (this.initialized) return;
    this.initialized = true;

    // Create component instances
    this.gridRenderer = new GridRenderer(document.getElementById('grid-canvas'));
    this.eventLog     = new EventLog(document.getElementById('event-log'));
    this.controls     = new Controls();

    // Wire controls
    this.controls.init(this.gridRenderer);

    // When controls fire an action and get new state, route it
    this.controls.onStateChange((state) => {
      this._applyState(state);
    });

    // Start the grid animation loop
    this.gridRenderer.start();

    // Reset to clean state on entry, then fetch
    API.reset().then(() => {
      return API.getState();
    }).then(state => {
      this._applyState(state);
    }).catch(err => {
      showToast('Failed to connect to backend', 'error');
    });
  },

  /** Route a full state object to all components */
  _applyState(state) {
    // Grid renderer
    this.gridRenderer.setState(state);

    // Event log
    this.eventLog.update(state.event_log || []);

    // Controls (phase, buttons, node counts)
    this.controls.updateState(state);
  },

};
