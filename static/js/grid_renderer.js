/**
 * grid_renderer.js — Canvas 20×20 city grid renderer.
 * 15-layer rendering pipeline, offscreen static base + dynamic overlays.
 */

class GridRenderer {

  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.staticCanvas = document.createElement('canvas');
    this.staticCtx = this.staticCanvas.getContext('2d');

    this.state = null;
    this.options = {
      showMst:    true,
      showAug:    true,
      showLabels: true,
      showAmb:    true,
      showCrime:  false,
    };

    this.hoverNode   = null;
    this.selectedNode = null;
    this.floodFirst   = null;
    this.dirty        = true;
    this.time         = 0;
    this.cell         = 0;
    this.ox           = 0;
    this.oy           = 0;
    this.gridW        = 0;
    this.gridH        = 0;

    this._animId = null;
    this._onNodeClick = null;  // callback(nid)
  }

  // ── Node type colors — bright but cinematic, readable labels ──

  static _normalizeType(n) {
    const raw = n.type || n.kind || n.zone || n.node_type || n.category || n.label || null;
    if (raw === null) return 'Empty';
    return String(raw).trim();
  }

  static CELL_COLORS = {
    'Residential':    '#9B6BFF',  // electric violet
    'Hospital':       '#FF3B5C',  // tactical red
    'School':         '#59D5FF',  // arctic cyan
    'Industrial':     '#FF9F43',  // engine amber
    'PowerPlant':     '#C56CFF',  // plasma purple
    'AmbulanceDepot': '#FFE45E',  // beacon gold
    'Empty':          '#08111F',
  };

  static MST_COLOR = '#00E5FF';

  static SYM = {
    'Residential': 'R', 'Hospital': 'H', 'School': 'S',
    'Industrial': 'I', 'PowerPlant': 'P', 'AmbulanceDepot': 'A', 'Empty': '',
  };

  // ── Public API ──

  setState(state) {
    this.state = state;
    this.dirty = true;
  }

  setOptions(opts) {
    Object.assign(this.options, opts);
    this.dirty = true;
  }

  onNodeClick(fn) {
    this._onNodeClick = fn;
  }

  start() {
    this._resize();
    this._loop(0);
    window.addEventListener('resize', () => this._resize());
    this.canvas.addEventListener('mousemove', (e) => this._onMouseMove(e));
    this.canvas.addEventListener('click', (e) => this._onClick(e));
    this.canvas.addEventListener('mouseleave', () => {
      this.hoverNode = null;
    });
  }

  // ── Resize ──

  _resize() {
    const rect = this.canvas.parentElement.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width  = rect.width * dpr;
    this.canvas.height = rect.height * dpr;
    this.staticCanvas.width  = rect.width * dpr;
    this.staticCanvas.height = rect.height * dpr;
    this.dirty = true;
  }

  // ── Mouse -> Node ──

  _nodeFromMouse(mx, my) {
    const rect = this.canvas.getBoundingClientRect();
    const scaleX = this.canvas.width / rect.width;
    const scaleY = this.canvas.height / rect.height;
    const x = (mx - rect.left) * scaleX;
    const y = (my - rect.top) * scaleY;
    const col = Math.floor((x - this.ox) / this.cell);
    const row = Math.floor((y - this.oy) / this.cell);
    if (col >= 0 && col < 20 && row >= 0 && row < 20) {
      return row * 20 + col;
    }
    return null;
  }

  _onMouseMove(e) {
    this.hoverNode = this._nodeFromMouse(e.clientX, e.clientY);
  }

  _onClick(e) {
    const nid = this._nodeFromMouse(e.clientX, e.clientY);
    if (nid === null) return;

    if (this._onNodeClick) {
      this._onNodeClick(nid);
    }
  }

  // ── Animation Loop ──

  _loop(timestamp) {
    this.time = timestamp;

    if (this.dirty) {
      this._drawStaticBase();
      this.dirty = false;
    }

    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    ctx.drawImage(this.staticCanvas, 0, 0);
    try { this._drawDynamicOverlays(); } catch (e) { console.error('overlay error', e); }

    this._animId = requestAnimationFrame(t => this._loop(t));
  }

  // ── Static Base (drawn once when dirty) ──

  _drawStaticBase() {
    const ctx = this.staticCtx;
    const dpr = window.devicePixelRatio || 1;
    const W = this.canvas.width;
    const H = this.canvas.height;

    ctx.clearRect(0, 0, W, H);

    const cell = Math.min(W / 20, H / 20);
    const gridW = cell * 20;
    const gridH = cell * 20;
    const ox = (W - gridW) / 2;
    const oy = (H - gridH) / 2;

    this.cell  = cell;
    this.ox    = ox;
    this.oy    = oy;
    this.gridW = gridW;
    this.gridH = gridH;

    const g = this.state;
    if (!g) return;

    // 1. Panel background — deep cinematic black-blue
    ctx.fillStyle = '#030712';
    ctx.fillRect(ox, oy, gridW, gridH);

    // 1a. Subtle dot grid + crosshatch pattern
    ctx.save();
    const dotSpacing = Math.max(10, cell / 2.8);
    ctx.fillStyle = 'rgba(0, 217, 255, 0.10)';
    for (let dx = dotSpacing; dx < gridW; dx += dotSpacing) {
      for (let dy = dotSpacing; dy < gridH; dy += dotSpacing) {
        ctx.beginPath();
        ctx.arc(ox + dx, oy + dy, 0.6, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    // Fine diagonal crosshatch
    ctx.strokeStyle = 'rgba(0, 217, 255, 0.05)';
    ctx.lineWidth = 0.5;
    const crossSpacing = Math.max(18, cell / 1.4);
    for (let i = -gridH; i < gridW + gridH; i += crossSpacing) {
      ctx.beginPath();
      ctx.moveTo(ox + i, oy);
      ctx.lineTo(ox + i - gridH, oy + gridH);
      ctx.stroke();
    }
    ctx.restore();

    // 2. MST edges — glowing cyan, flooded edges red dashed glitch
    if (this.options.showMst && g.mst_edges) {
      for (const [a, b] of g.mst_edges) {
        const na = g.nodes[a], nb = g.nodes[b];
        if (!na || !nb) continue;
        const edge = g.edges.find(e =>
          (e.from === a && e.to === b) || (e.from === b && e.to === a));
        const flooded = edge && edge.flooded;
        if (flooded) {
          // Red dashed glitch flooded edge
          ctx.strokeStyle = 'rgba(239, 68, 68, 0.90)';
          ctx.lineWidth = 2.5;
          ctx.shadowColor = 'rgba(239, 68, 68, 0.55)';
          ctx.shadowBlur = 10;
          ctx.setLineDash([5, 3]);
        } else {
          // Bright glowing cyan MST edge
          ctx.strokeStyle = 'rgba(0, 229, 255, 0.88)';
          ctx.lineWidth = 2.5;
          ctx.shadowColor = 'rgba(0, 229, 255, 0.60)';
          ctx.shadowBlur = 16;
        }
        ctx.beginPath();
        ctx.moveTo(ox + na.col * cell + cell / 2, oy + na.row * cell + cell / 2);
        ctx.lineTo(ox + nb.col * cell + cell / 2, oy + nb.row * cell + cell / 2);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.shadowColor = 'transparent';
        ctx.shadowBlur = 0;
      }
    }

    // 3. Augment edges — amber dashed with glow
    if (this.options.showAug && g.augment_edges) {
      for (const [a, b] of g.augment_edges) {
        const na = g.nodes[a], nb = g.nodes[b];
        if (!na || !nb) continue;
        ctx.strokeStyle = 'rgba(255, 176, 32, 0.55)';
        ctx.lineWidth = 3;
        ctx.shadowColor = 'rgba(255, 176, 32, 0.35)';
        ctx.shadowBlur = 8;
        ctx.setLineDash([6, 4]);
        ctx.beginPath();
        ctx.moveTo(ox + na.col * cell + cell / 2, oy + na.row * cell + cell / 2);
        ctx.lineTo(ox + nb.col * cell + cell / 2, oy + nb.row * cell + cell / 2);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.shadowColor = 'transparent';
        ctx.shadowBlur = 0;
      }
    }

    // 4. A* team path — bright animated cyan dash
    if (g.simulation && g.simulation.team_path && g.simulation.team_path.length > 1) {
      const path = g.simulation.team_path;
      ctx.strokeStyle = 'rgba(0, 217, 255, 0.85)';
      ctx.lineWidth = 2.5;
      ctx.shadowColor = 'rgba(0, 217, 255, 0.50)';
      ctx.shadowBlur = 14;
      ctx.setLineDash([10, 4]);
      ctx.lineDashOffset = -(this.time * 0.04);
      ctx.beginPath();
      for (let i = 0; i < path.length; i++) {
        const n = g.nodes[path[i]];
        const px = ox + n.col * cell + cell / 2;
        const py = oy + n.row * cell + cell / 2;
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.shadowColor = 'transparent';
      ctx.shadowBlur = 0;
    }

    // 5. Cells — two-pass: empty first, then populated on top
    const populatedNodes = [];
    const emptyNodes = [];

    for (const n of g.nodes) {
      const nodeType = GridRenderer._normalizeType(n);
      if (nodeType && nodeType !== 'Empty') {
        populatedNodes.push(n);
      } else {
        emptyNodes.push(n);
      }
    }

    // Pass 1: empty cells
    for (const n of emptyNodes) {
      const x = ox + n.col * cell;
      const y = oy + n.row * cell;
      ctx.fillStyle = '#08111F';
      ctx.fillRect(x + 0.5, y + 0.5, cell - 1, cell - 1);
    }

    // Pass 2: populated cells — translucent fill + bloom glow + inner border
    for (const n of populatedNodes) {
      const x = ox + n.col * cell;
      const y = oy + n.row * cell;
      const nodeType = GridRenderer._normalizeType(n);
      const baseColor = GridRenderer.CELL_COLORS[nodeType] || '#FFFFFF';

      const isPriority = (nodeType === 'Hospital' || nodeType === 'AmbulanceDepot');
      const glowBlur = isPriority ? 22 : 12;
      const glowAlpha = isPriority ? 0.70 : 0.40;
      const inset = 0.3; // fuller cells

      // Bloom glow fill
      ctx.save();
      ctx.shadowColor = baseColor;
      ctx.shadowBlur = glowBlur;
      ctx.fillStyle = baseColor + 'E6'; // ~90% opacity
      ctx.fillRect(x + inset, y + inset, cell - inset * 2, cell - inset * 2);
      ctx.restore();

      // Subtle inner border — brighter edge
      ctx.strokeStyle = baseColor + 'FF';
      ctx.lineWidth = Math.max(0.7, cell / 30);
      ctx.globalAlpha = 0.50;
      const bi = inset + 0.4;
      ctx.strokeRect(x + bi, y + bi, cell - bi * 2, cell - bi * 2);
      ctx.globalAlpha = 1;
    }

    // 6. Special highlights — hospital tactical red, depot beacon gold
    if (g.primary_hospital_id !== null) {
      const n = g.nodes[g.primary_hospital_id];
      if (n) {
        ctx.strokeStyle = '#FF3B5C';
        ctx.lineWidth = 3;
        ctx.shadowColor = 'rgba(255, 59, 92, 0.85)';
        ctx.shadowBlur = 28;
        this._roundRect(ctx, ox + n.col * cell + 1, oy + n.row * cell + 1, cell - 2, cell - 2, 2);
        ctx.stroke();
        ctx.strokeStyle = 'rgba(255, 59, 92, 0.45)';
        ctx.lineWidth = 5;
        ctx.shadowColor = 'rgba(255, 59, 92, 0.55)';
        ctx.shadowBlur = 34;
        this._roundRect(ctx, ox + n.col * cell - 1, oy + n.row * cell - 1, cell + 2, cell + 2, 3);
        ctx.stroke();
        ctx.shadowColor = 'transparent';
        ctx.shadowBlur = 0;
      }
    }
    if (g.ambulance_depot_id !== null) {
      const n = g.nodes[g.ambulance_depot_id];
      if (n) {
        ctx.strokeStyle = '#FFE45E';
        ctx.lineWidth = 3;
        ctx.shadowColor = 'rgba(255, 228, 94, 0.80)';
        ctx.shadowBlur = 24;
        this._roundRect(ctx, ox + n.col * cell + 1, oy + n.row * cell + 1, cell - 2, cell - 2, 2);
        ctx.stroke();
        ctx.strokeStyle = 'rgba(255, 228, 94, 0.40)';
        ctx.lineWidth = 5;
        ctx.shadowColor = 'rgba(255, 228, 94, 0.50)';
        ctx.shadowBlur = 30;
        this._roundRect(ctx, ox + n.col * cell - 1, oy + n.row * cell - 1, cell + 2, cell + 2, 3);
        ctx.stroke();
        ctx.shadowColor = 'transparent';
        ctx.shadowBlur = 0;
      }
    }

    // 7. Labels — monospace cinematic
    if (this.options.showLabels && cell >= 14) {
      ctx.font = `${Math.max(8, cell * 0.43)}px "JetBrains Mono", "Consolas", monospace`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      for (const n of g.nodes) {
        const nodeType = GridRenderer._normalizeType(n);
        const sym = GridRenderer.SYM[nodeType];
        if (!sym) continue;
        const cx = ox + n.col * cell + cell / 2;
        const cy = oy + n.row * cell + cell / 2;
        const color = GridRenderer.CELL_COLORS[nodeType] || '#0E1030';
        const rgb = color.slice(1);
        const r = parseInt(rgb.slice(0,2), 16);
        const g2 = parseInt(rgb.slice(2,4), 16);
        const b = parseInt(rgb.slice(4,6), 16);
        const lum = (r + g2 + b) / 3;
        ctx.fillStyle = lum > 145 ? '#060B1E' : '#E6F1FF';
        ctx.fillText(sym, cx, cy);
      }
    }

    // 8. Crime heatmap overlay — transparent overlays per spec
    if (this.options.showCrime) {
      for (const n of g.nodes) {
        if (n.crime_risk === 'High') {
          // Red-orange glowing hotspot
          const grad = ctx.createRadialGradient(
            ox + n.col * cell + cell / 2, oy + n.row * cell + cell / 2, cell * 0.15,
            ox + n.col * cell + cell / 2, oy + n.row * cell + cell / 2, cell * 0.75
          );
          grad.addColorStop(0, 'rgba(255, 90, 40, 0.45)');
          grad.addColorStop(0.5, 'rgba(255, 120, 40, 0.25)');
          grad.addColorStop(1, 'rgba(255, 90, 40, 0)');
          ctx.fillStyle = grad;
          ctx.shadowColor = 'rgba(255, 80, 30, 0.35)';
          ctx.shadowBlur = 14;
          this._roundRect(ctx, ox + n.col * cell - 1, oy + n.row * cell - 1, cell + 2, cell + 2, 2);
          ctx.fill();
          ctx.shadowColor = 'transparent';
          ctx.shadowBlur = 0;
        } else if (n.crime_risk === 'Medium') {
          // Magenta/orange transparent
          const grad = ctx.createRadialGradient(
            ox + n.col * cell + cell / 2, oy + n.row * cell + cell / 2, cell * 0.15,
            ox + n.col * cell + cell / 2, oy + n.row * cell + cell / 2, cell * 0.7
          );
          grad.addColorStop(0, 'rgba(200, 80, 140, 0.30)');
          grad.addColorStop(0.5, 'rgba(220, 130, 50, 0.18)');
          grad.addColorStop(1, 'rgba(200, 80, 140, 0)');
          ctx.fillStyle = grad;
          ctx.shadowColor = 'rgba(200, 80, 140, 0.20)';
          ctx.shadowBlur = 8;
          this._roundRect(ctx, ox + n.col * cell - 1, oy + n.row * cell - 1, cell + 2, cell + 2, 2);
          ctx.fill();
          ctx.shadowColor = 'transparent';
          ctx.shadowBlur = 0;
        } else if (n.crime_risk === 'Low' || n.crime_risk === 'Safe') {
          // Transparent cyan/violet
          ctx.fillStyle = 'rgba(0, 217, 255, 0.06)';
          this._roundRect(ctx, ox + n.col * cell + 1, oy + n.row * cell + 1, cell - 2, cell - 2, 2);
          ctx.fill();
        }
      }
    }

    // 9. Grid lines — visible tactical grid
    ctx.strokeStyle = 'rgba(0, 217, 255, 0.12)';
    ctx.lineWidth = 0.6;
    for (let r = 0; r <= 20; r++) {
      ctx.beginPath();
      ctx.moveTo(ox, oy + r * cell);
      ctx.lineTo(ox + gridW, oy + r * cell);
      ctx.stroke();
    }
    for (let c = 0; c <= 20; c++) {
      ctx.beginPath();
      ctx.moveTo(ox + c * cell, oy);
      ctx.lineTo(ox + c * cell, oy + gridH);
      ctx.stroke();
    }

    // 9a. Corner brackets on grid perimeter — holographic cyan
    const brLen = Math.min(18, cell * 0.7);
    ctx.strokeStyle = 'rgba(0, 217, 255, 0.60)';
    ctx.lineWidth = 1.5;
    ctx.shadowColor = 'rgba(0, 217, 255, 0.45)';
    ctx.shadowBlur = 10;

    const drawBracket = (x, y, dirX, dirY) => {
      ctx.beginPath();
      ctx.moveTo(x, y + brLen * dirY);
      ctx.lineTo(x, y);
      ctx.lineTo(x + brLen * dirX, y);
      ctx.stroke();
    };

    drawBracket(ox - 1, oy - 1, 1, 1);                     // top-left
    drawBracket(ox + gridW + 1, oy - 1, -1, 1);            // top-right
    drawBracket(ox - 1, oy + gridH + 1, 1, -1);            // bottom-left
    drawBracket(ox + gridW + 1, oy + gridH + 1, -1, -1);   // bottom-right

    ctx.shadowColor = 'transparent';
    ctx.shadowBlur = 0;
  }

  // ── Dynamic Overlays (drawn every frame) ──

  _drawDynamicOverlays() {
    const ctx = this.ctx;
    const { ox, oy, cell, state: g, time } = this;
    if (!g) return;

    // 10. Hover highlight — cyan glow
    if (this.hoverNode !== null) {
      const n = g.nodes[this.hoverNode];
      if (n) {
        ctx.fillStyle = 'rgba(0, 217, 255, 0.15)';
        ctx.shadowColor = 'rgba(0, 217, 255, 0.28)';
        ctx.shadowBlur = 14;
        this._roundRect(ctx, ox + n.col * cell + 1, oy + n.row * cell + 1, cell - 2, cell - 2, 2);
        ctx.fill();
        ctx.shadowColor = 'transparent';
        ctx.shadowBlur = 0;
      }
    }

    // 11. Selected node highlight — cyan glow
    if (this.selectedNode !== null) {
      const n = g.nodes[this.selectedNode];
      if (n) {
        ctx.strokeStyle = '#00E5FF';
        ctx.lineWidth = 2.5;
        ctx.shadowColor = 'rgba(0, 217, 255, 0.65)';
        ctx.shadowBlur = 16;
        this._roundRect(ctx, ox + n.col * cell + 1, oy + n.row * cell + 1, cell - 2, cell - 2, 2);
        ctx.stroke();
        ctx.shadowColor = 'transparent';
        ctx.shadowBlur = 0;
      }
    }

    // 12. Flood first highlight — red glow
    if (this.floodFirst !== null) {
      const n = g.nodes[this.floodFirst];
      if (n) {
        ctx.strokeStyle = '#EF4444';
        ctx.lineWidth = 2;
        ctx.shadowColor = 'rgba(239, 68, 68, 0.50)';
        ctx.shadowBlur = 10;
        this._roundRect(ctx, ox + n.col * cell + 1, oy + n.row * cell + 1, cell - 2, cell - 2, 2);
        ctx.stroke();
        ctx.shadowColor = 'transparent';
        ctx.shadowBlur = 0;
      }
    }

    // 13. Ambulance markers — pulsing cyan rings + crosshairs with strong glow
    if (this.options.showAmb && g.ambulance_positions) {
      for (const ambId of g.ambulance_positions) {
        const n = g.nodes[ambId];
        if (!n) continue;
        const ax = ox + n.col * cell + cell / 2;
        const ay = oy + n.row * cell + cell / 2;
        const pulse = 0.7 + 0.3 * Math.sin(time * 0.01);
        const r = cell * 0.82 * pulse;

        // Outer glow ring
        ctx.strokeStyle = `rgba(0, 217, 255, ${0.15 + 0.10 * Math.sin(time * 0.01)})`;
        ctx.lineWidth = 3;
        ctx.shadowColor = 'rgba(0, 217, 255, 0.25)';
        ctx.shadowBlur = 14;
        ctx.beginPath();
        ctx.arc(ax, ay, r + 2, 0, Math.PI * 2);
        ctx.stroke();

        // Inner ring
        ctx.strokeStyle = `rgba(0, 217, 255, ${0.40 + 0.20 * Math.sin(time * 0.01)})`;
        ctx.lineWidth = 2;
        ctx.shadowColor = 'rgba(0, 217, 255, 0.40)';
        ctx.shadowBlur = 10;
        ctx.beginPath();
        ctx.arc(ax, ay, r, 0, Math.PI * 2);
        ctx.stroke();
        ctx.shadowColor = 'transparent';
        ctx.shadowBlur = 0;

        // Crosshair
        const hw = Math.max(2, cell / 5);
        ctx.strokeStyle = '#E6F1FF';
        ctx.lineWidth = 1.5;
        ctx.shadowColor = 'rgba(230, 241, 255, 0.35)';
        ctx.shadowBlur = 5;
        ctx.beginPath();
        ctx.moveTo(ax - hw, ay); ctx.lineTo(ax + hw, ay);
        ctx.moveTo(ax, ay - hw); ctx.lineTo(ax, ay + hw);
        ctx.stroke();
        ctx.shadowColor = 'transparent';
        ctx.shadowBlur = 0;
      }
    }

    // 14. Medical team marker — bright pulsing ring
    if (g.simulation && g.simulation.running && g.simulation.team_position !== null) {
      const tn = g.nodes[g.simulation.team_position];
      if (tn) {
        const tx = ox + tn.col * cell + cell / 2;
        const ty = oy + tn.row * cell + cell / 2;
        const pulse = 0.65 + 0.35 * Math.sin(time * 0.013);
        const r = cell * 0.88 * pulse;

        ctx.strokeStyle = `rgba(0, 217, 255, ${0.35 + 0.20 * Math.sin(time * 0.013)})`;
        ctx.lineWidth = 2.5;
        ctx.shadowColor = 'rgba(0, 217, 255, 0.45)';
        ctx.shadowBlur = 14;
        ctx.beginPath();
        ctx.arc(tx, ty, r, 0, Math.PI * 2);
        ctx.stroke();
        ctx.shadowColor = 'transparent';
        ctx.shadowBlur = 0;

        // Target civilian — red pulsing ring
        if (g.simulation.current_target !== null) {
          const tgt = g.nodes[g.simulation.current_target];
          if (tgt) {
            const tgx = ox + tgt.col * cell + cell / 2;
            const tgy = oy + tgt.row * cell + cell / 2;
            ctx.strokeStyle = '#EF4444';
            ctx.lineWidth = 2.5;
            ctx.shadowColor = 'rgba(239, 68, 68, 0.55)';
            ctx.shadowBlur = 14;
            ctx.beginPath();
            ctx.arc(tgx, tgy, Math.max(3, cell / 4), 0, Math.PI * 2);
            ctx.stroke();
            ctx.shadowColor = 'transparent';
            ctx.shadowBlur = 0;
          }
        }
      }
    }

    // 15. Spinner overlay (during solving phases or exec_running)
    const solvingPhases = ['SOLVING_LAYOUT', 'SOLVING_ROADS', 'SOLVING_RISK', 'SOLVING_AMBULANCE'];
    const isSolving = g.phase && solvingPhases.includes(g.phase);
    const isExecRunning = g.exec_running === true;
    if (isSolving || isExecRunning) {
      const cx = ox + this.gridW / 2;
      const cy = oy + this.gridH / 2;

      // Dark overlay behind spinner
      ctx.fillStyle = 'rgba(3, 7, 18, 0.50)';
      ctx.fillRect(ox, oy, this.gridW, this.gridH);

      // Rotating neon ring — cyan arcs
      const ringRadius = 40;
      const startAngle = (time * 0.005) % (Math.PI * 2);
      for (let i = 0; i < 3; i++) {
        const arcStart = startAngle + i * (Math.PI * 2 / 3);
        const arcEnd   = arcStart + Math.PI * 0.60;
        const alpha = 0.35 + 0.55 * (1 - i / 3);
        ctx.strokeStyle = `rgba(0, 217, 255, ${alpha})`;
        ctx.lineWidth = 3;
        ctx.shadowColor = 'rgba(0, 217, 255, 0.45)';
        ctx.shadowBlur = 12;
        ctx.beginPath();
        ctx.arc(cx, cy, ringRadius, arcStart, arcEnd);
        ctx.stroke();
        ctx.shadowColor = 'transparent';
        ctx.shadowBlur = 0;
      }

      // Center dot
      ctx.fillStyle = '#00E5FF';
      ctx.shadowColor = 'rgba(0, 217, 255, 0.70)';
      ctx.shadowBlur = 12;
      ctx.beginPath();
      ctx.arc(cx, cy, 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowColor = 'transparent';
      ctx.shadowBlur = 0;

      // Outer glow pulsing
      const glowAlpha = 0.10 + 0.08 * Math.sin(time * 0.006);
      const glow = ctx.createRadialGradient(cx, cy, ringRadius - 4, cx, cy, ringRadius + 24);
      glow.addColorStop(0, `rgba(0, 217, 255, ${glowAlpha})`);
      glow.addColorStop(1, 'rgba(0, 217, 255, 0)');
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(cx, cy, ringRadius + 24, 0, Math.PI * 2);
      ctx.fill();

      // Status text
      const label = g.progress_label || 'Processing…';
      ctx.font = 'bold 16px "JetBrains Mono", "Consolas", monospace';
      ctx.textAlign = 'center';
      ctx.fillStyle = '#00E5FF';
      ctx.shadowColor = 'rgba(0, 217, 255, 0.50)';
      ctx.shadowBlur = 8;
      ctx.fillText(label, cx, cy + 62);
      ctx.shadowColor = 'transparent';
      ctx.shadowBlur = 0;
    }

    // 16. Scan line sweep over grid
    const scanY = oy + ((time * 0.02) % this.gridH);
    const scanGrad = ctx.createLinearGradient(0, scanY - 4, 0, scanY + 4);
    scanGrad.addColorStop(0, 'rgba(0, 217, 255, 0)');
    scanGrad.addColorStop(0.5, 'rgba(0, 217, 255, 0.06)');
    scanGrad.addColorStop(1, 'rgba(0, 217, 255, 0)');
    ctx.fillStyle = scanGrad;
    ctx.fillRect(ox, scanY - 4, this.gridW, 8);
  }

  // ── Utility ──

  _roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.arcTo(x + w, y, x + w, y + r, r);
    ctx.lineTo(x + w, y + h - r);
    ctx.arcTo(x + w, y + h, x + w - r, y + h, r);
    ctx.lineTo(x + r, y + h);
    ctx.arcTo(x, y + h, x, y + h - r, r);
    ctx.lineTo(x, y + r);
    ctx.arcTo(x, y, x + r, y, r);
    ctx.closePath();
  }
}
