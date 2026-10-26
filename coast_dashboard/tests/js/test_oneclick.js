/* Copyright 2026 Gozunga and Coast contributors. Licensed under Apache-2.0. */
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../../static/coast_dashboard/oneclick.js'), 'utf8');

const placementSource = fs.readFileSync(path.join(__dirname,
  '../../templates/project/coast/apps/_environment_filter.html'), 'utf8')
  .match(/<script>([\s\S]*?)<\/script>/)[1];

function field(value, options) {
  return {
    value: value,
    options: (options || []).map(value => ({value: value})),
    handlers: {},
    addEventListener: function (type, callback) {
      (this.handlers[type] = this.handlers[type] || []).push(callback);
    },
    fire: function (type, value) {
      this.value = value;
      this.dispatchEvent({type: type, bubbles: true});
    },
    dispatchEvent: function (event) {
      (this.handlers[event.type] || []).forEach(callback => callback());
      if (event.bubbles && this.delegate) { this.delegate(); }
    }
  };
}

function fixture(overrides) {
  const data = Object.assign({
    groups: {g1: 's1', g2: 's2'},
    environments: {e1: 'g1', e2: 'g1', e3: 'g2'},
    workers: {w1: 's1', w2: 's1', w3: 's2'},
    templates: {s1: ['postgresql'], s2: ['mysql']},
    ports: {postgresql: [5432], mysql: [3001, 3002]},
    http_ports: {postgresql: null, mysql: 3001}
  }, overrides);
  const fields = {
    template_id: field('postgresql', ['postgresql', 'mysql']),
    appgroup_id: field('g1', ['g1', 'g2']),
    environment_id: field('e1', ['e1', 'e2', 'e3']),
    server_id: field('w1', ['w1', 'w2', 'w3']),
    health_check: field('none'),
    health_check_port: field(''),
    healthcheck_path: field('')
  };
  const form = {
    dataset: {},
    elements: {namedItem: key => fields[key]},
    querySelector: () => ({textContent: JSON.stringify(data)})
  };
  const root = {querySelectorAll: () => [form]};
  let pageInit, modalInit, ready, change;
  fields.appgroup_id.delegate = () => { if (change) { change(); } };
  const maps = {'#coast-environment-groups': data.environments,
    '#coast-appgroup-stacks': data.groups, '#coast-worker-stacks': data.workers};
  function $(target) {
    if (typeof target === 'function') { ready = target; return; }
    if (target === 'form') {
      return {has: () => ({each: callback => callback.call(form)})};
    }
    if (target === form) {
      return {find: key => ({text: () => JSON.stringify(maps[key])})};
    }
    return {off: function () { return this; }, on: function (event, selector, fn) {
      if (event.startsWith('change')) { change = fn; }
      return this;
    }};
  }
  const context = {
    Event: function (type, options) {
      this.type = type;
      this.bubbles = options.bubbles;
    }, jQuery: $,
    document: root,
    horizon: {
      addInitFunction: fn => { pageInit = fn; },
      modals: {addModalInitFunction: fn => { modalInit = fn; }}
    }
  };
  vm.runInNewContext(source, context);
  vm.runInNewContext(placementSource, context);
  return {fields, root, pageInit: () => { pageInit(); ready(); },
    modalInit: modal => { modalInit(modal); ready(); }};
}

// Template selection filters placement on full pages and in modals.
let app = fixture();
app.pageInit();
assert.equal(app.fields.environment_id.options[2].disabled, true);
app.fields.template_id.fire('change', 'mysql');
assert.equal(app.fields.appgroup_id.value, 'g2');
assert.equal(app.fields.environment_id.value, 'e3');
assert.equal(app.fields.server_id.value, 'w3');
assert.equal(app.fields.health_check_port.value, 3001);
assert.equal(app.fields.health_check.value, 'http');
assert.equal(app.fields.healthcheck_path.value, '/');
app.fields.appgroup_id.fire('change', 'g1');
assert.equal(app.fields.template_id.value, '');
assert.equal(app.fields.environment_id.value, '');
assert.equal(app.fields.server_id.value, '');
assert.equal(app.fields.health_check_port.value, '');

