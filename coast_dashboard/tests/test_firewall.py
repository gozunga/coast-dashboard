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

from django.contrib.messages import constants as message_constants
from django.contrib.messages import get_messages
from django.template.loader import render_to_string
from django.urls import reverse
from keystoneauth1 import adapter
from keystoneauth1 import session
import requests

from coast_dashboard.api import coast
from coast_dashboard.content.admin import resources
from coast_dashboard.content.stacks import firewall
from coast_dashboard.content.stacks import forms
from coast_dashboard.tests import helpers
from coast_dashboard.tests.test_api import _resp


MANAGED = dict(id='managed-http', protocol='tcp', port_range_min=80,
               port_range_max=80, source='0.0.0.0/0',
               description='Managed by Coast', managed=True)
CUSTOM = dict(MANAGED, id='custom', port_range_min=8080, port_range_max=8080,
              description='Customer web', managed=False)


class FirewallTests(helpers.TestCase):
    @mock.patch.object(coast, 'coastclient')
    @mock.patch.object(requests.sessions.Session, 'send')
    def test_wire_version_and_paths(self, send, client):
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"ingress_rules": []}'
        send.return_value = response
        client.return_value.adapter = adapter.Adapter(
            session=session.Session(), service_type='app-hosting',
            endpoint_override='https://coast.example/v1')
        self.assertEqual([], coast.stack_ingress_rule_list(self.request, 's1'))
        sent = send.call_args.args[0]
        self.assertEqual('https://coast.example/v1/stacks/s1/ingress_rules',
                         sent.url)
        self.assertEqual('app-hosting 1.25',
                         sent.headers['OpenStack-API-Version'])

    @mock.patch.object(coast, 'coastclient')
    def test_writes(self, client):
        call = client.return_value.adapter.request
        call.return_value = _resp({'ingress_rule': CUSTOM})
        self.assertEqual(CUSTOM, coast.stack_ingress_rule_create(
            self.request, 's1', {'protocol': 'icmp'}))
        self.assertEqual({'ingress_rule': {'protocol': 'icmp'}},
                         call.call_args.kwargs['json'])
        self.assertEqual('1.25', call.call_args.kwargs['microversion'])
        coast.stack_ingress_rule_delete(self.request, 's1', 'custom')
        self.assertEqual(('/stacks/s1/ingress_rules/custom', 'DELETE'),
                         call.call_args.args)

    @mock.patch.object(coast, '_get')
    def test_version_gate(self, get):
        for version, supported in [('1.24', False), ('1.25', True),
                                   ('1.26', True)]:
            request = mock.Mock()
            get.return_value = {'version': {'max_version': version}}
            self.assertEqual(supported, coast.ingress_supported(request))
        get.side_effect = RuntimeError()
        self.assertFalse(coast.ingress_supported(mock.Mock()))

    @mock.patch.object(coast, 'stack_ingress_rule_list')
    @mock.patch.object(coast, 'ingress_supported', return_value=False)
    def test_old_api_no_request_or_banner(self, supported, listing):
        group = SimpleNamespace(kwargs={'item': {'id': 's1'}})
        with mock.patch.object(firewall.exceptions, 'handle') as handle:
            self.assertIsNone(firewall.rules(group, self.request))
        listing.assert_not_called()
        handle.assert_not_called()
        self.assertFalse(firewall.Firewall.allowed(None, self.request))

    def test_validation(self):
        base = dict(protocol='tcp', port_range_min=8080, port_range_max=8080,
                    source='0.0.0.0/0', description='web')
        for changes, valid in [({}, True), ({'source': '::/0'}, False),
                               ({'port_range_min': 0}, False),
                               ({'port_range_max': 65536}, False),
                               ({'port_range_max': 80}, False),
                               ({'protocol': 'icmp'}, False),
                               ({'description': 'x' * 256}, False),
                               ({'protocol': 'icmp', 'port_range_min': '',
                                 'port_range_max': ''}, True),
                               ({'port_range_max': ''}, True),
                               ({'protocol': 'udp', 'port_range_max': ''},
                                True),
                               ({'port_range_min': ''}, False),
                               ({'port_range_min': '', 'port_range_max': ''},
                                False),
                               ({'protocol': 'icmp',
                                 'port_range_max': ''}, False)]:
            with self.subTest(changes=changes):
                form = forms.AddIngressRule(self.request,
                                            data=dict(base, **changes),
                                            stack_id='s1')
                self.assertEqual(valid, form.is_valid(), form.errors)
                if valid and changes.get('protocol') == 'icmp':
                    self.assertNotIn('port_range_min', form.cleaned_data)
                elif valid:
                    self.assertEqual(8080, form.cleaned_data['port_range_max'])

    def test_project_rendering(self):
        output = render_to_string('project/coast_stacks/firewall.html', {
            'item': {'id': 's1'}, 'rules': [MANAGED, CUSTOM]})
        self.assertIn('Managed by Coast', output)
        self.assertIn('App engine server', output)
        self.assertIn('/custom/delete/', output)
        self.assertNotIn('/managed-http/delete/', output)
        for forbidden in ('Coolify', 'Traefik', 'Management security group'):
            self.assertNotIn(forbidden, output)
        overview = render_to_string('project/coast_stacks/overview.html', {
            'item': {'id': 's1'}, 'firewall_supported': True,
            'custom_rule_count': 1})
        self.assertIn('80, 443 (+1 custom)', overview)
        self.assertIn('Edit rules', overview)

    @mock.patch.object(coast, 'stack_ingress_rule_delete')
    @mock.patch.object(coast, 'stack_ingress_rule_list',
                       return_value=[MANAGED, CUSTOM])
    @mock.patch.object(coast, 'ingress_supported', return_value=True)
    def test_delete_managed_guard_and_post_only(self, supported, listing,
                                                delete):
        ns = 'horizon:project:coast.stacks:delete_ingress_rule'
        url = reverse(ns, args=['s1', 'managed-http'])
        self.assertEqual(405, self.client.get(url).status_code)
        self.assertEqual(302, self.client.post(url).status_code)
        delete.assert_not_called()
        response = self.client.post(reverse(ns, args=['s1', 'custom']))
        self.assertEqual(302, response.status_code)
        self.assertIn('stack_details__firewall', response.url)
        self.assertEqual(
            [(message_constants.SUCCESS, 'Firewall rule deleted.')],
            [(message.level, str(message))
             for message in get_messages(response.wsgi_request)])
        delete.assert_called_once_with(mock.ANY, 's1', 'custom')

    def test_admin_group_names_and_copyable_ids(self):
        fields = dict(resources.overview(
            {'id': 's1', 'sg_ingress_id': 'worker-id',
             'sg_mgmt_id': 'mgmt-id'}, {}, {
                 'worker-id': SimpleNamespace(name='worker-name'),
                 'mgmt-id': SimpleNamespace(name='management-name')}))
        for label, name, identifier in [
                ('Worker security group', 'worker-name', 'worker-id'),
                ('Management security group', 'management-name', 'mgmt-id')]:
            value = str(fields[label])
            self.assertIn(name, value)
            self.assertIn(identifier, value)
            self.assertIn('data', value)
            self.assertNotIn('<a ', value)

    @mock.patch.object(coast, 'stack_ingress_rule_create')
    @mock.patch.object(coast, 'ingress_supported', return_value=True)
    def test_api_fault_on_form(self, supported, create):
        create.side_effect = coast.CoastError('Duplicate rule.', 409)
        form = forms.AddIngressRule(self.request, stack_id='s1')
        with mock.patch.object(form, 'api_error') as error:
            self.assertFalse(form.handle(self.request, {'protocol': 'icmp'}))
        error.assert_called_once_with('Duplicate rule.')

    def test_admin_rule_ownership(self):
        output = render_to_string('admin/coast/overview.html', {
            'fields': [], 'ingress_rules': [MANAGED, CUSTOM],
            'worker_rules': [SimpleNamespace(
                direction='egress', ip_protocol='udp', from_port=53,
                to_port=53, ip_range={'cidr': '0.0.0.0/0'},
                description='DNS')]})
        self.assertIn('Customer-added', output)
        self.assertIn('Managed by Coast', output)
        self.assertIn('egress', output)
        self.assertIn('DNS', output)
        self.assertNotIn('Delete', output)

    def test_applied_neutron_rules_mark_customer(self):
        rule = SimpleNamespace(ip_protocol='tcp', from_port=8080,
                               to_port=8080, direction='ingress',
                               ip_range={'cidr': '0.0.0.0/0'}, group={},
                               description='web')
        group = SimpleNamespace(rules=[rule])
        self.assertTrue(resources.worker_rules(group, [CUSTOM])[0][
            'customer_added'])
        rule.direction = 'egress'
        self.assertFalse(resources.worker_rules(group, [CUSTOM])[0][
            'customer_added'])

    @mock.patch.object(coast, 'stack_ingress_rule_create', return_value=CUSTOM)
    @mock.patch.object(coast, 'ingress_supported', return_value=True)
    def test_add_view(self, supported, create):
        url = reverse('horizon:project:coast.stacks:add_ingress_rule',
                      args=['s1'])
        page = self.client.get(url)
        for text in ('Source (IPv4 CIDR)', 'IPv4 only, for example',
                     'leave Last port blank',
                     'Leave blank to allow only the first port.'):
            self.assertContains(page, text)
        response = self.client.post(url, {
            'protocol': 'tcp', 'port_range_min': 8080,
            'port_range_max': '', 'source': '0.0.0.0/0',
            'description': 'web'})
        self.assertEqual(302, response.status_code)
        self.assertIn('stack_details__firewall', response.url)
        self.assertEqual(
            [(message_constants.SUCCESS, 'Firewall rule added.')],
            [(message.level, str(message))
             for message in get_messages(response.wsgi_request)])
        create.assert_called_once_with(mock.ANY, 's1', {
            'protocol': 'tcp', 'port_range_min': 8080,
            'port_range_max': 8080, 'source': '0.0.0.0/0',
            'description': 'web'})
