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
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest
from unittest import mock

from keystoneauth1 import adapter
from keystoneauth1 import session
import requests

from django.urls import reverse

from coast_dashboard.api import coast
from coast_dashboard.content.databases import forms
from coast_dashboard.content.databases import views
from coast_dashboard.tests import helpers
from coast_dashboard.tests.test_api import _resp
from coast_dashboard.tests.test_forms import APPGROUPS
from coast_dashboard.tests.test_forms import ENVIRONMENTS
from coast_dashboard.tests.test_forms import SERVERS


ENGINE_LIST = coast.database_engine_list
DATABASE_LIST = coast.database_list


ENGINE = {'engine': 'postgresql', 'display_name': 'PostgreSQL',
          'versions': ['17', '16'], 'default_version': '17',
          'has_username': True, 'has_database': True, 'port': 5432}
ITEM = {'id': 'db1', 'name': 'orders', 'engine': ENGINE['engine'],
        'version': '17', 'status': 'ACTIVE', 'server_id': 'v1',
        'internal_host': 'orders', 'port': 5432,
        'internal_url': 'postgresql://app@orders:5432/app'}


class PageLinks(HTMLParser):
    """Read navigation and action links from the rendered response."""

    def __init__(self, response):
        super().__init__()
        self.links = []
        self.href = None
        self.label = []
        self.feed(response.content.decode())

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.href = dict(attrs).get('href')
            self.label = []

    def handle_data(self, data):
        if self.href is not None:
            self.label.append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.href is not None:
            self.links.append((self.href, ' '.join(
                ''.join(self.label).split())))
            self.href = None


