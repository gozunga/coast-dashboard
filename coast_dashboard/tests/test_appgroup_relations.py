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

"""App group counts, related sections, and list filters."""

from unittest import mock

from django.test import RequestFactory
from django.urls import reverse

from coast_dashboard.api import coast
from coast_dashboard.content.appgroups import related
from coast_dashboard.content.appgroups import tables
from coast_dashboard.content.environments import views as environment_views
from coast_dashboard.content.oneclick import views as oneclick_views
from coast_dashboard.content.services import views as service_views
from coast_dashboard.tests import helpers


GROUP = {'id': 'group-1', 'name': 'Example', 'status': 'ACTIVE'}
ENVS = [{'id': 'env-%s' % i, 'name': 'Env %s' % i,
         'appgroup_id': 'group-1'} for i in range(4)]
RESOURCES = [
    {'id': 'app-1', 'name': 'Web', 'kind': 'app',
     'appgroup_id': 'group-1', 'status': 'ACTIVE'},
    {'id': 'svc-1', 'name': 'Database', 'kind': 'service',
     'appgroup_id': 'group-1', 'status': 'ACTIVE'},
    {'id': 'other', 'name': 'Other', 'kind': 'app',
     'appgroup_id': 'group-2', 'status': 'ACTIVE'}]


class AppgroupRelationsTests(helpers.TestCase):
    def setUp(self):
        super().setUp()
        for name, value in [('appgroup_list', [GROUP]),
                            ('appgroup_get', GROUP),
                            ('environment_list', ENVS),
                            ('service_list', RESOURCES),
                            ('stack_list', []),
                            ('service_deployment_list', [])]:
            patcher = mock.patch.object(coast, name, return_value=value)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def test_columns_and_bulk_loading(self):
        self.appgroup_list.return_value = [GROUP, dict(GROUP, id='group-2')]
        response = self.client.get(reverse(
            'horizon:project:coast.appgroups:index'))
        for heading in ['Environments', 'Apps', 'Services']:
            self.assertContains(response, heading)
        for panel, count in [('coast.environments', 4),
                             ('coast.apps', 1), ('coast.services', 1)]:
            link = reverse('horizon:project:%s:index' % panel)
            self.assertContains(response, '<a href="%s?appgroup=group-1">'
                                '%s</a>' % (link, count), html=True)
        self.environment_list.assert_called_once()
        self.service_list.assert_called_once()

    def test_environment_names_threshold_and_escaping(self):
        for size in range(1, 4):
            row = dict(GROUP, environments=ENVS[:size])
            html = str(tables.environments(row))
            for env in ENVS[:size]:
                self.assertIn(reverse(
                    'horizon:project:coast.environments:detail',
                    args=[env['id']]), html)
        html = str(tables.environments(dict(
            GROUP, environments=[dict(ENVS[0], name='<script>')])))
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('>0</a>', str(tables.environments(
            dict(GROUP, environments=[]))))

    def test_detail_sections(self):
        response = self.client.get(reverse(
            'horizon:project:coast.appgroups:detail', args=['group-1']))
        for name in ['Env 0', 'Web', 'Database']:
            self.assertContains(response, name)
        self.assertNotContains(response, '>Other<')
        for resource, panel in [('app-1', 'apps'), ('svc-1', 'services')]:
            self.assertContains(response, reverse(
                'horizon:project:coast.%s:detail' % panel, args=[resource]))
        self.service_list.assert_called_once()

    def test_detail_tab_order_and_database_create_context(self):
        from urllib.parse import parse_qs
        from urllib.parse import urlsplit
        url = reverse('horizon:project:coast.appgroups:detail',
                      args=['group-1'])
        page = self.client.get(url, {'environment_id': 'env-0'})
        html = page.content.decode()
        positions = [html.index('appgroup_details__' + tab) for tab in
                     ('apps', 'databases', 'services')]
        self.assertEqual(sorted(positions), positions)
        group = page.context['tab_group']
        table = group.get_tab('databases')._tables['databases']
        action = table.base_actions['create']
        link = action.get_link_url()
        self.assertEqual(reverse('horizon:project:coast.databases:engines'),
                         urlsplit(link).path)
        params = parse_qs(urlsplit(link).query)
        self.assertEqual(['group-1'], params['appgroup_id'])
        self.assertEqual(['env-0'], params['environment_id'])

    def test_empty_detail(self):
        self.environment_list.return_value = []
        self.service_list.return_value = []
        response = self.client.get(reverse(
            'horizon:project:coast.appgroups:detail', args=['group-1']))
        for resource in ['environments', 'apps', 'services']:
            self.assertContains(
                response, 'No %s in this app group.' % resource)

    def test_filters_before_deployment_requests(self):
        for view_class, method in [(environment_views.IndexView, 'get_data'),
                                   (service_views.IndexView, 'get_data'),
                                   (oneclick_views.IndexView,
                                    'get_oneclick_data')]:
            view = view_class()
            view.request = RequestFactory().get('/', {'appgroup': 'group-1'})
            rows = getattr(view, method)()
            self.assertTrue(rows)
            self.assertTrue(all(row['appgroup_id'] == 'group-1'
                                for row in rows))
        self.assertNotIn(mock.call(mock.ANY, 'other'),
                         self.service_deployment_list.call_args_list)

    def test_filter_note_and_clear(self):
        for panel in ['coast.environments', 'coast.apps',
                      'coast.services']:
            url = reverse('horizon:project:%s:index' % panel)
            response = self.client.get(url, {'appgroup': 'group-1'})
            self.assertContains(response, 'Filtered by app group group-1')
            self.assertContains(response, '<a href="%s">clear</a>' % url,
                                html=True)

    @mock.patch('horizon.exceptions.handle')
    def test_partial_failure_does_not_report_zero(self, handle):
        self.environment_list.side_effect = coast.CoastError('Denied')
        request = RequestFactory().get('/')
        item = related.for_group(request, GROUP)
        self.assertEqual('Unavailable', str(tables.environments(item)))
        self.assertEqual(1, len(item['apps']))
        handle.assert_called_once_with(request, 'Denied')

    def test_ajax_row_keeps_counts(self):
        request = RequestFactory().get('/')
        row = tables.UpdateRow(tables.AppgroupsTable(request))
        item = row.get_data(request, 'group-1')
        self.assertEqual(4, len(item['environments']))
        self.assertEqual(1, len(item['apps']))
        self.assertEqual(1, len(item['services']))

    def test_unfiltered_and_unknown_group(self):
        view = environment_views.IndexView()
        view.request = RequestFactory().get('/')
        self.assertEqual(ENVS, view.get_data())
        view.request = RequestFactory().get('/', {'appgroup': 'missing'})
        self.assertEqual([], view.get_data())

    def test_clear_preserves_other_query_parameters(self):
        url = reverse('horizon:project:coast.environments:index')
        response = self.client.get(url, {'appgroup': 'group-1', 'foo': 'bar'})
        self.assertContains(response, '<a href="%s?foo=bar">clear</a>' % url,
                            html=True)
