/* Organization observability dashboard — self-contained frontend.
 *
 * No dependencies, no CDN: hand-rolled canvas renderers (stacked/overlaid
 * cumulative time series + bars), an SSE client for live updates, and the
 * conversation monitor (active pod live + last-N historical pods).
 */
'use strict';

// ---------- state + SSE ------------------------------------------------------

let state = null;
const $ = (id) => document.getElementById(id);
// expanded pod ids — survives the 1-second re-render (the pod list is
// rebuilt on every SSE push, so the open state must be tracked here or the
// <details> dropdowns would collapse on every tick).
const expandedPods = new Set();

function setStatus(text, live) {
  const el = $('status');
  el.textContent = text;
  el.className = 'status' + (live ? ' live' : '');
}

function connect() {
  const es = new EventSource('/api/stream');
  es.onopen = () => setStatus('live', true);
  es.onerror = () => setStatus('reconnecting…', false);
  es.onmessage = (ev) => {
    try { state = JSON.parse(ev.data); } catch (e) { return; }
    render();
  };
}

// ---------- chart helpers ----------------------------------------------------

const PALETTE = ['#4cc9f0', '#f72585', '#ffd166', '#80ed99', '#b388ff',
                 '#ff9e64', '#7bdff2', '#f9c74f'];

function prepCanvas(canvas) {
  const dpr = 2;
  const w = canvas.clientWidth || 600;
  const h = canvas.clientHeight || 220;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  return { ctx, w, h };
}

function drawEmpty(canvas, msg) {
  const { ctx, w, h } = prepCanvas(canvas);
  ctx.fillStyle = '#5c677d';
  ctx.font = '14px sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText(msg || 'no data yet', w / 2, h / 2);
}

function fmtDur(sec) {
  if (sec < 60) return Math.round(sec) + 's';
  return Math.floor(sec / 60) + 'm ' + Math.round(sec % 60) + 's';
}

function timeBounds(seriesList) {
  let t0 = Infinity, t1 = -Infinity;
  for (const s of seriesList) for (const p of s.points) {
    if (p.t < t0) t0 = p.t;
    if (p.t > t1) t1 = p.t;
  }
  if (!isFinite(t0)) return null;
  if (t1 - t0 < 1) t1 = t0 + 60;
  return { t0, t1 };
}

function valueAt(points, t) {  // last cumulative value at or before t (step)
  let v = 0;
  for (const p of points) { if (p.t <= t) v = p.v; else break; }
  return v;
}

function drawLegend(ctx, series, w) {
  let x = 8;
  ctx.font = '10px sans-serif';
  ctx.textAlign = 'left';
  for (const s of series) {
    // A3: for error/retry tool-call outcomes, append the error_type breakdown
    // to the legend label (e.g. "error — TimeoutError×2, ParseError×1").
    let label = s.label;
    if (s.errorTypes && (s.label === 'error' || s.label === 'retry')) {
      const parts = Object.keys(s.errorTypes)
        .map((t) => t + '×' + s.errorTypes[t]).join(', ');
      label += ' — ' + parts;
    }
    if (x > w - 60) break;
    ctx.fillStyle = s.color;
    ctx.fillRect(x, 2, 8, 8);
    ctx.fillStyle = '#9aa5bd';
    ctx.fillText(label, x + 11, 10);
    x += 11 + ctx.measureText(label).width + 12;
  }
}

/* Draw cumulative time series — stacked areas or overlaid lines.
 * series: [{label, color, points: [{t, v}]}] with v cumulative. */
