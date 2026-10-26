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

from django.contrib.messages.storage.fallback import FallbackStorage
from django.urls import reverse

from coast_dashboard.api import coast
from coast_dashboard.content.oneclick import forms
from coast_dashboard.tests import helpers
from coast_dashboard.tests.test_api import _resp
from coast_dashboard.tests.test_forms import APPGROUPS
from coast_dashboard.tests.test_forms import ENVIRONMENTS
from coast_dashboard.tests.test_forms import SERVERS


TEMPLATE = {'id': 'postgresql', 'name': 'PostgreSQL',
            'description': 'Database'}
DATA = {'name': 'database', 'template_id': 'postgresql',
        'appgroup_id': 'a1', 'environment_id': 'e1', 'server_id': 'v1'}


class SearchForm(HTMLParser):
    def __init__(self, response):
        super().__init__()
        self.attrs = {}
        self.fields = {}
        self.active = False
        self.feed(response.content.decode())

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self.active = attrs.get('id') == 'template-search-form'
            if self.active:
                self.attrs = attrs
        if tag == 'input' and self.active and 'name' in attrs:
            self.fields[attrs['name']] = attrs.get('value', '')

    def handle_endtag(self, tag):
        if tag == 'form':
            self.active = False


class OneClickTests(helpers.TestCase):
    def setUp(self):
        super().setUp()
        self.request._messages = FallbackStorage(self.request)
        for name, value in [('appgroup_list', APPGROUPS),
                            ('environment_list', ENVIRONMENTS),
                            ('stack_server_list', SERVERS),
                            ('stack_list', [{'id': 's1'}, {'id': 's2'}]),
                            ('template_list', [TEMPLATE]),
                            ('service_list', [])]:
            patcher = mock.patch.object(coast, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.url = reverse('horizon:project:coast.services:create')
        self.index = reverse('horizon:project:coast.services:index')

    @mock.patch.object(coast, 'database_engine_list')
    def test_services_exclude_standalone_engines(self, engines):
        bundled = dict(TEMPLATE, id='app-with-postgresql',
                       name='App with PostgreSQL')
        with mock.patch.object(coast, 'template_list', return_value=[bundled]):
            catalog = self.client.get(self.index)
            self.assertContains(catalog, bundled['name'])
            self.assertContains(catalog,
                                self.url + '?template_id=' + bundled['id'])
            modal = self.client.get(
                self.url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        for page in (catalog, modal):
            self.assertNotContains(page, 'Create database')
            self.assertNotContains(page, 'fa-database')
            self.assertNotContains(page, 'A database for apps on your server.')
        engines.assert_not_called()

    def test_create_service_field_order(self):
        form = forms.CreateOneClick(self.request)
        self.assertEqual([
            'name', 'template_id', 'appgroup_id', 'environment_id',
            'server_id', 'health_check', 'health_check_port',
            'healthcheck_path'], list(form.fields))

    @mock.patch.object(coast, 'coastclient')
    def test_template_with_ports_http_probe(self, client):
        client.return_value.request.return_value = _resp(
            {'service': {'id': 'svc'}})
        with mock.patch.object(coast, 'template_list', return_value=[
                dict(TEMPLATE, ports='80')]):
            form = forms.CreateOneClick(self.request, data=dict(
                DATA, health_check='http', health_check_port='80',
                healthcheck_path='/ready'))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual({'id': 'svc'}, form.handle(
            self.request, form.cleaned_data))
        call = client.return_value.request.call_args.kwargs
        self.assertEqual('1.4', call['health_check_microversion'])
        self.assertEqual('http', call['json']['service']['health_check'])
        self.assertEqual(80, call['json']['service']['health_check_port'])
        self.assertEqual('/ready', call['json']['service']['healthcheck_path'])

    def test_mixed_catalog_no_port_template_ignores_probe(self):
        with mock.patch.object(coast, 'template_list', return_value=[
                TEMPLATE, dict(TEMPLATE, id='web', ports='80')]):
            form = forms.CreateOneClick(self.request, data=dict(
                DATA, health_check='http', health_check_port='invalid',
                healthcheck_path='invalid'))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertNotIn('health_check', form.cleaned_data)

    def test_template_http_health_defaults(self):
        for extra, expected in (
                ({'http_port': 8080}, ('http', 8080, '/')),
                ({'http_port': None}, ('none', '', '')),
                ({}, ('none', '', ''))):
            with self.subTest(extra=extra), mock.patch.object(
                    coast, 'template_list', return_value=[
                        dict(TEMPLATE, ports=[3001, 3002], **extra)]):
                form = forms.CreateOneClick(
                    self.request, initial={'template_id': 'postgresql'})
                self.assertEqual(extra.get('http_port'),
                                 form.defaults['http_ports']['postgresql'])
                self.assertEqual(expected, tuple(form[key].value() for key in
                                 ('health_check', 'health_check_port',
                                  'healthcheck_path')))
                blank = forms.CreateOneClick(self.request)
                self.assertEqual('none', blank['health_check'].value())
                self.assertEqual('', blank['health_check_port'].value())
                self.assertEqual('', blank['healthcheck_path'].value())

    def test_http_port_without_catalog_ports(self):
        with mock.patch.object(coast, 'template_list', return_value=[
                dict(TEMPLATE, http_port=8080)]):
            form = forms.CreateOneClick(self.request, data=dict(
                DATA, health_check='http', health_check_port='8080',
                healthcheck_path='/'))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual('http', form.cleaned_data['health_check'])
        self.assertEqual(8080, form.cleaned_data['health_check_port'])

    @mock.patch.object(coast, 'coastclient')
    def test_template_port_preserves_edits_and_clear(self, client):
        client.return_value.request.return_value = _resp(
            {'service': {'id': 'svc'}})
        for value in ('', '9000'):
            with self.subTest(port=value), mock.patch.object(
                    coast, 'template_list', return_value=[
                        dict(TEMPLATE, ports=[3001], http_port=3001)]):
                form = forms.CreateOneClick(
                    self.request, initial={'template_id': 'postgresql'},
                    data=dict(DATA, health_check='http',
                              health_check_port=value))
                self.assertEqual(value, form['health_check_port'].value())
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual({'id': 'svc'}, form.handle(
                    self.request, form.cleaned_data))
                payload = client.return_value.request.call_args.kwargs[
                    'json']['service']
                if value:
                    self.assertEqual(9000, payload['health_check_port'])
                else:
                    self.assertNotIn('health_check_port', payload)

    def test_template_without_ports_ignores_probe_fields(self):
        form = forms.CreateOneClick(self.request, data=DATA)
        self.assertEqual('none', form.fields['health_check'].initial)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertNotIn('health_check', form.cleaned_data)

    @mock.patch.object(coast, 'oneclick_create', return_value={'id': 'svc'})
    def test_create_form(self, create):
        form = forms.CreateOneClick(self.request, data=DATA)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual({'id': 'svc'},
                         form.handle(self.request, form.cleaned_data))
        create.assert_called_once_with(self.request, **DATA)

    @mock.patch.object(coast, 'oneclick_create')
    def test_invalid_choices(self, create):
        for field, value in [('server_id', ''), ('server_id', 'control'),
                             ('server_id', 'v2'), ('environment_id', 'e2'),
                             ('template_id', ''), ('template_id', 'hidden'),
                             ('appgroup_id', 'unknown'), ('name', 'Bad Name')]:
            with self.subTest(field=field, value=value):
                form = forms.CreateOneClick(
                    self.request, data=dict(DATA, **{field: value}))
                self.assertFalse(form.is_valid())
                self.assertIn(field, form.errors)
        create.assert_not_called()

    def test_inactive_choices(self):
        for method, rows, field in [
                ('appgroup_list', APPGROUPS, 'appgroup_id'),
                ('environment_list', ENVIRONMENTS, 'environment_id'),
                ('stack_server_list', SERVERS, 'server_id')]:
            with self.subTest(field=field), mock.patch.object(
                    coast, method, return_value=[
                        dict(row, status='PENDING') for row in rows]):
                form = forms.CreateOneClick(self.request, data=DATA)
                self.assertFalse(form.is_valid())
                self.assertIn(field, form.errors)

    def test_catalog_is_stack_scoped(self):
        with mock.patch.object(coast, 'template_list',
                               side_effect=[[], [TEMPLATE]]) as catalog:
            form = forms.CreateOneClick(self.request, data=DATA)
        self.assertFalse(form.is_valid())
        self.assertIn('template_id', form.errors)
        self.assertEqual([mock.call(self.request, 's1'),
                          mock.call(self.request, 's2')],
                         catalog.call_args_list)

    def test_catalog_failure(self):
        with mock.patch.object(
                coast, 'template_list',
                side_effect=RuntimeError('catalog-sensitive-detail')):
            form = forms.CreateOneClick(self.request, data=DATA)
            self.assertFalse(form.is_valid())
            self.assertIn('template_id', form.errors)
            result = self.client.get(self.index)
        self.assertContains(result, 'Unable to retrieve templates.')
        self.assertNotContains(result, 'catalog-sensitive-detail')

    @mock.patch.object(coast, 'oneclick_create',
                       side_effect=RuntimeError('catalog-sensitive-detail'))
    def test_create_failure(self, create):
        form = forms.CreateOneClick(self.request, data=DATA)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertFalse(form.handle(self.request, form.cleaned_data))
        self.assertIn('Unable to create service.', str(form.errors))
        self.assertNotIn('catalog-sensitive-detail', str(form.errors))

    @mock.patch.object(coast, 'oneclick_create')
    def test_get_preselects_template(self, create):
        result = self.client.get(self.url, {'template_id': 'postgresql'})
        self.assertEqual(200, result.status_code)
        self.assertEqual('postgresql',
                         result.context['form'].initial['template_id'])
        create.assert_not_called()

    @mock.patch.object(coast, 'oneclick_create', return_value={'id': 'svc'})
    def test_post(self, create):
        result = self.client.post(self.url, DATA)
        self.assertRedirects(result, self.index, fetch_redirect_response=False)
        create.assert_called_once_with(mock.ANY, **DATA)

    @mock.patch.object(coast, 'oneclick_create', return_value={
        'id': 'svc', 'deployment_id': 'dep'})
    def test_post_opens_deployment(self, create):
        result = self.client.post(self.url, DATA)
        self.assertRedirects(
            result, reverse('horizon:project:coast.apps:deployment',
                            args=['svc', 'dep']),
            fetch_redirect_response=False)

    @mock.patch.object(coast, 'oneclick_create')
    def test_invalid_post(self, create):
        result = self.client.post(self.url, dict(DATA, server_id=''))
        self.assertEqual(200, result.status_code)
        self.assertIn('server_id', result.context['form'].errors)
        create.assert_not_called()

    def test_catalog_deploy_links(self):
        result = self.client.get(self.index)
        self.assertContains(result, self.url + '?template_id=postgresql')
        self.assertContains(result, 'PostgreSQL')
        self.assertContains(result, 'Create Service')

    def test_catalog_fetches_once_per_version_and_deduplicates_ids(self):
        stacks = [{'id': 's1', 'engine_version': '1'},
                  {'id': 's2', 'engine_version': '1'},
                  {'id': 's3', 'engine_version': '2'}]
        with mock.patch.object(coast, 'stack_list', return_value=stacks), \
                mock.patch.object(coast, 'template_list', side_effect=[
                    [TEMPLATE], [TEMPLATE, dict(TEMPLATE, id='redis',
                                                name='Redis')]]) as catalog:
            response = self.client.get(self.index)
        self.assertEqual(['postgresql', 'redis'], [row['id'] for row in
                         response.context['templates_table'].data])
        self.assertEqual(
            ['s1', 's3'], [call.args[1] for call in catalog.call_args_list])
        self.assertNotIn('stack_name',
                         response.context['templates_table'].columns)

    def test_catalog_pagination_search_and_deploy(self):
        items = [dict(TEMPLATE, id='db-%03d' % i, name='DB %03d' % i,
                      category='Database') for i in range(105)]
        items.append(dict(TEMPLATE, id='other', name='Other',
                          category='Tools', description='Tooling'))
        with mock.patch.object(coast, 'template_list', return_value=items):
            first = self.client.get(self.index, {
                'q': 'DATABASE', 'appgroup': 'a1'})
            second = self.client.get(
                self.index + first.context['templates_next_url'])
            last = self.client.get(self.index, {
                'q': 'database', 'templates_page': '3'})
            named = self.client.get(self.index, {'q': 'db 102'})
            empty = self.client.get(self.index, {'q': 'missing'})
        self.assertEqual(50, len(first.context['templates_table'].data))
        self.assertEqual('db-050',
                         second.context['templates_table'].data[0]['id'])
        self.assertEqual(5, len(last.context['templates_table'].data))
        self.assertIn('appgroup=a1', first.context['templates_next_url'])
        self.assertIn('q=DATABASE',
                      first.context['templates_next_url'])
        self.assertEqual(['db-102'], [row['id'] for row in
                         named.context['templates_table'].data])
        self.assertContains(named, self.url + '?template_id=db-102')
        self.assertEqual([], empty.context['templates_table'].data)
        self.assertNotContains(first, self.url + '?template_id=db-050')

    def test_rendered_search_form_submits_q_and_resets_page(self):
        items = [dict(TEMPLATE, id='router-%03d' % i,
                      name='9router %03d' % i) for i in range(60)]
        items.append(TEMPLATE)
        with mock.patch.object(coast, 'template_list', return_value=items):
            response = self.client.get(self.index, {
                'templates_page': '2', 'appgroup': 'a1'})
            form = SearchForm(response)
            self.assertEqual('get', form.attrs['method'])
            self.assertEqual(self.index, form.attrs['action'])
            self.assertIn('q', form.fields)
            self.assertNotIn('templates_page', form.fields)
            form.fields['q'] = 'postgres'
            filtered = self.client.get(form.attrs['action'], form.fields)
        self.assertEqual(['postgresql'], [row['id'] for row in
                         filtered.context['templates_table'].data])
        self.assertEqual(1, filtered.context['templates_page'].number)
        self.assertNotContains(filtered, '9router')
        self.assertContains(filtered, self.url + '?template_id=postgresql')

    def test_services_use_bulk_state_without_per_row_requests(self):
        rows = [dict(id='svc-%s' % i, name='Service %s' % i,
                     status='STOPPED', current_deployment_id='deployment',
                     appgroup_id='a1', environment_id='e1')
                for i in range(10)]
        with mock.patch.object(coast, 'service_list', return_value=rows), \
                mock.patch.object(coast, 'service_deployment_list') as deps, \
                mock.patch.object(coast, 'service_get') as get:
            response = self.client.get(self.index)
        data = response.context['oneclick_table'].data
        self.assertEqual(10, len(data))
        self.assertTrue(all(row['deployed'] for row in data))
        self.assertTrue(all(row['status'] == 'STOPPED' for row in data))
        deps.assert_not_called()
        get.assert_not_called()
        self.assertNotContains(response, 'ajax-update')
        self.assertContains(response, 'Redeploy')

    def test_server_defaults_are_ready_to_deploy(self):
        with mock.patch.object(coast, 'appgroup_list',
                               return_value=APPGROUPS[:1]), \
                mock.patch.object(coast, 'environment_list',
                                  return_value=ENVIRONMENTS[:1]):
            response = self.client.get(self.url, {'template_id': 'postgresql'})
        initial = response.context['form'].initial
        self.assertEqual(dict(DATA, name='postgresql', health_check='none',
                              health_check_port='', healthcheck_path=''),
                         initial)
        self.assertTrue(all(not field.disabled for field in
                            response.context['form'].fields.values()))

    def test_initial_template_and_name_are_blank(self):
        response = self.client.get(self.url)
        form = response.context['form']
        self.assertEqual('', form['template_id'].value())
        self.assertEqual('', form['name'].value())
        self.assertEqual(('', 'Select a template'),
                         form.fields['template_id'].choices[0])
        for hook in ('data-user-edited="false"', 'input.coastName',
                     'change.coastName', 'shown.bs.modal.coastName'):
            self.assertContains(response, hook)

    def test_preselected_name_is_unique_in_appgroup(self):
        rows = [{'name': 'postgresql', 'appgroup_id': 'a1'},
                {'name': 'postgresql-2', 'appgroup_id': 'a1'},
                {'name': 'postgresql-3', 'appgroup_id': 'a2'}]
        with mock.patch.object(coast, 'service_list', return_value=rows):
            response = self.client.get(self.url, {
                'template_id': 'postgresql', 'appgroup_id': 'a1'})
        form = response.context['form']
        self.assertEqual('postgresql-3', form['name'].value())
        self.assertEqual(rows, form.defaults['names'])
        self.assertContains(response, '"name": "postgresql-2"')

    def test_blank_name_is_field_error(self):
        for value in ('', '   '):
            form = forms.CreateOneClick(
                self.request, data=dict(DATA, name=value))
            self.assertFalse(form.is_valid())
            self.assertIn('name', form.errors)

    def test_name_normalization_and_long_suffix(self):
        self.assertEqual('postgresql', forms.template_name('PostgreSQL'))
        self.assertEqual('my-database', forms.template_name('My Database!'))
        self.assertEqual('service', forms.template_name('!!!'))
        base = forms.template_name('A' * 80)
        value = forms.available_name(base, [base])
        self.assertEqual('a' * 61 + '-2', value)
        self.assertEqual('db-2', forms.available_name('db', ['db', 'db-3']))

    def test_remembers_successful_placement(self):
        data = dict(DATA, appgroup_id='a2', environment_id='e2',
                    server_id='v2')
        with mock.patch.object(coast, 'oneclick_create',
                               return_value={'id': 'svc'}):
            response = self.client.post(self.url, data)
        self.assertEqual(302, response.status_code)
        saved = self.client.session[forms.PLACEMENT_SESSION_KEY]
        self.assertEqual('a2', saved['appgroup_id'])
        response = self.client.get(self.url, {'template_id': 'postgresql'})
        form = response.context['form']
        self.assertEqual(('', 'Select an app group'),
                         form.fields['appgroup_id'].choices[0])
        for field in forms.PLACEMENT_FIELDS:
            self.assertEqual('', form.initial[field])

    def test_single_choices_override_stale_preferences(self):
        self.request.session[forms.PLACEMENT_SESSION_KEY] = {
            'project_id': self.request.user.project_id,
            'appgroup_id': 'a2', 'environment_id': 'e2', 'server_id': 'v2'}
        with mock.patch.object(coast, 'appgroup_list',
                               return_value=APPGROUPS[:1]), \
                mock.patch.object(coast, 'environment_list',
                                  return_value=ENVIRONMENTS[:1]):
            form = forms.CreateOneClick(self.request)
        for field in forms.PLACEMENT_FIELDS:
            self.assertEqual(DATA[field], form.initial[field])

    def test_dependents_preselect_only_when_one_choice(self):
        env = dict(ENVIRONMENTS[0], id='e3', name='Staging')
        worker = dict(SERVERS[0], id='v3', name='extra')
        self.request.session[forms.PLACEMENT_SESSION_KEY] = {
            'project_id': self.request.user.project_id,
            'appgroup_id': 'a1', 'environment_id': 'e3', 'server_id': 'v3'}
        with mock.patch.object(coast, 'appgroup_list',
                               return_value=APPGROUPS[:1]), \
                mock.patch.object(coast, 'environment_list',
                                  return_value=ENVIRONMENTS[:1] + [env]), \
                mock.patch.object(coast, 'stack_server_list',
                                  return_value=SERVERS + [worker]):
            form = forms.CreateOneClick(self.request)
        self.assertEqual('a1', form.initial['appgroup_id'])
        self.assertEqual('', form.initial['environment_id'])
        self.assertEqual('', form.initial['server_id'])

    def test_project_and_template_compatibility(self):
        self.request.session[forms.PLACEMENT_SESSION_KEY] = {
            'project_id': 'other-project', 'appgroup_id': 'a2',
            'environment_id': 'e2', 'server_id': 'v2'}
        form = forms.CreateOneClick(self.request)
        self.assertEqual('', form.initial['appgroup_id'])
        with mock.patch.object(coast, 'template_list',
                               side_effect=[[], [TEMPLATE]]):
            form = forms.CreateOneClick(
                self.request, initial={'template_id': 'postgresql'})
        self.assertEqual('a2', form.initial['appgroup_id'])
        self.assertEqual('e2', form.initial['environment_id'])
        self.assertEqual('v2', form.initial['server_id'])

    @mock.patch.object(coast, 'oneclick_create',
                       side_effect=coast.CoastError())
    def test_failure_does_not_remember_placement(self, create):
        self.client.post(self.url, DATA)
        self.assertNotIn(forms.PLACEMENT_SESSION_KEY, self.client.session)

    def test_bound_form_preserves_edits(self):
        data = dict(DATA, name='my-custom-name')
        form = forms.CreateOneClick(self.request, data=data)
        self.assertEqual('my-custom-name', form['name'].value())
        self.assertTrue(form.defaults['bound'])
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(data, form.cleaned_data)

    @mock.patch.object(coast, 'service_list',
                       side_effect=coast.CoastError('Names unavailable'))
    def test_name_lookup_failure(self, names):
        response = self.client.get(self.url)
        self.assertContains(response, 'Names unavailable')
        self.assertEqual(
            '', response.context['form'].initial['name'])


class OneClickApiTests(helpers.TestCase):
    @mock.patch.object(coast, 'coastclient')
    def test_template_catalog(self, client):
        template = dict(TEMPLATE, http_port=8080)
        client.return_value.adapter.request.return_value = _resp(
            {'templates': [template]})
        self.assertEqual([template], coast.template_list(self.request, 's1'))
        client.assert_called_once_with(self.request, '1.0')
        client.return_value.adapter.request.assert_called_once_with(
            '/templates?stack_id=s1', 'GET', microversion='1.7', log=False,
            connect_retries=0, status_code_retries=0)
        client.return_value.request.assert_not_called()

    @mock.patch.object(coast, 'coastclient')
    def test_create_deploys_template(self, client):
        client.return_value.request.return_value = _resp(
            {'service': {'id': 'svc', 'deployment_id': 'dep'}})
        self.assertEqual({'id': 'svc', 'deployment_id': 'dep'},
                         coast.oneclick_create(self.request, **DATA))
        client.return_value.request.assert_called_once_with(
            '/services', 'POST', json={'service': {
                'name': 'database', 'appgroup_id': 'a1',
                'environment_id': 'e1', 'server_id': 'v1',
                'source': {'type': 'template', 'template_id': 'postgresql'},
                'deploy': True}})
