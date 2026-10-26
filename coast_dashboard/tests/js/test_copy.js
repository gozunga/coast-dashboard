/* Copyright 2026 Gozunga and Coast contributors. Licensed under Apache-2.0. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname,
  '../../templates/project/coast_common/_copy_script.html'), 'utf8')
  .match(/<script>([\s\S]*?)<\/script>/)[1];

async function check(mode, success, logTarget) {
  const value = 'https://example.com/hook?token="quoted"&branch=main';
  const feedback = {textContent: ''};
  const attrs = {'data-copy-target': logTarget, 'data-copy-value': value, 'data-copied-label': 'Copied',
    'data-copy-error-label': 'Copy failed'};
  const button = {getAttribute: key => attrs[key], querySelector: () => feedback};
  let click, reset, copied, selected, removed = false, focused = false;
  const field = {style: {}, setAttribute: () => {},
    select: () => { selected = field.value; },
    remove: () => { removed = true; }};
  const document = {activeElement: {focus: () => { focused = true; }},
    querySelector: selector => {
      assert.equal(selector, logTarget);
      return {textContent: logText};
    },
    createElement: () => field, body: {appendChild: () => {}},
    execCommand: command => { assert.equal(command, 'copy'); return success; }};
  var logText = 'first line\n<plain text> & symbols\n';
  const navigator = {};
  if (mode !== 'missing') {
    navigator.clipboard = {writeText: async text => {
      copied = text;
      if (mode === 'denied') { throw new Error('denied'); }
    }};
  }
  const events = {off: function () { return this; },
    on: function (event, selector, handler) {
      assert.equal(selector, '[data-copy-value], [data-copy-target]');
      click = handler;
      return this;
    }};
  vm.runInNewContext(source, {document, navigator, jQuery: () => events,
    clearTimeout: () => {}, setTimeout: (callback, delay) => {
      assert.equal(delay, 1500);
      reset = callback;
    }});
  let prevented = false;
  await click.call(button, {preventDefault: () => { prevented = true; }});
  assert.ok(prevented);
  if (mode === 'native') {
    assert.equal(copied, logTarget ? logText : value);
    assert.equal(selected, undefined);
  } else {
    assert.equal(selected, logTarget ? logText : value);
    assert.ok(removed);
    assert.ok(focused);
  }
  assert.equal(feedback.textContent, success ? ' Copied' : ' Copy failed');
  reset();
  assert.equal(feedback.textContent, '');
  if (logTarget) {
    // Polling replaces the log node. The next click must read its current text.
    logText = 'first line\nsecond line\n<new text> & symbols\n';
    await click.call(button, {preventDefault: () => {}});
    assert.equal(mode === 'native' ? copied : selected, logText);
    assert.equal(feedback.textContent, ' Copied');
  }
}
(async function () {
  await check('native', true);
  await check('missing', true);
  await check('denied', true);
  await check('missing', false);
  for (const target of ['.coast-deploy-log .coast-log-box',
    '.coast-logs .coast-log-box']) {
    await check('native', true, target);
    await check('missing', true, target);
    await check('denied', true, target);
  }
  console.log('Clipboard JavaScript tests passed.');
}()).catch(error => { console.error(error); process.exitCode = 1; });
