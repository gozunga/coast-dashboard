/* Copyright 2026 Gozunga and Coast contributors. Licensed under Apache-2.0. */
(function (global) {
  'use strict';
  var ranges = {'15m': 900, '1h': 3600, '6h': 21600, '24h': 86400,
    '7d': 604800, '30d': 2592000};
  var colors = ['#006bb6', '#b34c00', '#16823b', '#8246af', '#ad2861', '#40777c'];
  function bytes(value) {
    if (value === null || value === undefined) return 'no limit';
    var units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
    var index = 0;
    while (value >= 1024 && index < units.length - 1) { value /= 1024; index++; }
    return value.toFixed(index ? 1 : 0) + ' ' + units[index];
  }
  function element(doc, tag, text, parent) {
    var node = doc.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (parent) parent.appendChild(node);
    return node;
  }
  function svgNode(doc, tag, attrs, parent, text) {
    var node = doc.createElementNS('http://www.w3.org/2000/svg', tag);
    Object.keys(attrs).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    if (text !== undefined) node.textContent = text;
    parent.appendChild(node);
    return node;
  }
  function chart(doc, parent, containers, field, title, range, now, step) {
    element(doc, 'h4', title, parent);
    var svg = svgNode(doc, 'svg', {viewBox: '0 0 900 240', width: '100%',
      role: 'img', 'aria-label': title + ' by container; time in UTC'}, parent);
    var start = now - ranges[range] * 1000;
    var timeSet = new Set();
    function bucket(timestamp) { return Math.floor(Date.parse(timestamp) / step) * step; }
    containers.forEach(function (c) {
      c.points.forEach(function (p) {
        var t = bucket(p.timestamp);
        if (t >= start && t <= now) timeSet.add(t);
      });
    });
    var times = Array.from(timeSet).sort(function (a, b) { return a - b; });
    var totals = times.map(function () { return 0; });
    var series = containers.map(function (c) {
      var points = new Map(c.points.map(function (p) { return [bucket(p.timestamp), p]; }));
      return times.map(function (t, i) {
        var p = points.get(t);
        var base = totals[i];
        var value = p ? p[field] : 0;
        totals[i] += value;
        return {t: t, base: base, top: totals[i], point: p};
      });
    });
    var max = Math.max.apply(null, [field === 'cpu_percent' ? 100 : 1].concat(totals));
    if (field === 'memory_bytes') containers.forEach(function (c) {
      c.points.forEach(function (p) { max = Math.max(max, p.memory_limit_bytes || 0); });
    });
    function x(t) { return 100 + (t - start) / (now - start) * 780; }
    function y(v) { return 205 - v / max * 185; }
    function coords(p, key) { return x(p.t).toFixed(2) + ',' + y(p[key]).toFixed(2); }
    for (var tick = 0; tick <= 4; tick++) {
      var value = max * tick / 4;
      svgNode(doc, 'line', {x1: 100, x2: 880, y1: y(value), y2: y(value),
        stroke: '#ddd'}, svg);
      svgNode(doc, 'text', {x: 95, y: y(value) + 4, 'text-anchor': 'end',
        'font-size': 12}, svg, field === 'cpu_percent' ? value.toFixed(1) + '%' : bytes(value));
    }
    [start, (start + now) / 2, now].forEach(function (t) {
      svgNode(doc, 'text', {x: x(t), y: 230, 'text-anchor': t === start ? 'start' :
        t === now ? 'end' : 'middle', 'font-size': 12}, svg,
      new Date(t).toISOString().replace('T', ' ').slice(5, 16) + ' UTC');
    });
    series.forEach(function (points, i) {
      if (!points.length) return;
      var color = colors[i % colors.length];
      // Missing samples break the area instead of inventing a zero reading.
      var segments = [], segment = [];
      points.forEach(function (p) {
        if (!p.point || (segment.length && p.t - segment[segment.length - 1].t > step * 1.5)) {
          if (segment.length) segments.push(segment);
          segment = [];
        }
        if (p.point) segment.push(p);
      });
      if (segment.length) segments.push(segment);
      segments.forEach(function (part) {
        var d = 'M' + part.map(function (p) { return coords(p, 'top'); }).join(' L') +
          ' L' + part.slice().reverse().map(function (p) { return coords(p, 'base'); }).join(' L') + ' Z';
        var area = svgNode(doc, 'path', {d: d, fill: color, 'fill-opacity': 0.4,
          stroke: color, 'stroke-width': 1.5}, svg);
        svgNode(doc, 'title', {}, area, containers[i].name);
      });
      segments.forEach(function (part) {
        if (part.length !== 1) return;
        var p = part[0];
        var dot = svgNode(doc, 'circle', {cx: x(p.t), cy: y(p.top), r: 2,
          fill: color}, svg);
        svgNode(doc, 'title', {}, dot, containers[i].name + ': ' +
          (field === 'cpu_percent' ? p.point[field].toFixed(1) + '%' : bytes(p.point[field])) +
          ' at ' + p.point.timestamp);
      });
      if (field === 'memory_bytes') {
        segments.forEach(function (part) {
          var line = '', connected = false;
          part.forEach(function (p) {
            var limit = p.point.memory_limit_bytes;
            if (limit === null) { connected = false; return; }
            line += (connected ? 'L' : 'M') + x(p.t) + ',' + y(limit);
            // Extend a limit through its sampling interval, including a lone sample.
            line += 'L' + x(Math.min(now, p.t + step)) + ',' + y(limit);
            connected = true;
          });
          if (line) {
            var limit = svgNode(doc, 'path', {d: line, fill: 'none', stroke: color,
              'stroke-width': 2, 'stroke-dasharray': '6 4'}, svg);
            svgNode(doc, 'title', {}, limit, containers[i].name + ' memory limit');
          }
        });
      }
    });
    var legend = element(doc, 'p', undefined, parent);
    containers.forEach(function (c, i) {
      var item = element(doc, 'span', '■ ' + c.name + '  ', legend);
      item.style.color = colors[i % colors.length];
      item.style.marginRight = '12px';
    });
    if (field === 'memory_bytes') element(doc, 'p',
      'Dashed lines: each container’s memory limit. Areas: stacked memory used.', parent);
  }
  function render(doc, parent, metrics, range, now) {
    parent.textContent = '';
    var containers = metrics.containers || [];
    if (!containers.some(function (c) { return c.points.length; })) return false;
    chart(doc, parent, containers, 'cpu_percent', 'CPU use (%)', range, now, metrics.step_seconds * 1000);
    chart(doc, parent, containers, 'memory_bytes', 'Memory used', range, now, metrics.step_seconds * 1000);
    var table = element(doc, 'table', undefined, parent);
    table.className = 'table table-striped table-condensed';
    element(doc, 'caption', 'Current container values (latest sample)', table);
    var head = element(doc, 'tr', undefined, element(doc, 'thead', undefined, table));
    ['Container', 'CPU % now', 'Memory used / limit'].forEach(function (label) {
      element(doc, 'th', label, head);
    });
    var body = element(doc, 'tbody', undefined, table);
    containers.forEach(function (c) {
      var p = c.points[c.points.length - 1];
      var row = element(doc, 'tr', undefined, body);
      element(doc, 'td', c.name, row);
      element(doc, 'td', p ? p.cpu_percent.toFixed(1) + '%' : '—', row);
      element(doc, 'td', p ? bytes(p.memory_bytes) + ' / ' + bytes(p.memory_limit_bytes) : '—', row);
    });
    return true;
  }
  function bind(node, options) {
    options = options || {};
    var doc = node.ownerDocument;
    var request = options.fetch || global.fetch.bind(global);
    var clock = options.now || Date.now;
    var select = node.querySelector('.coast-metrics-range');
    var status = node.querySelector('.coast-metrics-status');
    var data = node.querySelector('.coast-metrics-data');
    var generation = 0, busy = false, controller;
    function active() { return node.isConnected && node.getClientRects().length > 0 && !doc.hidden; }
    function refresh(force) {
      if (!active() || (busy && !force)) return;
      if (controller) controller.abort();
      controller = new AbortController();
      var id = ++generation;
      var range = select.value;
      busy = true;
      status.textContent = 'Loading metrics…';
      var currentController = controller;
      var timeout = global.setTimeout(function () {
        currentController.abort();
        if (id !== generation) return;
        generation++;
        busy = false;
        if (active()) showError();
      }, 25000);
      request(node.dataset.url + '?range=' + encodeURIComponent(range), {
        credentials: 'same-origin', cache: 'no-store', signal: controller.signal
      }).then(function (response) {
        if (!response.ok) throw new Error('metrics');
        return response.json();
      }).then(function (body) {
        if (id !== generation || !active()) return;
        status.textContent = render(doc, data, body.metrics, range, clock()) ? '' :
          'No data yet - samples arrive every 30 seconds';
      }).catch(function (error) {
        if (id !== generation || error.name === 'AbortError' || !active()) return;
        showError();
      }).finally(function () {
        global.clearTimeout(timeout);
        if (id === generation) busy = false;
      });
    }
    function showError() {
      data.textContent = '';
      status.textContent = 'Unable to retrieve metrics. Try another time range or wait for the next refresh.';
    }
    select.addEventListener('change', function () { refresh(true); });
    function sync() {
      if (!active()) {
        if (busy) { generation++; controller.abort(); busy = false; }
        return;
      }
      refresh(false);
    }
    function dispose() {
      global.clearInterval(timer);
      if (controller) controller.abort();
      doc.removeEventListener('visibilitychange', sync);
      if (global.jQuery) global.jQuery(doc).off(tabEvents, sync);
    }
    var tabEvents = 'shown.bs.tab.coastMetrics hidden.bs.tab.coastMetrics';
    doc.addEventListener('visibilitychange', sync);
    if (global.jQuery) global.jQuery(doc).on(tabEvents, sync);
    var timer = global.setInterval(function () {
      if (!node.isConnected) { dispose(); return; }
      sync();
    }, 30000);
    refresh(false);
    return refresh;
  }
  function mountAll() {
    global.document.querySelectorAll('.coast-metrics:not([data-bound])').forEach(function (node) {
      node.dataset.bound = '1';
      bind(node);
    });
  }
  global.coastMetrics = {bytes: bytes, render: render, bind: bind, mountAll: mountAll};
})(typeof window !== 'undefined' ? window : globalThis);
