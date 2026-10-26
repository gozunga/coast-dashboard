/* Copyright 2026 Gozunga and Coast contributors. Licensed under Apache-2.0. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const template = fs.readFileSync(path.join(__dirname,
  '../../templates/project/coast/apps/_health_check.html'), 'utf8');
const source = template.match(/<script>([\s\S]*?)<\/script>/)[1];
const health = {value: 'none'};
const document = {};
let ready, change, shown;
let hasDomain = 'false', required, ariaRequired;
const group = {
  toggle() { return this; },
  toggleClass() { return this; },
  find() { return this; }
};
const ports = {
  prop(name, value) { if (name === 'required') required = value; return this; },
  attr(name, value) {
    if (name === 'data-has-domain') return hasDomain;
    if (name === 'aria-required') ariaRequired = value;
    return this;
  },
  closest() { return group; }
};
const form = {
  find(selector) {
    if (selector === '[name="template_id"]') return {length: 0};
    if (selector === '[name="ports"]') return ports;
    return {prop() { return this; }, closest: () => group};
  }
};
function $(target) {
  if (typeof target === 'function') { ready = target; return; }
  if (target === 'select[name="health_check"]') {
    return {each: callback => callback.call(health)};
  }
  if (target === health) return {
    closest: selector => selector === 'form' ? form : group,
    prop() { return this; }
  };
  assert.equal(target, document);
  return {
    off() { return this; },
    on(event, selector, callback) {
      if (event.startsWith('change')) change = callback;
      else shown = selector;
      return this;
    }
  };
}
vm.runInNewContext(source, {jQuery: $, document});
ready();
assert.equal(required, false);
health.value = 'http';
change();
assert.equal(required, true);
assert.equal(ariaRequired, 'true');
health.value = 'none';
change();
assert.equal(required, false);
hasDomain = 'true';
shown();
assert.equal(required, true);
hasDomain = 'false';
change();
assert.equal(required, false);
assert.equal(ariaRequired, 'false');
console.log('Health check port requirement tests passed.');
