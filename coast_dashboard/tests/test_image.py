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

import copy
from unittest import mock

from coast_dashboard.api import coast
from coast_dashboard.tests import helpers
from coast_dashboard.tests import test_navigation_settings as nav


class ImageTests(helpers.TestCase):
    def setUp(self):
        nav.NavigationSettingsTests.setUp(self)
        self.records = copy.deepcopy(self.records)
        self.records['app-id']['source'] = {
            'type': 'image', 'image': 'nginx', 'tag': 'stable'}

    list_services = nav.NavigationSettingsTests.list_services
    get_service = nav.NavigationSettingsTests.get_service
    update_service = nav.NavigationSettingsTests.update_service
    url = nav.NavigationSettingsTests.url

    def target(self):
        return self.url('services', 'change_image', ['app-id'])

    def test_prefill_and_visibility(self):
        response = self.client.get(self.target())
        self.assertEqual('nginx', response.context['form'].initial['image'])
        self.assertEqual('stable', response.context['form'].initial['tag'])
        response = self.client.get(self.url('services', 'detail', ['app-id']))
        self.assertIn('Change image', response.context['actions'])
        self.assertContains(response, 'title="Change image"')
        for source in ({'type': 'git'},
                       {'type': 'git', 'build_pack': 'compose'},
                       {'type': 'template'}):
            self.records['app-id']['source'] = source
            response = self.client.get(self.url(
                'services', 'detail', ['app-id']))
            self.assertNotIn('Change image', response.context['actions'])
            self.assertEqual(403, self.client.get(self.target()).status_code)

    @mock.patch.object(coast, 'service_deploy')
    @mock.patch.object(coast, 'service_image_update')
    def test_save_and_redeploy(self, save, deploy):
        calls = mock.Mock()
        calls.attach_mock(save, 'save')
        calls.attach_mock(deploy, 'deploy')
        for operation in ('save', 'redeploy'):
            calls.reset_mock()
            response = self.client.post(self.target(), {
                'image': 'redis', 'tag': '7', 'operation': operation,
                'privileged': 'true', 'source_type': 'git',
                'host_path': '/host', 'volumes': '/host:/data',
                'network_mode': 'host', 'pid': 'host', 'ipc': 'host',
                'uts': 'host', 'userns_mode': 'host', 'devices': '/dev/sda',
                'cap_add': 'SYS_ADMIN',
                'mounts': '/var/run/docker.sock:/var/run/docker.sock'})
            expected = [mock.call.save(mock.ANY, 'app-id', 'redis', '7')]
            target = self.url('services', 'detail', ['app-id'])
            if operation == 'redeploy':
                expected.append(mock.call.deploy(mock.ANY, 'app-id'))
                target += '?tab=service_details__logs'
            self.assertEqual(expected, calls.mock_calls)
            self.assertRedirects(response, target,
                                 fetch_redirect_response=False)

    @mock.patch.object(coast, 'service_deploy')
    @mock.patch.object(coast, 'service_image_update')
    def test_faults_and_invalid_posts(self, save, deploy):
        data = {'image': 'redis', 'tag': '7', 'operation': 'redeploy'}
        save.side_effect = coast.CoastError('Invalid image repository')
        response = self.client.post(self.target(), data)
        self.assertContains(response, 'Invalid image repository')
        self.assertEqual('redis', response.context['form']['image'].value())
        deploy.assert_not_called()
        save.side_effect = None
        deploy.side_effect = coast.CoastError('Stack is busy')
        response = self.client.post(self.target(), data)
        self.assertContains(response, 'Image was saved. Stack is busy')
        save.reset_mock()
        for values in (dict(data, image=''), dict(data, tag=''),
                       dict(data, operation='delete')):
            self.client.post(self.target(), values)
        with mock.patch('coast_dashboard.content.common.project_member',
                        return_value=False):
            self.assertEqual(403, self.client.post(
                self.target(), data).status_code)
        self.records['app-id']['source'] = {'type': 'git'}
        self.assertEqual(403, self.client.post(
            self.target(), data).status_code)
        save.assert_not_called()

    def test_load_failure_redirects_with_api_fault(self):
        with mock.patch.object(coast, 'service_get', side_effect=(
                coast.CoastError('Service not found'))):
            response = self.client.get(self.target())
        self.assertRedirects(response, self.url('services', 'index'),
                             fetch_redirect_response=False)

    @mock.patch.object(coast, 'coastclient')
    def test_adapter_contract_and_fault(self, client):
        adapter = client.return_value.adapter.request
        adapter.return_value.json.return_value = {'service': {'id': 'svc'}}
        self.assertEqual({'id': 'svc'}, coast.service_image_update(
            self.request, 'svc', 'nginx', 'stable'))
        adapter.assert_called_once_with(
            '/services/svc', 'PATCH', microversion='1.14', log=False,
            connect_retries=0, status_code_retries=0,
            json={'service': {'source': {'image': 'nginx', 'tag': 'stable'}}})
        client.return_value.request.assert_not_called()
        response = mock.Mock(status_code=400)
        response.json.return_value = {'faultstring': 'Invalid image'}
        adapter.side_effect = coast.client_exceptions.BadRequest(
            response=response)
        with self.assertRaises(coast.CoastError) as caught:
            coast.service_image_update(self.request, 'svc', 'bad', 'tag')
        self.assertEqual('Invalid image', caught.exception.api_message)
