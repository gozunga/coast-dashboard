/* Copyright 2026 Gozunga and Coast contributors. Licensed under Apache-2.0. */
'use strict';
const fs = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));

// Model the DOM operations used by the modal, including moving existing nodes.
class Element {
  constructor(tag, name) {
    this.tag = tag;
    this.name = name;
    this.children = [];
    this.parentNode = null;
    this.textContent = '';
    this.open = false;
  }
  insertBefore(child, next) {
    if (child.parentNode) {
      const siblings = child.parentNode.children;
      siblings.splice(siblings.indexOf(child), 1);
    }
    const index = next == null ? this.children.length : this.children.indexOf(next);
    if (index < 0) throw new Error('Reference node is not a child');
    this.children.splice(index, 0, child);
    child.parentNode = this;
    return child;
  }
  appendChild(child) { return this.insertBefore(child, null); }
  get nextSibling() {
    return this.parentNode.children[this.parentNode.children.indexOf(this) + 1] || null;
  }
  closest(selector) {
    if ((selector === 'form' && this.tag === 'form') ||
        (selector === '.form-group' && this.tag === 'group')) return this;
    return this.parentNode ? this.parentNode.closest(selector) : null;
  }
  querySelector(selector) {
    const match = selector.match(/^\[name="([^"]+)"\]$/);
    if (!match) throw new Error('Unsupported selector: ' + selector);
    return descendants(this).find(node => node.name === match[1]) || null;
  }
}
function descendants(node) {
  return node.children.flatMap(child => [child, ...descendants(child)]);
}
const form = new Element('form');
const fieldset = form.appendChild(new Element('fieldset'));
for (const name of input.fields) {
  fieldset.appendChild(new Element('group')).appendChild(new Element('input', name));
}
const script = form.appendChild(new Element('script'));
vm.runInNewContext(input.script, {
  document: {currentScript: script, createElement: tag => new Element(tag)}
}, {timeout: 1000});

// Only report sections attached to the form: detached sections must fail tests.
const sections = {};
for (const section of descendants(form).filter(node => node.tag === 'details')) {
  const summary = section.children.find(node => node.tag === 'summary');
  if (!summary) throw new Error('Section has no summary');
  sections[summary.textContent] = {
    open: section.open,
    fields: descendants(section).filter(node => node.name).map(node => node.name),
    notes: section.children.filter(node => node.tag === 'p').map(node => node.textContent)
  };
}
process.stdout.write(JSON.stringify(sections));
