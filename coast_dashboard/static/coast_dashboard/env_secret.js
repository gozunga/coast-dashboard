/*
 * Mask an environment variable value only while Secret is checked.
 * Delegated on the document so it also works for forms loaded in modals.
 */
(function () {
  'use strict';
  document.addEventListener('change', function (event) {
    var secret = event.target;
    if (secret.name !== 'secret' || !secret.form) { return; }
    var value = secret.form.querySelector('.coast-env-value');
    if (value) {
      value.style.webkitTextSecurity = secret.checked ? 'disc' : '';
    }
  });
}());
