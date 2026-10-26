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

import json
from unittest import mock

from django.urls import reverse

from coast_dashboard.api import coast
from coast_dashboard.content import common
from coast_dashboard.tests import helpers
from coast_dashboard.tests.test_navigation_settings import APP
from coast_dashboard.tests.test_navigation_settings import SERVICE


SESSION = {'url': 'wss://console.example/session?token=abc',
           'expires_at': '2026-10-18T00:01:00Z'}


def _response(body):
    response = mock.Mock(content=b'x')
    response.json.return_value = body
    return response


class ConsoleApiTests(helpers.TestCase):

    @mock.patch.object(coast, 'coastclient')
    def test_app_and_service_console_paths(self, client):
        client.return_value.adapter.request.return_value = _response(SESSION)
        for kind, collection, resource in (
                ('app', 'apps', 'app-1'),
                ('service', 'services', 'svc-1')):
            body = coast.service_console(self.request, resource, kind)
            self.assertEqual(SESSION['url'], body['url'])
            client.return_value.adapter.request.assert_called_with(
                '/%s/%s/console' % (collection, resource), 'POST',
                microversion='1.9', log=False, connect_retries=0,
                status_code_retries=0)
        client.assert_called_with(self.request, '1.0')
        client.return_value.request.assert_not_called()

    @mock.patch.object(coast, 'coastclient')
    def test_command_is_optional_one_off_exec(self, client):
        client.return_value.adapter.request.return_value = _response(SESSION)
        coast.service_console(self.request, 'app-1', 'app',
                              command=['sh', '-c', 'true'])
        client.return_value.adapter.request.assert_called_once_with(
            '/apps/app-1/console', 'POST', microversion='1.9', log=False,
            connect_retries=0, status_code_retries=0,
            json={'command': ['sh', '-c', 'true']})

    def test_rejects_bad_command_and_kind(self):
        for command in ((), ['ok', 1], [''], 'sh'):
            with self.assertRaises(ValueError):
                coast.service_console(self.request, 'app-1', 'app',
                                      command=command)
        with self.assertRaises(ValueError):
            coast.service_console(self.request, 'app-1', 'stack')

    def test_session_url_accepts_only_wss_without_userinfo(self):
        self.assertEqual('wss://console.example/s?token=abc',
                         coast.console_session_url(
                             '  wss://console.example/s?token=abc  '))
        for value in ('ws://console.example/s', 'https://console.example/s',
                      'wss://user:secret@console.example/s',
                      'wss:///missing-host', '', None, 5):
            self.assertIsNone(coast.console_session_url(value))


class _RoleRequest:
    def __init__(self, roles):
        self.user = mock.Mock(roles=roles)


