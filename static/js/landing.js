/**
 * landing.js — CityMind Cinematic Canvas Overlay Engine
 *
 * Renders on top of the background image, beneath the HTML/CSS UI.
 * Systems: NetworkMesh, ScanSweep, ParticleField, FogDrift, PerfMonitor
 */

function rand(min, max) { return min + Math.random() * (max - min); }
function randInt(min, max) { return Math.floor(rand(min, max + 1)); }

const C = {
  CYAN:      [0, 217, 255],
  BLUE:      [37, 99, 255],
  AMBER:     [255, 176, 32],
  WHITE:     [220, 230, 255],
  DIM_WHITE: [180, 200, 230],
  VIOLET:    [139, 92, 246],
  ROSE:      [236, 72, 153],
};

function rgba(arr, a) { return 'rgba(' + arr[0] + ',' + arr[1] + ',' + arr[2] + ',' + a + ')'; }

// ═════════════════════════════════════════════════════════════
// NETWORK MESH — Transmission arcs, nodes, data motes
// ═════════════════════════════════════════════════════════════
class NetworkMesh {
  constructor() {
    this.nodes = [];
    this.arcs = [];
    this.motes = [];
    this.MAX_MOTES = 180;
  }

  generate(W, H) {
    this.nodes = [];
    this.arcs = [];
    var nodeCount = 28;

    for (var i = 0; i < nodeCount; i++) {
      var yFrac;
      var r = Math.random();
      // Weight nodes toward the city (lower portion of screen)
      if (r < 0.50)       yFrac = rand(0.48, 0.88);   // city core
      else if (r < 0.80)  yFrac = rand(0.22, 0.48);   // mid-towers
      else                yFrac = rand(0.05, 0.22);   // high spires

      this.nodes.push({
        x: rand(0.03, 0.97) * W,
        y: yFrac * H,
        pulsePhase: Math.random() * Math.PI * 2,
        pulseSpeed: rand(0.3, 1.1),
        ringCount: randInt(1, 3),
        glowSize: rand(3, 10),
        importance: yFrac > 0.48 ? rand(0.5, 1) : rand(0.15, 0.5),
      });
    }

    // Connect to 2-4 nearest neighbors
    for (var a = 0; a < this.nodes.length; a++) {
      var dists = [];
      for (var b = 0; b < this.nodes.length; b++) {
        if (a === b) continue;
        var dx = this.nodes[a].x - this.nodes[b].x;
        var dy = this.nodes[a].y - this.nodes[b].y;
        dists.push({ idx: b, dist: Math.sqrt(dx * dx + dy * dy) });
      }
      dists.sort(function (x, y) { return x.dist - y.dist; });

      var maxDist = Math.min(W * 0.5, H * 0.4);
      var connections = randInt(2, 4);
      var added = 0;
      for (var c = 0; c < dists.length && added < connections; c++) {
        if (dists[c].dist > maxDist) break;
        var already = false;
        for (var d = 0; d < this.arcs.length; d++) {
          if ((this.arcs[d].a === a && this.arcs[d].b === dists[c].idx) ||
              (this.arcs[d].a === dists[c].idx && this.arcs[d].b === a)) {
            already = true; break;
          }
        }
        if (!already) {
          this.arcs.push({ a: a, b: dists[c].idx, dashOff: Math.random() * 40 });
          added++;
        }
      }
    }

    // Pre-allocate data motes
    this.motes = new Array(this.MAX_MOTES);
    for (var m = 0; m < this.MAX_MOTES; m++) {
      this.motes[m] = this._spawnMote();
    }
  }

  _spawnMote() {
    if (this.arcs.length === 0) return { arc: 0, t: 0, speed: 0.1, size: 1, alpha: 0 };
    return {
      arc: randInt(0, this.arcs.length - 1),
      t: Math.random(),
      speed: rand(0.03, 0.16),
      size: rand(0.5, 1.8),
      alpha: rand(0.2, 0.65),
    };
  }

  update(dt, time) {
    if (this.arcs.length === 0) return;
    var ds = dt * 0.001;
    var activeCount = Math.min(this.MAX_MOTES, Math.max(0, Math.floor(this.arcs.length * 3.8)));
    for (var i = 0; i < activeCount; i++) {
      var m = this.motes[i];
      if (!m || m.arc >= this.arcs.length) { this.motes[i] = this._spawnMote(); continue; }
      m.t += m.speed * ds;
      if (m.t > 1) this.motes[i] = this._spawnMote();
    }
  }

