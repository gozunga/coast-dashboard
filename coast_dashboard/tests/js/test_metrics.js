/* Copyright 2026 Gozunga and Coast contributors. Licensed under Apache-2.0. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('coast_dashboard/static/coast_dashboard/metrics.js', 'utf8');
const globalEvents = {};
const apiContext = {AbortController, Date, Map, console, setInterval, clearInterval, setTimeout, clearTimeout,
  addEventListener: (event, fn) => { globalEvents[event] = fn; },
  removeEventListener: event => { delete globalEvents[event]; }};
vm.runInNewContext(source, apiContext);
const api = apiContext.coastMetrics;
class Node {
  constructor(tag, doc) {
    this.tag = tag; this.ownerDocument = doc; this.children = []; this.attrs = {};
    this.style = {}; this.dataset = {}; this.events = {}; this.isConnected = true;
    this.visible = true;
  }
  set textContent(value) { this.text = value; this.children = []; }
  get textContent() { return (this.text || '') + this.children.map(c => c.textContent).join(''); }
  appendChild(node) { this.children.push(node); return node; }
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener(event, fn) { this.events[event] = fn; }
  getClientRects() { return this.visible ? [1] : []; }
  all(tag) { return this.children.flatMap(c => (c.tag === tag ? [c] : []).concat(c.all(tag))); }
}
const documentEvents = {};
const doc = {hidden: false, addEventListener: (event, fn) => { documentEvents[event] = fn; },
  removeEventListener: event => { delete documentEvents[event]; }, createElement: tag => new Node(tag, doc),
  createElementNS: (ns, tag) => new Node(tag, doc)};
const now = Date.parse('2026-10-19T05:00:30Z');
const point = (cpu, mem, limit, timestamp = '2026-10-19T05:00:00Z') =>
  ({timestamp, cpu_percent: cpu, memory_bytes: mem, memory_limit_bytes: limit});
const metrics = {step_seconds: 30, containers: [
  {name: '<script>web</script>', points: [point(12.5, 104857600, 536870912),
    point(25, 209715200, 536870912, '2026-10-19T05:00:30Z')]},
  {name: 'worker', points: [point(20, 52428800, null)]},
  {name: 'waiting', points: []}
]};
const host = new Node('div', doc);
assert.equal(api.bytes(104857600), '100.0 MiB');
assert.equal(api.bytes(null), 'no limit');
assert.equal(api.bytes(0), '0 B');
assert.equal(api.render(doc, host, {containers: []}, '1h', now), false);
assert.equal(api.render(doc, host, {containers: [{name: 'empty', points: []}]}, '1h', now), false);
for (const range of ['15m', '1h', '6h', '24h', '7d', '30d']) {
  assert.equal(api.render(doc, host, metrics, range, now), true);
  assert.equal(host.all('svg').length, 2);
  assert.equal(host.all('table').length, 1);
  assert.ok(host.textContent.includes('25.0%'));
  assert.ok(host.textContent.includes('200.0 MiB / 512.0 MiB'));
  assert.ok(host.textContent.includes('50.0 MiB / no limit'));
  assert.equal(host.all('script').length, 0);
  assert.ok(host.all('path').some(p => p.attrs['stroke-dasharray'] === '6 4'));
  assert.ok(host.all('text').some(p => p.textContent.includes('UTC')));
  assert.ok(host.all('path').every(p => !/NaN|Infinity/.test(p.attrs.d)));
}
// Stacking adds containers at each sampling bucket, including samples with clock offsets.
const chartHost = new Node('div', doc);
const stacked = {step_seconds: 30, containers: [
  {name: 'first', points: [point(80, 10, null)]},
  {name: 'second', points: [point(70, 20, null, '2026-10-19T05:00:02Z')]}
]};
api.render(doc, chartHost, stacked, '1h', now);
const cpu = chartHost.all('svg')[0];
const dots = cpu.all('circle');
assert.equal(dots.length, 2);
assert.equal(dots[0].attrs.cx, dots[1].attrs.cx);
assert.equal(dots[1].attrs.cy, 20); // 150% total; CPU must not be clamped to 100%.
assert.equal(chartHost.all('path').filter(p => p.attrs['stroke-dasharray']).length, 0);
const gap = {step_seconds: 30, containers: [{name: 'web', points: [
  point(10, 100, 200, '2026-10-19T04:58:00Z'),
  point(20, 200, null, '2026-10-19T05:00:00Z')]}]};
api.render(doc, chartHost, gap, '15m', now);
assert.equal(chartHost.all('svg')[0].all('path').length, 2); // No area across missing samples.
const limitLine = chartHost.all('path').find(p => p.attrs['stroke-dasharray']);
assert.ok(/M.+L/.test(limitLine.attrs.d)); // A single limit sample remains visible.
// Long ranges use the API's coarser step without changing current table values.
for (const step of [300, 3600]) {
  api.render(doc, chartHost, {...stacked, step_seconds: step}, '30d', now);
  assert.ok(chartHost.all('path').every(p => !/NaN/.test(p.attrs.d)));
  assert.ok(chartHost.textContent.includes('70.0%'));
}
const flush = () => new Promise(setImmediate);
(async () => {
  let tabSync;
  apiContext.jQuery = () => ({on: (events, fn) => { tabSync = fn; },
    off: (events, fn) => { assert.equal(fn, tabSync); tabSync = undefined; }});
  let timeoutFn;
  apiContext.setTimeout = (fn, ms) => { assert.equal(ms, 25000); timeoutFn = fn; return 8; };
  apiContext.clearTimeout = id => { assert.equal(id, 8); };
  let poll, cleared = 0, calls = [], response = {ok: true, json: async () => ({metrics})};
  apiContext.setInterval = (fn, ms) => { assert.equal(ms, 30000); poll = fn; return 5; };
  apiContext.clearInterval = id => { assert.equal(id, 5); cleared++; };
  const root = new Node('root', doc), select = new Node('select', doc);
  select.value = '1h';
  const status = new Node('status', doc), data = new Node('data', doc);
  root.dataset.url = '/metrics/';
  root.querySelector = name => ({'.coast-metrics-range': select,
    '.coast-metrics-status': status, '.coast-metrics-data': data})[name];
  const fetch = async (url, options) => { calls.push({url, options}); return response; };
  api.bind(root, {fetch, now: () => now});
  await flush();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/metrics/?range=1h');
  assert.equal(calls[0].options.credentials, 'same-origin');
  assert.equal(calls[0].options.cache, 'no-store');
  assert.equal(data.all('svg').length, 2);
  poll(); await flush(); assert.equal(calls.length, 2);
  root.visible = false; poll(); await flush(); assert.equal(calls.length, 2);
  root.visible = true; tabSync(); await flush(); assert.equal(calls.length, 3);
  doc.hidden = true; poll(); await flush(); assert.equal(calls.length, 3);
  doc.hidden = false;
  for (const range of ['15m', '6h', '24h', '7d', '30d']) {
    select.value = range; select.events.change(); await flush();
    assert.equal(calls[calls.length - 1].url, '/metrics/?range=' + range);
  }
  response = {ok: true, json: async () => ({metrics: {containers: []}})};
  poll(); await flush();
  assert.equal(status.textContent, 'No data yet - samples arrive every 30 seconds');
  assert.equal(data.children.length, 0);
  response = {ok: false}; poll(); await flush();
  assert.ok(status.textContent.includes('Unable to retrieve metrics'));
  response = {ok: true, json: async () => { throw new Error('invalid json'); }};
  poll(); await flush(); assert.ok(status.textContent.includes('Unable to retrieve metrics'));
  response = {ok: true, json: async () => ({metrics})};
  poll(); await flush(); assert.equal(data.all('svg').length, 2);
  // A slow response must not overwrite the result of a later range selection.
  let resolveOld;
  response = new Promise(resolve => { resolveOld = resolve; });
  poll(); await flush();
  const count = calls.length; poll(); await flush(); assert.equal(calls.length, count);
  response = {ok: true, json: async () => ({metrics: {containers: []}})};
  select.value = '15m'; select.events.change(); await flush();
  assert.equal(calls[count - 1].options.signal.aborted, true);
  resolveOld({ok: true, json: async () => ({metrics})}); await flush();
  assert.equal(data.children.length, 0);
  // A hung request times out and permits the next scheduled retry.
  response = new Promise(() => {}); poll(); await flush();
  timeoutFn(); assert.ok(status.textContent.includes('Unable to retrieve metrics'));
  response = {ok: true, json: async () => ({metrics})};
  poll(); await flush(); assert.equal(data.all('svg').length, 2);
  doc.hidden = true; documentEvents.visibilitychange();
  const beforeHidden = calls.length; poll(); await flush(); assert.equal(calls.length, beforeHidden);
  doc.hidden = false; documentEvents.visibilitychange(); await flush();
  assert.equal(calls.length, beforeHidden + 1);
  root.isConnected = false; poll(); assert.equal(cleared, 1);
  assert.equal(documentEvents.visibilitychange, undefined);
  assert.equal(globalEvents.pagehide, undefined);
  assert.equal(tabSync, undefined);
  console.log('Metrics rendering, range, polling, race, empty, and error tests passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
