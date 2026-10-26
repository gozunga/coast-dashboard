# Copyright 2026 Gozunga and Coast contributors
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.


"""Runs the Default domain live preview script with Node and a tiny DOM."""

import json
import os
import re
import shutil
import subprocess
import unittest

TEMPLATE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), 'templates', 'project',
    'coast_stacks', '_dns_preview.html')

HARNESS = r"""
function el(props) {
  var e = Object.assign({hidden: false, textContent: '', dataset: {}}, props);
  return e;
}
var listeners = {};
var zone = el({value: 'z', selectedIndex: 1,
               options: [{text: 'Manual DNS / no zone'},
                         {text: 'Example.COM.'}]});
var host = el({value: ''});
var parts = {'.coast-dd-zone': el({}), '.coast-dd-none': el({}),
             '.coast-dd-preview': el({})};
var form = {
  querySelector: function (s) {
    return {'[name="zone_id"]': zone, '[name="host"]': host}[s];
  },
  addEventListener: function (name, fn) { listeners[name] = fn; }
};
var box = el({closest: function () { return form; },
              querySelector: function (s) { return parts[s]; }});
var document = {querySelectorAll: function () { return [box]; }};
var window = {};
function jQuery(fn) { fn(); }
function state() {
  return parts['.coast-dd-zone'].hidden ? 'sslip' :
    parts['.coast-dd-preview'].textContent;
}
var out = [];
SCRIPT
out.push(state());
host.value = 'apps'; listeners.input(); out.push(state());
host.value = ' Apps.example.com. '; listeners.input(); out.push(state());
host.value = 'example.com'; listeners.input(); out.push(state());
zone.options[1].text = 'other.test.'; listeners.change(); out.push(state());
host.value = 'apps'; listeners.input(); out.push(state());
zone.value = ''; zone.selectedIndex = 0; listeners.change(); out.push(state());
out.push(parts['.coast-dd-none'].hidden);
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class DefaultDomainPreviewScriptTest(unittest.TestCase):
    def test_preview_follows_zone_and_host(self):
        page = open(TEMPLATE).read()
        script = re.search(r'<script>(.*?)</script>', page, re.S).group(1)
        result = subprocess.run(
            ['node', '-e', HARNESS.replace('SCRIPT', script)],
            capture_output=True, text=True, timeout=30, check=True)
        self.assertEqual(
            ['example.com', 'apps.example.com', 'apps.example.com',
             'example.com', 'example.com.other.test', 'apps.other.test',
             'sslip', False],
            json.loads(result.stdout))