function drawTimeSeries(canvas, series, stacked, emptyMsg) {
  stacked = stacked !== false;
  const bounds = timeBounds(series);
  // A4: a custom empty message (e.g. "no code volume yet").
  if (!bounds) return drawEmpty(canvas, emptyMsg);
  const { ctx, w, h } = prepCanvas(canvas);
  const padL = 34, padB = 20, padT = 14, padR = 8;
  const iw = w - padL - padR, ih = h - padT - padB;
  const { t0, t1 } = bounds;
  const X = (t) => padL + (t - t0) / (t1 - t0) * iw;

  const times = new Set();
  for (const s of series) for (const p of s.points) times.add(p.t);
  const ts = Array.from(times).sort((a, b) => a - b);
  const vals = series.map((s) => ts.map((t) => valueAt(s.points, t)));

  // item 7: generic hover tooltip — on mousemove, find the nearest time point
  // and list each series' value at that point with its legend label + color
  // (so the operator can see which shaded band is which, and the value at any
  // x). Reuses the tooltip DOM pattern.
  canvas.onmousemove = (ev) => {
    const r = canvas.getBoundingClientRect();
    const mx = ev.clientX - r.left;
    let best = ts[0], bestDx = Infinity;
    for (const t of ts) {
      const dx = Math.abs(X(t) - mx);
      if (dx < bestDx) { bestDx = dx; best = t; }
    }
    const rows = series.map((s) => ({
      label: s.label, color: s.color, v: valueAt(s.points, best),
    }));
    let tip = $('ts-tooltip');
    if (!tip) {
      tip = document.createElement('div');
      tip.id = 'ts-tooltip';
      tip.className = 'ts-tooltip';
      document.body.appendChild(tip);
    }
    tip.innerHTML = rows.map((row) =>
      '<div class="ts-tip-row">' +
      '<span class="ts-tip-swatch" style="background:' + row.color +
      '"></span>' +
      '<span class="ts-tip-label">' + row.label + '</span>' +
      '<span class="ts-tip-val">' + row.v + '</span></div>').join('');
    tip.style.display = 'block';
    tip.style.left = (ev.clientX + 12) + 'px';
    tip.style.top = (ev.clientY + 12) + 'px';
  };
  canvas.onmouseleave = () => {
    const tip = $('ts-tooltip');
    if (tip) tip.style.display = 'none';
  };

  let maxV = 1;
  ts.forEach((t, i) => {
    if (stacked) {
      let v = 0;
      for (const row of vals) v += row[i];
      if (v > maxV) maxV = v;
    } else {
      for (const row of vals) if (row[i] > maxV) maxV = row[i];
    }
  });
  const Y = (v) => padT + ih - (v / maxV) * ih;

  // axes + ticks
  ctx.strokeStyle = '#2a3247';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(padL, padT);
  ctx.lineTo(padL, padT + ih);
  ctx.lineTo(padL + iw, padT + ih);
  ctx.stroke();
  ctx.fillStyle = '#5c677d';
  ctx.font = '10px sans-serif';
  ctx.textAlign = 'right';
  for (let i = 0; i <= 3; i++) {
    const v = maxV * i / 3;
    ctx.fillText(String(Math.round(v)), padL - 4, Y(v) + 3);
  }
  ctx.textAlign = 'center';
  for (let i = 0; i <= 3; i++) {
    const t = t0 + (t1 - t0) * i / 3;
    ctx.fillText(fmtDur(t - t0), X(t), h - 6);
  }

  // series
  let base = ts.map(() => 0);
  series.forEach((s, si) => {
    // A3: `error`/`retry` tool-call outcomes are rendered red with a
    // translucent fill (failures stand out); the legend carries the
    // error_type breakdown (s.errorTypes, set by buildCumulativeSeries).
    const isFail = (s.label === 'error' || s.label === 'retry');
    // A4: `refused` code-edits are rendered with a dashed (striped) line so
    // they're visually distinct from applied edits.
    const isRefused = s.label.indexOf('refused') !== -1;
    const color = isFail ? '#f72585' : s.color;
    const top = ts.map((t, i) => base[i] + vals[si][i]);
    if (stacked) {
      ctx.beginPath();
      ctx.moveTo(X(ts[0]), Y(base[0]));
      top.forEach((v, i) => ctx.lineTo(X(ts[i]), Y(v)));
      for (let i = ts.length - 1; i >= 0; i--) {
        ctx.lineTo(X(ts[i]), Y(base[i]));
      }
      ctx.closePath();
      ctx.globalAlpha = isFail ? 0.28 : 0.5;
      ctx.fillStyle = color;
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.beginPath();
      top.forEach((v, i) => {
        if (i) ctx.lineTo(X(ts[i]), Y(v));
        else ctx.moveTo(X(ts[i]), Y(v));
      });
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      if (isRefused) ctx.setLineDash([4, 3]);
      ctx.stroke();
      ctx.setLineDash([]);
    } else {
      ctx.beginPath();
      vals[si].forEach((v, i) => {
        if (i) ctx.lineTo(X(ts[i]), Y(v));
        else ctx.moveTo(X(ts[i]), Y(v));
      });
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      if (isRefused) ctx.setLineDash([4, 3]);
      ctx.stroke();
      ctx.setLineDash([]);
    }
    base = top;
  });
  drawLegend(ctx, series, w);
}

/* Bars: groups [{label, segments: [{label, color, v}]}] (stacked segments).
 * A2: wider left padding (y-labels not cut off), a total-duration label per
 * bar + an overall total (canvas + caption), a hover tooltip on a segment
 * (phase + duration), and a dashed outline on the setup bar (cycle 0) so it's
 * visually distinct from the iteration bars. */
