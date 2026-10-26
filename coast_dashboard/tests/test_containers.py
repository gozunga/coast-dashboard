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
from coast_dashboard.tests import test_compose


CONTAINER = {'id': 'c-web', 'name': 'web', 'image': 'nginx:stable',
             'state': 'running', 'health': 'healthy', 'restart_count': 0,
             'limits': {'cpu': 0.5, 'memory_bytes': None},
             'environment': {'TOKEN': '***', 'PASSWORD': 'plain-password',
                             'HTML': '<script>alert(1)</script>'}}


class ContainerTests(test_compose.helpers.TestCase):
    setUp = test_compose.ComposeTests.setUp
    list_services = test_compose.ComposeTests.list_services
    get_service = test_compose.ComposeTests.get_service
    update_service = test_compose.ComposeTests.update_service
    url = test_compose.ComposeTests.url

    # Reuse only the service fixtures, not Compose's tests.
    def target(self, panel='oneclick', service_id='service-id'):
        return self.url(panel, 'container', [service_id, 'c-web'])

    @mock.patch.object(coast, 'service_container_list',
                       return_value=[dict(CONTAINER)])
    def test_list_visibility_and_link(self, get):
        url = self.url('oneclick', 'detail', ['service-id'])
        response = self.client.get(url + '?tab=service_details__containers')
        self.assertContains(response, self.target())
        self.assertContains(response, 'running (healthy)')
        self.assertContains(response, 'nginx:stable')
        self.assertNotContains(response, '>c-web<')
        response = self.client.get(self.url('services', 'detail', ['app-id']))
        self.assertNotContains(response, 'service_details__containers')
        get.side_effect = coast.CoastError('Worker is unavailable')
        response = self.client.get(url + '?tab=service_details__containers')
        self.assertContains(response, 'Worker is unavailable')

    @mock.patch.object(coast, 'service_container_list', return_value=[])
    def test_empty_and_stopped_containers(self, get):
        url = self.url('oneclick', 'detail', ['service-id'])
        url += '?tab=service_details__containers'
        response = self.client.get(url)
        self.assertContains(response, 'No items to display')
        get.return_value = [dict(CONTAINER, state='exited', health=None,
                                 restart_count=None)]
        response = self.client.get(url)
        self.assertContains(response, 'exited')
        self.assertNotContains(response, '(None)')
        self.records['app-id']['source']['build_pack'] = 'compose'
        response = self.client.get(self.url('services', 'detail', ['app-id']) +
                                   '?tab=service_details__containers')
        self.assertContains(response, self.target('services', 'app-id'))

    @mock.patch.object(coast, 'service_container_get', return_value=CONTAINER)
    def test_overview_environment_reader_and_breadcrumb(self, get):
        with mock.patch('coast_dashboard.content.common.project_member',
                        return_value=False):
            response = self.client.get(self.target())
            self.assertContains(response, 'Container overview')
            self.assertContains(response, 'Unlimited')
            self.assertContains(response, 'c-web')
            self.assertContains(response, 'database')
            self.assertIn('no-store', response['Cache-Control'])
            response = self.client.get(
                self.target() + '?tab=container_details__environment')
        self.assertContains(response, 'plain-password')
        self.assertContains(response, '***')
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, '&lt;script&gt;')

    @mock.patch.object(coast, 'service_container_logs')
    @mock.patch.object(coast, 'service_container_get', return_value=CONTAINER)
    def test_logs_and_faults(self, get, logs):
        logs.return_value = {'lines': [
            {'ts': '2026-10-19T00:00:00Z', 'stream': 'stderr',
             'line': '<script>bad</script> ***'}]}
        response = self.client.get(
            self.target() + '?tab=container_details__logs')
        self.assertContains(response, 'Auto-refresh every 3 seconds')
        self.assertContains(response, '&lt;script&gt;bad&lt;/script&gt; ***')
        fragment = self.url('oneclick', 'container_logs_fragment',
                            ['service-id', 'c-web'])
        logs.side_effect = coast.CoastError('Invalid tail value')
        response = self.client.get(fragment)
        self.assertContains(response, 'Invalid tail value')
        self.assertIn('no-store', response['Cache-Control'])
        get.side_effect = coast.CoastError('Container is unavailable')
        response = self.client.get(self.target())
        self.assertEqual(302, response.status_code)
        self.assertIn('no-store', response['Cache-Control'])

    @mock.patch.object(coast, 'coastclient')
    def test_container_adapter_contract(self, client):
        adapter = client.return_value.adapter.request
        adapter.return_value.json.return_value = {
            'containers': [CONTAINER], 'container': CONTAINER,
            'logs': {'lines': []}}
        self.assertEqual([CONTAINER], coast.service_container_list(
            self.request, 'svc'))
        self.assertEqual(CONTAINER, coast.service_container_get(
            self.request, 'svc', 'c-web'))
        self.assertEqual({'lines': []}, coast.service_container_logs(
            self.request, 'svc', 'c-web'))
        self.assertEqual([
            mock.call(path, 'GET', microversion='1.13', log=False,
                      connect_retries=0, status_code_retries=0)
            for path in ('/services/svc/containers',
                         '/services/svc/containers/c-web',
                         '/services/svc/containers/c-web/logs?tail=200')],
            adapter.call_args_list)
        client.return_value.request.assert_not_called()
        response = mock.Mock(status_code=400)
        response.json.return_value = {'faultstring': 'Invalid container'}
        adapter.side_effect = coast.client_exceptions.BadRequest(
            response=response)
        with self.assertRaises(coast.CoastError) as caught:
            coast.service_container_get(self.request, 'svc', 'c-web')
        self.assertEqual('Invalid container', caught.exception.api_message)
