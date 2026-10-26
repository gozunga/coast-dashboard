/* Copyright 2026 Gozunga and Coast contributors. Licensed under Apache-2.0.
 * Terminal UI: @xterm/xterm 6.0.0 and @xterm/addon-fit 0.11.0 (MIT).
 * https://github.com/xtermjs/xterm.js/releases/tag/6.0.0
 * The fit browser build assigns window.FitAddon.FitAddon.
 */
(function (root) {
  'use strict';

  var UNABLE = 'Unable to open a console session.';
  var CANNOT_START = 'The console cannot start.';

  function resizePayload(cols, rows) {
    return JSON.stringify({type: 'resize', cols: cols, rows: rows});
  }

  function inputFrame(text) {
    return new TextEncoder().encode(String(text));
  }

  function readFrame(data) {
    if (typeof data !== 'string') {
      var bytes = data instanceof ArrayBuffer ? new Uint8Array(data) : data;
      return {kind: 'output', bytes: bytes};
    }
    var message;
    try {
      message = JSON.parse(data);
    } catch (error) {
      return {kind: 'ignore'};
    }
    if (!message || message.type !== 'exit') {
      return {kind: 'ignore'};
    }
    return {kind: 'exit', code: message.code};
  }

  function endedText(code) {
    if (typeof code === 'number') {
      return 'Session ended (exit code ' + code + '). ' +
        'Press Reconnect to start a new session.';
    }
    return 'Session ended. Press Reconnect to start a new session.';
  }

  function sessionUrl(value) {
    var parsed;
    try {
      parsed = new URL(value);
    } catch (error) {
      return null;
    }
    if (parsed.protocol !== 'wss:' || !parsed.hostname ||
        parsed.username || parsed.password) {
      return null;
    }
    return value;
  }

  function terminalClass(scope) {
    return typeof scope.Terminal === 'function' ? scope.Terminal : null;
  }

  function fitClass(scope) {
    var exported = scope.FitAddon;
    if (typeof exported === 'function') {
      return exported;
    }
    if (exported && typeof exported.FitAddon === 'function') {
      return exported.FitAddon;
    }
    return null;
  }

  function bind(node, deps) {
    deps = deps || {};
    var scope = deps.scope || root;
    var windowRef = deps.window || root;
    var fetchImpl = deps.fetch || root.fetch;
    var Terminal = deps.Terminal || terminalClass(scope);
    var Fit = deps.FitAddon || fitClass(scope);
    var openSocket = deps.openSocket || function (url) {
      return new scope.WebSocket(url);
    };
    var status = node.querySelector('.coast-console-status');
    var connect = node.querySelector('.coast-console-connect');
    var reconnect = node.querySelector('.coast-console-reconnect');
    var host = node.querySelector('.coast-console-host');
    var socket = null;
    var term = null;
    var fit = null;
    var ended = false;
    var opened = false;
    var generation = 0;

    function setStatus(text, state) {
      status.textContent = text || '';
      status.setAttribute('data-state', state || '');
    }

    function show(button, visible) {
      // Bootstrap .btn display rules override the hidden attribute.
      button.hidden = !visible;
      button.style.display = visible ? '' : 'none';
    }

    function setButtons(mode) {
      show(connect, mode === 'idle');
      show(reconnect, mode === 'ended' || mode === 'error');
      connect.disabled = mode === 'busy';
      reconnect.disabled = mode === 'busy';
    }

    function sendSize() {
      if (socket && socket.readyState === 1 && term) {
        socket.send(resizePayload(term.cols, term.rows));
      }
    }

    function fitAndSend() {
      if (!fit || !term) {
        return;
      }
      var cols = term.cols;
      var rows = term.rows;
      fit.fit();
      if (term.cols === cols && term.rows === rows) {
        sendSize();
      }
    }

    function onWindowResize() {
      if (!host.isConnected) {
        windowRef.removeEventListener('resize', onWindowResize);
        return;
      }
      if (socket && socket.readyState === 1) {
        fitAndSend();
      }
    }

    function closeSocket() {
      var current = socket;
      socket = null;
      if (current && current.readyState < 2) {
        current.close();
      }
    }

    function stop(mode, text) {
      if (ended) {
        return;
      }
      ended = true;
      windowRef.removeEventListener('resize', onWindowResize);
      closeSocket();
      if (term && term.options) {
        term.options.disableStdin = true;
        term.options.cursorBlink = false;
      }
      host.classList.add('coast-console-ended');
      setStatus(text, mode);
      setButtons(mode);
    }

    function attachSocket(url, generationId) {
      var current = openSocket(url);
      socket = current;
      current.binaryType = 'arraybuffer';
      current.onopen = function () {
        if (generationId !== generation) {
          return;
        }
        opened = true;
        host.hidden = false;
        setStatus('Connected.', 'connected');
        setButtons('live');
        fitAndSend();
        if (term.focus) {
          term.focus();
        }
      };
      current.onmessage = function (event) {
        if (generationId !== generation) {
          return;
        }
        var frame = readFrame(event.data);
        if (frame.kind === 'output') {
          term.write(frame.bytes);
        } else if (frame.kind === 'exit') {
          stop('ended', endedText(frame.code));
        }
      };
      current.onerror = function () {};
      current.onclose = function () {
        if (generationId !== generation || socket !== current) {
          return;
        }
        if (!opened) {
          stop('error', UNABLE);
          return;
        }
        stop('ended', endedText(undefined));
      };
    }

    function openSession() {
      if (!Terminal || !Fit) {
        setStatus(CANNOT_START);
        setButtons('error');
        return;
      }
      generation += 1;
      var generationId = generation;
      ended = false;
      opened = false;
      closeSocket();
      setButtons('busy');
      host.classList.remove('coast-console-ended');
      setStatus('Connecting…', 'connecting');
      if (term && term.dispose) {
        term.dispose();
      }
      host.textContent = '';
      host.hidden = false;
      term = new Terminal({cursorBlink: true, fontSize: 14});
      fit = new Fit();
      term.loadAddon(fit);
      term.onData(function (text) {
        if (socket && socket.readyState === 1 && !ended) {
          socket.send(inputFrame(text));
        }
      });
      term.onResize(function () {
        sendSize();
      });
      term.open(host);
      windowRef.addEventListener('resize', onWindowResize);
      var schedule = windowRef.requestAnimationFrame || function (fn) {
        fn();
      };
      schedule(function () {
        if (generationId === generation) {
          fitAndSend();
        }
      });
      fetchImpl(node.dataset.consoleUrl, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {'X-CSRFToken': node.dataset.csrf || ''}
      }).then(function (response) {
        return response.json().then(function (body) {
          return {ok: response.ok, body: body || {}};
        });
      }).then(function (result) {
        if (generationId !== generation) {
          return;
        }
        var url = sessionUrl(result.body && result.body.url);
        if (!result.ok || !url) {
          stop('error', (result.body && result.body.error) || UNABLE);
          return;
        }
        attachSocket(url, generationId);
      }).catch(function () {
        if (generationId === generation) {
          stop('error', UNABLE);
        }
      });
    }

    connect.addEventListener('click', openSession);
    reconnect.addEventListener('click', openSession);
    setButtons('idle');
  }

  function loadScript(documentRef, src) {
    return new Promise(function (resolve, reject) {
      if (!src) {
        reject(new Error('missing script'));
        return;
      }
      if (documentRef.querySelector('script[src="' + src + '"]')) {
        resolve();
        return;
      }
      var script = documentRef.createElement('script');
      script.src = src;
      script.onload = function () {
        resolve();
      };
      script.onerror = function () {
        reject(new Error('load'));
      };
      documentRef.head.appendChild(script);
    });
  }

  function mountAll(doc) {
    var documentRef = doc || root.document;
    var nodes = documentRef.querySelectorAll(
      '.coast-console:not([data-bound])');
    Array.prototype.forEach.call(nodes, function (node) {
      node.dataset.bound = '1';
      var css = node.dataset.css;
      if (css && !documentRef.querySelector('link[href="' + css + '"]')) {
        var link = documentRef.createElement('link');
        link.rel = 'stylesheet';
        link.href = css;
        documentRef.head.appendChild(link);
      }
      loadScript(documentRef, node.dataset.xterm).then(function () {
        return loadScript(documentRef, node.dataset.fit);
      }).then(function () {
        bind(node);
      }).catch(function () {
        var statusNode = node.querySelector('.coast-console-status');
        if (statusNode) {
          statusNode.textContent = CANNOT_START;
        }
      });
    });
  }

  root.coastConsole = {
    resizePayload: resizePayload,
    inputFrame: inputFrame,
    readFrame: readFrame,
    endedText: endedText,
    sessionUrl: sessionUrl,
    fitClass: fitClass,
    bind: bind,
    mountAll: mountAll
  };
})(typeof window !== 'undefined' ? window : globalThis);
