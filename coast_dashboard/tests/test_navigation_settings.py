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
from unittest import mock

from django.urls import resolve
from django.urls import reverse

from coast_dashboard.api import coast
from coast_dashboard.content import common
from coast_dashboard.content.services import views as service_views
from coast_dashboard.tests import helpers


APP = {'id': 'app-id', 'name': 'web', 'kind': 'app', 'status': 'ACTIVE',
       'stack_id': 'stack-id', 'appgroup_id': 'group-id',
       'environment_id': 'env-id', 'ports': '8080',
       'cpu_limit': 1, 'memory_limit_mb': 512, 'description': 'Original',
       'health_check': 'http', 'health_check_port': None,
       'healthcheck_path': '/health', 'pending_changes': False,
       'source': {'type': 'git', 'branch': 'main',
                  'repo_url': 'https://example.com/repo.git'}}
SERVICE = dict(APP, id='service-id', name='database', kind='service',
               current_deployment_id='deployment-id',
               source={'type': 'template', 'template_id': 'postgres'})
GROUP = {'id': 'group-id', 'name': 'Group', 'status': 'ACTIVE',
         'stack_id': 'stack-id'}
STACK = {'id': 'stack-id', 'name': 'Primary stack', 'status': 'ACTIVE'}
ENV = {'id': 'env-id', 'name': 'Production', 'status': 'ACTIVE',
       'appgroup_id': 'group-id'}


class Links(HTMLParser):
    def __init__(self, response):
        super().__init__()
        self.links = []
        self.current = None
        self.inputs = []
        self.copy_values = []
        self.buttons = []
        self.feed(response.content.decode())

    def handle_starttag(self, tag, attrs):
        if tag == 'button':
            self.buttons.append(dict(attrs))
        if tag == 'button' and 'data-copy-value' in dict(attrs):
            self.copy_values.append(dict(attrs)['data-copy-value'])
        if tag == 'input':
            self.inputs.append(dict(attrs))
        if tag == 'a':
            self.current = [dict(attrs), '']

    def handle_data(self, text):
        if self.current is not None:
            self.current[1] += text

    def handle_endtag(self, tag):
        if tag == 'a' and self.current is not None:
            self.links.append(self.current)
            self.current = None

    def matching(self, text):
        return [attrs for attrs, label in self.links if label.strip() == text]


