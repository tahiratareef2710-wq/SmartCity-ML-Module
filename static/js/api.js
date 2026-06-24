/**
 * api.js — Fetch wrappers for the CityMind Flask backend.
 * Every function returns a promise resolving to the parsed JSON body.
 */

const API = {

  // ── State queries ──

  getState() {
    return fetch('/api/state').then(r => r.json());
  },

  getPhase() {
    return fetch('/api/phase').then(r => r.json());
  },

  getEventLog() {
    return fetch('/api/event-log').then(r => r.json());
  },

  getNode(nid) {
    return fetch(`/api/node/${nid}`).then(r => r.json());
  },

  // ── Actions ──

  runC1() {
    return fetch('/api/run/c1', { method: 'POST' }).then(r => r.json());
  },

  runC2() {
    return fetch('/api/run/c2', { method: 'POST' }).then(r => r.json());
  },

  runC3() {
    return fetch('/api/run/c3', { method: 'POST' }).then(r => r.json());
  },

  runC5() {
    return fetch('/api/run/c5', { method: 'POST' }).then(r => r.json());
  },

  simTick() {
    return fetch('/api/run/sim-tick', { method: 'POST' }).then(r => r.json());
  },

  reset() {
    return fetch('/api/reset', { method: 'POST' }).then(r => r.json());
  },

  flood(a, b) {
    return fetch('/api/flood', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ a, b }),
    }).then(r => r.json());
  },

  floodClear() {
    return fetch('/api/flood/clear', { method: 'POST' }).then(r => r.json());
  },

};
