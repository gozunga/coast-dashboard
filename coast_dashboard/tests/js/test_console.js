/* Copyright 2026 Gozunga and Coast contributors. Licensed under Apache-2.0. */
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname,
  '../../static/coast_dashboard/console.js'), 'utf8');
const fitSource = fs.readFileSync(path.join(__dirname,
  '../../static/coast_dashboard/vendor/xterm/addon-fit.js'), 'utf8');

function loadApi() {
  const context = {
    console, TextEncoder, URL, Uint8Array, ArrayBuffer, Promise
  };
  context.window = context;
  context.globalThis = context;
  vm.runInNewContext(source, context);
  return context.coastConsole;
}

function fakeTerminal() {
  function Terminal() {
    this.cols = 80;
    this.rows = 24;
    this.handlers = {};
    this.written = [];
    Terminal.latest = this;
  }
  Terminal.prototype.loadAddon = function (addon) {
    const self = this;
    addon.fit = function () {
      if (self.cols === 100 && self.rows === 30) {
        return;
      }
      self.cols = 100;
      self.rows = 30;
      if (self.handlers.resize) {
        self.handlers.resize({cols: self.cols, rows: self.rows});
      }
    };
  };
  Terminal.prototype.onData = function (callback) {
    this.handlers.data = callback;
  };
  Terminal.prototype.onResize = function (callback) {
    this.handlers.resize = callback;
  };
  Terminal.prototype.open = function () {};
  Terminal.prototype.write = function (data) {
    this.written.push(data);
  };
  Terminal.prototype.focus = function () {
    this.focused = true;
  };
  Terminal.prototype.dispose = function () {
    this.disposed = true;
  };
  return Terminal;
}

function element() {
  const node = {
    hidden: false,
    disabled: false,
    textContent: '',
    isConnected: true,
    handlers: {},
    style: {},
    attrs: {},
    classes: new Set(),
    classList: {
      add(name) { this.owner.classes.add(name); },
      remove(name) { this.owner.classes.delete(name); }
    },
    setAttribute(name, value) {
      this.attrs[name] = value;
    },
    addEventListener(type, callback) {
      this.handlers[type] = callback;
    },
    click() {
      this.handlers.click();
    }
  };
  node.classList.owner = node;
  return node;
}

function page() {
  const connect = element();
  const reconnect = element();
  reconnect.hidden = true;
  const status = element();
  const host = element();
  host.hidden = true;
  return {
    dataset: {consoleUrl: '/console/', csrf: 'csrf-token'},
    querySelector: selector => ({
      '.coast-console-connect': connect,
      '.coast-console-reconnect': reconnect,
      '.coast-console-status': status,
      '.coast-console-host': host
    })[selector],
    connect, reconnect, status, host
  };
}

function harness(response) {
  const calls = [];
  const sockets = [];
  const node = page();
  const Terminal = fakeTerminal();
  const api = loadApi();
  api.bind(node, {
    Terminal: Terminal,
    FitAddon: function Fit() {},
    window: {
      addEventListener() {},
      removeEventListener() {},
      requestAnimationFrame(callback) {
        callback();
      }
    },
    fetch: async (url, options) => {
      calls.push({url, options});
      return {
        ok: response.ok !== false,
        json: async () => response.body
      };
    },
    openSocket: url => {
      const socket = {
        url, binaryType: '', readyState: 0, sent: [], closed: false,
        send(data) {
          this.sent.push(data);
        },
        close() {
          this.readyState = 3;
          this.closed = true;
        }
      };
      sockets.push(socket);
      return socket;
    }
  });
  return {node, calls, sockets, Terminal};
}

async function connect(session) {
  session.node.connect.click();
  await new Promise(setImmediate);
  const socket = session.sockets[0];
  socket.readyState = 1;
  socket.onopen();
  return socket;
}