function drawBars(canvas, groups) {
  if (!groups.length) return drawEmpty(canvas);
  const { ctx, w, h } = prepCanvas(canvas);
  const padL = 48, padB = 20, padT = 18, padR = 8;
  const iw = w - padL - padR, ih = h - padT - padB;
  const totals = groups.map((g) => g.segments.reduce((a, s) => a + s.v, 0));
  const maxV = Math.max(1, ...totals);
  const Y = (v) => padT + ih - (v / maxV) * ih;
  ctx.strokeStyle = '#2a3247';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(padL, padT);
  ctx.lineTo(padL, padT + ih);
  ctx.lineTo(padL + iw, padT + ih);
  ctx.stroke();
  ctx.fillStyle = '#5c677d';
  ctx.font = '10px sans-serif';
  ctx.textAlign = 'right';
  for (let i = 0; i <= 3; i++) {
    const v = maxV * i / 3;
    ctx.fillText(fmtDur(v), padL - 4, Y(v) + 3);
  }
  const bw = Math.min(40, (iw / groups.length) * 0.6);
  // Record the segment rectangles for hover hit-testing (the tooltip).
  const hits = [];
  const overallTotal = totals.reduce((a, b) => a + b, 0);
  groups.forEach((g, i) => {
    const cx = padL + iw * (i + 0.5) / groups.length;
    const isSetup = g.label === 'setup';
    let y0 = 0;
    for (const s of g.segments) {
      const y1 = y0 + s.v;
      ctx.fillStyle = s.color;
      ctx.fillRect(cx - bw / 2, Y(y1), bw, Math.max(0.5, Y(y0) - Y(y1)));
      hits.push({ x: cx - bw / 2, y: Y(y1), w: bw, h: Math.max(0.5, Y(y0) - Y(y1)),
                  label: g.label, seg: s.label, v: s.v });
      y0 = y1;
    }
    // A2: total-duration label above each bar.
    ctx.fillStyle = '#c9d2e8';
    ctx.textAlign = 'center';
    ctx.font = '10px sans-serif';
    ctx.fillText(fmtDur(totals[i]), cx, Y(totals[i]) - 3);
    // A2: the setup bar (cycle 0) gets a dashed outline so it's visually
    // distinct from the iteration bars.
    if (isSetup) {
      ctx.strokeStyle = '#8892ab';
      ctx.setLineDash([3, 2]);
      ctx.strokeRect(cx - bw / 2 - 1, Y(totals[i]) - 1, bw + 2, ih - Y(totals[i]) + 1);
      ctx.setLineDash([]);
    }
    ctx.fillStyle = '#9aa5bd';
    ctx.textAlign = 'center';
    ctx.fillText(g.label, cx, h - 6);
  });
  // A2: overall total (top-right of the canvas) + a caption for the page.
  ctx.fillStyle = '#8892ab';
  ctx.textAlign = 'right';
  ctx.font = '10px sans-serif';
  ctx.fillText('total ' + fmtDur(overallTotal), w - 8, 12);
  canvas.dataset.total = fmtDur(overallTotal);
  // A2: hover tooltip on a segment (phase + duration).
  canvas.onmousemove = (ev) => {
    const r = canvas.getBoundingClientRect();
    const mx = ev.clientX - r.left, my = ev.clientY - r.top;
    const hit = hits.find((s) => mx >= s.x && mx <= s.x + s.w &&
                                 my >= s.y && my <= s.y + s.h);
    let tip = $('bar-tooltip');
    if (!hit) { if (tip) tip.style.display = 'none'; return; }
    if (!tip) {
      tip = document.createElement('div');
      tip.id = 'bar-tooltip';
      tip.className = 'bar-tooltip';
      document.body.appendChild(tip);
    }
    tip.textContent = hit.label + ' · ' + hit.seg + ': ' + fmtDur(hit.v);
    tip.style.display = 'block';
    tip.style.left = (ev.clientX + 12) + 'px';
    tip.style.top = (ev.clientY + 12) + 'px';
  };
  canvas.onmouseleave = () => {
    const tip = $('bar-tooltip');
    if (tip) tip.style.display = 'none';
  };
  // Legend: the distinct segments (phases) across all bars, so the stacked
  // colors are explained (the time-series charts already draw legends).
  const seen = {};
  const legend = [];
  for (const g of groups) for (const s of g.segments) {
    if (!seen[s.label]) {
      seen[s.label] = true;
      legend.push({ label: s.label, color: s.color });
    }
  }
  drawLegend(ctx, legend, w);
}

// ---------- data mapping -----------------------------------------------------

function buildCumulativeSeries(records, keyFn, tsFn) {
  const map = {};
  // A3: for the tool-calls chart, collect the error_type breakdown per
  // outcome (so the legend can show "error — TimeoutError×2, …").
  const errTypes = {};
  for (const r of records) {
    const k = keyFn(r);
    (map[k] = map[k] || []).push(tsFn(r));
    if (r.error_type) {
      (errTypes[k] = errTypes[k] || {})[r.error_type] =
        (errTypes[k][r.error_type] || 0) + 1;
    }
  }
  return Object.keys(map).map((k, i) => ({
    label: k,
    color: PALETTE[i % PALETTE.length],
    errorTypes: errTypes[k] || null,
    points: map[k].map((t, i2) => ({ t, v: i2 + 1 })),
  }));
}

// item 4: the net headcount over time per department (accumulating the
// hire/fire deltas: hire +1, fire -1, clamped at 0 — matching the dashboard's
// agents_by_dept). The final value per department = the current active
// headcount (the metric the headcount chips show).
function buildNetHeadcountSeries(events) {
  const map = {};
  for (const e of events) {
    const k = e.department || 'leadership';
    (map[k] = map[k] || []).push({ t: e.ts, d: e.delta || 0 });
  }
  return Object.keys(map).sort().map((k, i) => {
    let v = 0;
    const points = map[k].map((p) => {
      v = Math.max(0, v + p.d);
      return { t: p.t, v };
    });
    return { label: k, color: PALETTE[i % PALETTE.length], points };
  });
}

