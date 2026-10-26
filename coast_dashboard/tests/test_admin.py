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

from html.parser import HTMLParser
import re
from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from django.contrib.messages import get_messages
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
import horizon
from openstack_auth import utils
from openstack_dashboard.api import cinder
from openstack_dashboard.api import glance
from openstack_dashboard.api import keystone
from openstack_dashboard.api import neutron
from openstack_dashboard.api import nova

from coast_dashboard.api import coast
from coast_dashboard.content.admin import panel
from coast_dashboard.content.admin import resources
from coast_dashboard.content.admin import tables as admin_tables
from coast_dashboard.content.admin import topology
from coast_dashboard.content import common
from coast_dashboard.tests import helpers
from coast_dashboard.tests.test_api import _resp


STACK = {'id': 'stack-id', 'name': 'Primary stack', 'project_id': 'owner-id',
         'service_project_id': 'service-id', 'status': 'ACTIVE',
         'created_at': '2026-10-18T10:00:00Z', 'server_count': 2,
         'workload_count': 0}
SERVER = {'id': 'worker-id', 'name': 'Worker one', 'role': 'worker',
          'compute_id': 'nova-id', 'image_id': 'image-id',
          'flavor_id': 'flavor-id', 'mgmt_ip': '192.0.2.1',
          'private_ip': '192.0.2.2', 'status': 'ACTIVE'}


