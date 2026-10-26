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

from django.urls import reverse

from coast_dashboard.api import coast
from coast_dashboard.content.stacks import resize_actions as actions
from coast_dashboard.content.stacks import resize_forms as forms
from coast_dashboard.content.stacks import tables
from coast_dashboard.tests import helpers
from coast_dashboard.tests.test_api import _resp
from coast_dashboard.tests import test_navigation_settings as navigation


STACK = dict(id='s1', status='ACTIVE')
SMALL = dict(id='small', name='Small', vcpus=1, ram=1024, disk=10)
SERVER = dict(id='v1', name='worker', hostname='worker', role='worker',
              kind='vm', status='ACTIVE', flavor=SMALL)
LARGE = dict(id='large', name='Large', vcpus=2, ram=2048, disk=20,
             plan='big', roles=['worker', 'build', 'control'])


class ResizeTests(helpers.TestCase):
    def setUp(self):
        super().setUp()
        for name, result in [('stack_get', STACK),
                             ('stack_server_get', SERVER),
                             ('flavor_list', [LARGE])]:
            patch = mock.patch.object(coast, name, return_value=result)
            patch.start()
            self.addCleanup(patch.stop)

    def form(self, data=None):
        return forms.ResizeServer(self.request, data=data,
                                  stack_id='s1', server_id='v1')

    def test_visibility(self):
        for role in ('worker', 'build', 'control', 'controller'):
            self.assertTrue(actions.eligible(STACK, dict(SERVER, role=role)))
        for change in ({'kind': 'baremetal'}, {'status': 'ERROR'},
                       {'status': 'FAILOVER'}, {'task_state': 'FAILING_OVER'}):
            self.assertFalse(actions.eligible(STACK, dict(SERVER, **change)))
        for change in ({'status': 'ERROR'}, {'task_state': 'FAILING_OVER'},
                       {'task_state': 'ADDING_SERVER'}):
            self.assertFalse(actions.eligible(dict(STACK, **change), SERVER))
        table = tables.ServersTable(self.request, data=[SERVER], item=STACK)
        self.assertIn('resize',
                      [a.name for a in table.get_row_actions(SERVER)])

    def test_row_action_hidden_when_ineligible(self):
        for stack, server in (
                (STACK, dict(SERVER, kind='baremetal')),
                (STACK, dict(SERVER, status='ERROR')),
                (STACK, dict(SERVER, status='FAILOVER')),
                (STACK, dict(SERVER, task_state='FAILING_OVER')),
                (dict(STACK, status='ERROR'), SERVER),
                (dict(STACK, task_state='ADDING_SERVER'), SERVER),
                (dict(STACK, task_state='FAILING_OVER'), SERVER)):
            with self.subTest(stack=stack, server=server):
                table = tables.ServersTable(
                    self.request, data=[server], item=stack)
                self.assertNotIn('resize', [
                    a.name for a in table.get_row_actions(server)])

    def test_larger_role_filter(self):
        catalog = [LARGE, dict(LARGE, plan='equal', **SMALL),
                   dict(LARGE, plan='smaller-disk', disk=1),
                   dict(LARGE, plan='wrong-role', roles=['build']),
                   dict(LARGE, plan='missing-size', ram=None)]
        with mock.patch.object(coast, 'flavor_list', return_value=catalog):
            form = self.form()
        self.assertEqual(['big'],
                         [c[0] for c in form.fields['flavor'].choices])
        self.assertIn('1024 MiB', form.fields['current_flavor'].initial)
        self.assertFalse(self.form({'flavor': 'small'}).is_valid())

    def test_flavor_labels_use_colon(self):
        form = self.form()
        labels = [form.fields['current_flavor'].initial] + [
            label for _, label in form.fields['flavor'].choices]
        self.assertEqual([
            'Small: 1 vCPU, 1024 MiB RAM, 10 GiB disk',
            'Large: 2 vCPU, 2048 MiB RAM, 20 GiB disk',
        ], labels)
        for label in labels:
            self.assertNotIn('\u2014', label)

    def test_each_single_dimension_increase_is_selectable(self):
        for dimension in forms.DIMENSIONS:
            with self.subTest(dimension=dimension):
                candidate = dict(SMALL, plan='single-increase',
                                 roles=['worker'])
                candidate[dimension] += 1
                with mock.patch.object(coast, 'flavor_list',
                                       return_value=[candidate]):
                    form = self.form({'flavor': 'single-increase'})
                self.assertEqual(['single-increase'], [
                    plan for plan, _ in form.fields['flavor'].choices])
                self.assertTrue(form.is_valid(), form.errors)

    def test_control_and_build_role_choices(self):
        for role in ('control', 'controller', 'build'):
            expected = 'control' if role == 'controller' else role
            with mock.patch.object(coast, 'stack_server_get',
                                   return_value=dict(SERVER, role=role)), \
                    mock.patch.object(coast, 'flavor_list', return_value=[
                        dict(LARGE, plan='allowed', roles=[expected]),
                        dict(LARGE, plan='worker-only', roles=['worker'])]):
                self.assertEqual(['allowed'], [
                    c[0] for c in self.form().fields['flavor'].choices])

    @mock.patch.object(coast, 'stack_server_resize')
    def test_post_busy_and_tampered_choices(self, resize):
        url = reverse('horizon:project:coast.stacks:resize_server',
                      args=['s1', 'v1'])
        self.client.post(url, {'flavor': 'not-allowed'})
        with mock.patch.object(coast, 'stack_get', return_value=dict(
                STACK, task_state='FAILING_OVER')):
            response = self.client.post(url, {'flavor': 'big'})
        self.assertContains(response, 'Only idle, ACTIVE VM servers')
        resize.assert_not_called()

    def test_no_larger(self):
        with mock.patch.object(coast, 'flavor_list', return_value=[]):
            form = self.form()
        self.assertFalse(form.available)
        self.assertIn('No larger flavors', form.fields['flavor'].help_text)

    @mock.patch.object(coast, 'coastclient')
    def test_wire_contract(self, client):
        call = client.return_value.adapter.request
        call.return_value = _resp({'server': SERVER})
        coast.stack_server_resize(self.request, 's1', 'v1', 'big')
        self.assertEqual(('/stacks/s1/servers/v1/action', 'POST'),
                         call.call_args.args)
        self.assertEqual({'resize': {'flavor': 'big'}},
                         call.call_args.kwargs['json'])
        self.assertEqual('1.26', call.call_args.kwargs['microversion'])

    @mock.patch.object(coast, 'stack_server_resize')
    def test_post_redirect_and_error(self, resize):
        url = reverse('horizon:project:coast.stacks:resize_server',
                      args=['s1', 'v1'])
        response = self.client.post(url, {'flavor': 'big'})
        self.assertRedirects(response, reverse(
            'horizon:project:coast.stacks:detail', args=['s1']) +
            '?tab=stack_details__servers', fetch_redirect_response=False)
        resize.assert_called_once_with(mock.ANY, 's1', 'v1', 'big')
        resize.side_effect = coast.CoastError('Stack is busy.', 409)
        response = self.client.post(url, {'flavor': 'big'})
        self.assertEqual(200, response.status_code)
        self.assertContains(response, 'Stack is busy.')

    @mock.patch.object(coast, 'coastclient')
    def test_api_refusal_text_reaches_modal(self, client):
        url = reverse('horizon:project:coast.stacks:resize_server',
                      args=['s1', 'v1'])
        for error in (coast.client_exceptions.BadRequest,
                      coast.client_exceptions.Conflict):
            with self.subTest(error=error):
                response = _resp({'faultstring': 'Choose a larger flavor.'})
                response.status_code = error.http_status
                client.return_value.adapter.request.side_effect = error(
                    response=response)
                result = self.client.post(url, {'flavor': 'big'})
                self.assertContains(result, 'Choose a larger flavor.')
                self.assertNotContains(result, 'Traceback')

    def test_api_error_names_are_scrubbed(self):
        url = reverse('horizon:project:coast.stacks:resize_server',
                      args=['s1', 'v1'])
        for operation in ('stack_get', 'stack_server_get', 'flavor_list',
                          'stack_server_resize'):
            for names in ('Coolify and Traefik', 'COOLIFY and traefik'):
                with self.subTest(operation=operation, names=names):
                    fault = coast.CoastError('%s are busy.' % names, 409)
                    with mock.patch.object(coast, operation,
                                           side_effect=fault):
                        if operation == 'stack_server_resize':
                            response = self.client.post(url, {'flavor': 'big'})
                        else:
                            response = self.client.get(url)
                    self.assertContains(
                        response, 'App engine server and proxy are busy.')
                    body = response.content.decode().lower()
                    self.assertNotIn('coolify', body)
                    self.assertNotIn('traefik', body)
                    self.assertNotIn('traceback', body)

    def test_failover_polls(self):
        server = dict(SERVER, status='FAILOVER', task_state='FAILING_OVER')
        table = tables.ServersTable(self.request, data=[server], item=STACK,
                                    stack_id='s1')
        row = table.get_rows()[0]
        self.assertIsNone(row.status)
        self.assertTrue(row.ajax)
        self.assertIn('FAILING_OVER', str(table.render()))


