/* Copyright 2026 Gozunga and Coast contributors. Licensed under Apache-2.0. */
(function () {
  'use strict';

  function init(root) {
    root.querySelectorAll('form[data-coast-oneclick]').forEach(function (form) {
      if (form.dataset.coastReady) { return; }
      form.dataset.coastReady = 'true';
      var data = JSON.parse(form.querySelector('script[type="application/json"]').textContent);
      var fields = {};
      ['template_id', 'appgroup_id'].forEach(function (key) {
        fields[key] = form.elements.namedItem(key);
      });
      var previousTemplate = fields.template_id.value;
      var healthDirty = Boolean(data.bound);
      var healthFields = ['health_check', 'health_check_port', 'healthcheck_path'];
      healthFields.forEach(function (key) {
        var field = form.elements.namedItem(key);
        if (!field) { return; }
        ['input', 'change'].forEach(function (event) {
          field.addEventListener(event, function () { healthDirty = true; });
        });
      });

      function choose(key, allowed) {
        var field = fields[key];
        if (field.disabled) { return; }
        var options = Array.from(field.options);
        var valid = options.filter(function (option) {
          if (!option.value) {
            option.disabled = false;
            option.hidden = false;
            return false;
          }
          return allowed(option.value);
        }).map(function (option) { return option.value; });
        if (valid.indexOf(field.value) !== -1) {
          return;
        }
        // Keep app group empty until one compatible choice remains.
        if (key !== 'template_id') {
          field.value = valid.length === 1 ? valid[0] : '';
          return;
        }
        field.value = '';
      }

      function update(changed) {
        if (changed === 'template_id') {
          choose('appgroup_id', function (id) {
            return !fields.template_id.value ||
              (data.templates[data.groups[id]] || []).indexOf(fields.template_id.value) !== -1;
          });
          fields.appgroup_id.dispatchEvent(new Event('change', {bubbles: true}));
        } else if (fields.appgroup_id.value) {
          choose('template_id', function (id) {
            return (data.templates[data.groups[fields.appgroup_id.value]] || []).indexOf(id) !== -1;
          });
        }
        if (fields.template_id.value !== previousTemplate) {
          if (!healthDirty) {
            var port = (data.http_ports || {})[fields.template_id.value];
            var http = port !== null && port !== undefined;
            var values = [http ? 'http' : 'none', http ? port : '', http ? '/' : ''];
            healthFields.forEach(function (key, index) {
              var field = form.elements.namedItem(key);
              if (field) { field.value = values[index]; }
            });
          }
          previousTemplate = fields.template_id.value;
        }
      }

      Object.keys(fields).forEach(function (key) {
        fields[key].addEventListener('change', function () { update(key); });
      });
      update('appgroup_id');
    });
  }

  horizon.addInitFunction(function () { init(document); });
  horizon.modals.addModalInitFunction(function (modal) { init((modal && modal[0]) || document); });
}());
