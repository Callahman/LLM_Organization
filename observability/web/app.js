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
function drawTimeSeries(canvas, series, stacked, emptyMsg, hoverRecords) {
  stacked = stacked !== false;
  const bounds = timeBounds(series);
  // A4: a custom empty message (e.g. "no edit attempts yet" for the
  // code-edits chart — a missing file is not "all refused").
  if (!bounds) return drawEmpty(canvas, emptyMsg);
  // A4: hover tooltip with the per-edit detail (path + refusal reason) for
  // the code-edits chart (hoverRecords = the raw edit records).
  if (hoverRecords && hoverRecords.length) {
    canvas.onmousemove = (ev) => {
      const last = hoverRecords[hoverRecords.length - 1];
      let tip = $('edit-tooltip');
      if (!tip) {
        tip = document.createElement('div');
        tip.id = 'edit-tooltip';
        tip.className = 'bar-tooltip';
        document.body.appendChild(tip);
      }
      const detail = last.ok
        ? last.path + ' — applied'
        : last.path + ' — refused: ' + (last.error || 'no reason');
      tip.textContent = detail;
      tip.style.display = 'block';
      tip.style.left = (ev.clientX + 12) + 'px';
      tip.style.top = (ev.clientY + 12) + 'px';
    };
    canvas.onmouseleave = () => {
      const tip = $('edit-tooltip');
      if (tip) tip.style.display = 'none';
    };
  }
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

// A2: distinct color per phase 1–6 (not all beige) so each phase in the
// cycle-duration bars is recognizable at a glance.
const PHASE_COLORS = {
  1: '#4cc9f0',  // intake — cyan
  2: '#f72585',  // mission — magenta
  3: '#ffd166',  // bootstrap — amber
  4: '#80ed99',  // dispatch — green
  5: '#b388ff',  // synthesis — purple
  6: '#ff9e64',  // evaluation — orange
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
    head.textContent = seg.role + ' · ' + seg.model;
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
        summary.textContent = seg.model + ' [tool_call]';
        details.appendChild(summary);
        const pre = document.createElement('pre');
        pre.className = 'stream-line stream-tool_call';
        pre.textContent = text;
        details.appendChild(pre);
        pane.appendChild(details);
      } else {
        const div = document.createElement('div');
        div.className = 'stream-line stream-' + kind;
        div.textContent = seg.model + ' [' + kind + ']: ' + text;
        pane.appendChild(div);
      }
    }
  }
  // Only snap to the bottom if the user was already there (within 30px); if
  // they scrolled up to read the stream, leave their position alone.
  if (stick) pane.scrollTop = pane.scrollHeight;
}

// ---------- render -------------------------------------------------------------

// A5: render the current headcount per department as number chips (the
// snapshot's agents.by_department is never rendered elsewhere).
function renderHeadcountChips() {
  const el = $('headcount-chips');
  if (!el || !state) return;
  const byDept = state.agents.by_department || {};
  const depts = Object.keys(byDept).sort();
  el.innerHTML = 'total ' + state.agents.total + ' · ' + depts.map(
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

// Story 22: render the efficiency panel (per-role / per-department invoke
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
  renderStaleness();
  // A5: current headcount per department (number chips) — the snapshot's
  // agents.by_department is never rendered elsewhere, so it goes here.
  renderHeadcountChips();
  // A5: the agents chart shows the cumulative hire/fire series (by
  // department) AND the activity-over-time series (model calls per dept from
  // tool_calls) — so the current headcount, the activity, and the hires are
  // all visible.
  drawTimeSeries(
    $('chart-agents'),
    buildCumulativeSeries(state.agents.events, (e) => e.department, (e) => e.ts)
      .concat(buildCumulativeSeries(
        state.tool_calls, (e) => e.department || 'unknown', (e) => e.ts)),
    true);
  // A4: segment the code-edits chart by department (like agents-over-time),
// with applied/refused within each department (applied solid, refused
// striped). The keyFn combines department + outcome so each department's
// applied/refused are distinct series. The empty state reads "no edit
// attempts yet" (a missing file is not "all refused"), and hovering shows the
// latest edit's path + refusal reason.
  drawTimeSeries(
    $('chart-edits'),
    buildCumulativeSeries(
      state.code_edits,
      (e) => (e.department || 'unknown') + ' ' + (e.ok ? 'applied' : 'refused'),
      (e) => e.ts),
    false, 'no edit attempts yet', state.code_edits);
  // A3: keep the outcome segmentation AND add a department split (who is
// calling) — the tool-calls chart shows both series (outcome first, then
// department) so failures are legible (type + red fill) and the caller is
// visible.
  drawTimeSeries(
    $('chart-tools'),
    buildCumulativeSeries(
      state.tool_calls, (e) => e.outcome || 'unknown', (e) => e.ts).concat(
      buildCumulativeSeries(
        state.tool_calls, (e) => e.department || 'unknown', (e) => e.ts)),
    true);
  drawBars($('chart-cycles'), buildCycleGroups(state.cycles));
  // A6: error mix over time — the tool-call error_type breakdown (timeout,
  // truncation, parse, transport, other) as a stacked series.
  drawTimeSeries(
    $('chart-errors'),
    buildCumulativeSeries(
      state.tool_calls.filter((e) => e.error_type),
      (e) => e.error_type, (e) => e.ts),
    true, 'no errors yet');
  renderMonitor();
  renderPodList();
  renderHaltList();
  // Story 22: the efficiency panel (per-role / per-department invoke time).
  renderEfficiencyPanel();
  renderModelStream();
}

connect();