class DatabaseTests(helpers.TestCase):
    def setUp(self):
        super().setUp()
        for name, value in [('database_engine_list', [ENGINE]),
                            ('database_get', ITEM),
                            ('appgroup_list', APPGROUPS),
                            ('environment_list', ENVIRONMENTS),
                            ('stack_server_list', SERVERS),
                            ('stack_list', [{'id': 's1'}, {'id': 's2'}])]:
            patcher = mock.patch.object(coast, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_detail_fault_alert_and_escaping(self):
        fault = '<script>alert("failed")</script>'
        for status, fields, visible in (
                ('ERROR', {'fault': fault}, True),
                ('ERROR', {'fault': None}, False),
                ('ERROR', {'fault': ''}, False),
                ('ERROR', {}, False),
                ('ACTIVE', {'fault': fault}, False)):
            with self.subTest(status=status, fields=fields):
                coast.database_get.return_value = dict(
                    ITEM, status=status, **fields)
                response = self.client.get(reverse(
                    views.NS + 'detail', args=['db1']))
                if visible:
                    self.assertContains(response, 'role="alert"')
                    self.assertContains(response, 'Reason: &lt;script&gt;')
                else:
                    self.assertNotContains(response, 'Reason:')
                    self.assertNotContains(response, 'role="alert"')
                self.assertNotContains(response, fault)

    @mock.patch.object(coast, 'database_list')
    def test_list_fault_tooltip_and_escaping(self, databases):
        fault = '<b title="reason">Unavailable</b>'
        for status, value in (('ERROR', fault), ('ERROR', None),
                              ('ERROR', ''), ('ACTIVE', fault)):
            with self.subTest(status=status, fault=value):
                databases.return_value = [dict(ITEM, status=status,
                                               fault=value)]
                response = self.client.get(reverse(views.NS + 'index'))
                if status == 'ERROR' and value:
                    self.assertContains(
                        response, 'title="&lt;b title=&quot;reason&quot;'
                        '&gt;Unavailable&lt;/b&gt;"')
                else:
                    self.assertNotContains(response, 'Unavailable&lt;/b&gt;')
                self.assertNotContains(response, fault)

    @mock.patch.object(coast, 'database_credentials')
    def test_initial_html_has_no_credentials(self, credentials):
        credentials.return_value = {'password': 'test-secret-value'}
        response = self.client.get(reverse(views.NS + 'detail', args=['db1']))
        self.assertEqual(200, response.status_code)
        self.assertContains(response, 'orders:5432/app')
        self.assertNotContains(response, 'test-secret-value')
        self.assertContains(
            response, 'data-url="%s"' % reverse(
                views.NS + 'credentials', args=['db1']))
        self.assertContains(response, 'Show password')
        credentials.assert_not_called()

    @mock.patch.object(coast, 'database_credentials')
    def test_explicit_credentials_are_not_cached(self, credentials):
        credentials.return_value = {'password': 'test-secret-value'}
        with mock.patch.object(
                views.common, 'project_member', return_value=True):
            response = self.client.get(reverse(
                views.NS + 'credentials', args=['db1']))
        self.assertEqual(200, response.status_code)
        self.assertEqual('no-store', response['Cache-Control'])
        self.assertEqual(credentials.return_value,
                         response.json()['credentials'])
        credentials.assert_called_once()

    @mock.patch.object(coast, 'database_credentials')
    def test_reader_cannot_reveal(self, credentials):
        with mock.patch.object(
                views.common, 'project_member', return_value=False):
            response = self.client.get(reverse(
                views.NS + 'credentials', args=['db1']))
        self.assertEqual(403, response.status_code)
        self.assertEqual('no-store', response['Cache-Control'])
        credentials.assert_not_called()

    def test_catalog_and_version_default(self):
        response = self.client.get(reverse(views.NS + 'engines'))
        self.assertContains(response, ENGINE['display_name'])
        form = forms.CreateDatabase(self.request,
                                    initial={'engine': ENGINE['engine']})
        self.assertEqual('17', form.initial['version'])
        self.assertEqual([('17', '17'), ('16', '16')],
                         list(form.fields['version'].choices))
        self.assertEqual('app', form.fields['username'].initial)

    def test_engine_catalog_table_search_and_context(self):
        expected = [
            ('postgresql', 'PostgreSQL',
             'Relational SQL database with strong consistency and extensions'),
            ('mysql', 'MySQL',
             'Relational SQL database for web applications'),
            ('mariadb', 'MariaDB',
             'Community-developed relational SQL database compatible with '
             'MySQL'),
            ('mongodb', 'MongoDB',
             'Document database for flexible JSON-like data'),
            ('redis', 'Redis',
             'In-memory key-value store for caches, queues and sessions'),
            ('keydb', 'KeyDB',
             'Multithreaded in-memory key-value store compatible with Redis'),
            ('dragonfly', 'Dragonfly',
             'In-memory data store compatible with Redis for high throughput'),
            ('clickhouse', 'ClickHouse',
             'Column-oriented SQL database for real-time analytics')]
        engines = [dict(engine=engine, display_name=name,
                        versions=[engine + '-api-current',
                                  engine + '-api-previous'])
                   for engine, name, description in expected]
        coast.database_engine_list.return_value = engines
        url = reverse(views.NS + 'engines')
        params = {'appgroup_id': 'a1', 'environment_id': 'e1'}
        page = self.client.get(url, params)
        self.assertContains(page, 'type="search"')
        self.assertContains(page, 'name="q"')
        self.assertContains(page, '<table')
        rows = page.context['table'].data
        self.assertEqual([e['engine'] for e in engines],
                         [r['engine'] for r in rows])
        for engine, (key, name, description) in zip(engines, expected):
            with self.subTest(engine=key):
                row = next(r for r in rows if r['engine'] == key)
                self.assertEqual(name, row['name'])
                self.assertEqual(description, row['description'])
                self.assertEqual(engine['versions'], row['versions'])
                self.assertContains(page, name)
                self.assertContains(page, description)
            self.assertContains(page, ', '.join(engine['versions']))
            action = page.context['table'].get_row_actions(
                next(r for r in rows if r['engine'] == engine['engine']))[0]
            link = action.get_link_url(engine)
            self.assertIn('engine=' + engine['engine'], link)
            self.assertIn('appgroup_id=a1', link)
            self.assertIn('environment_id=e1', link)
        for query, expected in [('PostgreSQL', ['postgresql']),
                                ('queues', ['redis']), ('missing', [])]:
            result = self.client.get(url, {'q': query})
            self.assertEqual(expected, [r['engine'] for r in
                                        result.context['table'].data])

    def test_detail_rendered_tab_order(self):
        page = self.client.get(reverse(views.NS + 'detail', args=['db1']))
        self.assertEqual(200, page.status_code)
        tabs = [label for href, label in PageLinks(page).links
                if href.startswith('?tab=database_details__')]
        self.assertEqual(['Overview', 'Backups', 'Logs'], tabs)

    def test_filtered_panel_create_through_catalog_to_form(self):
        coast.database_list.return_value = []
        with mock.patch.object(views.common, 'project_member',
                               return_value=True):
            panel = self.client.get(reverse(views.NS + 'index'),
                                    {'appgroup': 'a2'})
        self.assertEqual(200, panel.status_code)
        catalog_url, = [href for href, label in PageLinks(panel).links
                        if label == 'Create database']
        catalog = self.client.get(catalog_url)
        self.assertEqual(200, catalog.status_code)
        create_url, = [href for href, label in PageLinks(catalog).links
                       if label == 'Create database']
        response = self.client.get(
            create_url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(200, response.status_code)
        form = response.context['form']
        self.assertEqual('a2', form['appgroup_id'].value())
        self.assertTrue(form.fields['appgroup_id'].disabled)
        self.assertEqual(ENGINE['engine'], form['engine'].value())

    def test_create_modal_placement_and_defaults(self):
        coast.database_list.return_value = [
            dict(ITEM, name='postgresql', appgroup_id='a1')]
        response = self.client.get(reverse(views.NS + 'create'), {
            'engine': ENGINE['engine'], 'appgroup_id': 'a1',
            'environment_id': 'e1'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(200, response.status_code)
        form = response.context['form']
        self.assertEqual('postgresql-2', form.initial['name'])
        self.assertEqual(
            ['name', 'appgroup_id', 'environment_id', 'server_id'],
            list(form.fields)[:4])
        self.assertEqual('a1', form['appgroup_id'].value())
        self.assertEqual('e1', form['environment_id'].value())
        self.assertContains(response, 'coast-environment-groups')
        self.assertContains(response, 'data-coast-name-defaults')

    def test_create_connection_settings_for_engine_capabilities(self):
        for supported in (True, False):
            coast.database_engine_list.return_value = [dict(
                ENGINE, has_username=supported, has_database=supported)]
            response = self.client.get(reverse(views.NS + 'create'), {
                'engine': ENGINE['engine']},
                HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            form = response.context['form']
            self.assertEqual('Name', form.fields['name'].label)
            self.assertEqual(
                'The name shown in Coast. You type it to confirm a delete.',
                form.fields['name'].help_text)
            self.assertContains(response, 'Connection settings')
            self.assertContains(response, 'Coast generates a strong password')
            self.assertContains(response, 'Show password on its Overview tab.')
            self.assertNotIn('password', form.fields)
            if supported:
                self.assertEqual('Initial database',
                                 form.fields['database'].label)
                self.assertEqual('Username', form.fields['username'].label)
                self.assertEqual('app', form['database'].value())
                self.assertEqual('app', form['username'].value())
                self.assertEqual(
                    'The database created inside the engine for your app '
                    'to use. Defaults to app.',
                    form.fields['database'].help_text)
                self.assertEqual(
                    'Database user for your app. Defaults to app.',
                    form.fields['username'].help_text)
                self.assertContains(response, 'Defaults to app.', count=2)
            else:
                self.assertNotIn('database', form.fields)
                self.assertNotIn('username', form.fields)

    @unittest.skipUnless(shutil.which('node'), 'node is not installed')
    def test_connection_settings_dom_for_engine_capabilities(self):
        for supported in (True, False):
            with self.subTest(connection_fields=supported):
                coast.database_engine_list.return_value = [dict(
                    ENGINE, has_username=supported, has_database=supported)]
                response = self.client.get(reverse(views.NS + 'create'), {
                    'engine': ENGINE['engine']},
                    HTTP_X_REQUESTED_WITH='XMLHttpRequest')
                scripts = re.findall(r'<script>(.*?)</script>',
                                     response.content.decode(), re.S)
                script = next(s for s in scripts if 'var advanced =' in s)
                result = subprocess.run(
                    ['node', str(Path(__file__).parent / 'js' /
                                 'database_connection_settings.js')],
                    input=json.dumps({
                        'script': script,
                        'fields': list(response.context['form'].fields)}),
                    text=True, capture_output=True, timeout=30, check=True)
                sections = json.loads(result.stdout)
                connection = sections['Connection settings']
                self.assertFalse(connection['open'])
                self.assertEqual(
                    ['database', 'username'] if supported else [],
                    connection['fields'])
                self.assertEqual(
                    ['Coast generates a strong password and stores it '
                     'securely. After the database is created, reveal it '
                     'with Show password on its Overview tab.'],
                    connection['notes'])
                self.assertEqual(['cpu_limit', 'memory_limit_mb'],
                                 sections['Advanced']['fields'])

    def test_delete_confirmation_display_validation_and_escaping(self):
        from django.utils.html import escape
        for name in ('postgresql', '<b>orders & apps</b>'):
            coast.database_get.return_value = dict(ITEM, name=name)
            url = reverse(views.NS + 'delete', args=[ITEM['id']])
            response = self.client.get(url,
                                       HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertContains(response, '<strong>%s</strong>' % escape(name))
            self.assertContains(response, 'Coast name')
            for value in ('app', ' ' + name + ' ', name):
                form = forms.DeleteDatabase(self.request,
                                            {'confirmation': value},
                                            item=dict(ITEM, name=name))
                self.assertEqual(value == name, form.is_valid())
                if value != name:
                    self.assertEqual(['Type %s to confirm deletion.' % name],
                                     form.errors['confirmation'])
                    self.assertIn(escape(name), str(form.errors))

    def test_engine_capabilities_control_fields(self):
        with mock.patch.object(coast, 'database_engine_list', return_value=[
                dict(ENGINE, has_username=False, has_database=False)]):
            form = forms.CreateDatabase(self.request,
                                        initial={'engine': ENGINE['engine']})
        self.assertNotIn('username', form.fields)
        self.assertNotIn('database', form.fields)

    @mock.patch.object(coast, 'database_delete')
    def test_delete_requires_exact_name(self, delete):
        form = forms.DeleteDatabase(self.request,
                                    data={'confirmation': 'wrong'}, item=ITEM)
        self.assertFalse(form.is_valid())
        delete.assert_not_called()

    @mock.patch.object(coast, '_get')
    @mock.patch.object(coast, '_write')
    def test_api_contract(self, write, get):
        get.return_value = {'database': ITEM,
                            'credentials': {'username': 'app'},
                            'database_engines': [ENGINE], 'databases': [ITEM]}
        self.assertEqual([ENGINE], ENGINE_LIST(self.request))
        self.assertEqual(
            [ITEM], DATABASE_LIST(self.request, appgroup_id='a1'))
        self.assertEqual(ITEM, coast.database_get(self.request, 'db1'))
        with mock.patch.object(coast, '_raw_request') as raw:
            raw.return_value.json.return_value = get.return_value
            coast.database_credentials(self.request, 'db1')
            raw.assert_called_with(
                self.request, '/databases/db1/credentials', 'GET',
                microversion='1.29')
        write.return_value = {'database': ITEM}
        coast.database_create(self.request, name='orders')
        write.assert_called_with(self.request, '/databases', 'POST',
                                 {'database': {'name': 'orders'}},
                                 microversion='1.29')
        coast.database_delete(self.request, 'db1')
        write.assert_called_with(self.request, '/databases/db1', 'DELETE',
                                 microversion='1.29')

    @mock.patch.object(coast, 'coastclient')
    def test_credentials_transport_disables_logging(self, client):
        credentials = {'password': 'opaque-test-value'}
        client.return_value.adapter.request.return_value.json.return_value = {
            'credentials': credentials}
        self.assertEqual(credentials, coast.database_credentials(
            self.request, 'db1'))
        client.assert_called_once_with(self.request, '1.0')
        client.return_value.adapter.request.assert_called_once_with(
            '/databases/db1/credentials', 'GET', microversion='1.29',
            log=False, connect_retries=0, status_code_retries=0)

    @mock.patch.object(coast, 'database_create')
    def test_create_submits_catalog_version_and_placement(self, create):
        data = {'engine': ENGINE['engine'], 'version': '17',
                'name': 'orders', 'appgroup_id': 'a1',
                'environment_id': 'e1', 'server_id': 'v1',
                'database': 'app', 'username': 'app'}
        form = forms.CreateDatabase(self.request, data=data)
        self.assertTrue(form.is_valid(), form.errors)
        with mock.patch.object(forms.common, 'project_member',
                               return_value=True):
            form.handle(self.request, form.cleaned_data)
        create.assert_called_once_with(
            self.request, **data, cpu_limit=None, memory_limit_mb=None)

    def test_panel_order(self):
        import horizon
        panels = list(horizon.get_dashboard('project').get_panel_group(
            'app_hosting'))
        slugs = [panel.slug for panel in panels]
        self.assertEqual(slugs.index('coast.apps') + 1,
                         slugs.index('coast.databases'))
        self.assertEqual(slugs.index('coast.databases') + 1,
                         slugs.index('coast.services'))

    @mock.patch.object(coast, 'database_list')
    def test_list_columns_badge_gap_and_appgroup_filter(self, databases):
        databases.return_value = [
            dict(ITEM, status='PENDING', appgroup_id='a1',
                 environment_id='e1', stack_id='s1',
                 created_at='2026-10-23T12:00:00Z'),
            dict(ITEM, id='db2', name='excluded-database', appgroup_id='a2')]
        response = self.client.get(reverse(views.NS + 'index'),
                                   {'appgroup': 'a1'})
        self.assertEqual(200, response.status_code)
        columns = response.context['table'].columns
        self.assertEqual(
            ['Name', 'Engine', 'Version', 'Status', 'Stack', 'App group',
             'Environment', 'Server', 'Created'],
            [str(c.verbose_name) for key, c in columns.items()
             if key not in ('multi_select', 'actions')])
        for text in ('orders', 'Production', 'worker', 'margin-left:0.4em',
                     ENGINE['engine'], 'Creating'):
            self.assertContains(response, text)
        self.assertNotContains(response, 'excluded-database')

    def test_engine_link_opens_preselected_form(self):
        response = self.client.get(reverse(views.NS + 'create'),
                                   {'engine': ENGINE['engine']})
        self.assertEqual(ENGINE, response.context['form'].catalog_engine)

    def test_database_placement_auto_selection_and_create_rendering(self):
        with mock.patch.object(coast, 'appgroup_list',
                               return_value=APPGROUPS[:1]), \
                mock.patch.object(coast, 'environment_list',
                                  return_value=ENVIRONMENTS[:1]), \
                mock.patch.object(coast, 'stack_server_list',
                                  return_value=SERVERS[:1]):
            response = self.client.get(reverse(views.NS + 'create'),
                                       {'engine': ENGINE['engine']})
        form = response.context['form']
        for field, value in [('appgroup_id', 'a1'), ('environment_id', 'e1'),
                             ('server_id', 'v1')]:
            self.assertEqual(value, form[field].value())
        self.assertEqual('App group', form.fields['appgroup_id'].label)
        for text in ('Create database', 'Advanced', 'CPU limit',
                     'Memory limit (MB)', 'same server', 'internal host',
                     'Public access is off by default.',
                     "advanced.appendChild(group)"):
            self.assertContains(response, text)
        self.assertNotContains(response, 'Create Database')
        self.assertContains(response,
                            '<span class="field-label">App group</span>',
                            html=True)

    def test_connection_values_copy_controls_and_credential_labels(self):
        response = self.client.get(reverse(views.NS + 'detail', args=['db1']))
        for label in ('Internal host', 'Port', 'Initial database', 'Username',
                      'Internal URL', 'Root password', 'Public URL'):
            self.assertContains(response, label)
        for value in ('orders', '5432', 'app', ITEM['internal_url']):
            self.assertContains(response, value)
        self.assertContains(
            response, '<button type="button" '
            'class="btn btn-default db-copy">Copy</button>',
            count=5, html=True)
        self.assertContains(
            response, '<p>Initial database: <code>app</code> '
            '<button type="button" class="btn btn-default db-copy">'
            'Copy</button></p>', html=True)
        self.assertContains(response, "database: 'Initial database'")
        self.assertContains(response, 'navigator.clipboard.writeText')
        self.assertContains(response, "Object.keys(labels)")
        self.assertContains(response, ".text(labels[key] + ': ')")
        self.assertNotContains(response, ".text(key + ': ')")

    def test_unset_limits_and_connection_values_render_words(self):
        with mock.patch.object(coast, 'database_get', return_value=dict(
                ITEM, cpu_limit=None, memory_limit_mb=None, internal_host=None,
                port=None, internal_url=None)):
            response = self.client.get(reverse(views.NS + 'detail',
                                               args=['db1']))
        self.assertContains(response, '<dd>No limit</dd>', count=2, html=True)
        self.assertContains(response, '<code>Unavailable</code>', count=5,
                            html=True)
        self.assertNotContains(response, '—')
        with mock.patch.object(coast, 'database_get', return_value=dict(
                ITEM, cpu_limit=2, memory_limit_mb=512)):
            response = self.client.get(reverse(views.NS + 'detail',
                                               args=['db1']))
        self.assertContains(response, '<dd>2</dd>', html=True)
        self.assertContains(response, '<dd>512</dd>', html=True)

    @mock.patch.object(coast, 'database_delete')
    def test_successful_typed_delete_and_warning(self, delete):
        url = reverse(views.NS + 'delete', args=['db1'])
        response = self.client.get(url)
        self.assertContains(response, 'Delete database')
        self.assertContains(
            response, 'permanently removes its data and backups')
        self.assertContains(response, 'Coast name')
        self.assertContains(response, '<strong>orders</strong>')
        with mock.patch.object(forms.common, 'project_member',
                               return_value=True):
            response = self.client.post(url, {'confirmation': ITEM['name']})
        self.assertRedirects(response, reverse(views.NS + 'index'),
                             fetch_redirect_response=False)
        delete.assert_called_once_with(mock.ANY, ITEM['id'])

    @mock.patch.object(coast, 'database_list')
    @mock.patch.object(coast, 'service_list', return_value=[])
    def test_populated_related_database_tabs(self, services, databases):
        databases.return_value = [dict(
            ITEM, appgroup_id='a1', environment_id='e1', stack_id='s1',
            status='ERROR', fault='Database could not start.')]
        for panel, getter, parent, filter_key in (
                ('appgroups', 'appgroup_get', APPGROUPS[0], 'appgroup_id'),
                ('environments', 'environment_get', ENVIRONMENTS[0],
                 'environment_id')):
            with mock.patch.object(coast, getter, return_value=parent):
                response = self.client.get(reverse(
                    'horizon:project:coast.' + panel + ':detail',
                    args=[parent['id']]),
                    {'tab': panel[:-1] + '_details__databases'})
            self.assertEqual(200, response.status_code)
            self.assertContains(response, 'orders')
            self.assertContains(response, 'Production')
            if panel == 'environments':
                self.assertContains(response, '>App</a>')
            else:
                table = response.context['tab_group'].get_tab(
                    'databases')._tables['databases']
                self.assertEqual(['name', 'status', 'actions'],
                                 list(table.columns))
            self.assertContains(response,
                                'title="Database could not start."')
            databases.assert_called_with(
                mock.ANY, **{filter_key: parent['id']})

    def test_database_pages_have_no_forbidden_customer_text(self):
        urls = [reverse(views.NS + name) for name in ('index', 'engines')]
        urls += [reverse(views.NS + 'create') + '?engine=' + ENGINE['engine']]
        urls += [reverse(views.NS + name, args=['db1'])
                 for name in ('detail', 'delete')]
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(200, response.status_code)
            html = response.content.decode().casefold()
            for forbidden in ('coolify', 'traefik'):
                self.assertNotIn(forbidden, html)

    @mock.patch.object(coast, 'database_action')
    def test_state_actions_post_to_database_api(self, action):
        from coast_dashboard.content.databases import tables
        with mock.patch.object(tables.common, 'project_member',
                               return_value=True):
            table = tables.DatabasesTable(self.request, data=[ITEM])
            self.assertTrue(tables.Stop().allowed(self.request, ITEM))
            self.assertFalse(tables.Start().allowed(self.request, ITEM))
            self.assertFalse(tables.Stop().allowed(
                self.request, dict(ITEM, task_owner='other')))
            with mock.patch.object(tables.messages, 'success'):
                tables.Restart().single(table, self.request, ITEM['id'])
        action.assert_called_once_with(self.request, ITEM['id'], 'restart')
        with mock.patch.object(tables.common, 'project_member',
                               return_value=False):
            self.assertFalse(tables.Stop().allowed(self.request, ITEM))

    @mock.patch.object(coast, 'database_logs')
    def test_logs_fragment_uses_shared_box(self, logs):
        logs.return_value = {'lines': [{
            'ts': '2026-10-23T12:00:00Z', 'stream': 'stdout',
            'line': 'database startup complete'}]}
        response = self.client.get(reverse(
            views.NS + 'logs_fragment', args=[ITEM['id']]))
        self.assertEqual(200, response.status_code)
        logs.assert_called_once_with(mock.ANY, ITEM['id'], tail=200)
        self.assertContains(response, 'database startup complete')
        self.assertContains(response, '2026-10-23T12:00:00Z stdout')
        self.assertNotContains(response, 'No log lines yet.')
        self.assertTemplateUsed(
            response, 'project/coast_services/_log_box.html')

    @mock.patch.object(coast, 'database_logs')
    def test_logs_tab_uses_database_fragment(self, logs):
        logs.return_value = {'lines': [{
            'ts': '2026-10-23T12:00:00Z', 'stream': 'stdout',
            'line': 'database ready for connections'}]}
        response = self.client.get(reverse(
            views.NS + 'detail', args=[ITEM['id']]),
            {'tab': 'database_details__logs'})
        self.assertTemplateUsed(response,
                                'project/coast_services/logs_tab.html')
        self.assertContains(response, 'data-fragment-url="%s"' % reverse(
            views.NS + 'logs_fragment', args=[ITEM['id']]))
        self.assertContains(response, 'database ready for connections')
        self.assertContains(response, 'Last 200 runtime log lines.')
        self.assertContains(response, 'Refresh')
        logs.assert_called_once_with(mock.ANY, ITEM['id'], tail=200)

    @mock.patch.object(coast, 'database_logs')
    def test_logs_unavailable_in_tab_and_fragment(self, logs):
        logs.return_value = {'unavailable': 'Database is restarting.'}
        for name, query in (('logs_fragment', {}),
                            ('detail', {'tab': 'database_details__logs'})):
            with self.subTest(view=name):
                logs.reset_mock()
                response = self.client.get(reverse(
                    views.NS + name, args=[ITEM['id']]), query)
                self.assertContains(response, 'Database is restarting.')
                self.assertContains(response, 'coast-log-error')
                self.assertNotContains(response, 'No log lines yet.')
                self.assertNotContains(response, '<pre class="coast-log-box"')
                logs.assert_called_once_with(mock.ANY, ITEM['id'], tail=200)

    @mock.patch.object(coast, 'database_update')
    def test_public_access_validation_and_payload(self, update):
        data = {'enabled': True, 'port': '', 'allow_from': 'specific',
                'source': '192.0.2.0/24'}
        form = forms.PublicAccess(self.request, data, item=ITEM)
        self.assertTrue(form.is_valid(), form.errors)
        with mock.patch.object(views.common, 'project_member',
                               return_value=True):
            self.assertTrue(form.handle(self.request, form.cleaned_data))
        update.assert_called_once_with(
            self.request, ITEM['id'], public={
                'enabled': True, 'port': None, 'source': '192.0.2.0/24'})
        for source in ('::/0', 'not-a-range'):
            form = forms.PublicAccess(
                self.request, dict(data, source=source), item=ITEM)
            self.assertFalse(form.is_valid())
        form = forms.PublicAccess(
            self.request, dict(data, port=80), item=ITEM)
        self.assertFalse(form.is_valid())

    def test_database_backup_policy_derives_engine_and_container(self):
        from coast_dashboard.content.services import backups
        form = backups.DatabasePolicyForm({
            'schedule': 'daily', 'time': '02:00',
            'keep_daily': 14, 'keep_weekly': 8})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertNotIn('engine', form.policy())
        self.assertNotIn('container', form.policy())

    @mock.patch.object(coast, 'database_backup_create')
    def test_direct_backup_url_rejects_unsupported_engine(self, create):
        response = self.client.post(reverse(
            views.NS + 'backups', args=[ITEM['id']]), {'operation': 'create'})
        self.assertIn(response.status_code, (403, 404))
        create.assert_not_called()

    @mock.patch.object(coast, '_get')
    def test_logs_api_microversion_and_filters(self, get):
        lines = {'lines': [{'ts': '2026-10-23T12:00:00Z',
                            'stream': 'stdout', 'line': 'database ready'}]}
        get.return_value = {'logs': lines}
        self.assertEqual(lines, coast.database_logs(
            self.request, ITEM['id'], tail=20, since='2026-10-23T12:00:00Z'))
        self.assertEqual(coast.DATABASE_VERSION,
                         get.call_args.kwargs['microversion'])
        self.assertIn('/databases/db1/logs?tail=20&since=',
                      get.call_args.args[1])

    @mock.patch.object(coast, 'database_backup_policy_get', return_value={
        'enabled': False, 'hour': 2, 'minute': 0,
        'keep_daily': 14, 'keep_weekly': 8})
    @mock.patch.object(coast, 'database_backup_list', return_value=[])
    def test_database_backups_reuse_policy_and_history(self, listing, policy):
        coast.database_engine_list.return_value = [dict(ENGINE, backups=True)]
        response = self.client.get(reverse(
            views.NS + 'detail', args=[ITEM['id']]),
            {'tab': 'database_details__backups'})
        self.assertEqual(200, response.status_code)
        self.assertContains(response, 'Back up now')
        self.assertNotContains(response, 'Database container')
        self.assertNotContains(response, 'Select a database engine')
        listing.assert_called_once_with(mock.ANY, ITEM['id'])
        policy.assert_called_once_with(mock.ANY, ITEM['id'])

    @mock.patch.object(coast, 'database_backup_create')
    @mock.patch.object(coast, 'database_backup_policy_get', return_value={})
    def test_database_backup_create_without_container(self, policy, create):
        coast.database_engine_list.return_value = [dict(ENGINE, backups=True)]
        with mock.patch.object(views.common, 'project_member',
                               return_value=True):
            response = self.client.post(reverse(
                views.NS + 'backups', args=[ITEM['id']]),
                {'operation': 'create'})
        self.assertEqual(302, response.status_code)
        create.assert_called_once_with(mock.ANY, ITEM['id'])
        self.assertIn('database_details__backups', response.url)

    @mock.patch.object(coast, 'backup_get', return_value={
        'id': 'backup1', 'service_id': 'someone-else', 'status': 'ACTIVE'})
    @mock.patch.object(coast, 'backup_download')
    def test_backup_download_checks_database_ownership(self, download, get):
        coast.database_engine_list.return_value = [dict(ENGINE, backups=True)]
        with mock.patch.object(views.common, 'project_member',
                               return_value=True):
            response = self.client.get(reverse(
                views.NS + 'backup_download', args=[ITEM['id'], 'backup1']))
        self.assertEqual(404, response.status_code)
        download.assert_not_called()

    @mock.patch.object(coast, 'database_action', side_effect=coast.CoastError(
        'Database is busy: task_owner=backup.', 409))
    @mock.patch.object(coast, 'database_list', return_value=[ITEM])
    def test_busy_conflict_message_is_visible(self, listing, action):
        with mock.patch.object(views.common, 'project_member',
                               return_value=True):
            response = self.client.post(reverse(views.NS + 'index'), {
                'action': 'databases__restart__' + ITEM['id']})
        self.assertEqual(200, response.status_code)
        self.assertContains(response, 'Database is busy: task_owner=backup.')

    @mock.patch.object(coast, 'stack_get',
                       return_value={'network_id': 'network1'})
    def test_stack_only_public_source(self, stack):
        from openstack_dashboard.api import neutron
        with mock.patch.object(neutron, 'subnet_list', return_value=[mock.Mock(
                cidr='192.0.2.0/24')]):
            form = forms.PublicAccess(self.request, {
                'enabled': True, 'allow_from': 'stack', 'port': ''},
                item=dict(ITEM, stack_id='s1'))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual('192.0.2.0/24', form.values(
            form.cleaned_data)['public']['source'])

    def test_edit_modals_render_over_ajax(self):
        for name in ('public_access', 'limits'):
            response = self.client.get(reverse(
                views.NS + name, args=[ITEM['id']]),
                HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(200, response.status_code)
            self.assertContains(response, 'modal')
        response = self.client.get(reverse(
            views.NS + 'public_access', args=[ITEM['id']]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertContains(response, 'data-stack-source')
        self.assertContains(response, 'Specific IPv4 range')

    def database_post(self, name, data, backup=False, member=True):
        args = [ITEM['id'], 'backup1'] if backup else [ITEM['id']]
        with mock.patch.object(views.common, 'project_member',
                               return_value=member):
            return self.client.post(reverse(views.NS + name, args=args), data)

    def assert_database_api_call(self, adapter, path, method, body=None,
                                 stream=False):
        kwargs = {'microversion': '1.29', 'log': False,
                  'connect_retries': 0, 'status_code_retries': 0}
        if body is not None:
            kwargs['json'] = body
        if stream:
            kwargs['stream'] = True
        adapter.assert_any_call(path, method, **kwargs)

    @mock.patch.object(coast, 'coastclient')
    def test_limits_numeric_and_clearing_patch_contract(self, client):
        adapter = client.return_value.adapter.request
        adapter.return_value = _resp({})
        for data, expected in (
                ({'cpu_limit': '1.5', 'memory_limit_mb': '512'},
                 {'cpu_limit': 1.5, 'memory_limit_mb': 512}),
                ({'cpu_limit': '', 'memory_limit_mb': ''},
                 {'cpu_limit': None, 'memory_limit_mb': None})):
            with self.subTest(data=data):
                adapter.reset_mock()
                response = self.database_post('limits', data)
                self.assertRedirects(response, reverse(
                    views.NS + 'detail', args=[ITEM['id']]),
                    fetch_redirect_response=False)
                self.assert_database_api_call(
                    adapter, '/databases/db1', 'PATCH', {'database': expected})
                self.assertEqual(1, adapter.call_count)

    @mock.patch.object(coast, 'coastclient')
    def test_limits_invalid_values_do_not_patch(self, client):
        for data in ({'cpu_limit': '0'}, {'cpu_limit': '-1'},
                     {'cpu_limit': 'not-a-number'},
                     {'memory_limit_mb': '0'}, {'memory_limit_mb': '-1'},
                     {'memory_limit_mb': '1.5'}):
            with self.subTest(data=data):
                response = self.database_post('limits', data)
                self.assertEqual(200, response.status_code)
                self.assertTrue(response.context['form'].errors)
        client.assert_not_called()

    @mock.patch.object(coast, 'coastclient')
    def test_reader_cannot_patch_limits(self, client):
        response = self.database_post('limits', {
            'cpu_limit': '1', 'memory_limit_mb': '512'}, member=False)
        self.assertEqual(200, response.status_code)
        self.assertContains(response, 'Permission denied.')
        client.assert_not_called()

    def test_restart_required_banner_and_firewall_label(self):
        coast.database_get.return_value = dict(
            ITEM, restart_required=True, stack_id='s1')
        url = reverse(views.NS + 'detail', args=[ITEM['id']])
        response = self.client.get(url)
        self.assertContains(
            response, 'Restart needed to apply resource limits.')
        self.assertContains(response, 'Stack firewall')
        self.assertNotContains(response, 'Stack Firewall')
        coast.database_get.return_value = dict(ITEM, restart_required=False)
        self.assertNotContains(self.client.get(url),
                               'Restart needed to apply resource limits.')

    @mock.patch.object(coast, 'database_backup_policy_get', return_value={
        'enabled': False, 'hour': 2, 'minute': 0,
        'keep_daily': 14, 'keep_weekly': 8})
    @mock.patch.object(coast, 'database_backup_list')
    def test_incomplete_backup_rows_render_plain_text(self, listing, policy):
        coast.database_engine_list.return_value = [dict(ENGINE, backups=True)]
        listing.return_value = [
            {'id': 'backup1', 'status': 'ERROR', 'kind': 'manual'},
            {'id': 'backup2', 'status': 'ERROR', 'kind': 'manual',
             'started_at': None, 'size_bytes': None,
             'duration_seconds': None, 'error': ''}]
        response = self.client.get(reverse(
            views.NS + 'detail', args=[ITEM['id']]),
            {'tab': 'database_details__backups'})
        self.assertContains(response, 'Not available', count=6)
        self.assertContains(response, '<td>None</td>', count=2, html=True)
        self.assertNotContains(response, '\u2014')

    @mock.patch.object(coast, 'coastclient')
    def test_database_backup_policy_save_contract(self, client):
        coast.database_engine_list.return_value = [dict(ENGINE, backups=True)]
        adapter = client.return_value.adapter.request
        adapter.return_value = _resp({})
        response = self.database_post('backups', {
            'operation': 'save', 'schedule': 'daily', 'time': '03:15',
            'keep_daily': '7', 'keep_weekly': '4'})
        self.assertEqual(302, response.status_code)
        self.assertIn('database_details__backups', response.url)
        self.assert_database_api_call(
            adapter, '/databases/db1/backup_policy', 'PUT', {
                'backup_policy': {'enabled': True, 'hour': 3, 'minute': 15,
                                  'keep_daily': 7, 'keep_weekly': 4}})
        self.assertEqual(1, adapter.call_count)

    def backup_adapter(self, client):
        coast.database_engine_list.return_value = [dict(ENGINE, backups=True)]
        adapter = client.return_value.adapter.request
        adapter.return_value = _resp({'backup': {
            'id': 'backup1', 'service_id': ITEM['id'], 'status': 'ACTIVE'}})
        return adapter

    @mock.patch.object(coast, 'coastclient')
    def test_database_backup_restore_modes_contract(self, client):
        adapter = self.backup_adapter(client)
        for data, expected in (
                ({'mode': 'new_copy', 'name': 'orders-copy'},
                 {'mode': 'new_copy', 'name': 'orders-copy'}),
                ({'mode': 'overwrite', 'name': 'ignored',
                  'confirmation': ITEM['name']},
                 {'mode': 'overwrite', 'confirmation': ITEM['name']})):
            with self.subTest(mode=data['mode']):
                adapter.reset_mock()
                response = self.database_post('backup_restore', data,
                                              backup=True)
                self.assertEqual(302, response.status_code)
                self.assertIn('database_details__backups', response.url)
                self.assert_database_api_call(
                    adapter, '/backups/backup1', 'GET')
                self.assert_database_api_call(
                    adapter, '/backups/backup1/restore', 'POST', expected)
                self.assertEqual(2, adapter.call_count)

    @mock.patch.object(coast, 'coastclient')
    def test_database_backup_restore_requires_exact_confirmation(self, client):
        adapter = self.backup_adapter(client)
        for confirmation in ('', 'Orders', ' orders '):
            with self.subTest(confirmation=confirmation):
                adapter.reset_mock()
                response = self.database_post('backup_restore', {
                    'mode': 'overwrite', 'confirmation': confirmation},
                    backup=True)
                self.assertEqual(200, response.status_code)
                self.assertIn('confirmation', response.context['form'].errors)
                self.assert_database_api_call(
                    adapter, '/backups/backup1', 'GET')
                self.assertEqual(1, adapter.call_count)

    @mock.patch.object(coast, 'coastclient')
    def test_database_backup_delete_confirmation_and_contract(self, client):
        adapter = self.backup_adapter(client)
        response = self.database_post('backup_delete', {}, backup=True)
        self.assertEqual(200, response.status_code)
        self.assertIn('confirm', response.context['form'].errors)
        self.assertEqual(1, adapter.call_count)
        adapter.reset_mock()
        response = self.database_post('backup_delete', {'confirm': 'on'},
                                      backup=True)
        self.assertEqual(302, response.status_code)
        self.assertIn('database_details__backups', response.url)
        self.assert_database_api_call(adapter, '/backups/backup1', 'GET')
        self.assert_database_api_call(adapter, '/backups/backup1', 'DELETE')
        self.assertEqual(2, adapter.call_count)

    @mock.patch.object(coast, 'coastclient')
    def test_database_backup_download_stream_and_contract(self, client):
        adapter = self.backup_adapter(client)
        upstream = _resp({})
        upstream.iter_content.return_value = iter([b'first', b'second'])
        adapter.side_effect = [adapter.return_value, upstream]
        with mock.patch.object(views.common, 'project_member',
                               return_value=True):
            response = self.client.get(reverse(
                views.NS + 'backup_download', args=[ITEM['id'], 'backup1']))
        self.assertEqual(200, response.status_code)
        self.assertTrue(response.streaming)
        self.assertEqual(b'firstsecond', b''.join(response.streaming_content))
        self.assertEqual('no-store', response['Cache-Control'])
        self.assertEqual('attachment; filename="backup1.dump.gz"',
                         response['Content-Disposition'])
        self.assert_database_api_call(adapter, '/backups/backup1', 'GET')
        self.assert_database_api_call(adapter, '/backups/backup1/download',
                                      'GET', stream=True)
        self.assertEqual(2, adapter.call_count)
        upstream.iter_content.assert_called_once_with(chunk_size=65536)
        upstream.close.assert_called_once_with()

    def database_transport(self):
        transport = session.Session()
        client = mock.Mock(adapter=adapter.Adapter(
            session=transport, endpoint_override='http://coast.test/v1',
            service_type='app-hosting'))
        response = requests.Response()
        response.status_code = 202
        response._content = b'{}'
        response.headers['Content-Type'] = 'application/json'
        sender = mock.patch.object(transport.session, 'send',
                                   return_value=response)
        client_patch = mock.patch.object(coast, 'coastclient',
                                         return_value=client)
        send = sender.start()
        client_patch.start()
        self.addCleanup(sender.stop)
        self.addCleanup(client_patch.stop)
        return send, response

    def assert_database_http(self, send, method, path, body):
        send.assert_called_once()
        request = send.call_args.args[0]
        self.assertEqual(method, request.method)
        self.assertEqual('http://coast.test/v1' + path, request.url)
        self.assertEqual(body, json.loads(request.body))
        self.assertEqual('app-hosting 1.29',
                         request.headers['OpenStack-API-Version'])

    def test_state_actions_through_index_http_contract(self):
        send, upstream = self.database_transport()
        for state, offered in (('STOPPED', ('start',)),
                               ('ACTIVE', ('stop', 'restart')),
                               ('DELETING', ()), ('ERROR', ())):
            coast.database_list.return_value = [dict(ITEM, status=state)]
            coast.database_get.return_value = dict(ITEM, status=state)
            for operation in ('start', 'stop', 'restart'):
                with self.subTest(state=state, operation=operation), \
                        mock.patch.object(views.common, 'project_member',
                                          return_value=True):
                    send.reset_mock()
                    url = reverse(views.NS + 'index')
                    page = self.client.get(url)
                    marker = 'databases__' + operation + '__db1'
                    if operation in offered:
                        self.assertContains(page, marker)
                    else:
                        self.assertNotContains(page, marker)
                    detail = self.client.get(reverse(
                        views.NS + 'detail', args=['db1']))
                    if operation in offered:
                        self.assertContains(detail, marker)
                    else:
                        self.assertNotContains(detail, marker)
                    response = self.client.post(url, {'action': marker})
                    self.assertIn(response.status_code, (200, 302))
                    if operation in offered:
                        self.assert_database_http(
                            send, 'POST', '/databases/db1/action',
                            {operation: {}})
                    else:
                        send.assert_not_called()

    def test_action_http_conflict_is_readable(self):
        send, upstream = self.database_transport()
        upstream.status_code = 409
        upstream._content = json.dumps({
            'detail': 'Database is busy: task_owner=backup.'}).encode()
        coast.database_list.return_value = [ITEM]
        with mock.patch.object(views.common, 'project_member',
                               return_value=True):
            response = self.client.post(reverse(views.NS + 'index'), {
                'action': 'databases__restart__db1'})
        self.assertContains(response, 'Database is busy: task_owner=backup.')
        self.assert_database_http(send, 'POST', '/databases/db1/action',
                                  {'restart': {}})

    def test_public_access_default_enable_and_disable_http(self):
        send, upstream = self.database_transport()
        url = reverse(views.NS + 'public_access', args=['db1'])
        response = self.client.get(url)
        self.assertEqual('anywhere',
                         response.context['form']['allow_from'].value())
        self.assertContains(response, 'Anywhere (0.0.0.0/0)')
        self.assertContains(response,
                            'Anywhere allows connections from the entire')
        self.assertContains(response, 'IPv4 only.')
        for data, expected in (
                ({'enabled': 'on', 'allow_from': 'anywhere', 'port': ''},
                 {'enabled': True, 'port': None, 'source': '0.0.0.0/0'}),
                ({'allow_from': 'anywhere', 'port': '15432'},
                 {'enabled': False})):
            with self.subTest(data=data):
                send.reset_mock()
                response = self.database_post('public_access', data)
                self.assertEqual(302, response.status_code)
                self.assert_database_http(send, 'PATCH', '/databases/db1',
                                          {'database': {'public': expected}})

    def test_overview_public_and_private_connections(self):
        public_url = 'database://app@203.0.113.5:15432/app'
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                coast.database_get.return_value = dict(
                    ITEM, public={'enabled': enabled, 'host': '203.0.113.5',
                                  'private_host': '192.0.2.5', 'port': 15432},
                    public_url=public_url)
                response = self.client.get(reverse(
                    views.NS + 'detail', args=['db1']))
                self.assertContains(response, ITEM['internal_url'])
                if enabled:
                    self.assertContains(response, '203.0.113.5:15432')
                    self.assertContains(response, public_url)
                else:
                    self.assertNotContains(response, '203.0.113.5:15432')
                    self.assertNotContains(response, public_url)
                    self.assertNotContains(response, 'Public endpoint')