// The headcount series (from `headcount.jsonl` — the actual source, not the
// agents events). Accumulates the per-department net headcount from each
// entry's `{ts, event, department}` (`event === "fire" ? -1 : 1`, clamped at
// 0). Same shape as `buildNetHeadcountSeries`, but driven by the headcount
// log's `event` field (not the agents events' `delta`).
function buildHeadcountSeries(entries) {
  const map = {};
  for (const e of entries) {
    const k = e.department || 'leadership';
    const d = e.event === 'fire' ? -1 : 1;
    (map[k] = map[k] || []).push({ t: e.ts, d });
  }
  return Object.keys(map).sort().map((k, i) => {
    let v = 0;
    const points = map[k].map((p) => {
      v = Math.max(0, v + p.d);
      return { t: p.t, v };
    });
    return { label: k, color: PALETTE[i % PALETTE.length], points };
  });
}

// item 10: the code volume over time — total lines of code by file type,
// cumulative (accumulating the applied writes' physical line counts,
// segmented by file type).
function buildCodeVolumeSeries(records) {
  const map = {};
  for (const r of records) {
    const k = r.file_type || '.unknown';
    (map[k] = map[k] || []).push({ t: r.ts, d: r.lines || 0 });
  }
  return Object.keys(map).sort().map((k, i) => {
    let v = 0;
    const points = map[k].map((p) => {
      v += p.d;
      return { t: p.t, v };
    });
    return { label: k, color: PALETTE[i % PALETTE.length], points };
  });
}

// A2: distinct color per phase 1–8 (not all beige) so each phase in the
// cycle-duration bars is recognizable at a glance.
const PHASE_COLORS = {
  1: '#4cc9f0',  // intake — cyan
  2: '#f72585',  // mission — magenta
  3: '#ffd166',  // bootstrap — amber
  4: '#80ed99',  // plan — green
  5: '#b388ff',  // staff — purple
  6: '#ff9e64',  // execute — orange
  7: '#06d6a0',  // evaluate — teal
  8: '#ef476f',  // decide — red
};

function buildCycleGroups(cycles) {
  const byCycle = {};
  for (const c of cycles) {
    const cy = byCycle[c.cycle] = byCycle[c.cycle] || {};
    cy[c.phase] = (cy[c.phase] || 0) + (c.duration || 0);
  }
  return Object.keys(byCycle).map(Number).sort((a, b) => a - b)
    .map((cy) => ({
      label: cy === 0 ? 'setup' : 'iter ' + cy,
      segments: Object.keys(byCycle[cy]).map(Number).sort((a, b) => a - b)
        .map((ph) => ({
          label: 'phase ' + ph,
          color: PHASE_COLORS[ph] || '#888',
          v: byCycle[cy][ph],
        })),
    }));
}

// ---------- conversation monitor ---------------------------------------------

function podEntryText(e) {
  if (e.kind === 'agenda') return '[agenda] ' + e.role + ': ' + (e.summary || '');
  if (e.kind === 'speak') {
    return '[speak, r' + e.round + '] ' + e.role + ': ' + (e.summary || '');
  }
  if (e.kind === 'close') return '[close] ' + e.role + ': ' + (e.decision || '');
  if (e.kind === 'carried_decision') return '[carried] ' + (e.decision || '');
  return JSON.stringify(e);
}

// Sticky-bottom: true if the pane is scrolled to (near) its bottom (within
// 30px). Used to decide whether to auto-scroll after a re-render — if the
// user scrolled up to read, we leave their position alone (no yank to the
// bottom on every 1-second tick).
function isAtBottom(el) {
  return (el.scrollHeight - el.scrollTop - el.clientHeight) < 30;
}

function renderMonitor() {
  const pods = (state && state.pods) || [];
  const active = pods.filter((p) => p.status === 'active');
  const closed = pods.filter((p) => p.status === 'closed');

  const pane = $('active-pod');
  if (!active.length) {
    pane.textContent = 'no active pod';
    pane.classList.remove('busy');
    return;
  }
  // A1: show the most recently updated active pod (not the first by id) so the
// pane follows the pod that's actually working right now.
  const p = active.slice().sort((a, b) => (b.updated || 0) - (a.updated || 0))[0];
  pane.classList.add('busy');
  const stick = isAtBottom(pane);  // captured BEFORE the rebuild
  pane.innerHTML = '';
  const head = document.createElement('div');
  head.className = 'pod-head';
  head.textContent = 'pod ' + p.id;
  pane.appendChild(head);
  for (const e of p.entries) {
    const div = document.createElement('div');
    div.className = 'pod-entry';
    div.textContent = podEntryText(e);
    pane.appendChild(div);
  }
  // Only snap to the bottom if the user was already there; if they scrolled
  // up to read, leave their position alone.
  if (stick) pane.scrollTop = pane.scrollHeight;
}

