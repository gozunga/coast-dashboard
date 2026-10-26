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

"""Project pages never name the application engine or its proxy."""

import ast
import os
import pathlib
import re
from unittest import mock

from coast_dashboard.api import coast
from coast_dashboard import public_text
from coast_dashboard.tests import helpers

ROOT = pathlib.Path(__file__).resolve().parents[1]
# Assembled so this file does not itself trip a repository-wide grep.
NAMES = re.compile('cool' + 'ify|traef' + 'ik', re.IGNORECASE)
ENGINE = 'Cool' + 'ify'
PROXY = 'Traef' + 'ik'


def _resp(body):
    response = mock.Mock(content=b'x')
    response.json.return_value = body
    return response


class ScrubTests(helpers.TestCase):
    def test_scrub_replaces_every_case(self):
        for text in (ENGINE, ENGINE.upper(), ENGINE.lower(), PROXY,
                     PROXY.lower(), '%s via %s' % (ENGINE, PROXY)):
            with self.subTest(text=text):
                result = public_text.scrub(text)
                self.assertIsNone(NAMES.search(result))
        self.assertEqual('App engine server timed out',
                         public_text.scrub(ENGINE + ' timed out'))
        self.assertEqual('proxy restarted',
                         public_text.scrub(PROXY.lower() + ' restarted'))

    def test_scrub_tree_text_keys_and_data_keys(self):
        body = {
            'deployment': {
                'fault': ENGINE + ' API error',
                'status_reason': PROXY + ' down',
                'build_error': ENGINE + ' failed',
                'details': {'message': [ENGINE + ' says no']},
                'name': 'web',
            },
            'logs': {'note': ENGINE + ' unreachable',
                     'unavailable': PROXY + ' gone',
                     'lines': [{'line': 'user output ' + ENGINE}]},
            'env': {ENGINE.upper() + '_VOLUME_APP': ENGINE},
            'events': [{'reason': ENGINE}],
            'count': 3,
        }
        result = public_text.scrub_tree(body)
        deployment = result['deployment']
        for value in (deployment['fault'], deployment['status_reason'],
                      deployment['build_error'],
                      deployment['details']['message'][0],
                      result['logs']['note'], result['logs']['unavailable'],
                      result['events'][0]['reason']):
            self.assertIsNone(NAMES.search(value), value)
        self.assertEqual('web', deployment['name'])
        # Customer data and engine log output are not rewritten.
        self.assertEqual(body['logs']['lines'], result['logs']['lines'])
        self.assertEqual(body['env'], result['env'])
        self.assertEqual(3, result['count'])
        self.assertEqual(ENGINE + ' API error', body['deployment']['fault'])

    def test_environment_resource_is_not_data(self):
        body = {'environment': {'id': 'e', 'status_reason': PROXY + ' down'},
                'env': {'A': PROXY}}
        result = public_text.scrub_tree(body)
        self.assertEqual('proxy down', result['environment']['status_reason'])
        self.assertEqual({'A': PROXY}, result['env'])


