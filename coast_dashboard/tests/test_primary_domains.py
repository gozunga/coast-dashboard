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

from django.contrib.messages.storage.fallback import FallbackStorage
from django.template.loader import render_to_string
from django.urls import reverse

from coast_dashboard.api import coast
from coast_dashboard.content.admin import tables as admin_tables
from coast_dashboard.content import dns
from coast_dashboard.content.services import tables
from coast_dashboard.content.services import tabs
from coast_dashboard.content.stacks.tables import ServersTable
from coast_dashboard.tests import helpers
from coast_dashboard.tests.test_api import _resp


class PrimaryDomainTests(helpers.TestCase):
    def setUp(self):
        super().setUp()
        self.request._messages = FallbackStorage(self.request)
        self.row = {'id': 'd', 'fqdn': 'shop.example.com', 'status': 'ACTIVE'}
        self.table = tables.DomainsTable(
            self.request, data=[self.row], service_id='s',
            item={'default_domain_enabled': True})

    @mock.patch.object(coast, 'coastclient')
    def test_primary_and_default_writes(self, client):
        client.return_value.adapter.request.return_value = _resp(
            {'domain': self.row, 'service': {'id': 's'}})
        coast.service_domain_make_primary(self.request, 's', 'd')
        client.return_value.adapter.request.assert_called_once_with(
            '/services/s/domains/d', 'PATCH', microversion='1.23', log=False,
            connect_retries=0, status_code_retries=0,
            json={'domain': {'primary': True}})
        for enabled in (False, True):
            coast.service_update(self.request, 's',
                                 {'default_domain_enabled': enabled})
            self.assertEqual('1.23', client.return_value.adapter.request.
                             call_args.kwargs['microversion'])
            self.assertEqual({'service': {'default_domain_enabled': enabled}},
                             client.return_value.adapter.request.
                             call_args.kwargs['json'])

    @mock.patch.object(coast, 'service_domain_make_primary')
    def test_make_primary_action_and_marker(self, update):
        action = tables.MakePrimary()
        for changes, allowed in [({}, True), ({'status': 'VERIFIED'}, True),
                                 ({'status': 'PENDING_VERIFICATION'}, False),
                                 ({'is_default': True}, False),
                                 ({'primary': True}, False)]:
            self.assertEqual(allowed, action.allowed(
                self.request, dict(self.row, **changes)))
        response = action.single(self.table, self.request, 'd')
        self.assertEqual(302, response.status_code)
        update.assert_called_once_with(self.request, 's', 'd')
        self.row['primary'] = True
        self.assertEqual('Yes', str(self.table.columns['primary'].get_data(
            self.row)))
        actions = self.table.get_row_actions(self.row)
        self.assertNotIn('make_primary', [a.name for a in actions])

    def test_default_address_action_labels_are_singular(self):
        for enabled, cls, direction in (
                (False, tables.EnableDefaultAddress, 'on'),
                (True, tables.DisableDefaultAddress, 'off')):
            with self.subTest(direction=direction):
                self.table.kwargs['item']['default_domain_enabled'] = enabled
                action = cls()
                label = 'Turn default address ' + direction
                self.assertEqual(label, str(action.verbose_name))
                self.assertEqual(label, str(action.verbose_name_plural))
                for count in (1, 2):
                    self.assertEqual(label, str(action.action_present(count)))
                    self.assertEqual('Turned default address ' + direction,
                                     str(action.action_past(count)))
                rendered = self.table.render()
                self.assertRegex(rendered, r'>\s*' + label + r'\s*</button>')
                self.assertNotIn(label + 's', rendered)

    @mock.patch.object(tables.exceptions, 'handle')
    @mock.patch.object(coast, 'service_update')
    def test_toggle_both_directions_and_api_fault(self, update, handle):
        for enabled, cls in ((False, tables.DisableDefaultAddress),
                             (True, tables.EnableDefaultAddress)):
            self.table.kwargs['item']['default_domain_enabled'] = not enabled
            action = cls()
            action.table = self.table
            self.assertTrue(action.allowed(self.request))
            action.handle(self.table, self.request, [])
            update.assert_called_with(self.request, 's',
                                      {'default_domain_enabled': enabled})
            self.table.kwargs['item']['default_domain_enabled'] = enabled
            self.assertFalse(action.allowed(self.request))
        for message in ('Pick a main domain before turning off the default '
                        'address.', 'Domain operation is busy.'):
            update.side_effect = coast.CoastError(message, http_status=409)
            action.handle(self.table, self.request, [])
            handle.assert_called_with(self.request, message)
            self.assertEqual(message, dns.error_message(update.side_effect))

    def test_overview_prefers_primary_and_hostname_presentations(self):
        rendered = render_to_string('project/coast_services/overview.html', {
            'item': {'primary_url': 'https://shop.example.com',
                     'default_url': 'https://default.example.com'}})
        self.assertIn('https://shop.example.com', rendered)
        self.assertNotIn('https://default.example.com', rendered)
        row = {'id': 'v', 'hostname': 'worker-abc', 'role': 'worker'}
        rendered = ServersTable(
            self.request, data=[row], stack_id='s').render()
        self.assertIn('Hostname', rendered)
        self.assertIn('worker-abc', rendered)
        rendered = render_to_string('admin/coast/servers.html', {
            'servers': [row], 'servers_table': admin_tables.ServersTable(
                self.request, data=[row])})
        self.assertGreaterEqual(rendered.count('worker-abc'), 2)

    @mock.patch.object(tables.exceptions, 'handle')
    @mock.patch.object(coast, 'service_domain_make_primary')
    def test_primary_busy_fault_unchanged(self, update, handle):
        message = 'Domain verification is busy (started 2026-10-19T12:00:00Z).'
        update.side_effect = coast.CoastError(message, http_status=409)
        tables.MakePrimary().single(self.table, self.request, 'd')
        handle.assert_called_once_with(self.request, message)

    @mock.patch('coast_dashboard.content.common.parent_maps',
                return_value=({}, {}, {}))
    @mock.patch.object(coast, 'service_deployment_list', return_value=[])
    @mock.patch.object(coast, 'service_update')
    @mock.patch.object(coast, 'dns_available', return_value=False)
    @mock.patch.object(coast, 'service_domain_list', return_value=[])
    @mock.patch.object(coast, 'service_get')
    def test_default_off_control_on_both_routes(
            self, get, domains, dns_available, update, deployments, parents):
        for panel, kind in (('apps', 'app'), ('services', 'service')):
            get.return_value = {
                'id': 's', 'name': 'Shop', 'status': 'ACTIVE', 'kind': kind,
                'default_domain_enabled': False,
                'default_url': None, 'primary_url': 'https://shop.example.com'}
            url = reverse('horizon:project:coast.%s:detail' % panel,
                          args=['s'])
            tab_url = url + '?tab=service_details__domains'
            response = self.client.get(tab_url)
            self.assertContains(response, 'Turn default address on')
            self.assertNotContains(response, 'Turn default address off')
            response = self.client.post(tab_url, {
                'action': 'domains__enable_default_address'})
            self.assertEqual(302, response.status_code)
            self.assertEqual(('s', {'default_domain_enabled': True}),
                             update.call_args.args[1:])

    @mock.patch.object(coast, 'coastclient')
    def test_fault_text_survives_adapter_without_truncation(self, client):
        message = 'Domain operation is busy.\n' + 'Details ' * 60
        response = mock.Mock(status_code=409)
        response.json.return_value = {'faultstring': message}
        client.return_value.adapter.request.side_effect = (
            coast.client_exceptions.Conflict(response=response))
        with self.assertRaises(coast.CoastError) as caught:
            coast.service_domain_make_primary(self.request, 's', 'd')
        self.assertEqual(
            message, coast.error_message(caught.exception, 'Oops'))

    @mock.patch.object(coast, 'dns_available', return_value=False)
    @mock.patch.object(coast, 'service_domain_list')
    def test_default_primary_marker_tracks_custom_primary(self, domains, dns):
        tab = tabs.Domains.__new__(tabs.Domains)
        tab.request = self.request
        tab.tab_group = mock.Mock(kwargs={
            'service_id': 's',
            'item': {'default_url': 'https://default.test'}})
        for primary in (False, True):
            domains.return_value = [dict(self.row, primary=primary)]
            rows = tab.get_domains_data()
            self.assertEqual(not primary, rows[0]['primary'])
            self.assertEqual(primary, rows[1]['primary'])