function renderPodList() {
  const list = $('pod-list');
  const closed = ((state && state.pods) || []).filter(
    (p) => p.status === 'closed');
  list.innerHTML = '';
  for (const p of closed.slice(-10).reverse()) {
    const li = document.createElement('li');
    const det = document.createElement('details');
    det.open = expandedPods.has(p.id);
    det.addEventListener('toggle', () => {
      if (det.open) expandedPods.add(p.id);
      else expandedPods.delete(p.id);
    });
    const sum = document.createElement('summary');
    const closeE = p.entries.find((e) => e.kind === 'close');
    sum.textContent = 'pod ' + p.id
      + (closeE ? ' — ' + (closeE.decision || '').slice(0, 80) : '');
    det.appendChild(sum);
    const body = document.createElement('div');
    body.className = 'pod-body';
    for (const e of p.entries) {
      const div = document.createElement('div');
      div.className = 'pod-entry';
      div.textContent = podEntryText(e);
      body.appendChild(div);
    }
    det.appendChild(body);
    li.appendChild(det);
    list.appendChild(li);
  }
}

/* Live "model stream" window: the 2-slot ring (current + previous model
 * call). Each segment is headed by role (pod-window naming) + model, and its
 * streamed content is rendered as {model} [kind]: {output} lines that grow
 * live as the SSE pushes each second. */
function renderModelStream() {
  const pane = $('model-stream');
  const segments = (state && state.stream) || [];
  if (!segments.length) {
    pane.textContent = 'no model activity';
    pane.classList.remove('busy');
    return;
  }
  pane.classList.add('busy');
  const stick = isAtBottom(pane);  // captured BEFORE the rebuild
  pane.innerHTML = '';
  for (const seg of segments) {
    const head = document.createElement('div');
    head.className = 'stream-head';
    // The segment is headed by the role's full label (id · sub_architype ·
    // (personality) · department) + the reasoning level actually used
    // (HIGH/MEDIUM/LOW) — NOT the model name (all roles share the same
    // backbone, so it carries no useful info).
    const label = seg.label || seg.role;
    const reasoning = seg.reasoning ? ' · ' + seg.reasoning : '';
    head.textContent = label + reasoning;
    pane.appendChild(head);
    for (const kind of ['thinking', 'content', 'tool_call']) {
      const text = (seg.kinds && seg.kinds[kind]) || '';
      if (!text) continue;
      // A7: skip whitespace-only content (tools mode emits empty/whitespace
      // [content] lines).
      if (kind === 'content' && text.trim() === '') continue;
      if (kind === 'tool_call') {
        // A7: render tool_call as a collapsed (expandable) JSON block (the
        // raw JSON is noisy; the user can expand it to inspect).
        const details = document.createElement('details');
        details.className = 'stream-toolcall';
        const summary = document.createElement('summary');
        // The model name is no longer rendered in the window (all roles share
        // the same backbone, so it carries no useful info) — the segment head
        // already identifies the role + reasoning level.
        summary.textContent = '[tool_call]';
        details.appendChild(summary);
        const pre = document.createElement('pre');
        pre.className = 'stream-line stream-tool_call';
        pre.textContent = text;
        details.appendChild(pre);
        pane.appendChild(details);
      } else {
        const div = document.createElement('div');
        div.className = 'stream-line stream-' + kind;
        div.textContent = '[' + kind + ']: ' + text;
        pane.appendChild(div);
      }
    }
  }
  // Only snap to the bottom if the user was already there (within 30px); if
  // they scrolled up to read the stream, leave their position alone.
  if (stick) pane.scrollTop = pane.scrollHeight;
}

// ---------- render -------------------------------------------------------------

/* Sub-renderer + memoization per panel.

   Every panel is a sub-renderer (a function that draws ONE panel from the
   snapshot data). `renderPanel` memoizes each panel per data change: a panel
   re-renders only when its input data changes (the "data key" is a stable
   serialization of the panel's input). A panel whose data key is unchanged
   since the last render is SKIPPED — so the 1-second SSE tick does not trigger
   a redundant re-render of every panel (only the panels whose data actually
   changed are redrawn). This is the "sub-renderer per panel, memoized per
   data change" structure (the panels are data-bound: each renders from the
   snapshot data, never from hard-coded values). */
const _panelKeys = {};
function renderPanel(name, data, renderFn) {
  const key = JSON.stringify(data);
  if (_panelKeys[name] === key) return;  // unchanged since last render: skip
  _panelKeys[name] = key;
  renderFn();
}

/* Chart sub-renderers — each draws ONE chart from the snapshot data (the chart
 * drawing was previously inlined in render(); it is now a sub-renderer per
 * panel so each chart is independently memoized). */