class BoundaryTests(helpers.TestCase):
    """Every Coast response passes ``api.coast._request``."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(coast, 'dns_supported', return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    @mock.patch.object(coast, 'coastclient')
    def test_project_reads_are_scrubbed(self, client):
        body = {'deployment': {'id': 'd', 'fault': ENGINE + ' 500'}}
        client.return_value.request.return_value = _resp(body)
        client.return_value.adapter.request.return_value = _resp(body)
        item = coast.service_deployment_get(self.request, 'a', 'd')
        self.assertEqual('d', item['id'])
        self.assertEqual('App engine server 500', item['fault'])

    @mock.patch.object(coast, 'coastclient')
    def test_project_writes_are_scrubbed(self, client):
        body = {'backup': {'id': 'b', 'error': PROXY + ' refused'}}
        client.return_value.request.return_value = _resp(body)
        client.return_value.adapter.request.return_value = _resp(body)
        result = coast._write(self.request, '/backups', 'POST', {})
        self.assertEqual('proxy refused', result['backup']['error'])

    @mock.patch.object(coast, 'coastclient')
    def test_catalog_prose_is_scrubbed(self, client):
        body = {'templates': [{
            'id': 'proxy-ui', 'name': PROXY + ' dashboard',
            'description': 'Runs behind ' + PROXY, 'category': 'Network',
            'ports': [80]}]}
        client.return_value.request.return_value = _resp(body)
        client.return_value.adapter.request.return_value = _resp(body)
        item = coast.template_list(self.request, 's1')[0]
        self.assertEqual('proxy-ui', item['id'])
        self.assertEqual('proxy dashboard', item['name'])
        self.assertEqual('Runs behind proxy', item['description'])
        self.assertEqual([80], item['ports'])

    @mock.patch.object(coast, 'coastclient')
    def test_service_template_name_is_scrubbed(self, client):
        body = {'service': {'id': 'svc', 'template_name': PROXY + ' UI',
                            'source': {'type': 'template',
                                       'template_name': PROXY + ' UI'}}}
        client.return_value.request.return_value = _resp(body)
        client.return_value.adapter.request.return_value = _resp(body)
        result = coast._get(self.request, '/services/svc')['service']
        self.assertEqual('proxy UI', result['template_name'])
        self.assertEqual('proxy UI', result['source']['template_name'])

    @mock.patch.object(coast, 'coastclient')
    def test_compose_yaml_and_env_are_kept(self, client):
        yaml = 'services:\n  web:\n    labels:\n      - %s.enable=true\n' % (
            PROXY.lower())
        body = {'compose': {'yaml': yaml},
                'env': {ENGINE.upper() + '_VOLUME_APP': 'x'}}
        client.return_value.request.return_value = _resp(body)
        client.return_value.adapter.request.return_value = _resp(body)
        self.assertEqual(body, coast._get(self.request, '/services/s/env'))
        self.assertEqual(yaml, coast._get(
            self.request, '/services/s/compose')['compose']['yaml'])

    @mock.patch.object(coast, 'coastclient')
    def test_admin_all_projects_reads_keep_detail(self, client):
        body = {'stack': {'id': 's1', 'status_reason': ENGINE + ' down'}}
        client.return_value.request.return_value = _resp(body)
        client.return_value.adapter.request.return_value = _resp(body)
        result = coast._get(self.request, '/stacks/s1?all_projects=true')
        self.assertEqual(ENGINE + ' down', result['stack']['status_reason'])
        self.assertFalse(coast._admin_read('/stacks/s1?all_projects=false'))
        self.assertFalse(coast._admin_read('/stacks/all_projects=true'))

    def test_fault_message_is_scrubbed(self):
        exc = mock.Mock()
        exc.response.status_code = 409
        exc.response.json.return_value = {
            'faultstring': ENGINE + ' rejected the deploy'}
        self.assertEqual('App engine server rejected the deploy',
                         coast.fault_message(exc))


def _customer_files():
    templates = ROOT / 'templates'
    for path in sorted(templates.rglob('*')):
        if path.is_file() and 'admin' not in path.relative_to(
                templates).parts:
            yield path
    static = ROOT / 'static'
    for path in sorted(static.rglob('*')):
        if path.is_file() and 'vendor' not in path.relative_to(
                static).parts:
            yield path
    for path in sorted(ROOT.rglob('*.po')):
        yield path


def _python_strings(path):
    """String constants in ``path`` except docstrings and comments."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, 'body', [])
            if (body and isinstance(body[0], ast.Expr) and
                    isinstance(body[0].value, ast.Constant)):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docstrings):
            yield node.lineno, node.value


class CustomerStringLintTests(helpers.TestCase):
    """Fail if a project-facing string names the engine or proxy.

    The admin panel (content/admin, templates/admin) may name them; it is
    served only to cloud admins. ``public_text`` is the one place that
    spells them, to replace them.
    """

    def test_templates_static_and_translations(self):
        found = []
        for path in _customer_files():
            text = path.read_text(encoding='utf-8', errors='replace')
            for number, line in enumerate(text.splitlines(), 1):
                if NAMES.search(line):
                    found.append('%s:%d' % (path.relative_to(ROOT), number))
        self.assertEqual([], found)

    def test_python_strings(self):
        skip = (ROOT / 'tests', ROOT / 'content' / 'admin')
        found = []
        for path in sorted(ROOT.rglob('*.py')):
            if (path == ROOT / 'public_text.py' or
                    any(part in path.parents for part in skip)):
                continue
            for number, value in _python_strings(path):
                if NAMES.search(value):
                    found.append('%s:%d' % (path.relative_to(ROOT), number))
        self.assertEqual([], found)

    def test_lint_sees_the_tree(self):
        files = list(_customer_files())
        self.assertTrue(any(p.suffix == '.html' for p in files))
        self.assertTrue(any(p.suffix == '.js' for p in files))
        self.assertTrue(os.path.exists(ROOT / 'api' / 'coast.py'))