class ConsoleViewTests(helpers.TestCase):

    def setUp(self):
        super().setUp()
        self.rows = {APP['id']: dict(APP), SERVICE['id']: dict(SERVICE)}
        for name, result in (
                ('stack_list', []), ('stack_server_list', []),
                ('appgroup_list', []), ('environment_list', []),
                ('service_domain_list', []), ('service_env_list', []),
                ('storage_list', []),
                ('service_deployment_list', [])):
            patcher = mock.patch.object(coast, name, return_value=result)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(
            coast, 'service_get', side_effect=self._get)
        self.service_get = patcher.start()
        self.addCleanup(patcher.stop)

    def _get(self, request, service_id):
        return dict(self.rows[service_id])

    def _use(self, roles):
        self.setActiveUser(
            id=self.user.id, token=self.token, username=self.user.name,
            tenant_id=self.tenant.id, service_catalog=self.service_catalog,
            roles=roles)

    def _detail(self, resource_id):
        return self.client.get(reverse(
            'horizon:project:coast.apps:detail', args=[resource_id]),
            {'tab': 'service_details__console'})

    def test_member_roles(self):
        self.assertTrue(common.project_member(_RoleRequest(
            [{'name': 'member'}])))
        self.assertTrue(common.project_member(_RoleRequest(
            [{'name': 'Admin'}])))
        self.assertTrue(common.project_member(_RoleRequest(
            [{'name': 'reader'}, {'name': 'member'}])))
        self.assertFalse(common.project_member(_RoleRequest(
            [{'name': 'reader'}])))
        self.assertFalse(common.project_member(_RoleRequest([])))

    def test_tab_for_member_on_app_and_service(self):
        for row in (APP, SERVICE):
            response = self._detail(row['id'])
            names = [str(tab.name) for tab in
                     response.context['tab_group'].get_tabs()]
            self.assertIn('Console', names)
            self.assertContains(response, '15 minutes with no input')
            self.assertContains(response, 'does not record keystrokes')
            self.assertContains(response, '>Connect<')
            self.assertContains(response, '>Reconnect<')
            self.assertContains(
                response, reverse('horizon:project:coast.apps:console',
                                  args=[row['id']]))
            self.assertContains(response, 'vendor/xterm/xterm.js')
            self.assertContains(response, 'vendor/xterm/addon-fit.js')
            self.assertContains(response, 'vendor/xterm/xterm.css')
            self.assertContains(response, 'coast_dashboard/console.js')
            for banned in ('Coolify', 'HAProxy', 'console-proxy',
                           'nsenter', 'docker'):
                self.assertNotContains(response, banned)

    def test_reader_does_not_see_the_tab(self):
        self._use([{'id': '3', 'name': 'reader'}])
        response = self._detail(APP['id'])
        names = [str(tab.name) for tab in
                 response.context['tab_group'].get_tabs()]
        self.assertNotIn('Console', names)
        self.assertNotContains(response, 'coast-console')

    def test_admin_sees_the_tab(self):
        self._use([{'id': '1', 'name': 'admin'}])
        response = self._detail(SERVICE['id'])
        names = [str(tab.name) for tab in
                 response.context['tab_group'].get_tabs()]
        self.assertIn('Console', names)

    @mock.patch.object(coast, 'service_console', return_value=SESSION)
    def test_post_returns_session_for_app_and_service(self, console):
        for row, kind in ((APP, 'app'), (SERVICE, 'service')):
            console.reset_mock()
            response = self.client.post(
                reverse('horizon:project:coast.apps:console',
                        args=[row['id']]),
                data=json.dumps({'command': ['id']}),
                content_type='application/json')
            self.assertEqual(200, response.status_code)
            self.assertEqual(SESSION, response.json())
            console.assert_called_once_with(mock.ANY, row['id'], kind)

    @mock.patch.object(coast, 'service_console', return_value=SESSION)
    def test_reader_post_does_not_open_a_session(self, console):
        self._use([{'name': 'reader'}])
        self.service_get.reset_mock()
        response = self.client.post(reverse(
            'horizon:project:coast.apps:console', args=[APP['id']]))
        self.assertEqual(403, response.status_code)
        self.assertEqual('You cannot open a console session.',
                         response.json()['error'])
        console.assert_not_called()
        self.service_get.assert_not_called()

    def test_get_is_not_allowed(self):
        response = self.client.get(reverse(
            'horizon:project:coast.apps:console', args=[APP['id']]))
        self.assertEqual(405, response.status_code)

    @mock.patch.object(coast, 'service_console')
    def test_rejects_insecure_address_without_echoing_it(self, console):
        console.return_value = {'url': 'http://console.example/secret-token'}
        response = self.client.post(reverse(
            'horizon:project:coast.apps:console', args=[APP['id']]))
        self.assertEqual(502, response.status_code)
        self.assertIn('secure address', response.json()['error'])
        self.assertNotIn('secret-token', response.content.decode())

    @mock.patch.object(coast, 'service_console',
                       side_effect=coast.CoastError(
                           'The resource is not running.'))
    def test_api_error_is_shown(self, console):
        response = self.client.post(reverse(
            'horizon:project:coast.apps:console', args=[APP['id']]))
        self.assertEqual(400, response.status_code)
        self.assertEqual('The resource is not running.',
                         response.json()['error'])
        self.assertNotIn('Coolify', response.content.decode())

    @mock.patch.object(coast, 'service_console')
    def test_unknown_kind_does_not_call_the_api(self, console):
        self.rows[APP['id']]['kind'] = 'other'
        response = self.client.post(reverse(
            'horizon:project:coast.apps:console', args=[APP['id']]))
        self.assertEqual(400, response.status_code)
        console.assert_not_called()