function renderAgentsChart() {
  // item 4: the current active headcount per department as the primary series
  // (the net headcount over time — the final value per department = the
  // current headcount the headcount chips show). This answers "how large is
  // the org, and which departments make up a majority of the headcount".
  // Built from `headcount.jsonl` (the actual source), not the agents events.
  drawTimeSeries(
    $('chart-agents'),
    buildHeadcountSeries(state.headcount || []),
    true, 'no hires yet');
}

function renderLevelsChart() {
  // Role hierarchy levels: the cumulative hire/fire series (by level).
  drawTimeSeries(
    $('chart-levels'),
    buildCumulativeSeries(
      state.agents.level_events, (e) => e.level, (e) => e.ts),
    true, 'no hires yet');
}

function renderEditsChart() {
  // item 10: code volume over time — total lines of code by file type,
  // cumulative (replacing the edit-attempts chart).
  drawTimeSeries(
    $('chart-edits'),
    buildCodeVolumeSeries(state.code_volume || []),
    true, 'no code volume yet');
}

function renderToolsChart() {
  // A3: keep the outcome segmentation AND add a department split (who is
  // calling) — the tool-calls chart shows both series.
  drawTimeSeries(
    $('chart-tools'),
    buildCumulativeSeries(
      state.tool_calls, (e) => e.outcome || 'unknown', (e) => e.ts).concat(
      buildCumulativeSeries(
        state.tool_calls, (e) => e.department || 'unknown', (e) => e.ts)),
    true);
}

function renderCyclesChart() {
  drawBars($('chart-cycles'), buildCycleGroups(state.cycles));
}

function renderErrorsChart() {
  // A6: error mix over time — the tool-call error_type breakdown.
  drawTimeSeries(
    $('chart-errors'),
    buildCumulativeSeries(
      state.tool_calls.filter((e) => e.error_type),
      (e) => e.error_type, (e) => e.ts),
    true, 'no errors yet');
}

// Role hierarchy levels (Leader/Head/Manager/IC): the current counts per
// level (the snapshot's agents.by_level) as chips + the roster
// (agents.roles) with a level badge per role (fired roles are marked).
function renderLevelChips() {
  const chips = $('level-chips');
  const roster = $('role-roster');
  if (!chips || !roster || !state) return;
  const byLevel = state.agents.by_level || {};
  chips.innerHTML = ['Leader', 'Head', 'Manager', 'IC'].map(
    (l) => l + ' ' + (byLevel[l] || 0)).join(' · ');
  const roles = state.agents.roles || [];
  if (!roles.length) {
    roster.innerHTML =
      '<div class="roster-empty">no roles in the org chart yet</div>';
    return;
  }
  roster.innerHTML = roles.map((r) =>
    '<div class="roster-row">' +
    '<span class="level-badge level-' + String(r.level).toLowerCase() +
    '">' + r.level + '</span> ' +
    '<span class="roster-id">' + r.id + '</span> ' +
    '<span class="roster-dept">' + (r.department || '') + '</span> ' +
    (r.status !== 'active'
      ? '<span class="roster-fired">' + r.status + '</span>' : '') +
    '</div>').join('');
}

// A5: render the current headcount per department as number chips (the
// snapshot's agents.by_department is never rendered elsewhere).
function renderHeadcountChips() {
  const el = $('headcount-chips');
  if (!el || !state) return;
  // Compute the current total + per-department headcount from
  // `headcount.jsonl` (the latest accumulation of the hire/fire deltas — the
  // actual source), not the agents snapshot's `by_department`.
  const byDept = {};
  for (const e of (state.headcount || [])) {
    const k = e.department || 'leadership';
    const d = e.event === 'fire' ? -1 : 1;
    byDept[k] = Math.max(0, (byDept[k] || 0) + d);
  }
  let total = 0;
  for (const n of Object.values(byDept)) total += n;
  const depts = Object.keys(byDept).sort();
  el.innerHTML = 'total ' + total + ' · ' + depts.map(
    (d) => d + ' ' + byDept[d]).join(' · ');
}

// A6: render the halt events (Safety / Morality) as a list (the halt pane).
function renderHaltList() {
  const el = $('halt-list');
  if (!el || !state) return;
  const events = state.halt_events || [];
  if (!events.length) {
    el.innerHTML = '<li class="halt-empty">no halt events</li>';
    return;
  }
  el.innerHTML = events.slice(-10).reverse().map((e) =>
    '<li class="halt-item">' +
    '<span class="halt-ts">' + new Date(e.ts * 1000).toLocaleTimeString() +
    '</span> ' +
    '<span class="halt-kind">' + (e.kind || 'halt') + '</span> ' +
    '<span class="halt-reason">' + (e.reason || '') + '</span>' +
    '</li>').join('');
}