class NavigationSettingsTests(helpers.TestCase):
    def setUp(self):
        # Explicit base call so test_storage can reuse this setUp.
        helpers.TestCase.setUp(self)
        self.records = {APP['id']: dict(APP), SERVICE['id']: dict(SERVICE)}
        for name, result in [('stack_list', [STACK]), ('stack_get', STACK),
                             ('stack_server_list', []),
                             ('appgroup_get', GROUP), ('environment_get', ENV),
                             ('appgroup_list', [GROUP]),
                             ('environment_list', [ENV]),
                             ('service_env_list', []),
                             ('service_domain_list', []),
                             ('storage_list', []),
                             ('storage_supported', True),
                             ('service_deployment_list', [
                                 {'number': 1, 'status': 'ACTIVE'}])]:
            patcher = mock.patch.object(coast, name, return_value=result)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name, callback in [('service_list', self.list_services),
                               ('service_get', self.get_service),
                               ('service_update', self.update_service)]:
            patcher = mock.patch.object(coast, name, side_effect=callback)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def test_idle_first_deployment_has_banner_and_header_redeploy(self):
        for row in (APP, SERVICE):
            for status in ('ACTIVE', 'STOPPED', 'FAILED', 'ERROR',
                           'CANCELLED', 'PENDING', 'STARTING'):
                with self.subTest(kind=row['kind'], status=status), \
                        mock.patch.object(coast, 'service_deployment_list',
                                          return_value=[]), \
                        mock.patch.object(coast, 'service_deploy') as deploy:
                    self.records[row['id']].update(
                        status=status, pending_changes=True,
                        current_deployment_id=None)
                    response = self.client.get(self.url(
                        'services', 'detail', [row['id']]))
                    self.assertTrue(response.context['can_redeploy'])
                    self.assertIn('Redeploy', response.context['actions'])
                    self.assertContains(response, '<input type="hidden" '
                                        'name="action" value="' +
                                        response.context['deploy_action'])
                    self.assertNotContains(response, 'once the current '
                                           'operation finishes')
                    result = self.client.post(response.context['index_url'], {
                        'action': response.context['deploy_action']})
                    self.assertIn(result.status_code, (200, 302))
                    deploy.assert_called_once_with(mock.ANY, row['id'])

    def test_inflight_deployment_blocks_banner_and_header_redeploy(self):
        for status in ('PENDING', 'BUILDING', 'DEPLOYING'):
            with self.subTest(status=status), mock.patch.object(
                    coast, 'service_deployment_list', return_value=[{
                        'number': 1, 'status': status}]):
                self.records[APP['id']].update(
                    status='PENDING', pending_changes=True)
                response = self.client.get(self.url(
                    'services', 'detail', [APP['id']]))
                self.assertFalse(response.context['can_redeploy'])
                self.assertNotIn('Redeploy', response.context['actions'])
                self.assertContains(response, 'once the current '
                                    'operation finishes')

    def test_only_header_edit_settings_remains(self):
        for row in (APP, SERVICE):
            with self.subTest(kind=row['kind']):
                self.records[row['id']]['pending_changes'] = True
                panel = 'oneclick' if row['kind'] == 'service' else 'services'
                response = self.client.get(self.url(
                    panel, 'detail', [row['id']]))
                links = Links(response).matching('Edit Settings')
                self.assertEqual(1, len(links))
                self.assertEqual(self.url(panel, 'edit_settings',
                                          [row['id']]), links[0]['href'])
                self.assertIn('Edit Settings', response.context['actions'])

    def test_overview_health_check_and_worker_url(self):
        for row in (APP, SERVICE):
            self.records[row['id']].update(
                health_check='none', ports='', default_url=None,
                primary_url=None)
            response = self.client.get(self.url(
                'services', 'detail', [row['id']]))
            self.assertContains(response, 'None (container running is enough)')
            self.assertContains(response, 'No public networking (no port set)')
            self.records[row['id']].update(
                health_check='http', ports='8080', health_check_port=9000,
                healthcheck_path='/ready', default_url='https://app.test',
                primary_url='https://app.test')
            response = self.client.get(self.url(
                'services', 'detail', [row['id']]))
            self.assertContains(response, 'HTTP')
            self.assertContains(response, '9000')
            self.assertContains(response, '/ready')
            self.assertContains(response, 'href="https://app.test"')
            self.assertNotContains(response,
                                   'No public networking (no port set)')

    def test_overview_default_url_without_ports(self):
        for row in (APP, SERVICE):
            for dns_records in ([], [{'type': 'A', 'value': '192.0.2.58',
                                     'purpose': 'routing'}]):
                with self.subTest(kind=row['kind'], dns_records=dns_records):
                    self.records[row['id']].update(
                        ports='', default_url='https://app.test',
                        primary_url='https://app.test',
                        dns_records=dns_records)
                    response = self.client.get(self.url(
                        'services', 'detail', [row['id']]))
                    self.assertContains(response, 'Address')
                    self.assertContains(response, 'href="https://app.test"')
                    self.assertNotContains(
                        response, 'No public networking (no port set)')
                    self.assertNotContains(response, 'Point DNS to')
                    self.assertContains(response, 'Manage domains')

    def test_overview_public_networking_and_null_url(self):
        for row in (APP, SERVICE):
            for ports in (None, '', '8080'):
                for domains in ([], [{'fqdn': 'app.example.com',
                                      'tls': 'letsencrypt'}]):
                    with self.subTest(kind=row['kind'], ports=ports,
                                      domains=domains), mock.patch.object(
                            coast, 'service_domain_list',
                            return_value=domains):
                        self.records[row['id']].update(
                            ports=ports, default_url=None, primary_url=None,
                            dns_records=[{'type': 'A',
                                          'value': '192.0.2.58',
                                          'purpose': 'routing'}])
                        response = self.client.get(self.url(
                            'services', 'detail', [row['id']]))
                        self.assertNotContains(response, 'Default URL')
                        self.assertNotContains(response, 'href="None"')
                        self.assertNotIn('None', Links(response).copy_values)
                        self.assertNotContains(response, 'Point DNS to')
                        self.assertNotContains(response, 'A record -&gt;')
                        self.assertContains(response, 'Manage domains')
                        if domains:
                            self.assertContains(
                                response, 'href="https://app.example.com"')

    def test_tables_accept_null_default_url(self):
        for panel, row in (('services', APP), ('oneclick', SERVICE)):
            for ports in (None, '', '8080'):
                with self.subTest(panel=panel, ports=ports):
                    self.records[row['id']].update(
                        ports=ports, default_url=None)
                    response = self.client.get(self.url(panel))
                    self.assertContains(response, row['name'])
                    self.assertNotContains(response, 'href="None"')
                    self.assertNotIn('None', Links(response).copy_values)

    def test_overview_worker_name_links_to_stack(self):
        for row in (APP, SERVICE):
            with self.subTest(kind=row['kind']), mock.patch.object(
                    coast, 'stack_server_list', return_value=[{
                        'id': 'worker-uuid', 'name': 'Worker One'}]):
                self.records[row['id']].update(
                    server_id='worker-uuid', stack_id=STACK['id'])
                response = self.client.get(self.url(
                    'services', 'detail', [row['id']]))
                links = Links(response).matching('Worker One')
                self.assertEqual(1, len(links))
                self.assertEqual(self.url('stacks', 'detail', [STACK['id']]),
                                 links[0]['href'])
                self.assertNotContains(response, 'worker-uuid')

    def list_services(self, request, kind=None):
        return [dict(row) for row in self.records.values()
                if kind is None or row['kind'] == kind]

    def get_service(self, request, service_id):
        return dict(self.records[service_id])

    def update_service(self, request, service_id, values):
        row = self.records[service_id]
        row.update(values)
        if set(values) - {'name', 'description'}:
            row['pending_changes'] = True
        return dict(row)

    def url(self, panel, view='index', args=None):
        return reverse(helpers.view_name(panel, view),
                       args=args)

    def test_resource_names_link_to_details(self):
        for panel, row, target in [('services', APP, 'services'),
                                   ('oneclick', SERVICE, 'oneclick'),
                                   ('environments', ENV, 'environments'),
                                   ('appgroups', GROUP, 'appgroups')]:
            with self.subTest(panel=panel):
                response = self.client.get(self.url(panel))
                links = Links(response).matching(row['name'])
                expected = self.url(target, 'detail', [row['id']])
                self.assertTrue(links)
                self.assertTrue(all(link['href'] == expected
                                    for link in links))

    def test_edit_action_and_default_detail_button(self):
        for panel, row in [('services', APP), ('oneclick', SERVICE)]:
            with self.subTest(panel=panel):
                edit_url = self.url(panel, 'edit_settings', [row['id']])
                for url in [self.url(panel),
                            self.url(panel, 'detail', [row['id']])]:
                    response = self.client.get(url)
                    links = Links(response).matching('Edit Settings')
                    self.assertTrue(links)
                    self.assertTrue(all(link['href'] == edit_url
                                        for link in links))
                    self.assertTrue(all('ajax-modal' in link['class']
                                        for link in links))
                self.assertIs(service_views.EditSettingsView,
                              resolve(links[0]['href']).func.view_class)
                for ajax in (False, True):
                    headers = ({'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
                               if ajax else {})
                    form_page = self.client.get(edit_url, **headers)
                    self.assertEqual(200, form_page.status_code)
                    self.assertIn('ports', form_page.context['form'].fields)
                    self.assertEqual('coast_settings_form',
                                     form_page.context['form_id'])
                    if ajax:
                        self.assertTemplateUsed(
                            form_page,
                            'project/coast_services/_settings_form.html')

    def test_edit_settings_prefills_worker_health_check(self):
        for mode in ('none', None, 'missing'):
            with self.subTest(mode=mode):
                row = dict(APP, health_check=mode, ports='')
                if mode == 'missing':
                    row.pop('health_check')
                self.records[APP['id']] = row
                response = self.client.get(self.url(
                    'services', 'edit_settings', [row['id']]))
                form = response.context['form']
                self.assertEqual('none', form['health_check'].value())
                self.assertFalse(form.initial['has_domain'])
                self.assertFalse(form.fields['ports'].required)
                data = {key: value for key, value in form.initial.items()
                        if value is not None}
                data['description'] = 'Updated worker'
                response = self.client.post(self.url(
                    'services', 'edit_settings', [row['id']]), data)
                self.assertEqual(302, response.status_code)
                self.assertEqual(
                    mode,
                    self.records[row['id']].get('health_check', 'missing'))
                self.assertEqual('', self.records[row['id']]['ports'])

    def test_edit_settings_prefills_v14_http_path(self):
        self.records[APP['id']] = dict(
            APP, health_check_path='/ready', healthcheck_path='/old')
        response = self.client.get(self.url(
            'services', 'edit_settings', [APP['id']]))
        form = response.context['form']
        self.assertEqual('http', form['health_check'].value())
        self.assertEqual('/ready', form['healthcheck_path'].value())

    def test_prefill_supported_fields(self):
        for row in [APP, SERVICE]:
            response = self.client.get(self.url(
                'services', 'edit_settings', [row['id']]))
            self.assertNotIn('settings_saved', response.context['cancel_url'])
            form = response.context['form']
            for key in ('name', 'ports', 'cpu_limit', 'memory_limit_mb',
                        'healthcheck_path', 'description'):
                self.assertEqual(row[key], form.initial[key])
            self.assertNotIn('replicas', form.fields)
            self.assertEqual(row['source']['type'] == 'git',
                             'branch' in form.fields)
            if row['source']['type'] == 'git':
                self.assertEqual('main', form.initial['branch'])

    def test_save_redirect_banner_and_redeploy_for_both_kinds(self):
        for row, panel, table in [(APP, 'services', 'services'),
                                  (SERVICE, 'oneclick', 'oneclick')]:
            with self.subTest(kind=row['kind']):
                data = {'health_check': 'http', 'name': row['name'] + '-new',
                        'ports': '9000',
                        'cpu_limit': '0.5', 'memory_limit_mb': '1024',
                        'healthcheck_path': '/ready', 'description': 'Changed'}
                expected = dict(data, cpu_limit=0.5, memory_limit_mb=1024)
                if row['kind'] == 'app':
                    data['branch'] = 'release'
                    expected['source'] = {'branch': 'release'}
                response = self.client.post(self.url(
                    'services', 'edit_settings', [row['id']]), data,
                    HTTP_X_REQUESTED_WITH='XMLHttpRequest')
                self.assertEqual(200, response.status_code)
                location = response['X-Horizon-Location']
                self.service_update.assert_called_with(
                    mock.ANY, row['id'], expected)
                self.assertTrue(location.startswith(
                    self.url('services', 'detail', [row['id']])))
                self.assertNotIn('settings_saved', location)
                detail = self.client.get(location)
                self.assertContains(
                    detail, 'Changes saved, redeploy to apply.')
                action = '%s__deploy__%s' % (table, row['id'])
                self.assertContains(detail, action)
                self.assertContains(detail, 'Redeploy')
                with mock.patch.object(coast, 'service_deploy') as deploy:
                    result = self.client.post(self.url(panel),
                                              {'action': action})
                    self.assertIn(result.status_code, (200, 302))
                    deploy.assert_called_once_with(mock.ANY, row['id'])

    def test_metadata_save_has_no_redeploy_banner(self):
        for row in (APP, SERVICE):
            with self.subTest(kind=row['kind']):
                self.records[row['id']]['pending_changes'] = False
                data = {'health_check': 'http',
                        'name': row['name'] + '-renamed',
                        'ports': row['ports'],
                        'cpu_limit': row['cpu_limit'],
                        'memory_limit_mb': row['memory_limit_mb'],
                        'healthcheck_path': row['healthcheck_path'],
                        'description': row['description']}
                if row['source']['type'] == 'git':
                    data['branch'] = row['source']['branch']
                response = self.client.post(self.url(
                    'services', 'edit_settings', [row['id']]), data)
                self.assertEqual(302, response.status_code)
                self.assertNotIn('settings_saved', response.url)
                detail = self.client.get(response.url)
                self.assertContains(detail, 'Changes saved.')
                self.assertNotContains(
                    detail, 'Changes saved, redeploy to apply.')
                self.service_update.assert_called_with(
                    mock.ANY, row['id'],
                    {'name': data['name']})

    def test_redeploy_opens_the_new_deployment(self):
        for row, panel, table in [(APP, 'services', 'services'),
                                  (SERVICE, 'oneclick', 'oneclick')]:
            with self.subTest(kind=row['kind']), mock.patch.object(
                    coast, 'service_deploy',
                    return_value={'id': 'dep-9'}) as deploy:
                self.records[row['id']].update(
                    status='ACTIVE', pending_changes=True)
                detail = self.client.get(self.url(
                    'services', 'detail', [row['id']]))
                action = '%s__deploy__%s' % (table, row['id'])
                for target in (detail.context['index_url'],
                               detail.context['url']):
                    deploy.reset_mock()
                    result = self.client.post(target, {'action': action})
                    if row['kind'] == 'service':
                        # Template services have no build log.
                        expected = self.url(
                            'oneclick', 'detail', [row['id']]) + (
                                '?tab=service_details__logs')
                    else:
                        expected = self.url('services', 'deployment',
                                            [row['id'], 'dep-9'])
                    self.assertRedirects(result, expected,
                                         fetch_redirect_response=False)
                    deploy.assert_called_once_with(mock.ANY, row['id'])

    def test_overview_shows_worker_address_dns_and_links(self):
        for row in (APP, SERVICE):
            with self.subTest(kind=row['kind']), mock.patch.object(
                    coast, 'stack_server_list', return_value=[{
                        'id': 'worker-2', 'name': 'worker-2',
                        'floating_ip': '192.0.2.58'}]), \
                    mock.patch.object(coast, 'service_domain_list',
                                      return_value=[{
                                          'id': 'dom',
                                          'fqdn': 'app.example.com',
                                          'tls': 'letsencrypt',
                                          'status': 'ACTIVE'}]):
                self.records[row['id']].update(
                    server_id='worker-2', stack_id=STACK['id'],
                    default_url='https://web.apps.example.com',
                    primary_url='https://web.apps.example.com',
                    dns_records=[])
                response = self.client.get(self.url(
                    'services', 'detail', [row['id']]))
                self.assertContains(response, '>worker-2<')
                self.assertNotContains(response, 'worker-2 (192.0.2.58)')
                self.assertNotContains(response, 'A record -&gt; 192.0.2.58')
                for value in ('https://web.apps.example.com',
                              'https://app.example.com'):
                    self.assertIn(value, Links(response).copy_values)
                self.assertContains(
                    response,
                    'href="https://web.apps.example.com" target="_blank"')
                self.assertContains(
                    response,
                    'href="https://app.example.com" target="_blank"')

    def test_overview_uses_dns_a_record_without_floating_ip(self):
        with mock.patch.object(coast, 'stack_server_list', return_value=[{
                'id': 'worker-2', 'name': 'worker-2', 'floating_ip': None}]), \
                mock.patch.object(coast, 'stack_server_get', return_value={
                    'id': 'worker-2', 'name': 'worker-2',
                    'floating_ip': None}):
            self.records[APP['id']].update(
                server_id='worker-2', stack_id=STACK['id'],
                dns_records=[{'type': 'A', 'value': '192.0.2.58',
                              'purpose': 'routing'}])
            response = self.client.get(self.url(
                'services', 'detail', [APP['id']]))
        self.assertContains(response, '>worker-2<')
        self.assertNotContains(response, 'worker-2 (192.0.2.58)')
        self.assertNotContains(response, 'A record -&gt; 192.0.2.58')

    def test_clear_limits_and_skip_unchanged_fields(self):
        data = {'name': APP['name'], 'ports': APP['ports'],
                'health_check': 'http',
                'healthcheck_path': APP['healthcheck_path'],
                'description': APP['description'], 'branch': 'main'}
        url = self.url('services', 'edit_settings', [APP['id']])
        result = self.client.post(url, data)
        self.assertEqual(302, result.status_code)
        self.service_update.assert_called_once_with(
            mock.ANY, APP['id'],
            {'cpu_limit': None, 'memory_limit_mb': None})
        self.service_update.reset_mock()
        result = self.client.post(url, data)
        self.assertEqual(302, result.status_code)
        self.service_update.assert_not_called()

    def test_invalid_limits_and_name_do_not_write(self):
        for key, value in [('cpu_limit', '0'), ('cpu_limit', '-1'),
                           ('memory_limit_mb', '0'),
                           ('memory_limit_mb', '1.5'), ('name', 'Bad Name')]:
            with self.subTest(key=key, value=value):
                data = {'name': APP['name'], 'ports': '8080', 'branch': 'main',
                        key: value}
                response = self.client.post(self.url(
                    'services', 'edit_settings', [APP['id']]), data)
                self.assertEqual(200, response.status_code)
                self.assertIn(key, response.context['form'].errors)
        self.service_update.assert_not_called()

    def test_update_error_keeps_form(self):
        self.service_update.side_effect = coast.CoastError('Service is busy')
        response = self.client.post(self.url(
            'services', 'edit_settings', [APP['id']]),
            {'name': 'renamed', 'ports': '8080', 'branch': 'main',
             'health_check': 'http'})
        self.assertEqual(200, response.status_code)
        self.assertContains(response, 'Service is busy')

    def test_list_columns_use_parent_names_and_hide_ids(self):
        for panel in ('stacks', 'appgroups', 'environments', 'services',
                      'oneclick'):
            with self.subTest(panel=panel):
                response = self.client.get(self.url(panel))
                tables = (response.context['oneclick_table'],
                          response.context['templates_table']) if (
                              panel == 'oneclick') else (
                                  response.context['table'],)
                for table in tables:
                    self.assertFalse(set(table.columns) & {
                        'id', 'stack_id', 'appgroup_id', 'environment_id',
                        'project_id', 'server_id'})
                self.assertFalse(any(field.get('id') == 'resource-id'
                                     for field in Links(response).inputs))
        groups = self.client.get(self.url('appgroups')).context['table'].data
        self.assertEqual('Primary stack', groups[0]['stack_name'])
        envs = self.client.get(self.url('environments')).context['table'].data
        self.assertIn('>Group</a>', envs[0]['appgroup_name'])

    def test_app_and_service_lists_show_linked_stack(self):
        link = reverse('horizon:project:coast.stacks:detail',
                       kwargs={'stack_id': STACK['id']})
        apps = self.client.get(self.url('services')).context['table']
        self.assertIn('stack_name', apps.columns)
        self.assertIn(link, apps.data[0]['stack_name'])
        self.assertIn('>Primary stack</a>', apps.data[0]['stack_name'])
        services = self.client.get(
            self.url('oneclick')).context['oneclick_table']
        self.assertIn('stack_name', services.columns)
        self.assertIn(link, services.data[0]['stack_name'])

    def test_service_detail_shows_linked_stack(self):
        response = self.client.get(reverse(
            'horizon:project:coast.apps:detail', args=[APP['id']]))
        self.assertContains(response, '<dt>Stack</dt>', html=False)
        self.assertContains(response, reverse(
            'horizon:project:coast.stacks:detail',
            kwargs={'stack_id': STACK['id']}))

    def test_each_detail_has_plain_id_and_copy_button(self):
        for panel, row in [('stacks', STACK), ('appgroups', GROUP),
                           ('environments', ENV), ('services', APP),
                           ('services', SERVICE)]:
            with self.subTest(panel=panel, resource=row['id']):
                response = self.client.get(
                    self.url(panel, 'detail', [row['id']]))
                fields = [field for field in Links(response).inputs
                          if field.get('id') == 'resource-id']
                self.assertEqual([], fields)
                self.assertIn(row['id'], Links(response).copy_values)
                self.assertContains(response, 'fa fa-copy')

    def test_id_is_the_first_overview_row(self):
        for panel, row in [('stacks', STACK), ('appgroups', GROUP),
                           ('environments', ENV), ('services', APP)]:
            with self.subTest(panel=panel):
                response = self.client.get(
                    self.url(panel, 'detail', [row['id']]))
                html = response.content.decode()
                self.assertIn('header_rule', html)
                self.assertLess(html.find('nav-tabs'),
                                html.find('resource-id'))
                self.assertLess(html.find('<h4>Overview</h4>'),
                                html.find('resource-id'))

    def test_parent_names_survive_ajax_updates(self):
        for panel, row, parent in [('appgroups', GROUP, 'Primary stack'),
                                   ('environments', ENV, 'Group')]:
            with self.subTest(panel=panel):
                response = self.client.get(self.url(panel), {
                    'table': panel, 'action': 'row_update',
                    'obj_id': row['id']},
                    HTTP_X_REQUESTED_WITH='XMLHttpRequest')
                self.assertEqual(200, response.status_code)
                self.assertContains(response, parent)

    @mock.patch.object(coast, 'stack_list',
                       side_effect=coast.CoastError('Unavailable'))
    def test_missing_parent_names_keep_rows(self, stacks):
        response = self.client.get(self.url('appgroups'))
        row = response.context['table'].data[0]
        self.assertEqual('Unavailable', row['stack_name'])
        self.assertContains(response, 'Group')
        self.assertNotEqual(GROUP['stack_id'], row['stack_name'])

    def test_environment_badges_across_lists_and_links(self):
        for state, label in [('PENDING', 'Creating'), ('ACTIVE', None)]:
            with self.subTest(state=state), mock.patch.object(
                    coast, 'environment_list',
                    return_value=[dict(ENV, status=state)]):
                urls = [self.url('environments'), self.url('appgroups'),
                        self.url('appgroups', 'detail', [GROUP['id']]),
                        self.url('services'), self.url('oneclick')]
                for url in urls:
                    response = self.client.get(url)
                    if label:
                        self.assertContains(response, label)
                    else:
                        self.assertNotContains(response, '>Creating</span>')
                        self.assertNotContains(
                            response, 'Production</a> <span')
                response = self.client.get(self.url('environments'))
                self.assertNotIn('status', response.context['table'].columns)
                response = self.client.get(self.url(
                    'appgroups', 'detail', [GROUP['id']]))
                tab = response.context['tab_group'].get_tab('environments')
                self.assertNotIn('status', tab._tables['environments'].columns)

    def test_appgroup_badges_across_lists_and_references(self):
        for state, label in [('PENDING', 'Creating'), ('ACTIVE', None)]:
            with self.subTest(state=state), mock.patch.object(
                    coast, 'appgroup_list',
                    return_value=[dict(GROUP, status=state)]):
                urls = [self.url('appgroups'), self.url('environments'),
                        self.url('services'), self.url('oneclick'),
                        self.url('environments', 'detail', [ENV['id']]),
                        self.url('services', 'detail', [APP['id']]),
                        self.url('services', 'detail', [SERVICE['id']])]
                for url in urls:
                    response = self.client.get(url)
                    if label:
                        self.assertContains(response, label)
                    else:
                        self.assertNotContains(response, 'Group</a> <span')
                response = self.client.get(self.url('appgroups'))
                self.assertNotIn('status', response.context['table'].columns)

    def test_native_detail_tabs_titles_and_no_primary_list(self):
        cases = [
            ('stacks', STACK, ['Overview', 'Topology', 'Servers',
                               'App Groups', 'Activity']),
            ('appgroups', GROUP, ['Overview', 'Environments',
                                  'Apps', 'Databases', 'Services']),
            ('environments', ENV, ['Overview', 'Apps & Services',
                                   'Databases']),
            ('services', APP, ['Overview', 'Deployments', 'Logs', 'Console',
                               'Domains', 'Storage', 'Files',
                               'Env vars', 'Webhooks']),
            # Services have no deploy/Git webhooks (apps only).
            ('oneclick', SERVICE, ['Overview', 'Deployments', 'Logs',
                                   'Console', 'Domains', 'Storage', 'Files',
                                   'Env vars', 'Compose', 'Containers'])]
        for panel, row, expected in cases:
            with self.subTest(panel=panel, resource=row['id']):
                response = self.client.get(
                    self.url(panel, 'detail', [row['id']]))
                self.assertEqual(row['name'], response.context['page_title'])
                names = [str(tab.name) for tab in
                         response.context['tab_group'].get_tabs()]
                self.assertEqual(expected, names)
                self.assertTrue(response.context['actions'])
                if panel in ('services', 'oneclick'):
                    self.assertNotContains(response, 'Create App')
                    self.assertNotContains(response, 'Delete Apps')
                    self.assertNotContains(response, 'Create Service')
                    self.assertNotIn('services',
                                     response.context['view']._table_dict)
                    actions = str(response.context['actions'])
                    self.assertIn('edit_settings', actions)
                    self.assertIn('__deploy__' + row['id'], actions)
                    self.assertIn('__stop__' + row['id'], actions)
                    self.assertIn('__restart__' + row['id'], actions)
                    self.assertIn('__delete__' + row['id'], actions)
                    self.assertNotIn('__start__' + row['id'], actions)

    @mock.patch.object(coast, 'service_action')
    def test_lifecycle_actions_post_from_header_target(self, action):
        for row, panel, table in [(APP, 'services', 'services'),
                                  (SERVICE, 'oneclick', 'oneclick')]:
            for operation, state in [('start', 'STOPPED'), ('stop', 'ACTIVE'),
                                     ('restart', 'ACTIVE')]:
                with self.subTest(kind=row['kind'], operation=operation):
                    self.records[row['id']]['status'] = state
                    action.reset_mock()
                    detail = self.client.get(self.url(
                        'services', 'detail', [row['id']]))
                    self.assertEqual(self.url(panel), detail.context['url'])
                    value = '%s__%s__%s' % (table, operation, row['id'])
                    self.assertIn(value, str(detail.context['actions']))
                    result = self.client.post(detail.context['url'],
                                              {'action': value})
                    self.assertIn(result.status_code, (200, 302))
                    action.assert_called_once_with(
                        mock.ANY, row['id'], operation)

    @mock.patch.object(coast, 'service_action')
    def test_busy_lifecycle_action_is_rejected(self, action):
        self.records[APP['id']]['task_state'] = 'RECONCILING'
        detail = self.client.get(self.url('services', 'detail', [APP['id']]))
        self.assertNotIn('__restart__', str(detail.context['actions']))
        self.client.post(detail.context['url'],
                         {'action': 'services__restart__' + APP['id']})
        action.assert_not_called()

    def test_stack_server_ip_copy_button(self):
        with mock.patch.object(coast, 'stack_server_list', return_value=[{
                'id': 'worker', 'name': 'worker', 'role': 'worker',
                'kind': 'vm', 'status': 'ACTIVE',
                'floating_ip': '192.0.2.15'}]):
            response = self.client.get(self.url(
                'stacks', 'detail', [STACK['id']]))
        self.assertIn('192.0.2.15', Links(response).copy_values)

    def test_redeploy_is_primary_beside_edit_and_action_parity(self):
        for row in (APP, SERVICE):
            for state in ('ACTIVE', 'STOPPED', 'RECONCILING', 'DELETING'):
                with self.subTest(kind=row['kind'], state=state):
                    self.records[row['id']]['status'] = state
                    response = self.client.get(self.url(
                        'services', 'detail', [row['id']]))
                    item = response.context['item']
                    table = response.context['view'].get_action_table(item)
                    expected = table.get_row_actions(item)
                    actions = str(response.context['actions'])
                    for action in expected:
                        if action.name == 'edit_settings':
                            self.assertIn('Edit Settings', actions)
                        else:
                            self.assertIn('%s__%s__%s' % (
                                table.name, action.name, row['id']), actions)
                    for action_class in table._meta.row_actions:
                        if action_class.name not in {
                                action.name for action in expected}:
                            self.assertNotIn('%s__%s__%s' % (
                                table.name, action_class.name, row['id']),
                                actions)
                    buttons = Links(response).buttons
                    primary = [button for button in buttons if
                               'btn-primary' in button.get('class', '').split()
                               and button.get('name') == 'action']
                    if common.can_redeploy(item):
                        self.assertEqual(1, len(primary))
                        self.assertEqual('%s__deploy__%s' % (
                            table.name, row['id']), primary[0]['value'])
                        self.assertLess(actions.index('Redeploy'),
                                        actions.index('Edit Settings'))
                        self.assertLess(actions.index('Edit Settings'),
                                        actions.index('dropdown-toggle'))
                    else:
                        self.assertEqual([], primary)

    def test_header_cancel_only_for_running_latest_deployment(self):
        for row in (APP, SERVICE):
            for status in ('PENDING', 'BUILDING', 'DEPLOYING', 'ACTIVE',
                           'FAILED', 'CANCELLED'):
                with self.subTest(kind=row['kind'], status=status), \
                        mock.patch.object(coast, 'service_deployment_list',
                                          return_value=[{
                                              'id': 'dep', 'number': 2,
                                              'status': status}]):
                    response = self.client.get(self.url(
                        'services', 'detail', [row['id']]))
                    actions = str(response.context['actions'])
                    if status in ('PENDING', 'BUILDING', 'DEPLOYING'):
                        self.assertIn('deployments__cancel__dep', actions)
                        self.assertNotIn('__deploy__', actions)
                        button = next(button for button in
                                      Links(response).buttons if
                                      button.get('value') ==
                                      'deployments__cancel__dep')
                        with mock.patch.object(
                                coast, 'service_deployment_cancel') as cancel:
                            result = self.client.post(button['formaction'], {
                                'action': button['value']})
                        self.assertEqual(200, result.status_code)
                        cancel.assert_called_once_with(
                            mock.ANY, row['id'], 'dep')
                    else:
                        self.assertNotIn('deployments__cancel__dep', actions)

    def test_detail_delete_returns_to_own_list(self):
        for row, panel in ((APP, 'services'), (SERVICE, 'oneclick')):
            with mock.patch.object(coast, 'service_delete') as delete:
                response = self.client.get(self.url(
                    'services', 'detail', [row['id']]))
                result = self.client.post(response.context['url'], {
                    'action': '%s__delete__%s' % (panel, row['id'])})
            self.assertRedirects(result, self.url(panel),
                                 fetch_redirect_response=False)
            delete.assert_called_once_with(mock.ANY, row['id'])
