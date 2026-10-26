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

"""Create actions, locked placement, and return navigation."""

from html.parser import HTMLParser
from unittest import mock
from urllib.parse import urlencode

from django.urls import reverse

from coast_dashboard.api import coast
from coast_dashboard.content.environments.forms import CreateEnvironment
from coast_dashboard.content.oneclick.forms import CreateOneClick
from coast_dashboard.content.services.forms import CreateService
from coast_dashboard.tests import helpers
from coast_dashboard.tests.test_forms import APPGROUPS
from coast_dashboard.tests.test_forms import ENVIRONMENTS
from coast_dashboard.tests.test_forms import SERVERS
from coast_dashboard.tests.test_forms import SERVICE_DATA


class CreateLinks(HTMLParser):
    def __init__(self, response):
        super().__init__()
        self.urls = []
        self.feed(response.content.decode())

    def handle_starttag(self, tag, attrs):
        if tag == 'a' and dict(attrs).get('href'):
            self.urls.append(dict(attrs)['href'])


class CreateContextTests(helpers.TestCase):
    def setUp(self):
        super().setUp()
        for name, result in (
                ('appgroup_list', APPGROUPS),
                ('appgroup_get', APPGROUPS[0]),
                ('environment_list', ENVIRONMENTS),
                ('environment_get', ENVIRONMENTS[0]),
                ('stack_list', []), ('stack_server_list', SERVERS),
                ('service_list', []),
                ('template_list', [{'id': 'db', 'name': 'Database'}])):
            patch = mock.patch.object(coast, name, return_value=result)
            patch.start()
            self.addCleanup(patch.stop)

    def detail(self, panel, ident):
        return reverse(helpers.view_name(panel, 'detail'), args=[ident])

    def test_detail_and_empty_table_actions(self):
        for panel, ident, creates in (
                ('appgroups', 'a1', ('services', 'oneclick', 'environments')),
                ('environments', 'e1', ('services', 'oneclick'))):
            response = self.client.get(self.detail(panel, ident))
            for create in creates:
                url = reverse(helpers.view_name(create, 'create'))
                self.assertContains(response, 'appgroup_id=a1')
                self.assertContains(response, 'next=')
                # Each action appears in the header and the empty table.
                self.assertGreaterEqual(response.content.count(
                    (url + '?').encode()), 2)

    def test_locked_fields_ignore_post_tampering(self):
        self.request.GET = {'appgroup_id': 'a1', 'environment_id': 'e1'}
        for cls in (CreateService, CreateOneClick):
            data = dict(SERVICE_DATA, appgroup_id='a2', environment_id='e2',
                        template_id='db')
            form = cls(self.request, data=data)
            self.assertTrue(form.is_valid(), form.errors)
            for field, value in [('appgroup_id', 'a1'),
                                 ('environment_id', 'e1')]:
                self.assertTrue(form.fields[field].disabled)
                self.assertEqual(value, form.cleaned_data[field])
        form = CreateEnvironment(self.request, data={
            'name': 'staging', 'appgroup_id': 'a2'})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual('a1', form.cleaned_data['appgroup_id'])

    def test_single_environment_preselected(self):
        self.request.GET = {'appgroup_id': 'a1'}
        for cls in (CreateService, CreateOneClick):
            form = cls(self.request)
            self.assertTrue(form.fields['appgroup_id'].disabled)
            self.assertEqual('e1', form['environment_id'].value())
            self.assertFalse(form.fields['environment_id'].disabled)

    def test_multiple_environments_remain_selectable(self):
        self.request.GET = {'appgroup_id': 'a1'}
        envs = ENVIRONMENTS + [dict(ENVIRONMENTS[0], id='e3')]
        with mock.patch.object(coast, 'environment_list', return_value=envs):
            for cls in (CreateService, CreateOneClick):
                form = cls(self.request)
                self.assertFalse(form.fields['environment_id'].disabled)
                self.assertFalse(form['environment_id'].value())

    def test_invalid_locked_context_fails_validation(self):
        self.request.GET = {'appgroup_id': 'missing'}
        form = CreateService(self.request, data=SERVICE_DATA)
        self.assertFalse(form.is_valid())
        self.assertIn('appgroup_id', form.errors)

    def test_modal_preserves_context_and_redirect(self):
        target = self.detail('environments', 'e1')
        url = reverse('horizon:project:coast.apps:create')
        url += '?' + urlencode({
            'appgroup_id': 'a1', 'environment_id': 'e1', 'next': target})
        response = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertContains(response, 'environment_id=e1')
        with mock.patch.object(coast, 'service_create',
                               return_value={'id': 'n'}):
            response = self.client.post(
                url, SERVICE_DATA, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(target, response['X-Horizon-Location'])

    def test_environment_membership_validation(self):
        for cls in (CreateService, CreateOneClick):
            form = cls(self.request, data=dict(
                SERVICE_DATA, environment_id='e2', template_id='db'))
            self.assertFalse(form.is_valid())
            self.assertIn('environment_id', form.errors)

    def test_rendered_mapping_and_context_action(self):
        for panel in ('services', 'oneclick'):
            response = self.client.get(reverse(
                helpers.view_name(panel, 'create')),
                {'appgroup_id': 'a1', 'next': self.detail('appgroups', 'a1')})
            form = response.context['form']
            mapping = (form.defaults['environments'] if panel == 'oneclick'
                       else form.environment_groups)
            self.assertEqual({'e1': 'a1', 'e2': 'a2'}, mapping)
            self.assertContains(response, '"e1": "a1"')
            self.assertIn('appgroup_id=a1', response.context['submit_url'])

    def test_return_and_deployment_redirects(self):
        for panel, method, data in (
                ('services', 'service_create', SERVICE_DATA),
                ('oneclick', 'oneclick_create', {
                    'name': 'db', 'appgroup_id': 'a1',
                    'environment_id': 'e1', 'server_id': 'v1',
                    'template_id': 'db'}),
                ('environments', 'environment_create', {
                    'name': 'staging', 'appgroup_id': 'a1'})):
            url = reverse(helpers.view_name(panel, 'create'))
            for target in (self.detail('appgroups', 'a1'),
                           self.detail('environments', 'e1'),
                           'https://foreign.example/path', '//foreign/path',
                           '/unrelated/'):
                deployments = ((False, True) if panel != 'environments'
                               else (False,))
                for deploy in deployments:
                    item = {'id': 'new'}
                    if deploy:
                        item['deployment_id'] = 'dep'
                    with mock.patch.object(coast, method, return_value=item):
                        response = self.client.post(url + '?' + urlencode({
                            'appgroup_id': 'a1', 'next': target}), data)
                    expected = (target if target.startswith('/project/')
                                else reverse(
                                    helpers.view_name(panel, 'index')))
                    if deploy:
                        expected = reverse(
                            'horizon:project:coast.apps:deployment',
                            args=['new', 'dep'])
                    self.assertEqual(302, response.status_code)
                    self.assertEqual(expected, response['Location'])

    def test_locked_group_worker_choices_and_single_default(self):
        self.request.GET = {'appgroup_id': 'a1'}
        for cls in (CreateService, CreateOneClick):
            form = cls(self.request)
            choices = [key for key, _label in
                       form.fields['server_id'].choices if key]
            self.assertEqual(['v1'], choices)
            self.assertEqual('v1', form['server_id'].value())
            self.assertFalse(form.fields['server_id'].disabled)

    def test_multiple_workers_require_selection(self):
        self.request.GET = {'appgroup_id': 'a1'}
        servers = SERVERS + [dict(SERVERS[0], id='v3')]
        with mock.patch.object(coast, 'stack_server_list',
                               return_value=servers):
            for cls in (CreateService, CreateOneClick):
                form = cls(self.request)
                self.assertEqual(['', 'v1', 'v3'], [
                    key for key, _label in form.fields['server_id'].choices])
                self.assertFalse(form['server_id'].value())

    def test_wrong_stack_and_nonworker_rejected(self):
        for cls in (CreateService, CreateOneClick):
            for worker in ('v2', 'control', 'missing'):
                form = cls(self.request, data=dict(
                    SERVICE_DATA, server_id=worker, template_id='db'))
                self.assertFalse(form.is_valid())
                self.assertIn('server_id', form.errors)

    def test_worker_maps_rendered_for_page_and_modal(self):
        for panel in ('services', 'oneclick'):
            for headers in ({}, {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}):
                response = self.client.get(reverse(
                    helpers.view_name(panel, 'create')), **headers)
                form = response.context['form']
                groups = (form.defaults['groups'] if panel == 'oneclick'
                          else form.appgroup_stacks)
                workers = (form.defaults['workers'] if panel == 'oneclick'
                           else form.worker_stacks)
                self.assertEqual({'a1': 's1', 'a2': 's2'}, groups)
                self.assertEqual({'v1': 's1', 'v2': 's2'}, workers)
                self.assertContains(response, '"v1": "s1"')
                self.assertContains(response, '"a1": "s1"')

    def oneclick_entry_points(self):
        create = reverse('horizon:project:coast.services:create')
        with mock.patch.object(coast, 'stack_list', return_value=[{
                'id': 's1', 'name': 'Stack', 'engine_version': 'v1'}]):
            listing = self.client.get(reverse(
                'horizon:project:coast.services:index'))
        list_links = CreateLinks(listing).urls
        self.assertIn(create, list_links)
        template_url = create + '?template_id=db'
        self.assertIn(template_url, list_links)
        group_links = CreateLinks(self.client.get(
            self.detail('appgroups', 'a1'))).urls
        env_links = CreateLinks(self.client.get(
            self.detail('environments', 'e1'))).urls
        return [
            ('services', create, False, False),
            ('template', template_url, False, False),
            ('appgroup', next(url for url in group_links
                              if url.startswith(create + '?')), True, False),
            ('environment', next(url for url in env_links
                                 if url.startswith(create + '?')), True, True)]

    def test_oneclick_placement_for_every_entry_point(self):
        entries = self.oneclick_entry_points()
        for entry, url, locked_group, locked_env in entries:
            for headers in ({}, {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}):
                with self.subTest(entry=entry, modal=bool(headers)):
                    response = self.client.get(url, **headers)
                    form = response.context['form']
                    for hook in ('coast-environment-groups',
                                 'coast-appgroup-stacks',
                                 'coast-worker-stacks',
                                 'change.coastPlacement',
                                 'shown.bs.modal.coastEnvironments'):
                        self.assertContains(response, hook)
                    self.assertEqual({'e1': 'a1', 'e2': 'a2'},
                                     form.environment_groups)
                    self.assertEqual({'a1': 's1', 'a2': 's2'},
                                     form.appgroup_stacks)
                    workers = ({'v1': 's1'} if locked_group else
                               {'v1': 's1', 'v2': 's2'})
                    self.assertEqual(workers, form.worker_stacks)
                    self.assertEqual(set(workers), {
                        key for key, _label in form.fields['server_id'].choices
                        if key})
                    self.assertEqual({'e1', 'e2'}, {
                        key for key, _label in
                        form.fields['environment_id'].choices if key})
                    self.assertEqual(locked_group,
                                     form.fields['appgroup_id'].disabled)
                    self.assertEqual(locked_env,
                                     form.fields['environment_id'].disabled)
                    if locked_group:
                        self.assertEqual('a1', form['appgroup_id'].value())
                        self.assertEqual('e1', form['environment_id'].value())
                        self.assertEqual('v1', form['server_id'].value())
                    if entry == 'template':
                        self.assertEqual('db', form['template_id'].value())

    @mock.patch.object(coast, 'oneclick_create')
    def test_oneclick_rejects_wrong_placement_for_every_entry(self, create):
        entries = self.oneclick_entry_points()
        for entry, url, _locked_group, locked_env in entries:
            with self.subTest(entry=entry):
                response = self.client.post(url, dict(
                    SERVICE_DATA, template_id='db', environment_id='e2',
                    server_id='v2'))
                self.assertEqual(200, response.status_code)
                form = response.context['form']
                self.assertIn('server_id', form.errors)
                if locked_env:
                    self.assertEqual('e1', form.cleaned_data['environment_id'])
                else:
                    self.assertIn('environment_id', form.errors)
        create.assert_not_called()
