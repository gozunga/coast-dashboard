/* Copyright 2026 Gozunga and Coast contributors. Licensed under Apache-2.0. */
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname,
  '../../templates/project/coast/apps/deployment.html'), 'utf8')
  .match(/<script>([\s\S]*?)<\/script>/)[1];

function fixture(complete, template) {
  let poll, cleared = 0, reloaded = 0, removed = 0, responseComplete = '0';
  const target = {
    querySelector: selector => selector === '.coast-log-state' ?
      {dataset: {complete: responseComplete}} : null
  };
  const root = {
    dataset: {complete: complete, template: template ? '1' : '0',
      fragmentUrl: '/deployment/log/fragment/'},
    querySelector: selector => selector === '.coast-log-live' ?
      {remove: () => { removed++; }} : target
  };
  vm.runInNewContext(source, {
    document: {querySelector: () => root},
    setInterval: (callback, delay) => {
      assert.equal(delay, 3000);
      poll = callback;
      return 42;
    },
    clearInterval: timer => { assert.equal(timer, 42); cleared++; },
    fetch: async url => {
      assert.equal(url, root.dataset.fragmentUrl);
      return {ok: true, text: async () => '<log fragment>'};
    },
    window: {location: {reload: () => { reloaded++; }}}
  });
  return {
    poll: () => poll,
    respond: async complete => {
      responseComplete = complete;
      poll();
      await new Promise(setImmediate);
    },
    complete: () => root.dataset.complete,
    removed: () => removed,
    cleared: () => cleared,
    reloaded: () => reloaded
  };
}

(async function () {
  for (const template of [false, true]) {
    // API completion prevents a timer on the first page render.
    assert.equal(fixture('1', template).poll(), undefined);
    // Empty logs keep polling only until the API reports completion.
    const app = fixture('0', template);
    await app.respond('0');
    assert.equal(app.cleared(), 0);
    await app.respond('1');
    assert.equal(app.cleared(), 1);
    assert.equal(app.complete(), '1');
    assert.equal(app.removed(), 1);
    assert.equal(app.reloaded(), template ? 0 : 1);
  }
  console.log('Deployment log JavaScript tests passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