(async function () {
  const api = loadApi();
  assert.equal(api.resizePayload(80, 24),
    '{"type":"resize","cols":80,"rows":24}');
  assert.equal(api.inputFrame('a')[0], 97);
  assert.equal(api.readFrame('{"type":"exit","code":0}').code, 0);
  assert.equal(api.readFrame('{"type":"resize","cols":1,"rows":1}').kind,
    'ignore');
  assert.equal(api.readFrame(new Uint8Array([65]).buffer).kind, 'output');
  assert.equal(api.endedText(0),
    'Session ended (exit code 0). Press Reconnect to start a new session.');
  assert.equal(api.endedText(undefined),
    'Session ended. Press Reconnect to start a new session.');
  assert.equal(api.sessionUrl('wss://console.example/s?token=abc'),
    'wss://console.example/s?token=abc');
  assert.equal(api.sessionUrl('ws://console.example/s'), null);
  assert.equal(api.sessionUrl('wss://user:secret@console.example/s'), null);
  assert.equal(typeof api.fitClass({FitAddon: {FitAddon: function () {}}}),
    'function');

  const fitContext = {console};
  vm.runInNewContext(fitSource, fitContext);
  assert.equal(typeof fitContext.FitAddon.FitAddon, 'function');

  const session = harness({
    body: {url: 'wss://console.example/s?token=abc'}
  });
  const socket = await connect(session);
  const term = session.Terminal.latest;
  assert.equal(session.calls[0].url, '/console/');
  assert.equal(session.calls[0].options.method, 'POST');
  assert.equal(session.calls[0].options.credentials, 'same-origin');
  assert.equal(session.calls[0].options.headers['X-CSRFToken'], 'csrf-token');
  assert.equal(session.calls[0].options.body, undefined);
  assert.equal(socket.url, 'wss://console.example/s?token=abc');
  assert.equal(socket.binaryType, 'arraybuffer');
  assert.equal(socket.sent.length, 1);
  assert.equal(socket.sent[0], '{"type":"resize","cols":100,"rows":30}');
  assert.equal(term.focused, true);
  // Regression: the status must leave "Connecting" once the shell is live.
  assert.equal(session.node.status.textContent, 'Connected.');
  assert.equal(session.node.status.attrs['data-state'], 'connected');
  assert.equal(session.node.connect.style.display, 'none');
  assert.equal(session.node.reconnect.style.display, 'none');

  term.handlers.data('a');
  assert.ok(socket.sent[1] instanceof Uint8Array);
  assert.equal(socket.sent[1][0], 97);

  socket.onmessage({data: new Uint8Array([65, 66]).buffer});
  assert.equal(term.written.length, 1);
  assert.equal(term.written[0][0], 65);
  assert.equal(term.written[0][1], 66);

  socket.onmessage({data: '{"type":"exit","code":0}'});
  assert.equal(session.node.status.textContent,
    'Session ended (exit code 0). Press Reconnect to start a new session.');
  assert.equal(session.node.status.attrs['data-state'], 'ended');
  assert.ok(session.node.host.classes.has('coast-console-ended'));
  assert.equal(session.node.reconnect.hidden, false);
  assert.equal(session.node.reconnect.style.display, '');
  assert.equal(session.node.connect.hidden, true);
  assert.equal(socket.closed, true);
  term.handlers.data('b');
  assert.equal(socket.sent.length, 2);

  session.node.reconnect.click();
  await new Promise(setImmediate);
  assert.equal(session.calls.length, 2);
  assert.equal(term.disposed, true);
  const next = session.sockets[1];
  next.readyState = 1;
  next.onopen();
  assert.equal(next.sent[0], '{"type":"resize","cols":100,"rows":30}');

  const refused = harness({body: {url: 'http://console.example/s'}});
  refused.node.connect.click();
  await new Promise(setImmediate);
  assert.equal(refused.sockets.length, 0);
  assert.equal(refused.node.status.textContent,
    'Unable to open a console session.');
  assert.equal(refused.node.reconnect.hidden, false);

  const failed = harness({
    ok: false,
    body: {error: 'The resource is not running.'}
  });
  failed.node.connect.click();
  await new Promise(setImmediate);
  assert.equal(failed.node.status.textContent,
    'The resource is not running.');

  const dropped = harness({
    body: {url: 'wss://console.example/s?token=abc'}
  });
  dropped.node.connect.click();
  await new Promise(setImmediate);
  dropped.sockets[0].onclose();
  assert.equal(dropped.node.status.textContent,
    'Unable to open a console session.');

  console.log('Console JavaScript tests passed.');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
