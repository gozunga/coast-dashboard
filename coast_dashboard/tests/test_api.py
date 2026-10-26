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

from unittest import mock

from coast_dashboard.api import coast
from coast_dashboard.tests import helpers


def _resp(body):
    response = mock.Mock(content=b'x')
    response.json.return_value = body
    return response


class CoastApiTests(helpers.TestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(coast, 'dns_supported', return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    @mock.patch.object(coast, 'coastclient')
    def test_template_catalog_406_uses_default_version(self, client):
        client.return_value.adapter.request.side_effect = (
            coast.client_exceptions.NotAcceptable())
        template = {'id': 'db', 'ports': [5432]}
        client.return_value.request.return_value = _resp(
            {'templates': [template]})
        items = coast.template_list(self.request, 's1')
        self.assertEqual([template], items)
        self.assertIsNone(items[0].get('http_port'))
        client.assert_called_once_with(self.request, '1.0')
        client.return_value.adapter.request.assert_called_once_with(
            '/templates?stack_id=s1', 'GET', microversion='1.7', log=False,
            connect_retries=0, status_code_retries=0)
        client.return_value.request.assert_called_once_with(
            '/templates?stack_id=s1', 'GET')

    @mock.patch.object(coast, 'coastclient')
    def test_template_catalog_other_errors_do_not_retry(self, client):
        for error, expected in (
                (coast.client_exceptions.Unauthorized,
                 coast.exceptions.NotAuthorized),
                (coast.client_exceptions.NotFound, coast.exceptions.NotFound),
                (coast.client_exceptions.Forbidden, coast.CoastError),
                (coast.client_exceptions.InternalServerError,
                 coast.CoastError)):
            with self.subTest(error=error):
                client.reset_mock()
                client.return_value.adapter.request.side_effect = error()
                with self.assertRaises(expected):
                    coast.template_list(self.request, 's1')
                self.assertEqual(
                    1, client.return_value.adapter.request.call_count)
                client.return_value.request.assert_not_called()

    @mock.patch.object(coast, 'coastclient')
    def test_template_catalog_fallback_failure_is_not_retried(self, client):
        client.return_value.adapter.request.side_effect = (
            coast.client_exceptions.NotAcceptable())
        client.return_value.request.side_effect = (
            coast.client_exceptions.NotAcceptable())
        with self.assertRaises(coast.CoastError):
            coast.template_list(self.request, 's1')
        self.assertEqual(1, client.return_value.adapter.request.call_count)
        self.assertEqual(1, client.return_value.request.call_count)

    @mock.patch.object(coast, 'coastclient')
    def test_template_catalog_pagination_keeps_version_and_stack(self, client):
        templates = [{'id': 'web', 'http_port': 8080},
                     {'id': 'db', 'http_port': None}]
        client.return_value.adapter.request.side_effect = [
            _resp({'templates': templates[:1], 'links': [{
                'rel': 'next',
                'href': 'https://other/templates?marker=web'}]}),
            _resp({'templates': templates[1:]})]
        self.assertEqual(templates, coast.template_list(self.request, 's1'))
        self.assertEqual([
            mock.call('/templates?stack_id=s1', 'GET', microversion='1.7',
                      log=False, connect_retries=0, status_code_retries=0),
            mock.call('/templates?stack_id=s1&marker=web', 'GET',
                      microversion='1.7', log=False, connect_retries=0,
                      status_code_retries=0)],
            client.return_value.adapter.request.call_args_list)
        client.return_value.request.assert_not_called()

    @mock.patch.object(coast, 'coastclient')
    def test_health_read_406_does_not_use_catalog_fallback(self, client):
        client.return_value.adapter.request.side_effect = (
            coast.client_exceptions.NotAcceptable())
        with self.assertRaises(coast.CoastError):
            coast.service_get(self.request, 's1')
        client.return_value.request.assert_not_called()

    @mock.patch.object(coast, 'coastclient')
    def test_service_get_health_check_microversion(self, client):
        service = {'id': 'worker', 'health_check': 'none'}
        client.return_value.adapter.request.return_value = _resp(
            {'service': service})
        self.assertEqual(service, coast.service_get(self.request, 'worker'))
        client.assert_called_once_with(self.request, '1.0')
        client.return_value.adapter.request.assert_called_once_with(
            '/services/worker', 'GET', microversion='1.24', log=False,
            connect_retries=0, status_code_retries=0)
        client.return_value.request.assert_not_called()

    @mock.patch.object(coast, 'coastclient')
    def test_health_check_edit_uses_per_call_version(self, client):
        client.return_value.request.return_value = _resp(
            {'service': {'id': 'app'}})
        values = {'health_check': 'none', 'ports': ''}
        coast.service_update(self.request, 'app', values)
        client.assert_called_once_with(self.request, '1.0')
        client.return_value.request.assert_called_once_with(
            '/services/app', 'PATCH', json={'service': values},
            health_check_microversion='1.4')

    @mock.patch.object(coast, 'coastclient')
    def test_create_worker_omits_default_probe(self, client):
        client.return_value.request.return_value = _resp(
            {'service': {'id': 'app'}})
        coast.service_create(self.request, 'worker', 'a', 'e', 'w',
                             {'type': 'image'}, ports='')
        call = client.return_value.request.call_args.kwargs
        self.assertNotIn('health_check_microversion', call)
        self.assertNotIn('health_check', call['json']['service'])
        self.assertEqual('', call['json']['service']['ports'])

    @mock.patch.object(coast, 'coastclient')
    def test_appgroup_list_all_stacks(self, client):
        client.return_value.request.side_effect = [
            _resp({'stacks': [{'id': 's1'}, {'id': 's2'}]}),
            _resp({'appgroups': [{'id': 'a1'}]}),
            _resp({'appgroups': [{'id': 'a2'}]}),
        ]
        apps = coast.appgroup_list(self.request)
        self.assertEqual(['a1', 'a2'], [a['id'] for a in apps])
        client.return_value.request.assert_any_call(
            '/stacks/s2/appgroups', 'GET')

    @mock.patch.object(coast, 'coastclient')
    def test_stack_get(self, client):
        client.return_value.request.return_value = _resp(
            {'stack': {'id': 's1'}})
        self.assertEqual({'id': 's1'}, coast.stack_get(self.request, 's1'))
        client.return_value.request.assert_called_once_with(
            '/stacks/s1', 'GET')

    @mock.patch.object(coast, 'coastclient')
    def test_read_routes(self, client):
        reads = [
            (coast.stack_list, (), '/stacks', 'stacks', []),
            (coast.stack_server_list, ('s',), '/stacks/s/servers',
             'servers', []),
            (coast.stack_server_get, ('s', 'v'), '/stacks/s/servers/v',
             'server', {'id': 'v'}),
            (coast.environment_get, ('e',), '/environments/e',
             'environment', {'id': 'e'}),
            (coast.service_list, (), '/services', 'services', []),
            (coast.service_deployment_list, ('a',),
             '/services/a/deployments?sort_key=created_at&sort_dir=desc',
             'deployments', []),
            (coast.service_deployment_get, ('a', 'd'),
             '/services/a/deployments/d', 'deployment', {'id': 'd'}),
            (coast.service_domain_list, ('a',), '/services/a/domains',
             'domains', []),
            (coast.service_domain_get, ('a', 'd'), '/services/a/domains/d',
             'domain', {'id': 'd'}),
            (coast.service_logs, ('a',), '/services/a/logs',
             'logs', {'lines': []}),
        ]
        for function, args, path, key, value in reads:
            with self.subTest(path=path):
                client.reset_mock()
                client.return_value.request.return_value = _resp({key: value})
                client.return_value.adapter.request.return_value = _resp(
                    {key: value})
                self.assertEqual(value, function(self.request, *args))
                if function in (coast.service_list, coast.service_domain_list,
                                coast.service_domain_get,
                                coast.stack_server_list,
                                coast.stack_server_get):
                    version = {
                        coast.stack_server_list: '1.27',
                        coast.stack_server_get: '1.27',
                        coast.service_list: '1.24',
                    }.get(function, '1.23')
                    adapter = client.return_value.adapter
                    adapter.request.assert_called_once_with(
                        path, 'GET', microversion=version, log=False,
                        connect_retries=0, status_code_retries=0)
                else:
                    client.return_value.request.assert_called_once_with(
                        path, 'GET')

    @mock.patch.object(coast, 'coastclient')
    def test_stack_create(self, client):
        client.return_value.request.return_value = _resp(
            {'stack': {'id': 's'}})
        self.assertEqual({'id': 's'}, coast.stack_create(
            self.request, 'demo', 'm1.small', 'm1.medium', 2, True))
        client.return_value.request.assert_called_once_with(
            '/stacks', 'POST', json={'stack': {
                'name': 'demo', 'plan': 'm1.small', 'build_server': True,
                'workers': [{'kind': 'vm', 'plan': 'm1.medium'}] * 2}})

    @mock.patch.object(coast, 'coastclient')
    def test_stack_build_plan(self, client):
        client.return_value.request.return_value = _resp({'stack': {}})
        for enabled in (True, False):
            coast.stack_create(self.request, 'demo', 'm1.small', 'm1.medium',
                               build_server=enabled,
                               build_server_plan='m1.large')
            body = client.return_value.request.call_args.kwargs['json']
            stack = body['stack']
            version = client.call_args.args[1]
            if enabled:
                self.assertEqual('m1.large', stack['build_server_plan'])
                self.assertEqual('1.1', version)
            else:
                self.assertNotIn('build_server_plan', stack)
                self.assertEqual('1.0', version)

    @mock.patch.object(coast, 'coastclient')
    def test_api_fault_message_kept_for_4xx_only(self, client):
        for status, body, expected in [
                (400, {'faultstring': 'Flavor x is not available for '
                       'build servers.'},
                 'Flavor x is not available for build servers.'),
                (409, {'detail': 'Busy.'}, 'Busy.'),
                (500, {'faultstring': 'internal secret'}, None),
                (400, ['not', 'a', 'dict'], None)]:
            response = mock.Mock(status_code=status)
            response.json.return_value = body
            client.return_value.request.side_effect = (
                coast.client_exceptions.BadRequest(response=response))
            with self.assertRaises(coast.CoastError) as caught:
                coast.stack_create(self.request, 'n', 'p', 'w')
            self.assertEqual(expected, caught.exception.api_message)
            self.assertEqual(expected or 'Default',
                             coast.error_message(caught.exception, 'Default'))

    @mock.patch.object(coast, 'coastclient')
    def test_webhooks_use_per_call_1_3(self, client):
        client.return_value.request.return_value = _resp(
            {'webhooks': {'enabled': True}})
        self.assertEqual({'enabled': True},
                         coast.service_webhooks(self.request, 's'))
        self.assertEqual('1.0', client.call_args.args[1])
        client.return_value.request.assert_called_with(
            '/services/s/webhooks', 'GET', webhooks_microversion='1.3')

    @mock.patch.object(coast, 'coastclient')
    def test_plan_list_uses_1_1(self, client):
        client.return_value.request.return_value = _resp(
            {'plans': [{'name': 'p', 'flavor': 'f'}]})
        self.assertEqual([{'name': 'p', 'flavor': 'f'}],
                         coast.plan_list(self.request))
        self.assertEqual('1.1', client.call_args.args[1])

    @mock.patch.object(coast, 'coastclient')
    def test_service_create_and_deploy(self, client):
        source = {'type': 'git', 'repo_url': 'https://example.com/app.git'}
        client.return_value.request.return_value = _resp(
            {'service': {'id': 's'}})
        self.assertEqual({'id': 's'}, coast.service_create(
            self.request, 'web', 'a', 'e', None, source))
        client.return_value.request.assert_called_once_with(
            '/services', 'POST', json={'service': {
                'name': 'web', 'appgroup_id': 'a', 'environment_id': 'e',
                'server_id': None, 'source': source, 'ports': '8080',
                'deploy': True}})
        client.return_value.request.return_value = _resp(
            {'deployment': {'id': 'd'}})
        self.assertEqual({'id': 'd'}, coast.service_deploy(self.request, 's'))
        client.return_value.request.assert_called_with(
            '/services/s/deployments', 'POST', json={'deployment': {}})

    @mock.patch.object(coast, 'coastclient')
    def test_deletes_with_empty_response(self, client):
        client.return_value.request.return_value = mock.Mock(content=b'')
        for function, path in [(coast.stack_delete, '/stacks/s'),
                               (coast.service_delete, '/services/s'),
                               (coast.appgroup_delete, '/appgroups/s'),
                               (coast.environment_delete, '/environments/s')]:
            self.assertEqual({}, function(self.request, 's'))
            client.return_value.request.assert_called_with(path, 'DELETE')

    @mock.patch.object(coast, 'coastclient')
    def test_environments_across_appgroups(self, client):
        client.return_value.request.side_effect = [
            _resp({'stacks': [{'id': 's'}]}),
            _resp({'appgroups': [{'id': 'a'}, {'id': 'b'}]}),
            _resp({'environments': [{'id': 'e'}]}),
            _resp({'environments': [{'id': 'f'}]}),
        ]
        self.assertEqual([{'id': 'e'}, {'id': 'f'}],
                         coast.environment_list(self.request))
        client.return_value.request.assert_called_with(
            '/appgroups/b/environments', 'GET')

    @mock.patch.object(coast, 'coastclient')
    def test_pagination_uses_original_path(self, client):
        client.return_value.adapter.request.side_effect = [
            _resp({'services': [{'id': 'a'}], 'links': [{
                'rel': 'next',
                'href': 'https://other/v1/services?marker=a'}]}),
            _resp({'services': [{'id': 'b'}]}),
        ]
        self.assertEqual([{'id': 'a'}, {'id': 'b'}],
                         coast.service_list(self.request))
        client.return_value.adapter.request.assert_called_with(
            '/services?marker=a', 'GET', microversion='1.24', log=False,
            connect_retries=0, status_code_retries=0)

    @mock.patch.object(coast, 'coastclient')
    def test_repeated_pagination_is_rejected(self, client):
        client.return_value.adapter.request.return_value = _resp({
            'services': [], 'links': [{'rel': 'next', 'href': '?marker=a'}]})
        self.assertRaises(ValueError, coast.service_list, self.request)

    @mock.patch.object(coast, 'coastclient')
    def test_secret_values_are_removed(self, client):
        client.return_value.request.return_value = _resp({'env': {
            'PASSWORD': {'value': 'must-never-render', 'secret': True},
            'NULL_SECRET': {'value': None, 'secret': True},
            'MODE': {'value': 'production', 'secret': False,
                     'build_time': False}}})
        values = coast.service_env_list(self.request, 's')
        self.assertEqual(['production', '********', '********'],
                         [item['value'] for item in values])
        self.assertNotIn('must-never-render', str(values))
        self.assertFalse(values[0]['build_time'])
        self.assertIsNone(values[1]['build_time'])
        self.assertIsNone(values[2]['build_time'])

    @mock.patch.object(coast, 'coastclient')
    def test_api_failure_is_not_hidden(self, client):
        client.return_value.adapter.request.side_effect = RuntimeError(
            'unavailable')
        self.assertRaises(RuntimeError, coast.service_list, self.request)

    @mock.patch.object(coast, 'coastclient')
    def test_client_errors_map_to_horizon_errors(self, client):
        errors = [
            (coast.client_exceptions.NotFound,
             coast.exceptions.NotFound),
            (coast.client_exceptions.Unauthorized,
             coast.exceptions.NotAuthorized),
            (coast.client_exceptions.Forbidden,
             coast.exceptions.RecoverableError),
            (coast.client_exceptions.Conflict,
             coast.exceptions.RecoverableError),
            (coast.client_exceptions.ConnectFailure,
             coast.exceptions.RecoverableError),
        ]
        for source, expected in errors:
            with self.subTest(error=source):
                client.return_value.adapter.request.side_effect = source(
                    'body-with-sensitive-data')
                with self.assertRaises(expected) as caught:
                    coast.service_get(self.request, 'svc')
                self.assertNotIn('body-with-sensitive-data',
                                 str(caught.exception))

    @mock.patch.object(coast, 'coastclient')
    def test_parent_resource_create(self, client):
        for resource, parent in [('appgroup', 'stack'),
                                 ('environment', 'appgroup')]:
            client.return_value.request.reset_mock()
            client.return_value.request.return_value = _resp(
                {resource: {'id': 'new'}})
            result = getattr(coast, resource + '_create')(
                self.request, 'parent', 'demo')
            self.assertEqual({'id': 'new'}, result)
            client.return_value.request.assert_called_once_with(
                '/%ss/parent/%ss' % (parent, resource), 'POST',
                json={resource: {'name': 'demo'}})

    @mock.patch.object(coast, 'coastclient')
    def test_service_lifecycle_actions(self, client):
        client.return_value.request.return_value = _resp(
            {'service': {'id': 's'}})
        for action in ('start', 'stop', 'restart'):
            coast.service_action(self.request, 's', action)
            client.return_value.request.assert_called_with(
                '/services/s/action', 'POST', json={action: {}})
        client.return_value.request.reset_mock()
        with self.assertRaises(ValueError):
            coast.service_action(self.request, 's', 'unsupported')
        client.return_value.request.assert_not_called()
