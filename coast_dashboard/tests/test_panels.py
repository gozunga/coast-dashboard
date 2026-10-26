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

import re
from unittest import mock

from django.contrib.messages import get_messages
from django.urls import reverse

from openstack_dashboard.api import nova

from coast_dashboard.api import coast
from coast_dashboard.content import common
from coast_dashboard.content.oneclick import tables as oneclick_tables
from coast_dashboard.content.services import tables as service_tables
from coast_dashboard.content.stacks import tables as stack_tables
from coast_dashboard.tests import helpers
from coast_dashboard.tests.test_forms import APPGROUPS
from coast_dashboard.tests.test_forms import ENVIRONMENTS
from coast_dashboard.tests.test_forms import FLAVORS
from coast_dashboard.tests.test_forms import SERVERS
from coast_dashboard.tests.test_forms import SERVICE_DATA
from coast_dashboard.tests.test_forms import STACK_DATA


SERVICE = dict(SERVICE_DATA, id='svc', status='ACTIVE', stack_id='s1')


class PanelTests(helpers.TestCase):
    def url(self, panel, view='index', args=None):
        return reverse(helpers.view_name(panel, view),
                       args=args)

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(nova, 'flavor_list', return_value=FLAVORS)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(coast, 'plan_list', return_value=[
            {'name': 'all', 'kind': 'vm',
             'roles': ['control', 'worker', 'build'],
             'flavor': flavor.name} for flavor in FLAVORS])
        patcher.start()
        self.addCleanup(patcher.stop)
        for name, result in [('appgroup_list', APPGROUPS),
                             ('environment_list', ENVIRONMENTS),
                             ('stack_server_list', SERVERS),
                             ('service_list', [SERVICE]),
                             ('service_get', SERVICE),
                             ('service_deployment_list', [])]:
            patcher = mock.patch.object(coast, name, return_value=result)
            patcher.start()
            self.addCleanup(patcher.stop)

    @mock.patch.object(coast, 'stack_list', return_value=[])
    def test_oneclick_services_panel_lists_kind_service(self, stacks):
        with mock.patch.object(coast, 'service_list', return_value=[
                dict(SERVICE, name='pg', template_id='postgresql')]) as lst:
            result = self.client.get(self.url('oneclick'))
        self.assertEqual(200, result.status_code)
        self.assertContains(result, 'postgresql')
        lst.assert_called_with(mock.ANY, kind='service')

    def test_new_indexes(self):
        for panel, text in [('environments', 'Production'),
                            ('services', 'web')]:
            result = self.client.get(self.url(panel))
            self.assertEqual(200, result.status_code)
            self.assertContains(result, text)

    @mock.patch.object(coast, 'environment_get', return_value=ENVIRONMENTS[0])
    def test_environment_detail(self, get):
        result = self.client.get(self.url('environments', 'detail', ['e1']))
        self.assertContains(result, 'Production')
        self.assertContains(result, self.url('appgroups', 'detail', ['a1']))

    def test_service_overview(self):
        result = self.client.get(self.url('services', 'detail', ['svc']))
        self.assertEqual(200, result.status_code)
        self.assertContains(result, 'ACTIVE')
        self.assertContains(result, 'Deployments')

    @mock.patch.object(coast, 'service_deployment_list', return_value=[
        {'id': 'd', 'number': 1, 'status': 'BUILDING'}])
    def test_service_list_uses_deployment_status(self, deployments):
        result = self.client.get(self.url('services'))
        self.assertContains(result, 'BUILDING')

    @mock.patch.object(coast, 'service_env_list', return_value=[])
    @mock.patch.object(coast, 'service_domain_list', return_value=[
        {'id': 'dom', 'fqdn': 'web.example.com', 'status': 'PENDING_DNS'}])
    def test_domains_tab(self, domains, env):
        result = self.client.get(self.url('services', 'detail', ['svc']),
                                 {'tab': 'service_details__domains'})
        self.assertContains(result, 'web.example.com')
        self.assertContains(result, 'PENDING_DNS')

    @mock.patch.object(coast, 'service_deployment_list', return_value=[
        {'id': 'd', 'number': 1, 'status': 'BUILDING', 'source_ref': 'main'}])
    def test_deployments_tab(self, deployments):
        result = self.client.get(self.url('services', 'detail', ['svc']),
                                 {'tab': 'service_details__deployments'})
        self.assertContains(result, 'BUILDING')
        self.assertContains(result, 'main')

    @mock.patch.object(coast, 'service_deployment_list', return_value=[
        {'id': 'middle', 'number': 99, 'status': 'ACTIVE',
         'source_ref': 'middle-ref', 'created_at': '2026-10-16T12:00:00Z'},
        {'id': 'oldest', 'number': 100, 'status': 'ACTIVE',
         'source_ref': 'oldest-ref', 'created_at': '2026-10-15T12:00:00Z'},
        {'id': 'newest', 'number': 1, 'status': 'ACTIVE',
         'source_ref': 'newest-ref', 'created_at': '2026-10-17T12:00:00Z'},
        {'id': 'missing', 'number': 2, 'status': 'ACTIVE',
         'source_ref': 'missing-ref', 'created_at': None}])
    def test_deployments_tab_newest_first(self, deployments):
        result = self.client.get(self.url('services', 'detail', ['svc']),
                                 {'tab': 'service_details__deployments'})
        self.assertEqual(200, result.status_code)
        content = result.content.decode()
        positions = [content.index(ref) for ref in (
            'newest-ref', 'middle-ref', 'oldest-ref', 'missing-ref')]
        self.assertEqual(sorted(positions), positions)

    @mock.patch.object(coast, 'coastclient')
    def test_env_tab_masks_api_secret(self, client):
        response = mock.Mock(content=b'x')
        response.json.return_value = {'env': {
            'PASSWORD': {'secret': True, 'value': 'never-show-this'},
            'MODE': {'secret': False, 'value': 'production'}}}
        client.return_value.request.return_value = response
        result = self.client.get(self.url('services', 'detail', ['svc']),
                                 {'tab': 'service_details__settings'})
        self.assertContains(result, '********')
        self.assertContains(result, 'production')
        self.assertNotContains(result, 'never-show-this')

    @mock.patch.object(coast, 'service_logs', return_value={'lines': [
        {'ts': 'now', 'stream': 'stdout', 'line': 'listening on 80'}]})
    def test_logs_tab_inline(self, logs):
        result = self.client.get(self.url('services', 'detail', ['svc']),
                                 {'tab': 'service_details__logs'})
        self.assertContains(result, 'listening on 80')
        self.assertContains(result, 'coast-log-refresh')
        self.assertContains(result, 'data-copy-target=".coast-logs '
                            '.coast-log-box"')
        self.assertContains(result, 'logs/fragment/')
        logs.assert_called_with(mock.ANY, 'svc', tail=200)
        with mock.patch.object(coast, 'service_get',
                               return_value=dict(SERVICE, kind='service')):
            result = self.client.get(
                self.url('services', 'detail', ['svc']),
                {'tab': 'service_details__logs'},
                HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertContains(result, 'data-copy-target=".coast-logs '
                            '.coast-log-box"')

    @mock.patch.object(coast, 'service_logs', side_effect=coast.CoastError(
        'Service Unavailable'))
    def test_logs_fragment_error(self, logs):
        result = self.client.get(
            self.url('services', 'logs', ['svc']) + 'fragment/')
        self.assertContains(result, 'Service Unavailable')
        self.assertContains(result, 'coast-log-error')

    @mock.patch.object(coast, 'service_logs', return_value={'lines': []})
    def test_logs_fragment_empty(self, logs):
        result = self.client.get(
            self.url('services', 'logs', ['svc']) + 'fragment/')
        self.assertContains(result, 'No log lines yet')

    @mock.patch.object(coast, 'service_deployment_log', return_value={
        'lines': [{'ts': 't', 'stream': 'build', 'line': 'Step 1/3'}]})
    @mock.patch.object(coast, 'service_deployment_get', return_value={
        'id': 'd1', 'number': 4, 'status': 'FAILED',
        'fault': 'Image pull failed'})
    def test_deployment_detail(self, get, log):
        result = self.client.get(self.url(
            'services', 'deployment', ['svc', 'd1']))
        self.assertContains(result, 'FAILED')
        self.assertContains(result, 'Image pull failed')
        self.assertContains(result, 'Step 1/3')
        self.assertContains(result, 'header_rule')
        self.assertContains(result, 'd1')
        self.assertContains(result, 'data-copy-value="d1"')
        self.assertContains(result, 'data-copy-target=".coast-deploy-log '
                            '.coast-log-box"')
        self.assertNotContains(result, '<input id="resource-id"')
        log.assert_called_once_with(mock.ANY, 'svc', 'd1')

    @mock.patch.object(coast, 'service_deployment_log',
                       return_value={'lines': []})
    @mock.patch.object(coast, '_raw_request')
    def test_deployment_detail_hides_engine_names(self, raw, log):
        # The API skips its own scrub for admins; the dashboard does not.
        response = mock.Mock(content=b'x')
        response.json.return_value = {'deployment': {
            'id': 'd1', 'number': 4, 'status': 'FAILED',
            'fault': 'Cool' + 'ify API returned 500 from Traef' + 'ik'}}
        raw.return_value = response
        result = self.client.get(self.url(
            'services', 'deployment', ['svc', 'd1']))
        self.assertContains(result, 'App engine server API returned 500')
        self.assertNotContains(result, 'cool' + 'ify')
        self.assertNotContains(result, 'Cool' + 'ify')
        self.assertNotContains(result, 'Traef' + 'ik')

    @mock.patch.object(coast, 'service_deployment_log',
                       return_value={'lines': []})
    @mock.patch.object(coast, 'service_deployment_get')
    def test_deployment_cancel_button_only_while_running(self, get, log):
        cancel_url = self.url('services', 'deployment_cancel', ['svc', 'd1'])
        for state in ('PENDING', 'BUILDING', 'DEPLOYING', 'ACTIVE', 'FAILED',
                      'CANCELLED', 'SUPERSEDED', 'ROLLED_BACK'):
            with self.subTest(state=state):
                get.return_value = {'id': 'd1', 'number': 1, 'status': state}
                response = self.client.get(self.url(
                    'services', 'deployment', ['svc', 'd1']))
                if state in ('PENDING', 'BUILDING', 'DEPLOYING'):
                    self.assertContains(response, 'action="%s"' % cancel_url)
                    self.assertContains(response, 'btn btn-danger btn-sm')
                    self.assertContains(response, 'name="csrfmiddlewaretoken"')
                    self.assertContains(response, 'return confirm(')
                else:
                    self.assertNotContains(response, cancel_url)
                    self.assertNotContains(response, 'Cancel Deployment')

    @mock.patch.object(coast, 'service_deployment_log')
    @mock.patch.object(coast, 'service_deployment_get', return_value={
        'id': 'd1', 'number': 4, 'status': 'ACTIVE'})
    def test_template_deployment_empty_and_failed_logs(self, get, log):
        for service in (dict(SERVICE, template_id='postgresql'),
                        dict(SERVICE, source={'type': 'template'})):
            for failed in (False, True):
                for view in ('deployment', 'deployment_log_fragment',
                             'deployment_log'):
                    with self.subTest(service=service, failed=failed,
                                      view=view), mock.patch.object(
                            coast, 'service_get', return_value=service):
                        log.return_value = {'lines': [], 'complete': True}
                        log.side_effect = (
                            coast.CoastError() if failed else None)
                        response = self.client.get(self.url(
                            'services', view, ['svc', 'd1']))
                        if view == 'deployment':
                            # The page shows status, not a build log box.
                            self.assertContains(response, 'Status and events')
                            self.assertNotContains(
                                response, 'Template services have no build')
                        else:
                            self.assertContains(
                                response,
                                'Template services have no build log')
                        self.assertNotContains(
                            response, 'Unable to retrieve the build log')
                        self.assertNotContains(response, 'coast-log-error')
                        if (not failed and
                                view == 'deployment_log_fragment'):
                            self.assertContains(response, 'data-complete="1"')
                            self.assertNotContains(
                                response, 'Updating every 3 seconds')

    @mock.patch.object(coast, 'service_deployment_log',
                       side_effect=coast.CoastError())
    @mock.patch.object(coast, 'service_deployment_get', return_value={
        'id': 'd1', 'number': 4, 'status': 'ACTIVE'})
    def test_app_deployment_log_errors_remain_visible(self, get, log):
        for view in ('deployment', 'deployment_log_fragment',
                     'deployment_log'):
            with self.subTest(view=view):
                response = self.client.get(self.url(
                    'services', view, ['svc', 'd1']))
                self.assertContains(
                    response, 'Unable to retrieve the build log')
                self.assertContains(response, 'coast-log-error')
                self.assertNotContains(
                    response, 'Template services have no build log')

    @mock.patch.object(coast, 'service_deployment_log', return_value={
        'lines': [{'line': 'Deployment output'}], 'complete': True})
    @mock.patch.object(coast, 'service_deployment_get', return_value={
        'id': 'd1', 'number': 4, 'status': 'ACTIVE'})
    def test_deployment_navigation_by_service_source(self, get, log):
        for extra, label, panel in (
                ({'template_id': 'postgresql'}, 'Services', 'oneclick'),
                ({'source': {'type': 'template'}}, 'Services', 'oneclick'),
                ({'source': {'type': 'git'}}, 'Apps', 'services')):
            with self.subTest(extra=extra), mock.patch.object(
                    coast, 'service_get', return_value=dict(SERVICE, **extra)):
                response = self.client.get(self.url(
                    'services', 'deployment', ['svc', 'd1']))
                breadcrumb = response.content.decode().split(
                    '<ol class="breadcrumb">', 1)[1].split('</ol>', 1)[0]
                self.assertIn('href="%s"' % self.url(panel), breadcrumb)
                self.assertIn('>%s</a>' % label, breadcrumb)
                self.assertNotIn('>Apps</a>' if label == 'Services' else
                                 '>Services</a>', breadcrumb)
                self.assertContains(response, 'href="%s?tab=%s"' % (
                    self.url('services', 'detail', ['svc']),
                    'service_details__deployments'))
                if label == 'Services':
                    self.assertContains(response, 'Status and events')
                    self.assertContains(response, 'service_details__logs')
                    self.assertNotContains(
                        response, 'class="coast-deploy-log"')
                else:
                    self.assertContains(response, 'Deployment output')
                self.assertNotContains(
                    response, 'Template services have no build log')

    @mock.patch.object(coast, 'service_deployment_cancel')
    def test_deployment_cancel_post(self, cancel):
        response = self.client.post(self.url(
            'services', 'deployment_cancel', ['svc', 'd1']))
        cancel.assert_called_once_with(mock.ANY, 'svc', 'd1')
        self.assertRedirects(response, self.url(
            'services', 'deployment', ['svc', 'd1']),
            fetch_redirect_response=False)
        messages = [str(message) for message in
                    get_messages(response.wsgi_request)]
        self.assertIn('Cancellation requested.', messages)

    @mock.patch.object(coast, 'service_domain_list', return_value=[])
    @mock.patch.object(coast, 'service_env_list', return_value=[])
    @mock.patch.object(coast, 'service_webhooks', return_value={})
    @mock.patch.object(coast, 'service_logs', return_value={'lines': []})
    @mock.patch.object(coast, 'service_deployment_log',
                       return_value={'lines': [], 'complete': True})
    @mock.patch.object(coast, 'service_deployment_get', return_value={
        'id': 'd1', 'number': 4, 'status': 'ACTIVE'})
    def test_template_breadcrumbs_on_detail_tabs_and_log_pages(self, *mocks):
        detail = self.url('services', 'detail', ['svc'])
        urls = [detail + '?tab=service_details__' + tab for tab in (
            'overview', 'deployments', 'logs', 'console', 'settings',
            'domains', 'webhooks')]
        urls.extend([self.url('services', 'logs', ['svc']),
                     self.url('services', 'deployment', ['svc', 'd1']),
                     self.url('services', 'deployment_log', ['svc', 'd1'])])
        for extra, label, panel in (
                ({'template_id': 'uptime-kuma'}, 'Services', 'oneclick'),
                ({'source': {'type': 'template',
                             'template_id': 'uptime-kuma'}},
                 'Services', 'oneclick'),
                ({'source': {'type': 'git'}}, 'Apps', 'services')):
            with mock.patch.object(coast, 'service_get',
                                   return_value=dict(SERVICE, **extra)):
                for url in urls:
                    with self.subTest(extra=extra, url=url):
                        response = self.client.get(url)
                        self.assertEqual(200, response.status_code)
                        breadcrumb = response.content.decode().split(
                            '<ol class="breadcrumb">', 1)[1].split(
                                '</ol>', 1)[0]
                        self.assertIn('href="%s"' % self.url(panel),
                                      breadcrumb)
                        self.assertIn('>%s</a>' % label, breadcrumb)
                        other = 'Apps' if label == 'Services' else 'Services'
                        self.assertNotIn('>%s</a>' % other, breadcrumb)
                        crumbs = [re.sub(r'<[^>]+>', '', item).strip()
                                  for item in breadcrumb.split('</li>')
                                  if item.strip()]
                        self.assertEqual(['Project', 'App Hosting', label],
                                         crumbs[:3])

    @mock.patch.object(coast, 'service_domain_list', return_value=[])
    def test_template_overview_source_name_and_id(self, domains):
        for extra, label in (
                ({'template_id': 'uptime-kuma'}, 'uptime-kuma'),
                ({'template_id': 'uptime-kuma',
                  'template_name': 'Uptime Kuma'}, 'Uptime Kuma'),
                ({'source': {'type': 'template',
                             'template_id': 'uptime-kuma',
                             'repo_url': None, 'branch': 'main'}},
                 'uptime-kuma'),
                ({'source': {'type': 'template',
                             'template_id': 'uptime-kuma',
                             'template_name': 'Uptime Kuma'}}, 'Uptime Kuma')):
            with self.subTest(extra=extra), mock.patch.object(
                    coast, 'service_get', return_value=dict(SERVICE, **extra)):
                response = self.client.get(self.url(
                    'services', 'detail', ['svc']))
                self.assertContains(response, '<dt>Source</dt><dd>Template: '
                                    '%s</dd>' % label, html=True)

    @mock.patch.object(coast, 'service_domain_list', return_value=[])
    def test_template_overview_hides_engine_names(self, domains):
        proxy = 'Traef' + 'ik'
        for extra in ({'template_id': proxy.lower()},
                      {'source': {'type': 'template',
                                  'template_id': proxy.lower()}},
                      {'template_id': 'x', 'template_name': proxy}):
            with self.subTest(extra=extra), mock.patch.object(
                    coast, 'service_get', return_value=dict(SERVICE, **extra)):
                response = self.client.get(self.url(
                    'services', 'detail', ['svc']))
                self.assertContains(response, '<dt>Source</dt><dd>Template: '
                                    'proxy</dd>', html=True)
                self.assertNotContains(response, proxy)
                self.assertNotContains(response, proxy.lower())

    def test_oneclick_table_template_column_hides_engine_names(self):
        table = oneclick_tables.OneClickTable(self.request, data=[dict(
            SERVICE, template_id='traef' + 'ik')])
        row = table.get_rows()[0]
        self.assertEqual('proxy', row.cells['template_id'].data)
        self.assertEqual('traef' + 'ik', table.data[0]['template_id'])

    @mock.patch.object(coast, 'service_deployment_cancel')
    def test_deployment_cancel_get_not_allowed(self, cancel):
        response = self.client.get(self.url(
            'services', 'deployment_cancel', ['svc', 'd1']))
        self.assertEqual(405, response.status_code)
        cancel.assert_not_called()

    @mock.patch.object(coast, 'service_deployment_cancel',
                       side_effect=coast.CoastError('Deployment has finished'))
    def test_deployment_cancel_failure_returns_to_deployment(self, cancel):
        response = self.client.post(self.url(
            'services', 'deployment_cancel', ['svc', 'd1']))
        self.assertRedirects(response, self.url(
            'services', 'deployment', ['svc', 'd1']),
            fetch_redirect_response=False)
        messages = [str(message) for message in
                    get_messages(response.wsgi_request)]
        self.assertIn('Deployment has finished', messages)

    @mock.patch.object(coast, 'service_deployment_log', return_value={
        'lines': [], 'complete': False})
    @mock.patch.object(coast, 'service_deployment_get', return_value={
        'id': 'd1', 'number': 5, 'status': 'DEPLOYING'})
    def test_running_deployment_polls_log_fragment(self, get, log):
        result = self.client.get(self.url(
            'services', 'deployment', ['svc', 'd1']))
        self.assertContains(result, 'No build log lines yet.')
        self.assertContains(result, 'data-complete="0"')
        self.assertContains(result, 'setInterval')
        self.assertContains(result, self.url(
            'services', 'deployment_log_fragment', ['svc', 'd1']))
        log.return_value = {'complete': True, 'lines': [
            {'ts': 't', 'stream': 'build', 'line': 'Step 2/3'}]}
        result = self.client.get(self.url(
            'services', 'deployment_log_fragment', ['svc', 'd1']))
        self.assertContains(result, 'Step 2/3')
        self.assertContains(result, 'data-complete="1"')
        self.assertNotContains(result, '<html')

    @mock.patch.object(coast, 'service_deployment_log', return_value={
        'lines': [{'ts': 't', 'stream': 'build', 'line': 'Step 1/3'}]})
    def test_deployment_log_view(self, log):
        result = self.client.get(self.url('services', 'deployment_log',
                                          ['svc', 'd1']))
        self.assertContains(result, 'Step 1/3')
        log.assert_called_once_with(mock.ANY, 'svc', 'd1')

    @mock.patch.object(coast, 'service_domain_list', return_value=[])
    def test_settings_banner_and_edit(self, domains):
        pending = dict(SERVICE, pending_changes=True, ports='8080')
        with mock.patch.object(coast, 'service_get', return_value=pending), \
                mock.patch.object(coast, 'service_deployment_list',
                                  return_value=[{'number': 1,
                                                 'status': 'ACTIVE'}]):
            result = self.client.get(self.url('services', 'detail', ['svc']),
                                     {'tab': 'service_details__settings'})
        self.assertContains(result, 'Changes saved, redeploy to apply.')
        self.assertContains(result, 'services__deploy__svc')
        self.assertContains(result, 'Edit Settings')
        busy = dict(pending, status='DEPLOYING')
        with mock.patch.object(coast, 'service_get', return_value=busy), \
                mock.patch.object(coast, 'service_deployment_list',
                                  return_value=[{'number': 1,
                                                 'status': 'DEPLOYING'}]):
            result = self.client.get(self.url('services', 'detail', ['svc']),
                                     {'tab': 'service_details__settings'})
        self.assertContains(result, 'Changes saved, redeploy to apply.')
        self.assertNotContains(result, 'services__deploy__svc')
        with mock.patch.object(coast, 'service_update',
                               return_value=pending) as update:
            result = self.client.post(
                self.url('services', 'edit_settings', ['svc']),
                {'name': SERVICE['name'], 'ports': '81',
                 'health_check': SERVICE['health_check'],
                 'healthcheck_path': '', 'description': ''})
        self.assertRedirects(
            result, self.url('services', 'detail', ['svc']),
            fetch_redirect_response=False)
        update.assert_called_once_with(
            mock.ANY, 'svc', {'ports': '81'})

    def test_cancel_deployment_action(self):
        from coast_dashboard.content.services import tables
        action = tables.CancelDeployment()
        self.assertTrue(action.allowed(None, {'status': 'DEPLOYING'}))
        self.assertFalse(action.allowed(None, {'status': 'ACTIVE'}))
        with mock.patch.object(coast, 'service_deployment_cancel') as cancel, \
                mock.patch.object(tables.messages, 'success'):
            action.single(mock.Mock(kwargs={'service_id': 'svc'}),
                          self.request, 'd1')
        cancel.assert_called_once_with(self.request, 'svc', 'd1')

    def test_redeploy_allows_first_deployment_but_not_busy(self):
        from coast_dashboard.content.services import tables
        action = tables.DeployService()
        self.assertEqual('Redeploy', str(action.verbose_name))
        self.assertTrue(action.allowed(None, dict(status='ACTIVE')))
        self.assertTrue(action.allowed(None, dict(status='ACTIVE',
                                                  deployed=True)))
        self.assertTrue(action.allowed(None, dict(status='PENDING')))
        self.assertFalse(action.allowed(None, dict(
            status='PENDING', current_deployment_id='in-flight')))
        self.assertFalse(action.allowed(None, dict(
            status='STOPPED', task_state='RECONCILING')))
        for state in ('DEPLOYING', 'STARTING', 'DELETING'):
            self.assertFalse(action.allowed(None, dict(
                status='ACTIVE', deployed=True, deployment_status=state)))
            if state != 'STARTING':
                self.assertFalse(action.allowed(None, dict(
                    status=state, deployed=True)))
        # A start waiting on the engine (or a failed one) never hides
        # Redeploy.
        self.assertTrue(action.allowed(None, dict(
            status='STARTING', deployed=True)))

    @mock.patch.object(coast, 'stack_list', return_value=[
        {'id': 's1', 'name': 'teststack'}])
    def test_apps_table_shows_names(self, stacks):
        result = self.client.get(self.url('services'))
        self.assertContains(result, APPGROUPS[0]['name'])
        self.assertContains(result, 'App Group')
        self.assertNotContains(result, 'App Group ID')

    @mock.patch.object(coast, 'service_logs', return_value={'lines': [
        {'ts': 'now', 'stream': 'stdout',
         'line': '<script>alert(1)</script>'}]})
    def test_logs_are_escaped(self, logs):
        result = self.client.get(self.url('services', 'logs', ['svc']))
        self.assertContains(result, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(result, '<script>alert(1)</script>')

    @mock.patch.object(coast, 'stack_get', return_value={
        'id': 's1', 'name': 'demo', 'status': 'BUILDING'})
    def test_stack_servers(self, get):
        result = self.client.get(self.url('stacks', 'detail', ['s1']))
        self.assertContains(result, 'BUILDING')
        self.assertContains(result, 'App engine server')
        self.assertNotIn('coolify', result.content.decode().lower())
        self.assertContains(result, 'Worker')

    @mock.patch.object(coast, 'stack_create', return_value={'id': 's'})
    def test_create_stack_post(self, create):
        result = self.client.post(self.url('stacks', 'create'), STACK_DATA)
        self.assertRedirects(result, self.url('stacks'),
                             fetch_redirect_response=False)
        create.assert_called_once_with(mock.ANY, **STACK_DATA)

    @mock.patch.object(coast, 'service_create', return_value={'id': 'svc'})
    def test_create_service_post(self, create):
        result = self.client.post(self.url('services', 'create'), SERVICE_DATA)
        self.assertRedirects(result, self.url('services'),
                             fetch_redirect_response=False)
        create.assert_called_once()

    @mock.patch.object(coast, 'service_create', return_value={
        'id': 'svc', 'deployment_id': 'dep'})
    def test_create_service_opens_deployment(self, create):
        result = self.client.post(self.url('services', 'create'), SERVICE_DATA)
        self.assertRedirects(
            result, self.url('services', 'deployment', ['svc', 'dep']),
            fetch_redirect_response=False)

    @mock.patch.object(coast, 'service_deploy', return_value={'id': 'd'})
    def test_deploy_post(self, deploy):
        result = self.client.post(self.url('services'),
                                  {'action': 'services__deploy__svc'})
        self.assertIn(result.status_code, (200, 302))
        deploy.assert_called_once_with(mock.ANY, 'svc')

    @mock.patch.object(coast, 'service_deploy', side_effect=RuntimeError())
    def test_deploy_failure(self, deploy):
        result = self.client.post(self.url('services'),
                                  {'action': 'services__deploy__svc'})
        self.assertContains(result, 'Unable to redeploy')

    def test_delete_failure_shows_api_reason(self):
        response = mock.Mock(status_code=409)
        response.json.return_value = {'faultstring': 'Stack is busy.'}
        error = RuntimeError()
        error.response = response
        with mock.patch.object(coast, 'service_delete', side_effect=error):
            result = self.client.post(self.url('services'),
                                      {'action': 'services__delete__svc'},
                                      follow=True)
        self.assertContains(result, 'Stack is busy.')
        self.assertNotContains(result, 'Unable to delete')

    @mock.patch.object(coast, 'service_delete')
    def test_delete_service_post(self, delete):
        result = self.client.post(self.url('services'),
                                  {'action': 'services__delete__svc'})
        self.assertRedirects(result, self.url('services'),
                             fetch_redirect_response=False)
        delete.assert_called_once_with(mock.ANY, 'svc')

    @mock.patch.object(coast, 'stack_list', return_value=[
        {'id': 's1', 'name': 'demo', 'status': 'ACTIVE'}])
    @mock.patch.object(coast, 'stack_delete')
    def test_delete_stack_post(self, delete, stacks):
        result = self.client.post(self.url('stacks'),
                                  {'action': 'stacks__delete__s1'})
        self.assertRedirects(result, self.url('stacks'),
                             fetch_redirect_response=False)
        delete.assert_called_once_with(mock.ANY, 's1')

    @mock.patch.object(coast, 'stack_get', return_value={
        'id': 's1', 'name': 'demo', 'status': 'BUILDING'})
    def test_stack_ajax_refresh(self, get):
        result = self.client.get(self.url('stacks'), {
            'table': 'stacks', 'action': 'row_update', 'obj_id': 's1'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(200, result.status_code)
        self.assertContains(result, 'BUILDING')
        get.assert_called_once_with(mock.ANY, 's1')

    @mock.patch.object(coast, 'environment_get', return_value=dict(
        ENVIRONMENTS[0], status='PENDING'))
    def test_environment_ajax_refresh(self, get):
        result = self.client.get(self.url('environments'), {
            'table': 'environments', 'action': 'row_update', 'obj_id': 'e1'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertContains(result, 'Creating')
        get.assert_called_once_with(mock.ANY, 'e1')

    @mock.patch.object(coast, 'service_get', return_value=SERVICE)
    @mock.patch.object(coast, 'service_deployment_list', return_value=[
        {'id': 'd', 'number': 1, 'status': 'DEPLOYING'}])
    def test_service_ajax_refresh(self, deployments, get):
        for view, args in [('index', None), ('detail', ['svc'])]:
            result = self.client.get(self.url('services', view, args), {
                'table': 'services', 'action': 'row_update', 'obj_id': 'svc'},
                HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertContains(result, 'DEPLOYING')

    def test_status_uses_task_and_latest_deployment(self):
        self.assertEqual('RECONCILING', common.status(dict(
            SERVICE, task_state='RECONCILING')))
        self.assertEqual('ACTIVE', common.status(SERVICE))
        with mock.patch.object(coast, 'service_deployment_list', return_value=[
                {'number': 1, 'status': 'BUILDING'},
                {'number': 2, 'status': 'ACTIVE'}]):
            item = common.service_status(self.request, SERVICE)
        self.assertEqual('ACTIVE', common.status(item))

    def test_failure_does_not_hide_delete_status(self):
        with mock.patch.object(coast, 'service_deployment_list', return_value=[
                {'number': 1, 'status': 'BUILDING'}]):
            item = common.service_status(
                self.request, dict(SERVICE, status='DELETING'))
        self.assertEqual('DELETING', common.status(item))

    def test_error_paths(self):
        for panel, method, message in [
                ('services', 'service_list', 'Unable to retrieve apps'),
                ('environments', 'environment_list',
                 'Unable to retrieve environments')]:
            with mock.patch.object(coast, method, side_effect=RuntimeError()):
                result = self.client.get(self.url(panel))
                self.assertContains(result, message)

    def test_create_get_has_no_side_effects(self):
        with mock.patch.object(coast, 'stack_create') as stack_create, \
                mock.patch.object(coast, 'service_create') as service_create:
            for panel in ('stacks', 'services'):
                result = self.client.get(self.url(panel, 'create'))
                self.assertEqual(200, result.status_code)
            stack_create.assert_not_called()
            service_create.assert_not_called()

    def test_delete_actions_have_no_local_policy(self):
        self.assertEqual((), stack_tables.DeleteStack.policy_rules)
        self.assertEqual((), service_tables.DeleteService.policy_rules)

    def test_deleted_rows_return_404(self):
        for panel, method, table, obj_id in [
                ('stacks', 'stack_get', 'stacks', 's1'),
                ('environments', 'environment_get', 'environments', 'e1'),
                ('services', 'service_get', 'services', 'svc')]:
            with self.subTest(panel=panel), mock.patch.object(
                    coast, method, side_effect=coast.exceptions.NotFound()):
                result = self.client.get(self.url(panel), {
                    'table': table, 'action': 'row_update', 'obj_id': obj_id},
                    HTTP_X_REQUESTED_WITH='XMLHttpRequest')
                self.assertEqual(404, result.status_code)

    @mock.patch.object(coast, 'service_deployment_get', return_value={
        'id': 'd', 'number': 1, 'status': 'ACTIVE'})
    def test_deployment_ajax_refresh(self, get):
        result = self.client.get(self.url('services', 'detail', ['svc']), {
            'table': 'deployments', 'action': 'row_update', 'obj_id': 'd'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertContains(result, 'ACTIVE')
        get.assert_called_once_with(mock.ANY, 'svc', 'd')

    @mock.patch.object(coast, 'stack_get', return_value={
        'id': 's1', 'name': 'demo', 'status': 'ACTIVE'})
    @mock.patch.object(coast, 'stack_server_get', return_value={
        'id': 'build', 'name': 'builder', 'role': 'build', 'status': 'ACTIVE'})
    def test_server_ajax_refresh(self, get, stack):
        result = self.client.get(self.url('stacks', 'detail', ['s1']), {
            'table': 'servers', 'action': 'row_update', 'obj_id': 'build'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertContains(result, 'Build server')
        get.assert_called_once_with(mock.ANY, 's1', 'build')

    @mock.patch.object(coast, 'environment_list', return_value=[
        {'id': 'e1', 'name': 'production', 'appgroup_id': 'g1'}])
    @mock.patch.object(coast, 'appgroup_list', return_value=[
        {'id': 'g1', 'name': 'website', 'stack_id': 's1'},
        {'id': 'g2', 'name': 'other-stack', 'stack_id': 's2'}])
    @mock.patch.object(coast, 'service_list', return_value=[
        {'id': 'a1', 'name': 'web', 'kind': 'app', 'status': 'ACTIVE',
         'stack_id': 's1', 'environment_id': 'e1', 'server_id': 'w1'},
        {'id': 'a2', 'name': 'db', 'kind': 'service', 'status': 'DEPLOYING',
         'stack_id': 's1', 'environment_id': 'e1', 'server_id': 'w1'},
        {'id': 'a3', 'name': 'elsewhere', 'kind': 'app',
         'stack_id': 's2', 'environment_id': 'e9'}])
    @mock.patch.object(coast, 'stack_server_list', return_value=[
        {'id': 'w1', 'name': 'worker-1', 'role': 'worker',
         'status': 'ACTIVE', 'floating_ip': '203.0.113.5'},
        {'id': 'w2', 'name': 'worker-2', 'role': 'worker',
         'status': 'ACTIVE'},
        {'id': 'c1', 'name': 'controller', 'role': 'control',
         'status': 'ACTIVE'}])
    @mock.patch.object(coast, 'stack_get', return_value={
        'id': 's1', 'name': 'demo', 'status': 'ACTIVE'})
    def test_stack_topology_tab(self, stack, servers, services, groups,
                                envs):
        result = self.client.get(self.url('stacks', 'detail', ['s1']),
                                 {'tab': 'stack_details__topology'})
        for text in ('Topology', 'website', 'production', 'web', 'db',
                     'worker-1', '203.0.113.5', '1 app, 1 service', 'No apps',
                     'App engine server', 'coast-tree',
                     self.url('services', 'detail', ['a1']),
                     self.url('appgroups', 'detail', ['g1']),
                     self.url('environments', 'detail', ['e1'])):
            self.assertContains(result, text)
        self.assertNotContains(result, 'other-stack')
        self.assertNotContains(result, 'elsewhere')
        self.assertNotContains(result, 'Coolify')
        self.assertNotContains(result, '2 apps')
        envs.assert_called_once_with(mock.ANY, appgroup_id='g1')

    @mock.patch.object(coast, 'service_delete',
                       side_effect=coast.exceptions.RecoverableError())
    def test_delete_failure_is_reported(self, delete):
        result = self.client.post(self.url('services'),
                                  {'action': 'services__delete__svc'})
        self.assertEqual(302, result.status_code)
        result = self.client.get(self.url('services'))
        self.assertContains(result, 'Unable to delete app')

    def test_appgroup_environment_create_views(self):
        for panel, resource, parent, parent_id in [
                ('appgroups', 'appgroup', 'stack', 's1'),
                ('environments', 'environment', 'appgroup', 'a1')]:
            with mock.patch.object(coast, parent + '_list', return_value=[
                    {'id': parent_id, 'name': 'Ready', 'status': 'ACTIVE'}]), \
                    mock.patch.object(coast, resource + '_create',
                                      return_value={'id': 'new'}) as create:
                url = self.url(panel, 'create')
                result = self.client.get(url)
                self.assertEqual(200, result.status_code)
                create.assert_not_called()
                data = {parent + '_id': parent_id, 'name': 'demo'}
                result = self.client.post(url, data)
                self.assertRedirects(result, self.url(panel),
                                     fetch_redirect_response=False)
                create.assert_called_once_with(mock.ANY, **data)

    def test_appgroup_environment_delete(self):
        for panel, resource, obj_id in [
                ('appgroups', 'appgroup', 'a1'),
                ('environments', 'environment', 'e1')]:
            with mock.patch.object(coast, resource + '_delete') as delete:
                self.client.get(self.url(panel))
                delete.assert_not_called()
                result = self.client.post(self.url(panel), {
                    'action': '%s__delete__%s' % (panel, obj_id)})
                self.assertRedirects(result, self.url(panel),
                                     fetch_redirect_response=False)
                delete.assert_called_once_with(mock.ANY, obj_id)

    def test_parent_resource_refresh(self):
        for panel, resource, row in [
                ('appgroups', 'appgroup', APPGROUPS[0]),
                ('environments', 'environment', ENVIRONMENTS[0])]:
            for state in ('PENDING', 'DELETING', 'ACTIVE', 'ERROR'):
                with mock.patch.object(coast, resource + '_get',
                                       return_value=dict(row, status=state)):
                    result = self.client.get(self.url(panel), {
                        'table': panel, 'action': 'row_update',
                        'obj_id': row['id']},
                        HTTP_X_REQUESTED_WITH='XMLHttpRequest')
                    expected = {'PENDING': 'Creating', 'DELETING': 'Deleting',
                                'ERROR': 'Error', 'ACTIVE': row['name']}
                    self.assertContains(result, expected.get(state, state))
            with mock.patch.object(coast, resource + '_get',
                                   side_effect=coast.exceptions.NotFound()):
                result = self.client.get(self.url(panel), {
                    'table': panel, 'action': 'row_update',
                    'obj_id': row['id']},
                    HTTP_X_REQUESTED_WITH='XMLHttpRequest')
                self.assertEqual(404, result.status_code)

    @mock.patch.object(coast, 'stack_list', return_value=[
        {'id': 's1', 'name': 'Main', 'status': 'ACTIVE'}])
    @mock.patch.object(coast, 'template_list', return_value=[])
    def test_list_concept_introductions(self, templates, stacks):
        expected = {
            'stacks': ('A stack is the set of servers', 'app engine server',
                       'optional build server', 'workers'),
            'appgroups': ('App groups organize related apps and services as '
                          'projects.', 'Each app group belongs to a stack.'),
            'environments': ('Environments separate production, staging, and '
                             'testing within an app group.',
                             'on a worker in the app group stack.'),
            'services': ('Apps deploy your code from Git, a Dockerfile, or a '
                         'container image.',
                         'Each app runs in an environment'),
            'oneclick': ('Services deploy one-click templates such as '
                         'Postgres.',
                         'Each service runs in an environment')}
        for panel, snippets in expected.items():
            with self.subTest(panel=panel):
                result = self.client.get(self.url(panel))
                self.assertNotIn('coolify', result.content.decode().lower())
                for snippet in snippets:
                    self.assertContains(result, snippet)

    @mock.patch.object(coast, 'stack_list', return_value=[
        {'id': 's1', 'name': 'Main', 'status': 'ACTIVE'}])
    @mock.patch.object(coast, 'template_list', return_value=[
        {'id': 'postgresql', 'name': 'Postgres'}])
    def test_create_description_concepts(self, templates, stacks):
        expected = {
            'appgroups': ('An app group is a project for related apps and '
                          'services.', 'Choose the stack whose workers'),
            'environments': ('An environment separates production, staging, '
                             'or testing within an app group.',
                             'on a worker in the app group stack.'),
            'services': ('public Git repository', 'Dockerfile',
                         'container image', 'environment',
                         'worker in the app group stack.'),
            'oneclick': ('Deploy a one-click template such as Postgres.',
                         'Choose an environment and a worker')}
        for panel, snippets in expected.items():
            with self.subTest(panel=panel):
                result = self.client.get(self.url(panel, 'create'))
                self.assertContains(result, 'Description')
                self.assertNotIn('coolify', result.content.decode().lower())
                for snippet in snippets:
                    self.assertContains(result, snippet)

    def test_create_stack_engine_neutral_help(self):
        result = self.client.get(self.url('stacks', 'create'))
        self.assertContains(result, 'App engine server flavor')
        self.assertContains(
            result, 'Runs the app engine that builds and runs your apps.')
        self.assertContains(result, 'A stack contains an app engine server')
        self.assertNotIn('coolify', result.content.decode().lower())


class StatusChoicesTest(helpers.TestCase):
    def test_starting_and_deploying_are_transitional(self):
        for state in ('STARTING', 'DEPLOYING'):
            self.assertIn(state, common.TRANSITIONAL)
            self.assertIsNone(dict(common.STATUS_CHOICES)[state])


class LogsUnavailableTests(helpers.TestCase):
    def test_unavailable_reason_is_shown(self):
        from coast_dashboard.content.services import logs
        reason = 'The app container is starting or restarting.'
        with mock.patch.object(coast, 'service_logs', return_value={
                'lines': [], 'unavailable': reason}):
            self.assertEqual({'log_error': reason},
                             logs.log_context(None, 'svc'))
        with mock.patch.object(coast, 'service_logs',
                               return_value={'lines': []}):
            self.assertEqual({'logs': {'lines': []}},
                             logs.log_context(None, 'svc'))


class DetailActionsScriptTests(helpers.TestCase):
    def test_detail_pages_carry_action_submit_fix(self):
        from django.template import loader
        html = loader.render_to_string(
            'project/coast_common/_detail_actions_script.html')
        self.assertIn('.detail-actions-form button[name="action"]', html)
        self.assertIn('hidden.value = button.value', html)
        detail = loader.get_template(
            'project/coast_common/detail.html').template.source
        self.assertIn('_detail_actions_script.html', detail)


class RestartLogNoteTests(helpers.TestCase):
    def test_note_is_shown_above_lines(self):
        from django.template import loader
        html = loader.render_to_string(
            'project/coast_services/_log_box.html',
            {'logs': {'note': 'Container is restarting; showing output',
                      'lines': [{'ts': 't', 'stream': 'stdout',
                                 'line': 'boom'}]}})
        self.assertIn('coast-log-note', html)
        self.assertIn('Container is restarting; showing output', html)
        self.assertIn('boom', html)