class AdminPanelTests(helpers.TestCase):
    def setUp(self):
        super().setUp()
        self.set_user('admin')
        for obj, name, result in (
                (neutron, 'port_list', []),
                (neutron, 'security_group_get', None),
                (coast, 'ingress_supported', False),
                (neutron, 'network_list', []),
                (neutron, 'router_list', []),
                (neutron, 'networkclient', mock.Mock(
                    ips=mock.Mock(return_value=[]))),
                (cinder, 'volume_list', []),
                (coast, 'admin_stack_list', [STACK]),
                (coast, 'admin_stack_get', STACK),
                (coast, 'admin_resource_list', []),
                (coast, 'admin_event_list', ([], None)),
                (keystone, 'tenant_list', ([
                    SimpleNamespace(id='owner-id', name='Owner project'),
                    SimpleNamespace(id='service-id', name='Service project')],
                    False))):
            patcher = mock.patch.object(obj, name, return_value=result)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def set_user(self, role):
        self.setActiveUser(
            id=self.user.id, token=self.token, username=self.user.name,
            tenant_id=self.tenant.id, tenant_name=self.tenant.name,
            domain_id=self.domain.id, user_domain_name=self.domain.name,
            service_catalog=self.service_catalog,
            authorized_tenants=self.context['authorized_tenants'],
            roles=[{'name': role}])
        # Drop Horizon's access cache when changing users in one test.
        session = self.client.session
        session.pop('allowed', None)
        session.save()
        self.request.user = utils.get_user(self.request)

    def url(self, view='index'):
        return reverse('horizon:admin:stacks:' + view,
                       args=['stack-id'] if view == 'detail' else None)

    def get_tab(self, slug):
        return self.client.get(self.url('detail'),
                               {'tab': 'admin_stacks__' + slug})

    def test_admin_can_access_and_member_cannot(self):
        component = horizon.get_dashboard('admin').get_panel('stacks')
        self.assertEqual('Stacks', str(component.name))
        group = horizon.get_dashboard('admin').get_panel_group('app_hosting')
        self.assertEqual('App Hosting', str(group.name))
        self.assertIn(component, list(group))
        self.assertTrue(component.allowed({'request': self.request}))
        self.assertContains(self.client.get(self.url()), 'Primary stack')
        for role in ('member', 'reader'):
            self.set_user(role)
            self.assertFalse(component.allowed({'request': self.request}))
            self.admin_stack_list.reset_mock()
            self.admin_stack_get.reset_mock()
            for url in (self.url(), self.url('detail')):
                result = self.client.get(url)
                self.assertIn(result.status_code, (302, 403))
            self.admin_stack_list.assert_not_called()
            self.admin_stack_get.assert_not_called()

    @mock.patch.object(panel.policy, 'check', return_value=False)
    def test_coast_policy_denies_admin(self, check):
        component = horizon.get_dashboard('admin').get_panel('stacks')
        self.assertFalse(component.allowed({'request': self.request}))
        check.assert_called_with(panel.ADMIN_RULES, self.request)
        result = self.client.get(self.url('detail'))
        self.assertIn(result.status_code, (302, 403))
        self.admin_stack_get.assert_not_called()

    def test_stack_list_and_filters(self):
        self.admin_stack_list.return_value = [
            STACK, dict(STACK, id='other-id', name='Other stack',
                        project_id='other-project', status='ERROR')]
        result = self.client.get(self.url())
        for text in ('Owner project', 'Primary stack', 'Other stack',
                     'Servers', 'Workloads', 'Oct.'):
            self.assertContains(result, text)
        self.assertRegex(result.content.decode(), r'>\s*0\s*<')
        self.assertContains(result, self.url('detail'))
        # IDs are link targets, never visible table cell values.
        self.assertNotContains(result, '>stack-id<')
        self.assertNotContains(result, '>owner-id<')
        for params in ({'project': 'owner-id'}, {'status': 'ACTIVE'},
                       {'project': 'owner-id', 'status': 'ACTIVE'}):
            result = self.client.get(self.url(), params)
            self.assertContains(result, 'Primary stack')
            self.assertNotContains(result, '>Other stack<')
        result = self.client.get(self.url(),
                                 {'project': 'owner-id', 'status': 'ERROR'})
        self.assertNotContains(result, '>Primary stack<')

    def test_absent_and_null_counts(self):
        for values in ({}, {'server_count': None, 'workload_count': None}):
            self.admin_stack_list.return_value = [dict(
                id='stack-id', name='Minimal stack', project_id='owner-id',
                **values)]
            self.assertContains(self.client.get(self.url()), 'Minimal stack')

    def test_overview_links_and_optional_fields(self):
        self.admin_stack_get.return_value = dict(
            STACK, network_id='network-id', subnet_id='subnet-id',
            router_id='router-id', sg_ingress_id='ingress-id',
            sg_mgmt_id='mgmt-id')
        result = self.get_tab('overview')
        for text in ('Owner project', 'Service project', 'Actions', 'Refresh',
                     'Workloads', 'History', 'network-id', 'ingress-id'):
            self.assertContains(result, text)
        for resource, value in (
                ('networks', 'network-id'),
                ('networks:subnets', 'subnet-id'), ('routers', 'router-id')):
            self.assertContains(result, reverse(
                'horizon:admin:%s:detail' % resource, args=[value]))
        for stack in ({'id': 'stack-id', 'name': 'Minimal'},
                      dict(STACK, service_project_id=None, network_id=None)):
            self.admin_stack_get.return_value = stack
            result = self.get_tab('overview')
            self.assertContains(result, '<dd>-</dd>', html=True)

    def test_overview_engine_and_wrapping_labels(self):
        for version, expected in (('4.4.3', 'Coolify 4.4.3'),
                                  ('v4.4.3', 'Coolify v4.4.3'),
                                  (None, '-'), ('', '-')):
            with self.subTest(version=version):
                self.admin_stack_get.return_value = dict(
                    STACK, engine_version=version)
                result = self.get_tab('overview')
                self.assertContains(result, '<dt>App engine</dt><dd>%s</dd>'
                                    % expected, html=True)
                self.assertNotContains(result, 'App engine server version')
                for label, _ in resources.overview(STACK, {}):
                    self.assertContains(result, '<dt>%s</dt>' % label,
                                        html=True)
                self.assertContains(result, 'dl-horizontal coast-detail-dl')
                self.assertContains(result, '.coast-detail-dl dt')
                self.assertContains(result, 'white-space: normal;')
                self.assertContains(result, 'overflow: visible;')
                self.assertContains(result, 'text-overflow: clip;')
                self.assertContains(result, 'width: 15em;')
                self.assertNotContains(result, 'text-overflow: ellipsis')

    def cloud_mocks(self):
        instance = SimpleNamespace(id='nova-id', name='Actual Nova name',
                                   status='SHUTOFF')
        setattr(instance, 'OS-EXT-SRV-ATTR:hypervisor_hostname', 'compute-01')
        for obj, name, result in (
                (nova, 'server_list', ([nova.Server(instance, self.request)],
                                       False)),
                (glance, 'image_list_detailed', ([SimpleNamespace(
                    id='image-id', name='Worker image')], False, False)),
                (nova, 'flavor_list', [SimpleNamespace(
                    id='flavor-id', name='Standard flavor')])):
            patcher = mock.patch.object(obj, name, return_value=result)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def resource_list(self, request, stack_id, resource):
        return {
            'servers': [SERVER, dict(SERVER, id='control-id', role='control',
                                     name='coolify-traefik',
                                     compute_id='control-nova-id',
                                     image_id='engine-image-id')],
            'volumes': [{'id': 'volume-id', 'server_id': 'worker-id',
                         'name': 'Data volume', 'size_gb': 12,
                         'cinder_volume_id': 'cinder-id'},
                        {'id': 'unattached', 'server_id': None}],
            'services': [{'id': 'app-id', 'name': 'Web app', 'kind': 'app',
                          'server_id': 'worker-id'},
                         {'id': 'service-id', 'name': 'Database',
                          'kind': 'service', 'server_id': 'gone-worker'}]
        }[resource]

    def test_server_detail_hostname_from_api(self):
        self.cloud_mocks()
        for fields, expected in (({'hostname': 'worker-abc'}, 'worker-abc'),
                                 ({'hostname': ''}, '-'),
                                 ({'hostname': None}, '-'), ({}, '-')):
            with self.subTest(fields=fields):
                server = dict(SERVER, **fields)
                self.admin_resource_list.side_effect = lambda r, s, kind: (
                    [server] if kind == 'servers' else [])
                result = self.get_tab('servers')
                self.assertContains(
                    result, '<dt>Hostname</dt><dd>%s</dd>' % expected,
                    html=True)

    def test_server_cloud_mapping_is_batched(self):
        self.cloud_mocks()
        self.admin_resource_list.side_effect = self.resource_list
        result = self.get_tab('servers')
        for text in ('Worker one', 'App engine server', 'Actual Nova name',
                     'SHUTOFF', 'compute-01', 'Worker image', 'image-id',
                     'Standard flavor', '192.0.2.1', '192.0.2.2',
                     'Data volume', '12 GiB'):
            self.assertContains(result, text)
        for resource, value in (('instances', 'nova-id'),
                                ('volumes', 'cinder-id')):
            self.assertContains(result, reverse(
                'horizon:admin:%s:detail' % resource, args=[value]))
        for text in ('coolify', 'traefik', 'unattached'):
            self.assertNotContains(result, text)
        self.server_list.assert_called_once_with(mock.ANY, search_opts={
            'all_tenants': True, 'tenant_id': 'service-id'})
        self.image_list_detailed.assert_called_once_with(
            mock.ANY, filters={'id': 'in:engine-image-id,image-id'})
        self.flavor_list.assert_called_once()

    def test_missing_instance_keeps_coast_details(self):
        self.cloud_mocks()
        self.server_list.return_value = ([], False)
        self.admin_resource_list.side_effect = self.resource_list
        result = self.get_tab('servers')
        for text in ('not found', 'Worker one', 'nova-id', 'Worker image',
                     'Data volume', '192.0.2.1'):
            self.assertContains(result, text)

    def test_cloud_failure_keeps_coast_details(self):
        self.cloud_mocks()
        self.server_list.side_effect = coast.exceptions.RecoverableError()
        self.image_list_detailed.side_effect = (
            coast.exceptions.RecoverableError())
        self.flavor_list.side_effect = coast.exceptions.RecoverableError()
        self.admin_resource_list.side_effect = self.resource_list
        result = self.get_tab('servers')
        self.assertContains(result, 'Worker one')
        self.assertContains(result, 'Unavailable')
        self.assertContains(result, 'Data volume')

    def test_missing_server_fields_do_not_call_cloud(self):
        self.cloud_mocks()
        self.admin_resource_list.side_effect = lambda r, s, kind: (
            [{'id': 'worker-id'}] if kind == 'servers' else
            [{'server_id': 'worker-id'}])
        result = self.get_tab('servers')
        self.assertEqual(200, result.status_code)
        self.assertContains(result, '- GiB')
        self.server_list.assert_not_called()
        self.image_list_detailed.assert_not_called()
        self.flavor_list.assert_not_called()

    def test_nova_project_defaults_to_owner(self):
        self.cloud_mocks()
        resources.servers(self.request, dict(STACK, service_project_id=None),
                          [SERVER], [])
        self.server_list.assert_called_once_with(self.request, search_opts={
            'all_tenants': True, 'tenant_id': 'owner-id'})

    def test_resource_names_are_never_scrubbed(self):
        self.cloud_mocks()
        image_name = 'coast-coolify-controller-20261019'
        self.image_list_detailed.return_value = ([SimpleNamespace(
            id='image-id', name=image_name)], False, False)
        instance = SimpleNamespace(id='nova-id', name='traefik-coolify-vm',
                                   status='ACTIVE')
        setattr(instance, 'OS-EXT-SRV-ATTR:hypervisor_hostname',
                'coolify-host')
        self.server_list.return_value = ([instance], False)
        self.flavor_list.return_value = [SimpleNamespace(
            id='flavor-id', name='coolify-flavor')]
        self.admin_resource_list.side_effect = self.resource_list
        result = self.get_tab('servers')
        for name in (image_name, instance.name, 'coolify-host',
                     'coolify-flavor'):
            self.assertContains(result, name)
        self.assertNotContains(result, 'coast-App engine server-controller')
        image = self.image_list_detailed.return_value[0][0]
        image.name = '<script>bad</script>'
        result = self.get_tab('servers')
        self.assertContains(result, '&lt;script&gt;bad&lt;/script&gt;')
        self.assertNotContains(result, '<script>bad</script>')

    def test_stack_counts_link_to_servers_without_child_rows(self):
        self.admin_stack_list.return_value = [
            STACK, dict(STACK, id='empty-stack', server_count=0)]
        result = self.client.get(self.url())
        self.assertContains(
            result, '<a href="{}?tab=admin_stacks__servers" '
            'target="_blank" rel="noopener">2</a>'.format(
                self.url('detail')), html=True)
        self.assertNotContains(result, 'Show servers')
        self.assertNotContains(result, 'tablesorter-childRow')
        self.assertNotContains(result, '<details')
        table = result.context['table']
        empty_row = table.get_rows()[1]
        self.assertEqual(0, empty_row.cells['server_count'].value)
        self.assertTrue(table.columns['server_count'].sortable)
        self.assertTrue(table.columns['created_at'].sortable)
        self.assertNotContains(
            result, '/admin/stacks/empty-stack/?tab=admin_stacks__servers')

    def test_empty_server_counts_render_plain_zero(self):
        for values in ({'server_count': 0}, {'server_count': None}, {}):
            with self.subTest(values=values):
                stack = dict(STACK)
                stack.pop('server_count')
                stack.update(values)
                table = admin_tables.StacksTable(self.request, data=[stack])
                cell = table.get_rows()[0].cells['server_count']
                self.assertEqual(0, cell.value)
                self.assertRegex(cell.render(), r'>\s*0\s*</td>')
                self.assertNotIn('<a', cell.render())

    def test_server_count_link_loads_servers_tab(self):
        self.cloud_mocks()
        self.admin_resource_list.side_effect = self.resource_list
        result = self.client.get(self.url())
        href = re.search(
            r'href="([^"]+\?tab=admin_stacks__servers)"',
            result.content.decode()).group(1)
        result = self.client.get(href)
        self.assertEqual(200, result.status_code)
        self.assertContains(result, 'Worker one')
        self.assertContains(result, 'Actual Nova name')
        self.assertFalse(list(get_messages(result.wsgi_request)))

    def test_stack_created_uses_viewer_timezone(self):
        # Render directly so the timezone is not reset by request middleware.
        with timezone.override(ZoneInfo('America/Chicago')):
            table = admin_tables.StacksTable(self.request, data=[STACK])
            expected = common.local_datetime(STACK['created_at'])
            self.assertEqual(
                expected, table.get_rows()[0].cells['created_at'].value)
            self.assertIn('5 a.m.', expected)
            self.assertIn('CDT', expected)
            self.assertIn(expected, table.render())

    def test_inventory_filters_search_and_batch_mapping(self):
        self.cloud_mocks()
        self.server_list.return_value[0][0]._apiresource.status = 'ACTIVE'

        def inventory_resources(request, stack_id, resource):
            if stack_id == 'second':
                return []
            return self.resource_list(request, stack_id, resource) + [
                dict(SERVER, id='build-id', role='build', compute_id=None)]

        self.admin_resource_list.side_effect = inventory_resources
        self.admin_stack_list.return_value = [
            dict(STACK, engine_version='1.2'),
            dict(STACK, id='second', name='Second stack',
                 project_id='other-owner', status='ERROR')]
        self.port_list.return_value = [SimpleNamespace(
            id='port-id', device_id='nova-id', network_id='network-id',
            fixed_ips=[{'ip_address': '192.0.2.9'}])]
        self.networkclient.return_value.ips.return_value = [SimpleNamespace(
            id='fip-id', port_id='port-id',
            floating_ip_address='198.51.100.9')]
        result = self.client.get(self.url())
        for text in ('Workers', 'Build servers', 'App engine server version',
                     'Health', '1/3 active'):
            self.assertContains(result, text)
        self.assertContains(result, reverse('horizon:identity:projects:detail',
                                            args=['owner-id']))
        self.assertNotContains(result, 'coolify')
        self.assertNotContains(result, 'traefik')
        self.server_list.assert_called_once()
        self.image_list_detailed.assert_called_once()
        self.flavor_list.assert_called_once()
        self.port_list.assert_called_once_with(
            request=mock.ANY, device_id=('control-nova-id', 'nova-id'))
        for query in ('primary STACK', 'STACK-ID', 'owner PROJECT',
                      'OWNER-ID', 'aCtIvE', '1.2', 'WORKER-1', 'CONTROLLER',
                      'BUILD-1', 'WORKER-ID', 'actual NOVA', 'NOVA-ID',
                      'COMPUTE-01', 'worker IMAGE', 'standard FLAVOR',
                      '192.0.2.9', '198.51.100.9'):
            with self.subTest(query=query):
                result = self.client.get(self.url(), {'q': query})
                self.assertContains(result, '>Primary stack<')
                self.assertNotContains(result, '>Second stack<')
        filters = {'q': 'worker-1', 'host': 'compute-01',
                   'project': 'owner-id', 'status': 'ACTIVE'}
        result = self.client.get(self.url(), filters)
        self.assertContains(result, '>Primary stack<')
        self.assertNotContains(result, '>Second stack<')
        for params in ({'q': 'absent'}, {'host': 'absent-host'},
                       dict(filters, host='absent-host'),
                       dict(filters, project='other-owner'),
                       dict(filters, status='ERROR')):
            with self.subTest(params=params):
                result = self.client.get(self.url(), params)
                self.assertNotContains(result, '>Primary stack<')
                self.assertNotContains(result, '>Second stack<')
                self.assertContains(result, 'No stacks match these filters.')
                self.assertContains(
                    result, '<a href="%s" class="btn btn-link">'
                    'Clear filters</a>' % self.url(), html=True)
        self.assertContains(result, 'Stack, project, server, host, or IP')

    def topology_fakes(self):
        self.cloud_mocks()
        self.port_list.return_value = [
            SimpleNamespace(id='customer-port', device_id='nova-id',
                            network_id='customer-net', fixed_ips=[
                                {'ip_address': '192.0.2.2'}]),
            SimpleNamespace(id='management-port', device_id='nova-id',
                            network_id='management-net', fixed_ips=[
                                {'ip_address': '192.0.2.1'}]),
            SimpleNamespace(id='router-port', device_id='router-id',
                            network_id='customer-net', fixed_ips=[])]
        self.network_list.return_value = [
            SimpleNamespace(id='customer-net', name='Customer network name'),
            SimpleNamespace(id='management-net', name='coolify-backplane')]
        self.router_list.return_value = [SimpleNamespace(
            id='router-id', name='Stack router')]
        self.networkclient.return_value.ips.return_value = [SimpleNamespace(
            id='fip-id', floating_ip_address='198.51.100.9',
            port_id='customer-port')]
        self.volume_list.return_value = [SimpleNamespace(
            id='cinder-id', name='traefik-data', attachments=[
                {'server_id': 'nova-id'}])]
        return dict(STACK, router_id='router-id', network_id='customer-net')

    def test_topology_has_cloud_nodes_and_real_attachment_edges(self):
        stack = self.topology_fakes()
        data = topology.build(self.request, stack, [SERVER],
                              self.resource_list(None, None, 'volumes'))
        self.assertEqual(4, len(data['nodes']))
        self.assertEqual(3, len(data['edges']))
        self.assertFalse(any(n['missing'] for n in data['nodes']))
        for panel_name, resource_id in (
                ('instances', 'nova-id'), ('routers', 'router-id'),
                ('networks', 'management-net'), ('networks', 'customer-net'),
                ('volumes', 'cinder-id'), ('floating_ips', 'fip-id')):
            self.assertIn(reverse('horizon:admin:%s:detail' % panel_name,
                                  args=[resource_id]),
                          [n['url'] for n in data['nodes']] +
                          [i['url'] for n in data['nodes']
                           for i in n['items']])
        server = next(n for n in data['nodes'] if n['column'] == 2)
        self.assertEqual('worker-1', server['name'])
        self.assertEqual({'cinder-id', 'fip-id'},
                         {i['id'] for i in server['items']})
        self.assertEqual([server], data['columns'][2])
        markup = render_to_string('admin/coast/topology.html', data)
        self.assertEqual(markup.count('<a '),
                         markup.count('target="_blank" rel="noopener"'))
        self.assertIn(server['details'], markup)
        self.assertIn('width:100%', markup)
        self.assertIn('overflow-wrap:anywhere', markup)
        self.assertIn('repeat(2, minmax(0, 1fr))', markup)
        for forbidden in ('text-overflow', 'ellipsis', 'truncatechars',
                          'foreignObject', 'width="1340"', 'width="310"'):
            self.assertNotIn(forbidden, markup)
        self.assertNotIn('coolify', markup.lower())
        self.assertNotIn('traefik', markup.lower())

        self.port_list.assert_called_once_with(
            request=self.request, device_id=('nova-id', 'router-id'))
        self.volume_list.assert_called_once_with(self.request, search_opts={
            'all_tenants': True, 'project_id': 'service-id'})
        self.admin_stack_get.return_value = stack
        self.admin_resource_list.side_effect = self.resource_list
        result = self.get_tab('topology')
        for text in ('Stack topology', 'Management / backplane network',
                     'Management network', 'Data volume', 'worker-1',
                     'Actual Nova name', '198.51.100.9', 'Legend:',
                     'Dashed = not found', 'target="_blank"',
                     'rel="noopener"'):
            self.assertContains(result, text)

    def test_topology_wraps_full_addresses_names_and_identifiers(self):
        stack = self.topology_fakes()
        router_id = 'c6cea4c5-0460-4123-8123-123456789abc'
        stack['router_id'] = router_id
        self.port_list.return_value[-1].device_id = router_id
        self.router_list.return_value[0].id = router_id
        self.router_list.return_value[0].name = router_id
        addresses = ['198.51.100.165', '192.0.2.114',
                     '2001:db8:1234:5678::1234']
        self.port_list.return_value[0].fixed_ips = [
            {'ip_address': address} for address in addresses]
        long_name = 'Customer network with a long readable name'
        self.network_list.return_value[0].name = long_name
        data = topology.build(self.request, stack, [SERVER], [])
        markup = render_to_string('admin/coast/topology.html', data)
        full_addresses = sorted(set(addresses) | {SERVER['mgmt_ip'],
                                                  SERVER['private_ip']})
        self.assertIn(', '.join(full_addresses), markup)
        self.assertIn(long_name, markup)
        self.assertIn('title="%s"' % router_id, markup)
        self.assertIn('>%s ↗</a>' % router_id, markup)
        self.assertNotIn('…', markup)
        self.assertNotRegex(markup, r'<svg[^>]*width="[0-9]+"')
        self.assertNotIn('white-space:nowrap', markup)
        self.assertIn('ResizeObserver', markup)
        node_ids = {node['dom_id'] for node in data['nodes']}
        for edge in data['edges']:
            self.assertIn(edge['left'], node_ids)
            self.assertIn(edge['right'], node_ids)

    def test_topology_roles_purposes_and_unattached_resources(self):
        stack = self.topology_fakes()
        rows = [SERVER, dict(SERVER, id='control', compute_id=None,
                             role='control'),
                dict(SERVER, id='build', compute_id=None, role='build')]
        self.volume_list.return_value.append(SimpleNamespace(
            id='orphan', name='Loose data', attachments=[]))
        volumes = [{'server_id': 'worker-id', 'cinder_volume_id': 'cinder-id',
                    'purpose': '/var/lib/docker', 'size_gb': 40},
                   {'cinder_volume_id': 'orphan'}]
        data = topology.build(self.request, stack, rows, volumes)
        names = {n['name'] for n in data['nodes']}
        self.assertTrue({'worker-1', 'App engine server', 'build-1',
                         'Loose data'} <= names)
        worker = next(n for n in data['nodes'] if n['name'] == 'worker-1')
        self.assertEqual('docker disk · 40 GB', worker['items'][0]['name'])
        self.assertFalse(any(n['column'] == 3 and n['id'] == 'cinder-id'
                             for n in data['nodes']))

    def test_topology_missing_resources_keep_known_relationships(self):
        stack = self.topology_fakes()
        self.server_list.return_value = ([], False)
        self.network_list.return_value = []
        self.router_list.return_value = []
        self.volume_list.return_value = []
        self.networkclient.return_value.ips.return_value = []
        data = topology.build(self.request, stack,
                              [dict(SERVER, floating_ip_id='deleted-fip')],
                              self.resource_list(None, None, 'volumes'))
        self.assertTrue(all(n['missing'] for n in data['nodes']))
        self.assertEqual(6, len(data['nodes']))
        self.assertEqual(3, len(data['edges']))
        self.admin_stack_get.return_value = stack
        self.admin_resource_list.side_effect = self.resource_list
        self.assertContains(self.get_tab('topology'), 'not found')

    def test_volumes_and_workload_links(self):
        self.admin_resource_list.side_effect = self.resource_list
        result = self.get_tab('volumes')
        self.assertContains(result, 'Data volume')
        self.assertContains(result, 'data-copy-value="Data volume"')
        self.assertContains(result, 'coast-copy')
        self.assertContains(result, 'function fallback(value)')
        self.assertContains(result, 'class="coast-admin-stack-tabs"')
        self.assertContains(
            result, '.coast-admin-stack-tabs .tab-pane { '
            'padding-bottom: 40px; }')
        self.assertContains(result, reverse('horizon:admin:volumes:detail',
                                            args=['cinder-id']))
        result = self.get_tab('workloads')
        for panel_name, resource_id in (('apps', 'app-id'),
                                        ('services', 'service-id')):
            self.assertContains(result, reverse(
                'horizon:project:coast.%s:detail' % panel_name,
                args=[resource_id]))

    def test_stack_detail_links_open_new_tabs(self):
        self.admin_stack_get.return_value = self.topology_fakes()
        self.admin_resource_list.side_effect = self.resource_list
        self.admin_event_list.return_value = ([{
            'action': 'create', 'detail': {'compute_id': 'nova-id'}}],
            'next-id')

        class DetailLinks(HTMLParser):
            def __init__(inner):
                super().__init__()
                inner.depth = 0
                inner.links = []
                inner.refresh = []

            def handle_starttag(inner, tag, attrs):
                attrs = dict(attrs)
                if tag == 'div':
                    if inner.depth or 'coast-admin-stack-tabs' in (
                            attrs.get('class', '').split()):
                        inner.depth += 1
                if tag == 'a' and 'href' in attrs:
                    if inner.depth:
                        inner.links.append(attrs)
                    elif attrs['href'] == self.url('detail'):
                        inner.refresh.append(attrs)

            def handle_endtag(inner, tag):
                if tag == 'div' and inner.depth:
                    inner.depth -= 1

        for slug in ('overview', 'servers', 'volumes', 'topology',
                     'workloads', 'history'):
            with self.subTest(tab=slug):
                result = self.get_tab(slug)
                self.assertEqual(200, result.status_code)
                parser = DetailLinks()
                parser.feed(result.content.decode())
                self.assertEqual(1, len(parser.refresh))
                controls = list(parser.refresh)
                page_links = []
                for attrs in parser.links:
                    href = attrs['href']
                    if attrs.get('data-toggle') == 'tab' or href == (
                            self.url('detail') +
                            '?tab=admin_stacks__history&marker=next-id'):
                        controls.append(attrs)
                    else:
                        page_links.append(attrs)
                self.assertEqual(7 + (slug == 'history'), len(controls))
                for attrs in controls:
                    self.assertNotIn('target', attrs)
                self.assertTrue(page_links)
                for attrs in page_links:
                    self.assertEqual('_blank', attrs.get('target'), attrs)
                    self.assertIn('noopener', attrs.get('rel', '').split(),
                                  attrs)
                if slug == 'workloads':
                    for panel_name, resource_id in (
                            ('apps', 'app-id'), ('services', 'service-id')):
                        self.assertIn(reverse(
                            'horizon:project:coast.%s:detail' % panel_name,
                            args=[resource_id]),
                            [attrs['href'] for attrs in page_links])

    def test_workload_placement(self):
        self.admin_resource_list.side_effect = self.resource_list
        result = self.get_tab('workloads')
        for text in ('Web app', 'Database', 'Worker one'):
            self.assertContains(result, text)
        self.assertNotContains(result, 'gone-worker')

    def test_history_pagination_and_compute_ids(self):
        self.admin_event_list.return_value = ([{
            'id': 'event-id', 'action': 'failover', 'outcome': 'success',
            'resource_id': 'worker-id',
            'created_at': '2026-10-18T10:00:00Z',
            'detail': {'old_compute_id': 'old-nova-id',
                       'new_compute_id': 'new-nova-id',
                       'engine_token': 'do-not-render-this'}},
            {'action': 'create', 'detail': {'compute_id': 'created-nova-id'}},
            {'action': 'delete', 'detail': {'compute_id': 'deleted-nova-id'}},
            {'action': 'create', 'detail': None},
            {'action': 'replace', 'detail': 'unexpected'}], 'next-id')
        result = self.get_tab('history')
        for text in ('old-nova-id', 'new-nova-id', 'failover', 'Older events',
                     'marker=next-id', 'created-nova-id', 'deleted-nova-id',
                     'Oct.'):
            self.assertContains(result, text)
        self.assertNotContains(result, 'do-not-render-this')
        self.client.get(self.url('detail'), {
            'tab': 'admin_stacks__history', 'marker': 'next-id'})
        self.admin_event_list.assert_called_with(mock.ANY, 'stack-id',
                                                 marker='next-id')

    def test_api_fault_is_visible(self):
        for method, url in ((self.admin_stack_list, self.url()),
                            (self.admin_event_list, self.url('detail'))):
            method.side_effect = coast.CoastError('API validation reason')
            result = self.client.get(url, {'tab': 'admin_stacks__history'})
            self.assertContains(result, 'API validation reason')
            method.side_effect = None
        self.admin_stack_get.side_effect = coast.CoastError('Bad stack id')
        result = self.client.get(self.url('detail'))
        self.assertEqual(302, result.status_code)
        messages = [str(m) for m in get_messages(result.wsgi_request)]
        self.assertTrue(any('Bad stack id' in m for m in messages))