  _bezier(x1, y1, cx, cy, x2, y2, t) {
    var u = 1 - t;
    return {
      x: u * u * x1 + 2 * u * t * cx + t * t * x2,
      y: u * u * y1 + 2 * u * t * cy + t * t * y2,
    };
  }

  draw(ctx, W, H, time, heartbeat) {
    if (this.nodes.length === 0) return;
    var hb = 1 + heartbeat * 0.35;

    // ── Draw arcs ──
    for (var i = 0; i < this.arcs.length; i++) {
      var arc = this.arcs[i];
      var na = this.nodes[arc.a];
      var nb = this.nodes[arc.b];
      if (!na || !nb) continue;

      var mx = (na.x + nb.x) / 2;
      var my = (na.y + nb.y) / 2;
      var dx = nb.x - na.x;
      var dy = nb.y - na.y;
      var len = Math.sqrt(dx * dx + dy * dy);
      if (len < 1) continue;
      var perpX = -dy / len;
      var perpY = dx / len;
      var curve = rand(25, 90) * (Math.random() < 0.5 ? 1 : -1);
      var cx = mx + perpX * curve;
      var cy = my + perpY * curve;

      // Solid subtle line
      var imp = (na.importance + nb.importance) / 2;
      var alpha = (0.05 + imp * 0.06) * hb;
      ctx.strokeStyle = rgba(C.CYAN, alpha);
      ctx.lineWidth = 0.5;
      ctx.beginPath();
      ctx.moveTo(na.x, na.y);
      ctx.quadraticCurveTo(cx, cy, nb.x, nb.y);
      ctx.stroke();

      // Dashed animated overlay
      var dashOff = (time * 0.012 + arc.dashOff) % 18;
      ctx.setLineDash([3, 6, 1, 6]);
      ctx.lineDashOffset = -dashOff;
      ctx.strokeStyle = rgba(C.CYAN, alpha * 0.45);
      ctx.lineWidth = 0.3;
      ctx.beginPath();
      ctx.moveTo(na.x, na.y);
      ctx.quadraticCurveTo(cx, cy, nb.x, nb.y);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // ── Draw data motes ──
    var activeMotes = Math.min(this.motes.length, Math.floor(this.arcs.length * 3.8));
    for (var j = 0; j < activeMotes; j++) {
      var m = this.motes[j];
      if (!m || m.arc >= this.arcs.length) continue;
      var a = this.arcs[m.arc];
      var na2 = this.nodes[a.a];
      var nb2 = this.nodes[a.b];
      if (!na2 || !nb2) continue;

      var dmx = (na2.x + nb2.x) / 2;
      var dmy = (na2.y + nb2.y) / 2;
      var ddx = nb2.x - na2.x;
      var ddy = nb2.y - na2.y;
      var dlen = Math.sqrt(ddx * ddx + ddy * ddy);
      if (dlen < 1) continue;
      var ppx = -ddy / dlen;
      var ppy = ddx / dlen;
      var ccurve = rand(25, 90) * (Math.random() < 0.5 ? 1 : -1);
      var ccx = dmx + ppx * ccurve;
      var ccy = dmy + ppy * ccurve;

      var pt = this._bezier(na2.x, na2.y, ccx, ccy, nb2.x, nb2.y, m.t);

      // Occasionally use rose/amber for accent motes
      var moteColor = Math.random() < 0.08 ? C.ROSE : (Math.random() < 0.06 ? C.AMBER : C.CYAN);
      ctx.fillStyle = rgba(moteColor, m.alpha * hb);
      ctx.beginPath();
      ctx.arc(pt.x, pt.y, m.size, 0, Math.PI * 2);
      ctx.fill();
    }

    // ── Draw pulsing nodes ──
    for (var k = 0; k < this.nodes.length; k++) {
      var n = this.nodes[k];
      var pulse = 0.5 + 0.5 * Math.sin(time * 0.001 * n.pulseSpeed + n.pulsePhase);
      pulse += heartbeat * 0.3;
      pulse = Math.min(1, pulse);

      var imp = 0.3 + n.importance * 0.7;

      // Expanding rings
      for (var r = 0; r < n.ringCount; r++) {
        var ringPhase = (time * 0.0007 + r * 0.55 + n.pulsePhase) % 1;
        var ringR = 3 + ringPhase * 14 * imp;
        var ringAlpha = (1 - ringPhase) * 0.35 * pulse * imp;
        ctx.strokeStyle = rgba(C.CYAN, ringAlpha);
        ctx.lineWidth = 0.5;
        ctx.beginPath();
        ctx.arc(n.x, n.y, ringR, 0, Math.PI * 2);
        ctx.stroke();
      }

      // Core dot
      ctx.fillStyle = rgba(C.WHITE, 0.35 + pulse * 0.45 * imp);
      ctx.beginPath();
      ctx.arc(n.x, n.y, 1.5 * pulse * imp, 0, Math.PI * 2);
      ctx.fill();

      // Glow
      ctx.fillStyle = rgba(C.CYAN, pulse * 0.12 * imp);
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.glowSize * pulse, 0, Math.PI * 2);
      ctx.fill();
    }
  }
}

