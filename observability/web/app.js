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
    if (x > w - 60) break;
    ctx.fillStyle = s.color;
    ctx.fillRect(x, 2, 8, 8);
    ctx.fillStyle = '#9aa5bd';
    ctx.fillText(s.label, x + 11, 10);
    x += 11 + ctx.measureText(s.label).width + 12;
  }
}

/* Draw cumulative time series — stacked areas or overlaid lines.
 * series: [{label, color, points: [{t, v}]}] with v cumulative. */
function drawTimeSeries(canvas, series, stacked) {
  stacked = stacked !== false;
  const bounds = timeBounds(series);
  if (!bounds) return drawEmpty(canvas);
  const { ctx, w, h } = prepCanvas(canvas);
  const padL = 34, padB = 20, padT = 14, padR = 8;
  const iw = w - padL - padR, ih = h - padT - padB;
  const { t0, t1 } = bounds;
  const X = (t) => padL + (t - t0) / (t1 - t0) * iw;

  const times = new Set();
  for (const s of series) for (const p of s.points) times.add(p.t);
  const ts = Array.from(times).sort((a, b) => a - b);
  const vals = series.map((s) => ts.map((t) => valueAt(s.points, t)));

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
    const top = ts.map((t, i) => base[i] + vals[si][i]);
    if (stacked) {
      ctx.beginPath();
      ctx.moveTo(X(ts[0]), Y(base[0]));
      top.forEach((v, i) => ctx.lineTo(X(ts[i]), Y(v)));
      for (let i = ts.length - 1; i >= 0; i--) {
        ctx.lineTo(X(ts[i]), Y(base[i]));
      }
      ctx.closePath();
      ctx.globalAlpha = 0.5;
      ctx.fillStyle = s.color;
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.beginPath();
      top.forEach((v, i) => {
        if (i) ctx.lineTo(X(ts[i]), Y(v));
        else ctx.moveTo(X(ts[i]), Y(v));
      });
      ctx.strokeStyle = s.color;
      ctx.lineWidth = 1.5;
      ctx.stroke();
    } else {
      ctx.beginPath();
      vals[si].forEach((v, i) => {
        if (i) ctx.lineTo(X(ts[i]), Y(v));
        else ctx.moveTo(X(ts[i]), Y(v));
      });
      ctx.strokeStyle = s.color;
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }
    base = top;
  });
  drawLegend(ctx, series, w);
}

/* Bars: groups [{label, segments: [{label, color, v}]}] (stacked segments). */
function drawBars(canvas, groups) {
  if (!groups.length) return drawEmpty(canvas);
  const { ctx, w, h } = prepCanvas(canvas);
  const padL = 34, padB = 20, padT = 14, padR = 8;
  const iw = w - padL - padR, ih = h - padT - padB;
  const maxV = Math.max(
    1, ...groups.map((g) => g.segments.reduce((a, s) => a + s.v, 0)));
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
  groups.forEach((g, i) => {
    const cx = padL + iw * (i + 0.5) / groups.length;
    let y0 = 0;
    for (const s of g.segments) {
      const y1 = y0 + s.v;
      ctx.fillStyle = s.color;
      ctx.fillRect(cx - bw / 2, Y(y1), bw, Math.max(0.5, Y(y0) - Y(y1)));
      y0 = y1;
    }
    ctx.fillStyle = '#9aa5bd';
    ctx.textAlign = 'center';
    ctx.fillText(g.label, cx, h - 6);
  });
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
  for (const r of records) {
    const k = keyFn(r);
    (map[k] = map[k] || []).push(tsFn(r));
  }
  return Object.keys(map).map((k, i) => ({
    label: k,
    color: PALETTE[i % PALETTE.length],
    points: map[k].map((t, i2) => ({ t, v: i2 + 1 })),
  }));
}

const PHASE_COLORS = { 4: '#4cc9f0', 5: '#f72585', 6: '#ffd166' };

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
  const p = active[0];
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
    head.textContent = seg.role + ' · ' + seg.model;
    pane.appendChild(head);
    for (const kind of ['thinking', 'content', 'tool_call']) {
      const text = (seg.kinds && seg.kinds[kind]) || '';
      if (!text) continue;
      const div = document.createElement('div');
      div.className = 'stream-line stream-' + kind;
      div.textContent = seg.model + ' [' + kind + ']: ' + text;
      pane.appendChild(div);
    }
  }
  // Only snap to the bottom if the user was already there (within 30px); if
  // they scrolled up to read the stream, leave their position alone.
  if (stick) pane.scrollTop = pane.scrollHeight;
}

// ---------- render -------------------------------------------------------------

function render() {
  if (!state) return;
  drawTimeSeries(
    $('chart-agents'),
    buildCumulativeSeries(state.agents.events, (e) => e.department, (e) => e.ts),
    true);
  drawTimeSeries(
    $('chart-edits'),
    buildCumulativeSeries(
      state.code_edits, (e) => (e.ok ? 'applied' : 'refused'), (e) => e.ts),
    false);
  drawTimeSeries(
    $('chart-tools'),
    buildCumulativeSeries(
      state.tool_calls, (e) => e.outcome || 'unknown', (e) => e.ts),
    true);
  drawBars($('chart-cycles'), buildCycleGroups(state.cycles));
  renderMonitor();
  renderPodList();
  renderModelStream();
}

connect();