class AdminApiTests(helpers.TestCase):
    @mock.patch.object(coast, 'coastclient')
    def test_admin_reads_use_adapter_and_one_version(self, client):
        adapter = client.return_value.adapter.request
        for call, path, body in (
                (lambda: coast.admin_stack_list(self.request),
                 '/stacks?all_projects=true', {'stacks': []}),
                (lambda: coast.admin_stack_get(self.request, 's'),
                 '/stacks/s?all_projects=true', {'stack': {'id': 's'}}),
                (lambda: coast.admin_resource_list(
                    self.request, 's', 'servers'),
                 '/stacks/s/servers?all_projects=true', {'servers': []}),
                (lambda: coast.admin_resource_list(
                    self.request, 's', 'volumes'),
                 '/stacks/s/volumes?all_projects=true', {'volumes': []}),
                (lambda: coast.admin_resource_list(
                    self.request, 's', 'services'),
                 '/services?stack_id=s&all_projects=true', {'services': []})):
            adapter.return_value = _resp(body)
            call()
            adapter.assert_called_with(path, 'GET',
                                       microversion='1.18',
                                       log=False, connect_retries=0,
                                       status_code_retries=0)
        client.return_value.request.assert_not_called()
        self.assertTrue(all(c == mock.call(self.request, '1.0')
                            for c in client.call_args_list))

    @mock.patch.object(coast, 'coastclient')
    def test_admin_pagination_preserves_scope(self, client):
        adapter = client.return_value.adapter.request
        adapter.side_effect = [
            _resp({'servers': [{'id': 'first'}], 'links': [{
                'rel': 'next',
                'href': 'https://other/servers?marker=first'}]}),
            _resp({'servers': [{'id': 'second'}]})]
        self.assertEqual([{'id': 'first'}, {'id': 'second'}],
                         coast.admin_resource_list(self.request, 's',
                                                   'servers'))
        self.assertEqual('/stacks/s/servers?all_projects=true&marker=first',
                         adapter.call_args.args[0])
        self.assertEqual(coast.ADMIN_VERSION,
                         adapter.call_args.kwargs['microversion'])

    @mock.patch.object(coast, 'coastclient')
    def test_event_page_uses_scope_and_local_marker(self, client):
        adapter = client.return_value.adapter.request
        adapter.return_value = _resp({
            'events': [{'action': 'failover'}], 'links': [{
                'rel': 'next', 'href': 'https://other/?marker=next'}]})
        self.assertEqual(([{'action': 'failover'}], 'next'),
                         coast.admin_event_list(self.request, 's', 'old'))
        path = urlsplit(adapter.call_args.args[0])
        self.assertEqual('/stacks/s/events', path.path)
        self.assertEqual({'all_projects': ['true'],
                          'resource_type': ['server'],
                          'limit': ['50'], 'marker': ['old']},
                         parse_qs(path.query))
        self.assertEqual(coast.ADMIN_VERSION,
                         adapter.call_args.kwargs['microversion'])
        self.assertEqual(([{'action': 'failover'}], None),
                         coast.admin_event_list(self.request, 's', 'next'))

    @mock.patch.object(coast, 'coastclient')
    def test_admin_400_keeps_api_fault(self, client):
        response = _resp({'faultstring': 'Invalid project filter'})
        response.status_code = 400
        client.return_value.adapter.request.side_effect = (
            coast.client_exceptions.BadRequest(response=response))
        with self.assertRaises(coast.CoastError) as caught:
            coast.admin_stack_list(self.request)
        self.assertEqual('Invalid project filter',
                         caught.exception.api_message)

    @mock.patch.object(coast, 'coastclient')
    def test_admin_version_is_not_silently_downgraded(self, client):
        client.return_value.adapter.request.side_effect = (
            coast.client_exceptions.NotAcceptable())
        with self.assertRaises(coast.CoastError):
            coast.admin_stack_list(self.request)
        client.return_value.request.assert_not_called()


