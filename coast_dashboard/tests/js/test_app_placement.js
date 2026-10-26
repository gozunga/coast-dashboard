/* Copyright 2026 Gozunga and Coast contributors. Licensed under Apache-2.0. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const template = fs.readFileSync(path.join(__dirname,
  '../../templates/project/coast/apps/_environment_filter.html'), 'utf8');
const source = template.match(/<script>([\s\S]*?)<\/script>/)[1];
function select(value, values) {
  return {value, options: values.map(value => ({value}))};
}
const group = select('a1', ['', 'a1', 'a2']);
const environment = select('e1', ['', 'e1', 'e2']);
const worker = select('v1', ['', 'v1', 'v2', 'v3']);
const form = {elements: {namedItem: name => ({
  appgroup_id: group, environment_id: environment, server_id: worker
})[name]}};
const maps = {
  '#coast-environment-groups': {e1: 'a1', e2: 'a2'},
  '#coast-appgroup-stacks': {a1: 's1', a2: 's2'},
  '#coast-worker-stacks': {v1: 's1', v2: 's2', v3: 's2'}
};
const document = {};
let change, shown, ready;
function $(target) {
  if (typeof target === 'function') { ready = target; return; }
  if (target === 'form') {
    return {has: () => ({each: callback => callback.call(form)})};
  }
  if (target === form) {
    return {find: key => ({text: () => JSON.stringify(maps[key])})};
  }
  return {off: function () { return this; }, on: function (event, selector, callback) {
    if (event.startsWith('change')) { change = callback; } else { shown = selector; }
    return this;
  }};
}
vm.runInNewContext(source, {jQuery: $, document});
ready();
assert.equal(worker.value, 'v1');
assert.equal(worker.options[2].hidden, true);
group.value = 'a2';
change();
assert.equal(worker.options[1].disabled, true);
assert.equal(worker.options[2].hidden, false);
assert.equal(worker.value, ''); // Multiple matching workers require a choice.
assert.equal(environment.value, 'e2');
group.value = 'a1';
shown(); // AJAX modal initialization also applies placement filtering.
assert.equal(worker.value, 'v1');
assert.equal(worker.options[2].disabled, true);
group.value = '';
change();
assert.equal(worker.value, '');
assert.ok(worker.options.slice(1).every(option => option.hidden));
console.log('App placement JavaScript tests passed.');