// render the efficiency panel (per-role / per-department invoke
// time). The snapshot's `efficiency` is a cumulative snapshot (the latest line
// of history/efficiency.jsonl) with `per_role` and `per_department` maps
// (role/department -> seconds). Rendered as two columns of sorted rows
// (highest time first).
function renderEfficiencyPanel() {
  const el = $('efficiency-panel');
  if (!el || !state) return;
  const eff = state.efficiency;
  if (!eff || (!eff.per_role && !eff.per_department)) {
    el.textContent = 'no efficiency data yet';
    el.classList.remove('busy');
    return;
  }
  el.classList.add('busy');
  const rows = (m) => Object.keys(m || {})
    .map((k) => ({ k, v: m[k] }))
    .sort((a, b) => b.v - a.v);
  const roleRows = rows(eff.per_role);
  const deptRows = rows(eff.per_department);
  const fmt = (v) => (v < 60 ? Math.round(v * 10) / 10 + 's'
                              : Math.floor(v / 60) + 'm ' + Math.round(v % 60) + 's');
  const col = (title, list) => {
    const body = list.length
      ? list.map((r) => '<div class="eff-row"><span class="eff-key">' + r.k +
          '</span><span class="eff-val">' + fmt(r.v) + '</span></div>').join('')
      : '<div class="eff-empty">none</div>';
    return '<div class="eff-col"><h3 class="eff-title">' + title + '</h3>' + body +
      '</div>';
  };
  const total = eff.total_time ? '<div class="eff-total">total ' +
    fmt(eff.total_time) + ' · ' + (eff.total_calls || 0) + ' invokes</div>' : '';
  el.innerHTML = total +
    '<div class="eff-cols">' +
    col('per-role', roleRows) +
    col('per-department', deptRows) +
    '</div>';
}

// render the per-iteration efficiency metrics (the Phase 3-6 loop
// metrics). The snapshot's `efficiency_metrics` is the latest per-iteration
// snapshot (the last line of history/efficiency_metrics.jsonl) with T_total,
// T_p, T_dept, T_role, H_peak, C, N_created, M_satisfaction, E,
// EFFICIENCY_FLOOR.
function renderLoopMetricsPanel() {
  const el = $('loop-metrics-panel');
  if (!el || !state) return;
  const m = state.efficiency_metrics;
  if (!m) {
    el.textContent = 'no loop metrics yet';
    el.classList.remove('busy');
    return;
  }
  el.classList.add('busy');
  const fmt = (v) => (v < 60 ? Math.round(v * 10) / 10 + 's'
                              : Math.floor(v / 60) + 'm ' + Math.round(v % 60) + 's');
  const parts = [];
  parts.push('<div class="eff-total">cycle ' + (m.cycle ?? '?') +
    ' · T_total ' + fmt(m.T_total || 0) +
    ' · H_peak ' + (m.H_peak || 0) +
    ' · C ' + fmt(m.C || 0) +
    ' · N_created ' + (m.N_created || 0) + '</div>');
  if (m.T_p && Object.keys(m.T_p).length) {
    const tps = Object.keys(m.T_p).map((p) => 'p' + p + ' ' + fmt(m.T_p[p]))
      .join(' · ');
    parts.push('<div class="eff-row"><span class="eff-key">per-phase</span>' +
      '<span class="eff-val">' + tps + '</span></div>');
  }
  parts.push('<div class="eff-row"><span class="eff-key">M_satisfaction</span>' +
    '<span class="eff-val">' + (m.M_satisfaction || 0).toFixed(2) + '</span></div>');
  parts.push('<div class="eff-row"><span class="eff-key">E</span>' +
    '<span class="eff-val">' + (m.E || 0).toFixed(3) +
    ' (floor ' + (m.EFFICIENCY_FLOOR || 0.4) +
    (m.below_floor ? ' — BELOW FLOOR' : '') + ')</span></div>');
  el.innerHTML = parts.join('');
}