class AdminVolumeCardTests(helpers.TestCase):
    def test_grouping_cards_and_links(self):
        servers = [dict(SERVER), {'id': 'control', 'role': 'control',
                                  'compute_id': 'control-nova'},
                   {'id': 'build', 'role': 'build',
                    'compute_id': 'build-nova'}]
        volumes = [dict(server_id=server, name='coast-' + purpose,
                        cinder_volume_id='volume-' + purpose, size_gb=2,
                        status='IN_USE', mount_path='/data')
                   for server, purpose in [('worker-id', 'data'),
                                           ('control', 'docker'),
                                           ('build', 'registry'),
                                           (None, 'data')]]
        volumes[0]['device'] = '/dev/vdb'
        groups = resources.volume_groups(volumes, servers)
        self.assertIn('App engine server', str(groups[0]['link']))
        self.assertIn('build-1', str(groups[1]['link']))
        self.assertIn('worker-1', str(groups[2]['link']))
        self.assertEqual('Unattached', str(groups[3]['link']))
        html = render_to_string('admin/coast/volumes.html', {
            'volume_groups': groups})
        for text in ('Attached to <a', 'worker-1', 'Not attached',
                     'title="IN_USE"', '>data</a>', '>docker disk</a>',
                     '>registry</a>', '/dev/vdb', 'auto-fill', 'minmax',
                     'coast-data — volume-data'):
            self.assertIn(text, html)

        class Links(HTMLParser):
            def handle_starttag(inner, tag, attrs):
                if tag == 'a':
                    self.assertEqual('_blank', dict(attrs).get('target'))
                    self.assertEqual('noopener', dict(attrs).get('rel'))

        Links().feed(html)

    def test_full_name_copy_and_responsive_cards(self):
        name = 'coast-6f4a2a78-91a7-5cdf-a5e0-4844d3ce21bd-data'
        groups = resources.volume_groups([{
            'name': name, 'cinder_volume_id': 'volume-id'}], [])
        html = render_to_string('admin/coast/volumes.html', {
            'volume_groups': groups})
        self.assertIn('title="%s — volume-id"' % name, html)
        self.assertIn('>%s <button' % name, html)
        self.assertIn('data-copy-value="%s"' % name, html)
        self.assertIn('class="btn btn-default btn-xs coast-copy"', html)
        identity_css = re.search(
            r'\.coast-volume-identity \{([^}]+)\}', html).group(1)
        for rule in ('font-family: monospace', 'font-size: 12px',
                     'overflow-wrap: anywhere'):
            self.assertIn(rule, identity_css)
        for rule in ('text-overflow', 'white-space: nowrap',
                     'overflow: hidden'):
            self.assertNotIn(rule, identity_css)
        width = re.search(r'minmax\(min\((\d+)px, 100%\), 1fr\)', html)
        self.assertGreaterEqual(int(width.group(1)), 340)
        self.assertIn('min-width: 0', html)

    def test_statuses_devices_and_escaping(self):
        for raw, expected in [('AVAILABLE', 'Available'),
                              ('ERROR_DELETING', 'Error'),
                              ('CREATING', 'Creating'),
                              ('DELETING', 'Deleting'),
                              ('ATTACHING', 'Attaching'),
                              ('DETACHING', 'Detaching'),
                              ('BACKING_UP', 'Backing Up'),
                              ('', 'Not attached')]:
            groups = resources.volume_groups([{
                'name': '<disk>', 'status': raw,
                'attachments': [{'device': '/dev/vdc'}]}], [])
            row = groups[0]['volumes'][0]
            self.assertEqual(expected, row['badge'])
            self.assertEqual('/dev/vdc', row['device'])
            html = render_to_string('admin/coast/volumes.html', {
                'volume_groups': groups})
            self.assertNotIn('<disk>', html)
        self.assertEqual([], resources.volume_groups([], []))

    def test_servers_and_overview_resource_links_open_new_tabs(self):
        server = dict(SERVER)
        instance = SimpleNamespace(id='nova-id', name='worker',
                                   status='ACTIVE')
        mapped = resources.servers(self.request, STACK, [server], [{
            'server_id': server['id'], 'cinder_volume_id': 'disk'}],
            cloud=([instance], [], [], [], []))
        html = render_to_string('admin/coast/servers.html',
                                {'servers': mapped})
        self.assertEqual(3, html.count('target="_blank" rel="noopener"'))
        fields = resources.overview(dict(STACK, network_id='network'), {})
        html = render_to_string('admin/coast/overview.html',
                                {'fields': fields})
        self.assertIn('target="_blank" rel="noopener"', html)

    def test_uuid_suffix_and_missing_device(self):
        name = 'coast-6f4a2a78-91a7-5cdf-a5e0-4844d3ce21bd-backups'
        groups = resources.volume_groups([{
            'name': name, 'cinder_volume_id': 'disk',
            'status': 'AVAILABLE'}], [])
        row = groups[0]['volumes'][0]
        self.assertIn('>backups</a>', str(row['cloud_link']))
        self.assertIn(name + ' — disk', str(row['cloud_link']))
        html = render_to_string('admin/coast/volumes.html', {
            'volume_groups': groups})
        self.assertNotIn('<dt>Device</dt>', html)
        self.assertIn('<dd>-</dd>', html)