// ═════════════════════════════════════════════════════════════
// SCAN SWEEP — LIDAR-style scanning line
// ═════════════════════════════════════════════════════════════
class ScanSweep {
  constructor() {
    this.yFrac = -0.1;
    this.pauseRemaining = 0;
    this.speed = 0.2;
    this.pauseDuration = 5.5;
  }

  update(dt) {
    var ds = dt * 0.001;
    if (this.pauseRemaining > 0) {
      this.pauseRemaining -= ds;
      if (this.pauseRemaining <= 0) {
        this.yFrac = -0.1;
        this.pauseRemaining = 0;
      }
    } else {
      this.yFrac += this.speed * ds;
      if (this.yFrac > 1.05) {
        this.yFrac = 1.05;
        this.pauseRemaining = this.pauseDuration;
      }
    }
  }

  draw(ctx, W, H) {
    if (this.pauseRemaining > 0 && this.pauseRemaining > this.pauseDuration - 0.6) return;

    var y = this.yFrac * H;
    var active = this.pauseRemaining > 0
      ? Math.max(0, this.pauseRemaining / this.pauseDuration)
      : 1;

    // Glow below the line
    var glowH = 60;
    var grad = ctx.createLinearGradient(0, y - 4, 0, y + glowH);
    grad.addColorStop(0, 'rgba(0,0,0,0)');
    grad.addColorStop(0.12, 'rgba(0,200,255,' + (0.03 * active) + ')');
    grad.addColorStop(0.5, 'rgba(0,150,255,' + (0.018 * active) + ')');
    grad.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = grad;
    ctx.fillRect(0, y - 4, W, glowH + 4);

    // Scan line
    var lineGrad = ctx.createLinearGradient(0, 0, W, 0);
    lineGrad.addColorStop(0, 'rgba(0,217,255,0)');
    lineGrad.addColorStop(0.1, 'rgba(0,217,255,' + (0.06 * active) + ')');
    lineGrad.addColorStop(0.3, 'rgba(0,217,255,' + (0.13 * active) + ')');
    lineGrad.addColorStop(0.5, 'rgba(0,217,255,' + (0.18 * active) + ')');
    lineGrad.addColorStop(0.7, 'rgba(0,217,255,' + (0.13 * active) + ')');
    lineGrad.addColorStop(0.9, 'rgba(0,217,255,' + (0.06 * active) + ')');
    lineGrad.addColorStop(1, 'rgba(0,217,255,0)');
    ctx.strokeStyle = lineGrad;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(W, y);
    ctx.stroke();

    // Bloom
    ctx.strokeStyle = 'rgba(0,217,255,' + (0.05 * active) + ')';
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(W, y);
    ctx.stroke();
  }
}

// ═════════════════════════════════════════════════════════════
// PARTICLE FIELD — Fog, data, spark (object pool)
// ═════════════════════════════════════════════════════════════
const PT_FOG  = 0;
const PT_DATA = 1;
const PT_SPARK = 2;

const PDEF = [
  { count: 24, minS: 30, maxS: 110, minA: 0.006, maxA: 0.025, sy: [0.03, 0.14], sx: 0.04, color: [140, 180, 220] },
  { count: 45, minS: 0.8,maxS: 3.2,  minA: 0.08, maxA: 0.36,  sy: [0.15,0.5],   sx: 0.06, color: C.CYAN },
  { count: 20, minS: 0.4,maxS: 1.6,  minA: 0.12, maxA: 0.5,   sy: [0.25,0.7],   sx: 0.1,  color: C.WHITE },
];

class ParticleField {
  constructor() {
    var total = 0;
    for (var i = 0; i < PDEF.length; i++) total += PDEF[i].count;
    this.MAX = total;
    this.pool = new Array(this.MAX);
    for (var j = 0; j < this.MAX; j++) this.pool[j] = this._spawn();
    this.activeCount = this.MAX;
  }

  _spawn() {
    var r = Math.random();
    var type = r < 0.28 ? PT_FOG : (r < 0.80 ? PT_DATA : PT_SPARK);
    var def = PDEF[type];
    return {
      type: type,
      x: Math.random(),
      y: Math.random(),
      vy: -rand(def.sy[0], def.sy[1]),
      vx: (Math.random() - 0.5) * def.sx,
      size: rand(def.minS, def.maxS),
      alpha: rand(def.minA, def.maxA),
      life: Math.random(),
      maxLife: rand(5, 18),
    };
  }

