/* Copyright 2026 Gozunga and Coast contributors. Licensed under Apache-2.0. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const jquery = require('jquery');
const source = fs.readFileSync(path.join(__dirname,
  '../../templates/project/coast_oneclick/_name_defaults.html'), 'utf8')
  .match(/<script>([\s\S]*?)<\/script>/)[1];

async function test() {
  const dom = new JSDOM('<!doctype html><body></body>', {runScripts: 'outside-only'});
  const {window} = dom;
  const $ = jquery(window);
  window.jQuery = $;
  try {
    // Register before adding the forms, as happens with AJAX modals.
    window.eval(source);
    await new Promise(resolve => $(resolve));
    for (const [attribute, selector] of [
      ['data-coast-oneclick', 'template_id'],
      ['data-coast-name-defaults', 'engine']
    ]) {
      const form = window.document.createElement('form');
      form.setAttribute(attribute, '');
      form.innerHTML = `<input name="name" data-user-edited="false">
        <select name="${selector}">
          <option value=""></option><option value="router">Router</option>
          <option value="postgres">Postgres</option>
        </select>
        <select name="appgroup_id">
          <option value="a1">Group 1</option><option value="a2">Group 2</option>
          <option value=""></option>
        </select><script type="application/json"></script>`;
      const data = {selector, bases: {router: '9router', postgres: 'postgres'}, names: [
        {name: '9router', appgroup_id: 'a1'},
        {name: '9router-2', appgroup_id: 'a1'},
        {name: '9router-3', appgroup_id: 'a2'}]};
      const defaults = form.querySelector('script');
      defaults.textContent = JSON.stringify(data);
      window.document.body.appendChild(form);
      const name = form.elements.namedItem('name');
      const template = form.elements.namedItem(selector);
      const group = form.elements.namedItem('appgroup_id');
      const change = (field, value) => $(field).val(value).trigger('change');
      $(window.document).trigger('shown.bs.modal');
      assert.equal(name.value, '');
      change(template, 'router');
      assert.equal(name.value, '9router-3');
      change(template, 'postgres');
      assert.equal(name.value, 'postgres');
      change(group, '');
      change(template, 'router');
      assert.equal(name.value, '9router-4');
      change(group, 'a2');
      assert.equal(name.value, '9router');
      const base = 'a'.repeat(63);
      data.bases.router = base;
      data.names = [{name: base, appgroup_id: 'a2'}];
      defaults.textContent = JSON.stringify(data);
      $(group).trigger('change');
      assert.equal(name.value, 'a'.repeat(61) + '-2');
      $(name).val('my-database').trigger('input');
      assert.equal(name.dataset.userEdited, 'true');
      change(template, 'postgres');
      change(group, 'a1');
      $(window.document).trigger('shown.bs.modal');
      assert.equal(name.value, 'my-database');
      $(name).val('').trigger('input');
      change(template, 'router');
      $(window.document).trigger('shown.bs.modal');
      assert.equal(name.value, ''); // Clearing a manual name keeps protection.
      // A sibling form must not be affected by delegated events in this form.
      name.value = 'submitted';
    }
    assert.deepEqual(Array.from(window.document.querySelectorAll('[name="name"]'),
      field => field.value), ['submitted', 'submitted']);
    console.log('Service and database real jQuery event tests passed.');
  } finally {
    window.close();
  }
}
test().catch(error => { console.error(error); process.exitCode = 1; });
