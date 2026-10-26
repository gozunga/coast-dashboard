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
from coast_dashboard.content.services import forms
from coast_dashboard.tests import helpers
from coast_dashboard.tests import test_navigation_settings as nav


YAML = 'services:\n  web:\n    image: nginx\n'


class ComposeTests(helpers.TestCase):
    def setUp(self):
        nav.NavigationSettingsTests.setUp(self)
        self.records = copy.deepcopy(self.records)

    list_services = nav.NavigationSettingsTests.list_services
    get_service = nav.NavigationSettingsTests.get_service
    update_service = nav.NavigationSettingsTests.update_service
    url = nav.NavigationSettingsTests.url

    def target(self, panel='oneclick', service_id='service-id'):
        return self.url(panel, 'detail', [service_id]) + (
            '?tab=service_details__compose')

    @mock.patch.object(coast, 'service_compose_get', return_value=YAML)
    def test_tab_visibility_and_load_failure(self, get):
        response = self.client.get(self.target())
        self.assertContains(response, 'Compose configuration')
        self.assertContains(response, YAML)
        self.assertIn('no-store', response['Cache-Control'])
        response = self.client.get(self.target('services', 'app-id'))
        self.assertNotContains(response, 'service_details__compose')
        get.assert_called_once()
        self.records['app-id']['source']['build_pack'] = 'compose'
        response = self.client.get(self.target('services', 'app-id'))
        self.assertContains(response, 'Compose configuration')
        get.side_effect = coast.CoastError('Application editing unavailable')
        response = self.client.get(self.target())
        self.assertContains(response, 'Application editing unavailable')
        self.assertNotContains(response, 'name="yaml"')

    @mock.patch.object(coast, 'service_deploy')
    @mock.patch.object(coast, 'service_compose_update', return_value=YAML)
    def test_save_and_redeploy(self, save, deploy):
        response = self.client.post(self.target(),
                                    {'yaml': YAML, 'operation': 'save'})
        self.assertRedirects(response, self.target(),
                             fetch_redirect_response=False)
        deploy.assert_not_called()
        self.assertIn('no-store', response['Cache-Control'])
        calls = mock.Mock()
        calls.attach_mock(save, 'save')
        calls.attach_mock(deploy, 'deploy')
        for panel, service_id in [('oneclick', 'service-id'),
                                  ('services', 'app-id')]:
            self.records[service_id]['source']['build_pack'] = 'compose'
            calls.reset_mock()
            response = self.client.post(self.target(panel, service_id),
                                        {'yaml': YAML,
                                         'operation': 'redeploy'})
            self.assertEqual([
                mock.call.save(mock.ANY, service_id, YAML),
                mock.call.deploy(mock.ANY, service_id)], calls.mock_calls)
            self.assertRedirects(
                response, self.url(panel, 'detail', [service_id]) +
                '?tab=service_details__logs', fetch_redirect_response=False)

    @mock.patch.object(coast, 'service_compose_get')
    @mock.patch.object(coast, 'service_deploy')
    @mock.patch.object(coast, 'service_compose_update')
    def test_errors_keep_edits_and_do_not_refetch(self, save, deploy, get):
        for fault in ('Service web: privileged is not allowed',
                      'Service is busy', 'Secret store unavailable'):
            save.side_effect = coast.CoastError(fault)
            response = self.client.post(self.target(),
                                        {'yaml': YAML,
                                         'operation': 'redeploy'})
            self.assertContains(response, fault)
            self.assertContains(response, YAML)
            self.assertIn('no-store', response['Cache-Control'])
        deploy.assert_not_called()
        get.assert_not_called()
        save.side_effect = None
        deploy.side_effect = coast.CoastError('Stack is busy')
        response = self.client.post(self.target(),
                                    {'yaml': YAML, 'operation': 'redeploy'})
        self.assertContains(response, 'Compose YAML was saved.')
        self.assertContains(response, 'Stack is busy')
        self.assertContains(response, YAML)

    @mock.patch.object(coast, 'service_compose_get')
    @mock.patch.object(coast, 'service_compose_update')
    def test_access_and_non_compose_posts(self, save, get):
        response = self.client.post(self.target('services', 'app-id'),
                                    {'yaml': YAML, 'operation': 'save'})
        self.assertEqual(403, response.status_code)
        with mock.patch('coast_dashboard.content.common.project_member',
                        return_value=False):
            response = self.client.get(self.target())
            self.assertNotContains(response, 'service_details__compose')
            response = self.client.post(self.target(),
                                        {'yaml': YAML, 'operation': 'save'})
            self.assertEqual(403, response.status_code)
        save.assert_not_called()
        get.assert_not_called()

    def test_form_preserves_whitespace_and_rejects_missing_input(self):
        text = YAML + '\n'
        form = forms.ComposeForm(self.request,
                                 {'yaml': text, 'operation': 'save'})
        self.assertTrue(form.is_valid())
        self.assertEqual(text, form.cleaned_data['yaml'])
        for values in ({'yaml': '', 'operation': 'save'},
                       {'yaml': YAML, 'operation': 'delete'}):
            form = forms.ComposeForm(self.request, values)
            self.assertFalse(form.is_valid())

    @mock.patch.object(coast, 'coastclient')
    def test_adapter_contract_and_fault_message(self, client):
        adapter = client.return_value.adapter.request
        adapter.return_value.json.return_value = {'compose': {'yaml': YAML}}
        self.assertEqual(YAML, coast.service_compose_get(self.request, 'svc'))
        self.assertEqual(YAML, coast.service_compose_update(
            self.request, 'svc', YAML))
        self.assertEqual([
            mock.call('/services/svc/compose', 'GET', microversion='1.12',
                      log=False, connect_retries=0, status_code_retries=0),
            mock.call('/services/svc/compose', 'PUT', microversion='1.12',
                      log=False, connect_retries=0, status_code_retries=0,
                      json={'compose': {'yaml': YAML}})],
            adapter.call_args_list)
        client.return_value.request.assert_not_called()
        response = mock.Mock(status_code=400)
        response.json.return_value = {
            'faultstring': 'Service web: devices is not allowed'}
        adapter.side_effect = coast.client_exceptions.BadRequest(
            response=response)
        with self.assertRaises(coast.CoastError) as caught:
            coast.service_compose_update(self.request, 'svc', YAML)
        self.assertEqual('Service web: devices is not allowed',
                         coast.error_message(caught.exception, 'fallback'))
