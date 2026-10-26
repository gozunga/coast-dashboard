/* Copyright 2026 Gozunga and Coast contributors. Licensed under Apache-2.0. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname,
  '../../templates/project/coast_services/logs_tab.html'), 'utf8')
  .match(/<script>([\s\S]*?)<\/script>/)[1];
let poll, change, manual, cleared = 0;
const box = {scrollHeight: 100};
const target = {querySelector: () => box};
const root = {
  dataset: {fragmentUrl: '/service/logs/fragment/'},
  querySelector: selector => {
    if (selector === '.coast-log-target') return target;
    return {addEventListener: (event, callback) => {
      if (event === 'change') change = callback;
      else manual = callback;
    }};
  }
};
vm.runInNewContext(source, {
  document: {querySelector: () => root},
  setInterval: (callback, delay) => {
    assert.equal(delay, 3000);
    poll = callback;
    return 42;
  },
  clearInterval: timer => { assert.equal(timer, 42); cleared++; },
  fetch: async (url, options) => {
    assert.equal(url, root.dataset.fragmentUrl);
    assert.equal(options.credentials, 'same-origin');
    return {text: async () => 'new runtime logs'};
  }
});
(async function () {
  assert.equal(typeof poll, 'function');
  poll();
  await new Promise(setImmediate);
  assert.equal(target.innerHTML, 'new runtime logs');
  assert.equal(box.scrollTop, 100);
  change({target: {checked: false}});
  assert.equal(cleared, 1);
  change({target: {checked: true}});
  assert.equal(typeof poll, 'function');
  manual();
  await new Promise(setImmediate);
  assert.equal(target.innerHTML, 'new runtime logs');
  console.log('Service logs polling tests passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