  update(dt) {
    var ds = dt * 0.001;
    for (var i = 0; i < this.activeCount; i++) {
      var p = this.pool[i];
      p.x += p.vx * ds * 0.6;
      p.y += p.vy * ds * 0.55;
      p.life += ds * 0.05;
      if (p.life > p.maxLife || p.x < -0.15 || p.x > 1.15 || p.y < -0.15 || p.y > 1.15) {
        this.pool[i] = this._spawn();
      }
    }
  }

  draw(ctx, W, H) {
    for (var i = 0; i < this.activeCount; i++) {
      var p = this.pool[i];
      var lifeFrac = p.life / p.maxLife;
      var alpha = p.alpha * Math.sin(lifeFrac * Math.PI);
      var def = PDEF[p.type];
      var clr = def.color;
      ctx.fillStyle = 'rgba(' + clr[0] + ',' + clr[1] + ',' + clr[2] + ',' + alpha + ')';
      ctx.beginPath();
      ctx.arc(p.x * W, p.y * H, p.size, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  setQuality(q) {
    this.activeCount = Math.max(22, Math.floor(this.MAX * (0.35 + q * 0.65)));
  }
}

// ═════════════════════════════════════════════════════════════
// FOG DRIFT — Slow atmospheric bands
// ═════════════════════════════════════════════════════════════
class FogDrift {
  constructor() {
    this.bands = [];
    for (var i = 0; i < 5; i++) {
      this.bands.push({
        yFrac: 0.06 + i * 0.19,
        xOff: Math.random() * 2 - 1,
        speed: rand(0.015, 0.06),
        alpha: 0.01 + i * 0.018,
        height: 0.05 + Math.random() * 0.07,
      });
    }
  }

  update(dt) {
    var ds = dt * 0.001;
    for (var i = 0; i < this.bands.length; i++) {
      this.bands[i].xOff += this.bands[i].speed * ds * 0.25;
      if (this.bands[i].xOff > 1.5) this.bands[i].xOff -= 2;
      if (this.bands[i].xOff < -0.5) this.bands[i].xOff += 2;
    }
  }

  draw(ctx, W, H) {
    for (var i = 0; i < this.bands.length; i++) {
      var b = this.bands[i];
      var y = b.yFrac * H;
      var h = b.height * H;
      var grad = ctx.createLinearGradient(0, y - h, 0, y + h);
      grad.addColorStop(0, 'rgba(0,0,0,0)');
      grad.addColorStop(0.5, 'rgba(6,14,32,' + b.alpha + ')');
      grad.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = grad;
      ctx.fillRect(0, y - h, W, h * 2);
    }
  }
}

// ═════════════════════════════════════════════════════════════
// PERFORMANCE MONITOR
// ═════════════════════════════════════════════════════════════
const FW = 60;
class PerfMonitor {
  constructor() {
    this.samples = new Array(FW);
    for (var i = 0; i < FW; i++) this.samples[i] = 16.67;
    this.idx = 0;
    this.quality = 1;
    this.counter = 0;
  }

  record(dtMs) {
    this.samples[this.idx] = dtMs;
    this.idx = (this.idx + 1) % FW;

    var sum = 0;
    for (var i = 0; i < FW; i++) sum += this.samples[i];
    var avg = sum / FW;

    if (avg > 19) {
      this.counter++;
      if (this.counter > 30) { this.quality = Math.max(0.3, this.quality - 0.12); this.counter = 0; }
    } else if (avg < 13 && this.quality < 1) {
      this.counter = Math.max(0, this.counter - 2);
      if (this.counter <= 0) { this.quality = Math.min(1, this.quality + 0.08); this.counter = 0; }
    }
  }

  getQuality() { return this.quality; }
}

// ═════════════════════════════════════════════════════════════
// CITYMIND CANVAS — Orchestrator
// ═════════════════════════════════════════════════════════════
var LandingMouse = { x: 0.5, y: 0.5 };

class CityMindCanvas {
  constructor() {
    this.canvas = document.getElementById('landing-canvas');
    this.ctx = this.canvas.getContext('2d');

    this.network   = new NetworkMesh();
    this.scan      = new ScanSweep();
    this.particles = new ParticleField();
    this.fog       = new FogDrift();
    this.perf      = new PerfMonitor();

    this.time = 0;
    this.lastTime = 0;
    this.W = 0;
    this.H = 0;
    this.frameCount = 0;

    this._resize();
    this._build();

    window.addEventListener('resize', this._onResize.bind(this));
    document.addEventListener('mousemove', this._onMouse.bind(this));

    this._loop(0);
  }

  _resize() {
    var dpr = window.devicePixelRatio || 1;
    var w = window.innerWidth;
    var h = window.innerHeight;
    this.canvas.width = w * dpr;
    this.canvas.height = h * dpr;
    this.canvas.style.width = w + 'px';
    this.canvas.style.height = h + 'px';
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.W = w;
    this.H = h;
  }

  _onResize() {
    this._resize();
    this._build();
  }

  _onMouse(e) {
    LandingMouse.x = e.clientX / window.innerWidth;
    LandingMouse.y = e.clientY / window.innerHeight;
  }

  _build() {
    this.network.generate(this.W, this.H);
  }

  _loop(timestamp) {
    var dt = this.lastTime ? Math.min(timestamp - this.lastTime, 50) : 16.67;
    this.lastTime = timestamp;
    this.time = timestamp;
    this.frameCount++;

    this.perf.record(dt);
    var quality = this.perf.getQuality();

    // 8-second heartbeat
    var beatPhase = (timestamp * 0.001) % 8;
    var heartbeat = 0;
    if (beatPhase < 0.15) heartbeat = beatPhase / 0.15;
    else if (beatPhase < 0.3) heartbeat = 1;
    else if (beatPhase < 1.5) heartbeat = 1 - (beatPhase - 0.3) / 1.2;

    // Mouse parallax
    var mx = (LandingMouse.x - 0.5) * 5;
    var my = (LandingMouse.y - 0.5) * 3;

    var ctx = this.ctx;
    var W = this.W, H = this.H;

    // Update
    this.network.update(dt, timestamp);
    this.scan.update(dt);
    this.particles.update(dt);
    this.fog.update(dt);

    this.particles.setQuality(quality);

    // ── Render ──
    ctx.clearRect(0, 0, W, H);

    ctx.save();
    ctx.translate(mx, my);

    this.fog.draw(ctx, W, H);
    this.network.draw(ctx, W, H, timestamp, heartbeat);

    ctx.restore();

    this.scan.draw(ctx, W, H);
    this.particles.draw(ctx, W, H);

    requestAnimationFrame(this._loop.bind(this));
  }
}

// ═════════════════════════════════════════════════════════════
// INIT
// ═════════════════════════════════════════════════════════════
var landingCanvas = null;

document.addEventListener('DOMContentLoaded', function () {
  landingCanvas = new CityMindCanvas();

  var btnLaunch   = document.getElementById('btn-launch');
  var btnOverview = document.getElementById('btn-overview');
  var btnFS       = document.getElementById('btn-fullscreen');
  var btnReload   = document.getElementById('btn-reload');

  if (btnLaunch) btnLaunch.addEventListener('click', launchDashboard);
  if (btnOverview) btnOverview.addEventListener('click', function () {
    var modal = document.getElementById('about-modal');
    if (modal) modal.classList.add('visible');
  });
  if (btnFS) btnFS.addEventListener('click', function () {
    if (document.fullscreenElement) { document.exitFullscreen(); }
    else { document.documentElement.requestFullscreen(); }
  });
  if (btnReload) btnReload.addEventListener('click', function () { window.location.reload(); });

  var btnClose = document.getElementById('btn-about-close');
  var aboutModal = document.getElementById('about-modal');
  if (btnClose && aboutModal) {
    btnClose.addEventListener('click', function () { aboutModal.classList.remove('visible'); });
  }
  if (aboutModal) {
    aboutModal.addEventListener('click', function (e) {
      if (e.target === aboutModal) aboutModal.classList.remove('visible');
    });
  }
});

// ═════════════════════════════════════════════════════════════
// TRANSITIONS
// ═════════════════════════════════════════════════════════════
function launchDashboard() {
  var landing = document.getElementById('landing-page');
  var dashboard = document.getElementById('dashboard-page');

  landing.classList.add('transitioning-out');

  setTimeout(function () {
    landing.style.display = 'none';
    landing.classList.remove('transitioning-out');
    dashboard.style.display = 'grid';
    dashboard.classList.add('transitioning-in');

    Dashboard.init();

    setTimeout(function () {
      dashboard.classList.remove('transitioning-in');
    }, 550);
  }, 500);
}

function showToast(msg, type) {
  var container = document.getElementById('toast-container');
  var el = document.createElement('div');
  el.className = 'toast ' + (type || '');
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(function () { el.remove(); }, 3000);
}