class FlavorCatalogContractTests(helpers.TestCase):
    @mock.patch.object(coast, 'coastclient')
    def test_flavor_list_transport_contract(self, client):
        transport = client.return_value.adapter.request
        transport.return_value = _resp({'flavors': [LARGE]})

        self.assertEqual([LARGE], coast.flavor_list(self.request))

        transport.assert_called_once_with(
            '/flavors', 'GET', microversion='1.27', log=False,
            connect_retries=0, status_code_retries=0)
        client.return_value.request.assert_not_called()


class ResizeTabTests(helpers.TestCase):
    def setUp(self):
        navigation.NavigationSettingsTests.setUp(self)

    list_services = navigation.NavigationSettingsTests.list_services
    get_service = navigation.NavigationSettingsTests.get_service
    update_service = navigation.NavigationSettingsTests.update_service

    @mock.patch.object(coast, 'stack_server_list', return_value=[SERVER])
    def test_servers_tab_resize_link(self, listing):
        response = self.client.get(reverse(
            'horizon:project:coast.stacks:detail',
            args=[navigation.STACK['id']]) + '?tab=stack_details__servers')
        self.assertEqual(200, response.status_code)
        self.assertContains(response, 'Resize')
        self.assertContains(response, reverse(
            'horizon:project:coast.stacks:resize_server',
            args=[navigation.STACK['id'], SERVER['id']]))
