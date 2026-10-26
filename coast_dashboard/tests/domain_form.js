// Run the rendered initializer with the script element in head, as in DOMEval.
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(0, 'utf8');
for (const location of ['head', 'form']) {
  for (const returnedMode of ['zone', 'manual']) {
    const zoneControl = {disabled: false, required: returnedMode === 'zone'};
    const domainControl = {value: '', disabled: false, required: returnedMode === 'manual'};
    const editControl = {disabled: true};
    const sectionControls = [[zoneControl], [domainControl], [editControl]];
    const sections = ['zone', 'manual', ''].map((mode, index) => ({
      style: {}, getAttribute: () => mode,
      querySelectorAll: () => sectionControls[index]
    }));
    const controls = {
      '[name="dns_mode"]': {value: returnedMode},
      '[name="zone_id"]': {selectedIndex: 0, options: [{text: 'example.com'}]},
      '[name="host"]': {value: 'shop'},
      '[name="fqdn"]': domainControl,
      '#coast-domain-names': {textContent: '["shop.example.com","default.example.com"]'},
      '.coast-domain-preview': {}, '.coast-domain-duplicate': {},
      '.coast-manual-domain': {}
    };
    const listeners = {};
    const root = {dataset: {}, querySelector: key => controls[key],
      querySelectorAll: selector => selector === '[data-domain-section]'
        ? sections : sectionControls.flat(),
      addEventListener: (event, fn) => { listeners[event] = fn; }};
    let modalInit;
    const ready = [];
    const horizon = {modals: {addModalInitFunction: fn => { modalInit = fn; }}};
    const context = {window: {}, document: {
      currentScript: {parentNode: location === 'head' ? {} : root},
      querySelectorAll: () => [root]},
      horizon: location === 'head' ? horizon : {},
      jQuery: fn => { ready.push(fn); }};
    context.window.horizon = context.horizon;
    vm.runInNewContext(source, context);
    // Full-page forms execute before the footer defines horizon.modals.
    context.horizon = horizon;
    context.window.horizon = horizon;
    ready.forEach(fn => fn());
    modalInit();
    // Reproduce a returned manual form with an empty required Domain.
    if (returnedMode === 'manual') {
      assert.equal(domainControl.required, true);
      assert.equal(domainControl.disabled, false);
      assert.equal(zoneControl.disabled, true);
      controls['[name="dns_mode"]'].value = 'zone';
      listeners.change();
    }
    assert.equal(domainControl.disabled, true);
    assert.equal(zoneControl.disabled, false);
    assert.equal(editControl.disabled, true);
    assert.equal(sections[0].style.display, '');
    assert.equal(sections[1].style.display, 'none');
    assert.equal(controls['.coast-domain-preview'].textContent, 'shop.example.com');
    assert.equal(controls['.coast-domain-duplicate'].hidden, false);
    controls['[name="dns_mode"]'].value = 'manual';
    controls['[name="fqdn"]'].value = 'DEFAULT.example.com.';
    listeners.change();
    assert.equal(domainControl.disabled, false);
    assert.equal(zoneControl.disabled, true);
    assert.equal(editControl.disabled, true);
    assert.equal(sections[0].style.display, 'none');
    assert.equal(sections[1].style.display, '');
    assert.equal(controls['.coast-domain-duplicate'].hidden, false);
    controls['[name="fqdn"]'].value = 'new.example.net';
    listeners.input();
    assert.equal(controls['.coast-domain-duplicate'].hidden, true);
    assert.equal(controls['.coast-manual-domain'].textContent, 'new.example.net');
    controls['[name="dns_mode"]'].value = 'zone';
    controls['[name="host"]'].value = 'default';
    listeners.change();
    assert.equal(sections[1].style.display, 'none');
    assert.equal(domainControl.disabled, true);
    assert.equal(zoneControl.disabled, false);
    assert.equal(controls['.coast-domain-duplicate'].hidden, false);
  }
}
