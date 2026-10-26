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

from types import SimpleNamespace
from unittest import mock

from django.urls import reverse
from openstack_dashboard.api import cinder
from openstack_dashboard.api import nova

from coast_dashboard.api import coast
from coast_dashboard.content.stacks import add_server as forms
from coast_dashboard.content.stacks import tables
from coast_dashboard.tests import helpers


class AddServerTests(helpers.TestCase):
    def setUp(self):
        super().setUp()
        self.stack = {'id': 's1', 'status': 'ACTIVE'}
        self.flavor = SimpleNamespace(id='f1', name='small', ram=1024,
                                      vcpus=1, disk=10)
        patches = [
            (nova, 'flavor_list', [self.flavor]),
            (coast, 'flavor_list', [{
                'id': 'f1', 'name': 'small', 'vcpus': 1, 'ram': 1024,
                'disk': 10, 'plan': 'vm-small',
                'roles': ['worker', 'build']}]),
            (coast, 'stack_get', self.stack),
            (nova, 'tenant_absolute_limits', {}),
            (cinder, 'tenant_absolute_limits', {})]
        self.mocks = {}
        for owner, name, value in patches:
            patch = mock.patch.object(owner, name, return_value=value)
            self.mocks[name] = patch.start()
            self.addCleanup(patch.stop)
        self.data = {'role': 'worker', 'plan': 'vm-small', 'name': ''}
        self.url = reverse(helpers.view_name('stacks', 'add_server'),
                           args=['s1'])

    def test_table_action_and_busy_stack(self):
        table = tables.ServersTable(self.request, item=self.stack)
        action = table.base_actions['add_server']
        self.assertTrue(action.allowed(self.request))
        self.assertEqual(self.url, action.get_link_url())
        self.assertIn(self.url, table.render_table_actions())
        busy = tables.ServersTable(
            self.request, item=self.stack,
            data=[{'id': 'v1', 'status': 'BUILDING'}])
        self.assertFalse(busy.base_actions['add_server'].allowed(self.request))
        self.stack['task_state'] = 'RECONCILING'
        self.assertFalse(action.allowed(self.request))
        self.stack['task_state'] = 'NONE'
        self.stack['status'] = 'BUILDING'
        self.assertFalse(action.allowed(self.request))

    def test_form_roles_and_flavors(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'Worker')
        self.assertContains(response, 'Build server')
        self.assertContains(response, 'small (1 vCPU, 1 GB RAM, 10 GB disk)')
        self.assertNotContains(response, 'value="control"')

    def test_get_catalog_failure(self):
        self.mocks['flavor_list'].side_effect = RuntimeError('private detail')
        response = self.client.get(self.url)
        self.assertContains(
            response, 'Unable to retrieve flavors. Please try again.')
        form = response.context['form']
        self.assertFalse(form.is_bound)
        self.assertFalse(hasattr(form, 'cleaned_data'))
        self.assertIn('Unable to retrieve flavors.', str(
            form.non_field_errors()))
        self.assertNotContains(response, 'private detail')
        self.assertNotContains(response, 'Traceback')

    @mock.patch.object(coast, 'stack_server_create')
    def test_post_catalog_failure(self, create):
        self.mocks['flavor_list'].side_effect = RuntimeError('private detail')
        response = self.client.post(self.url, self.data)
        self.assertContains(
            response, 'Unable to retrieve flavors. Please try again.')
        form = response.context['form']
        self.assertFalse(form.is_valid())
        self.assertIn('Unable to retrieve flavors.', str(
            form.non_field_errors()))
        self.assertNotContains(response, 'private detail')
        self.assertNotContains(response, 'Traceback')
        create.assert_not_called()

    def test_quota_exceeded(self):
        self.mocks['tenant_absolute_limits'].return_value = {
            'maxTotalVolumes': 1, 'totalVolumesUsed': 0}
        form = forms.AddServer(self.request, self.data, stack_id='s1')
        self.assertFalse(form.is_valid())
        self.assertIn('exceeds your project quota', str(form.errors))

    def test_compute_quota_exceeded(self):
        with mock.patch.object(nova, 'tenant_absolute_limits', return_value={
                'maxTotalCores': 1, 'totalCoresUsed': 1}):
            form = forms.AddServer(self.request, self.data, stack_id='s1')
            self.assertFalse(form.is_valid())
            self.assertIn('exceeds your project quota', str(form.errors))

    @mock.patch.object(coast, '_write', return_value={'server': {'id': 'v1'}})
    def test_post_body_and_redirect(self, write):
        response = self.client.post(self.url, self.data)
        write.assert_called_once()
        self.assertEqual(('/stacks/s1/servers', 'POST', {'server': {
            'kind': 'vm', 'role': 'worker', 'plan': 'vm-small'}}),
            write.call_args.args[1:])
        self.assertRedirects(response, reverse(
            helpers.view_name('stacks', 'detail'), args=['s1']) +
            '?tab=stack_details__servers', fetch_redirect_response=False)

    @mock.patch.object(coast, 'stack_server_create')
    def test_api_error(self, create):
        error = ValueError('Server refused')
        error.api_message = 'Project server quota exceeded.'
        create.side_effect = error
        response = self.client.post(self.url, self.data)
        self.assertEqual(200, response.status_code)
        self.assertContains(response, 'Project server quota exceeded.')
        self.assertNotContains(response, 'Traceback')

    def test_short_hostname(self):
        table = tables.ServersTable(self.request, item=self.stack)
        self.assertEqual('worker-1', table.columns['hostname'].get_raw_data(
            {'hostname': 'worker-1.example.com'}))

    @mock.patch.object(coast, 'stack_server_create')
    def test_busy_stack_rejects_post(self, create):
        self.stack['status'] = 'BUILDING'
        response = self.client.post(self.url, self.data)
        self.assertContains(response, 'The stack is busy.')
        create.assert_not_called()

    @mock.patch.object(coast, '_write', return_value={'server': {'id': 'v1'}})
    def test_build_server_and_optional_name(self, write):
        data = dict(self.data, role='build', build_plan='vm-small',
                    name='builder')
        self.client.post(self.url, data)
        self.assertEqual({'server': {'kind': 'vm', 'role': 'build',
                                     'plan': 'vm-small', 'name': 'builder'}},
                         write.call_args.args[3])

    def test_storage_capacity_exceeded(self):
        self.mocks['tenant_absolute_limits'].return_value = {
            'maxTotalVolumeGigabytes': 119, 'totalGigabytesUsed': 0}
        form = forms.AddServer(self.request, self.data, stack_id='s1')
        self.assertFalse(form.is_valid())
        self.assertIn('exceeds your project quota', str(form.errors))

    @mock.patch.object(coast, 'stack_server_create')
    def test_api_error_uses_customer_wording(self, create):
        error = ValueError()
        error.api_message = 'Coolify failed to configure Traefik.'
        create.side_effect = error
        response = self.client.post(self.url, self.data)
        self.assertContains(response, 'App engine server failed to configure')
        self.assertNotContains(response, 'Coolify')
        self.assertNotContains(response, 'Traefik')

    def detail_url(self):
        return reverse(helpers.view_name('stacks', 'detail'), args=['s1'])

    def project_server(self, status='BUILDING'):
        # Project response: no compute IDs, management IPs or task_state.
        return {'id': 'v1', 'project_id': self.request.user.project_id,
                'stack_id': 's1', 'name': 'worker-1',
                'hostname': 'worker-1.example.com', 'kind': 'vm',
                'role': 'worker', 'status': status, 'floating_ip': None,
                'flavor': {'id': 'f1', 'name': 'small', 'vcpus': 1,
                           'ram': 1024, 'disk': 10},
                'created_at': None, 'updated_at': None}

    @mock.patch.object(coast, 'appgroup_list', return_value=[])
    @mock.patch.object(coast, 'ingress_supported', return_value=False)
    @mock.patch.object(coast, 'dns_available', return_value=False)
    @mock.patch.object(coast, 'stack_server_list', return_value=[])
    def test_project_servers_tab_has_action(self, servers, *unused):
        response = self.client.get(self.detail_url(), {
            'tab': 'stack_details__servers'})
        self.assertContains(response, self.url)
        self.assertContains(response, 'Add server')
        servers.assert_called_once_with(mock.ANY, 's1')

    @mock.patch.object(coast, 'appgroup_list', return_value=[])
    @mock.patch.object(coast, 'ingress_supported', return_value=False)
    @mock.patch.object(coast, 'dns_available', return_value=False)
    @mock.patch.object(coast, 'stack_server_list')
    @mock.patch.object(coast, '_write')
    def test_post_redirect_lists_building_server(
            self, write, servers, *unused):
        server = self.project_server()
        write.return_value = {'server': server}
        servers.return_value = [server]
        response = self.client.post(self.url, self.data, follow=True)
        self.assertEqual([(self.detail_url() +
                           '?tab=stack_details__servers', 302)],
                         response.redirect_chain)
        self.assertContains(response, 'Server creation requested.')
        self.assertRegex(response.content.decode(), r'>\s*Worker\s*</td>')
        self.assertRegex(response.content.decode(), r'>\s*worker-1\s*</td>')
        self.assertNotContains(response, 'worker-1.example.com')
        self.assertRegex(response.content.decode(), r'>\s*small\s*</td>')
        self.assertContains(response, 'BUILDING')
        self.assertContains(response, 'ajax-update')
        self.assertContains(response, 'data-update-interval')
        self.assertNotContains(response, self.url)

    @mock.patch.object(coast, 'appgroup_list', return_value=[])
    @mock.patch.object(coast, 'ingress_supported', return_value=False)
    @mock.patch.object(coast, 'dns_available', return_value=False)
    @mock.patch.object(coast, 'stack_server_get')
    def test_building_row_polls_using_tab_stack(self, get_server, *unused):
        get_server.return_value = self.project_server(status='ACTIVE')
        response = self.client.get(self.detail_url(), {
            'tab': 'stack_details__servers', 'table': 'servers',
            'action': 'row_update', 'obj_id': 'v1'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(200, response.status_code)
        get_server.assert_called_once_with(mock.ANY, 's1', 'v1')
        self.assertRegex(response.content.decode(), r'>\s*Worker\s*</td>')
        self.assertRegex(response.content.decode(), r'>\s*worker-1\s*</td>')
        self.assertRegex(response.content.decode(), r'>\s*small\s*</td>')
        self.assertContains(response, 'ACTIVE')

    def test_public_flavor_name(self):
        table = tables.ServersTable(self.request, item=self.stack)
        self.assertEqual('small', table.columns['flavor'].get_raw_data(
            self.project_server()))

    def test_deleted_flavor_falls_back_to_id(self):
        server = dict(self.project_server(), flavor={'id': 'f1', 'name': None})
        table = tables.ServersTable(self.request, item=self.stack)
        self.assertEqual('f1', table.columns['flavor'].get_raw_data(server))

    def test_pending_server_without_flavor(self):
        server = dict(self.project_server(), flavor=None, status='PENDING')
        table = tables.ServersTable(self.request, item=self.stack)
        self.assertIsNone(table.columns['flavor'].get_raw_data(server))

    def test_role_specific_catalog(self):
        self.mocks['flavor_list'].return_value = [
            {'id': 'w', 'name': 'worker-only', 'vcpus': 1, 'ram': 1024,
             'disk': 10, 'plan': 'worker-plan', 'roles': ['worker']},
            {'id': 'b', 'name': 'build-only', 'vcpus': 2, 'ram': 2048,
             'disk': 20, 'plan': 'build-plan', 'roles': ['build']}]
        form = forms.AddServer(self.request, stack_id='s1')
        self.assertEqual(['worker-plan'], [
            value for value, label in form.fields['plan'].choices])
        self.assertEqual(['build-plan'], [
            value for value, label in form.fields['build_plan'].choices])
        data = dict(self.data, plan='build-plan')
        form = forms.AddServer(self.request, data, stack_id='s1')
        self.assertFalse(form.is_valid())

    @mock.patch.object(coast, 'coastclient')
    def test_create_uses_127_adapter(self, client):
        response = mock.Mock(content=b'x')
        response.json.return_value = {'server': {'id': 'v1'}}
        client.return_value.adapter.request.return_value = response
        coast.stack_server_create(self.request, 's1', 'worker', 'vm-small')
        client.return_value.adapter.request.assert_called_once_with(
            '/stacks/s1/servers', 'POST', microversion='1.27', log=False,
            connect_retries=0, status_code_retries=0,
            json={'server': {'kind': 'vm', 'role': 'worker',
                             'plan': 'vm-small'}})
        client.return_value.request.assert_not_called()


class ServerFlavorApiTests(helpers.TestCase):
    @mock.patch.object(coast, 'coastclient')
    def test_catalog_and_server_reads_use_127(self, client):
        response = mock.Mock(content=b'x')
        client.return_value.adapter.request.return_value = response
        for call, body, path in (
                (lambda: coast.flavor_list(self.request),
                 {'flavors': []}, '/flavors'),
                (lambda: coast.stack_server_list(self.request, 's1'),
                 {'servers': []}, '/stacks/s1/servers'),
                (lambda: coast.stack_server_get(self.request, 's1', 'v1'),
                 {'server': {}}, '/stacks/s1/servers/v1')):
            with self.subTest(path=path):
                response.json.return_value = body
                call()
                client.return_value.adapter.request.assert_called_with(
                    path, 'GET', microversion='1.27', log=False,
                    connect_retries=0, status_code_retries=0)
        client.return_value.request.assert_not_called()