// item 6: the org-flow panel — the 8-phase flow (stepper), the current phase
// (highlighted), the current cycle, and the active roles in the current phase
// (their task = the pod agenda / decomposition objective, matched by role).
function renderOrgFlowPanel() {
  const el = $('org-flow');
  if (!el || !state) return;
  const flow = state.org_flow;
  if (!flow || !flow.current_phase) {
    el.textContent = 'no phase activity yet';
    el.classList.remove('busy');
    return;
  }
  el.classList.add('busy');
  const phases = flow.phases || [1, 2, 3, 4, 5, 6, 7, 8];
  const current = flow.current_phase;
  const cycle = flow.current_cycle || 0;
  // The active pod's agenda (the roles + their task, matched by role) — the
  // task source (your answer 6: the pod agenda / decomposition objective).
  const pods = state.pods || [];
  const activePod = pods
    .filter((p) => p.status === 'active')
    .sort((a, b) => (b.updated || 0) - (a.updated || 0))[0];
  const agenda = {};
  if (activePod) {
    for (const e of activePod.entries) {
      if (e.kind === 'agenda' && e.role) agenda[e.role] = e.summary || '';
    }
  }
  // The stepper: each phase as a step (done < current, current highlighted,
  // upcoming > current).
  const steps = phases.map((ph) => {
    const cls = ph < current ? 'done' : (ph === current ? 'current' : 'todo');
    return '<span class="org-step org-step-' + cls + '">' + ph + '</span>';
  }).join('<span class="org-step-sep">→</span>');
  // The active roles in the current phase (with their task from the agenda).
  const roles = flow.active_roles || [];
  const roleRows = roles.length
    ? roles.map((r) =>
        '<div class="org-role-row">' +
        '<span class="org-role-id">' + r.role + '</span>' +
        (r.department
          ? '<span class="org-role-dept">' + r.department + '</span>' : '') +
        '<span class="org-role-task">' +
        (agenda[r.role] || '(task from the pod agenda)') + '</span>' +
        '</div>').join('')
    : '<div class="org-empty">no active roles in phase ' + current + ' yet</div>';
  // The cycle-level summaries (one row per cycle, with the per-iteration
  // wall-clock duration + the per-phase breakdown) — the org-flow panel's
  // cycle history (one row per cycle, not one row per phase as cycles.jsonl
  // does, which made the flow look like it had too many cycles).
  const cycleRows = (flow.cycles || []).slice().reverse().map((c) =>
    '<div class="org-cycle-row">' +
    '<span class="org-cycle-id">cycle ' + c.cycle + '</span>' +
    (c.duration != null
      ? '<span class="org-cycle-dur">' + c.duration + 's</span>' : '') +
    (c.headcount != null
      ? '<span class="org-cycle-hc">' + c.headcount + ' roles</span>' : '') +
    '</div>').join('');
  el.innerHTML =
    '<div class="org-stepper">' + steps + '</div>' +
    '<div class="org-cycle">cycle ' + cycle + ' · phase ' + current + '</div>' +
    (cycleRows ? '<div class="org-cycle-history">' + cycleRows + '</div>' : '') +
    '<div class="org-roles">' + roleRows + '</div>';
}

// A6: staleness gauge — seconds since the last stream chunk (the model has
// been silent for a while). Warns past a threshold (60s: the model is
// probably stuck or the stream is broken).
function renderStaleness() {
  const el = $('staleness');
  if (!el || !state) return;
  if (!state.last_stream_ts) {
    el.textContent = '';
    el.className = 'staleness';
    return;
  }
  const secs = Math.max(0, (state.ts - state.last_stream_ts));
  el.textContent = 'stream ' + Math.round(secs) + 's ago';
  el.className = 'staleness' + (secs > 60 ? ' stale' : '');
}

function render() {
  if (!state) return;
  // A6: staleness gauge — seconds since the last stream chunk, warning past
  // a threshold (the model has been silent for a while).
  renderPanel('staleness', [state.last_stream_ts, state.ts], renderStaleness);
  // A5: current headcount per department (number chips) — built from
  // `headcount.jsonl` (the actual source).
  renderPanel('headcount', state.headcount, renderHeadcountChips);
  // item 4: the headcount chart (the net headcount over time per department)
  // — built from `headcount.jsonl` (the actual source).
  renderPanel('agents-chart', state.headcount, renderAgentsChart);
  // Role hierarchy levels: the current counts per level (chips + roster).
  renderPanel('level-chips',
    [state.agents.by_level, state.agents.roles], renderLevelChips);
  // Role hierarchy levels: the cumulative hire/fire series (by level).
  renderPanel('levels-chart', state.agents.level_events, renderLevelsChart);
  // item 6: the org-flow panel (the 8-phase flow + current phase + active
  // roles, data-bound to state.org_flow + the active pod's agenda).
  renderPanel('org-flow', [state.org_flow, state.pods], renderOrgFlowPanel);
  // item 10: the code-volume chart (lines by file type, cumulative).
  renderPanel('edits-chart', state.code_volume || [], renderEditsChart);
  // The tool-calls chart (by outcome + by department).
  renderPanel('tools-chart', state.tool_calls, renderToolsChart);
  // The cycle-duration bars (phase durations per iteration).
  renderPanel('cycles-chart', state.cycles, renderCyclesChart);
  // The error-mix chart (tool-call error_type breakdown).
  renderPanel('errors-chart', state.tool_calls, renderErrorsChart);
  renderPanel('monitor', state.pods, renderMonitor);
  // The historical pod list (last-N closed pods, expandable).
  renderPanel('pod-list', state.pods, renderPodList);
  // A6: the halt events (Safety / Morality) — the EventPanel (data-bound to
  // state.halt_events).
  renderPanel('halt-list', state.halt_events, renderHaltList);
  // The efficiency panel (per-role / per-department invoke time) — the
  // EfficiencyPanel (data-bound to state.efficiency).
  renderPanel('efficiency-panel', state.efficiency, renderEfficiencyPanel);
  // The per-iteration efficiency metrics (the Phase 3-6 loop metrics).
  renderPanel('loop-metrics-panel', state.efficiency_metrics,
    renderLoopMetricsPanel);
  // The live "model stream" window (current + previous model call).
  renderPanel('model-stream', state.stream, renderModelStream);
}

connect();