// Initialization preserves an edited or cleared port after validation errors.
for (const value of ['9000', '']) {
  app = fixture({bound: true});
  app.fields.health_check_port.value = value;
  app.pageInit();
  app.modalInit([app.root]);
  assert.equal(app.fields.health_check_port.value, value);
  app.fields.appgroup_id.fire('change', 'g1');
  assert.equal(app.fields.health_check_port.value, value);
}

// Only http_port supplies defaults, even when catalog ports exist.
for (const httpPorts of [{mysql: null}, {}, {mysql: 8080}]) {
  app = fixture({http_ports: httpPorts});
  app.pageInit();
  app.fields.template_id.fire('change', 'mysql');
  const http = httpPorts.mysql !== null && httpPorts.mysql !== undefined;
  assert.equal(app.fields.health_check.value, http ? 'http' : 'none');
  assert.equal(app.fields.health_check_port.value, http ? 8080 : '');
  assert.equal(app.fields.healthcheck_path.value, http ? '/' : '');
  app.fields.template_id.fire('change', 'postgresql');
  assert.equal(app.fields.health_check.value, 'none');
  assert.equal(app.fields.health_check_port.value, '');
  assert.equal(app.fields.healthcheck_path.value, '');
  app.fields.template_id.fire('change', 'mysql');
  assert.equal(app.fields.health_check.value, http ? 'http' : 'none');
}

// Each user health edit protects all health values on later template changes.
for (const key of ['health_check', 'health_check_port', 'healthcheck_path']) {
  for (const event of ['input', 'change']) {
    app = fixture();
    app.pageInit();
    app.fields.template_id.fire('change', 'mysql');
    app.fields[key].fire(event, key === 'health_check' ? 'none' : '');
    const expected = ['health_check', 'health_check_port', 'healthcheck_path']
      .map(name => app.fields[name].value);
    app.fields.template_id.fire('change', 'postgresql');
    app.fields.template_id.fire('change', 'mysql');
    assert.deepEqual(['health_check', 'health_check_port', 'healthcheck_path']
      .map(name => app.fields[name].value), expected);
  }
}

// Opening a blank form must not silently choose its first template.
app = fixture();
app.fields.template_id.value = '';
app.pageInit();
assert.equal(app.fields.template_id.value, '');

// A template launched with no group stays selected until placement is chosen.
app = fixture();
app.fields.appgroup_id.value = '';
app.pageInit();
assert.equal(app.fields.template_id.value, 'postgresql');

// Modal initialization does not duplicate handlers or replace locked placement.
app = fixture();
app.fields.appgroup_id.disabled = true;
app.fields.environment_id.disabled = true;
app.modalInit([app.root]);
app.pageInit();
assert.equal(app.fields.template_id.handlers.change.length, 1);
app.fields.template_id.fire('change', 'mysql');
assert.equal(app.fields.appgroup_id.value, 'g1');
assert.equal(app.fields.environment_id.value, 'e1');
// Several environments or workers stay empty. One remaining choice is selected.
app = fixture();
app.fields.environment_id.value = '';
app.fields.server_id.value = '';
app.pageInit();
assert.equal(app.fields.environment_id.value, '');
assert.equal(app.fields.server_id.value, '');
app = fixture({
  environments: {e1: 'g1', e3: 'g2'},
  workers: {w1: 's1', w3: 's2'}
});
app.fields.environment_id.value = '';
app.fields.server_id.value = '';
app.pageInit();
assert.equal(app.fields.environment_id.value, 'e1');
assert.equal(app.fields.server_id.value, 'w1');

console.log('One-click placement JavaScript tests passed.');
