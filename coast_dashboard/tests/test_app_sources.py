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

import copy
from html.parser import HTMLParser
from unittest import mock

from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string

from coast_dashboard.api import coast
from coast_dashboard.content import common
from coast_dashboard.content.services import forms
from coast_dashboard.tests import helpers
from coast_dashboard.tests import test_forms
from coast_dashboard.tests import test_navigation_settings as nav


class SourceFormsTests(helpers.TestCase):
    def setUp(self):
        super().setUp()
        self.request._messages = FallbackStorage(self.request)
        for name, result in (
                ('appgroup_list', test_forms.APPGROUPS),
                ('environment_list', test_forms.ENVIRONMENTS),
                ('stack_server_list', test_forms.SERVERS)):
            patcher = mock.patch.object(coast, name, return_value=result)
            patcher.start()
            self.addCleanup(patcher.stop)

    def form(self, kind, files=None, **values):
        return forms.CreateService(
            self.request, data=dict(test_forms.SERVICE_DATA,
                                    source_type=kind, **values), files=files)

    @mock.patch.object(coast, 'service_create', return_value={'id': 'svc'})
    def test_private_git_generation_and_upload(self, create):
        for url in ('git@example.com:org/repo.git',
                    'ssh://git@example.com:2222/org/repo.git'):
            form = self.form('private_git', ssh_url=url)
            self.assertTrue(form.is_valid(), form.errors)
            form.handle(self.request, form.cleaned_data)
            source = create.call_args.args[5]
            self.assertEqual('git', source['type'])
            self.assertEqual(url, source['repo_url'])
            self.assertEqual({'generate': True}, source['deploy_key'])
        key = 'fake-private-input'
        for files, values in (
                (None, {'private_key': key}),
                ({'private_key_file': SimpleUploadedFile(
                    'key', key.encode())}, {})):
            form = self.form('private_git', files=files,
                             ssh_url='git@example.com:org/repo.git',
                             key_mode='upload', **values)
            self.assertTrue(form.is_valid(), form.errors)
            form.handle(self.request, form.cleaned_data)
            self.assertEqual({'private_key': key},
                             create.call_args.args[5]['deploy_key'])
            self.assertNotIn(key, form.as_p())

    def test_private_validation_and_no_redisplay_on_error(self):
        for url in ('https://example.com/repo', 'git@example.com',
                    'ssh://git:password@example.com/org/repo'):
            form = self.form('private_git', ssh_url=url)
            self.assertFalse(form.is_valid())
            self.assertIn('ssh_url', form.errors)
        form = self.form('private_git', ssh_url='git@host:org/repo',
                         key_mode='upload')
        self.assertFalse(form.is_valid())
        self.assertIn('private_key', form.errors)
        form = self.form('private_git', ssh_url='', key_mode='upload',
                         private_key='fake-sensitive-input')
        self.assertFalse(form.is_valid())
        self.assertNotIn('fake-sensitive-input', form.as_p())

    @mock.patch.object(coast, 'service_create', return_value={'id': 'svc'})
    def test_pasted_and_uploaded_sources(self, create):
        sources = [('dockerfile', 'FROM scratch\n'),
                   ('compose', 'services:\n  web:\n    image: nginx\n')]
        for kind, text in sources:
            for files, values in (
                    (None, {kind: text}),
                    ({kind + '_file': SimpleUploadedFile(
                        'source', text.encode())}, {})):
                form = self.form(kind, files=files, **values)
                self.assertTrue(form.is_valid(), form.errors)
                form.handle(self.request, form.cleaned_data)
                self.assertEqual({'type': kind, kind: text},
                                 create.call_args.args[5])
                self.assertNotIn(text, form.as_p())
            for value in ('', '   '):
                form = self.form(kind, **{kind: value})
                self.assertFalse(form.is_valid())
                self.assertIn(kind, form.errors)
            form = self.form(kind, files={kind + '_file':
                             SimpleUploadedFile('source', b'file')},
                             **{kind: text})
            self.assertFalse(form.is_valid())

    def test_upload_encoding_and_hidden_fields(self):
        form = self.form('dockerfile', files={
            'dockerfile_file': SimpleUploadedFile('source', b'\xff')})
        self.assertFalse(form.is_valid())
        self.assertIn('dockerfile', form.errors)
        form = self.form('git', private_key='fake-ignored',
                         dockerfile='ignored')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual('', form.cleaned_data['private_key'])
        html = render_to_string('project/coast_services/_create.html',
                                {'form': form, 'page_title': 'Source'},
                                request=self.request)
        for label in ('Public Git repository', 'Private Git repository',
                      'Container image', 'Dockerfile', 'Docker Compose'):
            self.assertIn(label, html)
        self.assertIn('enctype="multipart/form-data"', html)
        self.assertNotIn('fake-ignored', html)

    @mock.patch.object(coast, 'service_update')
    def test_replace_error_never_redisplays_key(self, update):
        update.side_effect = coast.CoastError('Only unencrypted keys allowed')
        form = forms.ReplaceDeployKey(
            self.request, {'key_mode': 'upload',
                           'private_key': 'fake-sensitive-input'},
            service_id='svc')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertFalse(form.handle(self.request, form.cleaned_data))
        html = render_to_string('project/coast_services/_settings_form.html',
                                {'form': form, 'page_title': 'Source'},
                                request=self.request)
        self.assertIn('Only unencrypted keys allowed', html)
        self.assertNotIn('fake-sensitive-input', html)
        self.assertIn('enctype="multipart/form-data"', html)

    def test_source_visibility_attributes(self):
        class Inputs(HTMLParser):
            def __init__(self, html):
                super().__init__()
                self.fields = {}
                self.feed(html)

            def handle_starttag(self, tag, attrs):
                values = dict(attrs)
                if tag in ('select', 'input', 'textarea') and 'name' in values:
                    self.fields[values['name']] = values

        for form, template in (
                (self.form('git'), '_create.html'),
                (forms.ReplaceDeployKey(self.request, service_id='svc'),
                 '_settings_form.html')):
            html = render_to_string(
                'project/coast_services/' + template,
                {'form': form, 'page_title': 'Source'}, request=self.request)
            fields = Inputs(html).fields
            # Horizon adds Bootstrap classes through a set; order varies.
            for attrs in fields.values():
                attrs['class'] = set(attrs.get('class', '').split()) - {
                    'form-control'}
            self.assertEqual('key-mode', fields['key_mode']['data-slug'])
            self.assertEqual({'switchable', 'switched'}
                             if 'source_type' in fields else {'switchable'},
                             fields['key_mode']['class'])
            for name in ('private_key', 'private_key_file'):
                attrs = fields[name]
                self.assertEqual({'switched'}, attrs['class'])
                self.assertEqual('key-mode', attrs['data-switch-on'])
                self.assertEqual(str(form.fields[name].label),
                                 attrs['data-key-mode-upload'])
                self.assertEqual({'data-switch-on', 'data-key-mode-upload'},
                                 {key for key in attrs
                                  if key.startswith('data-')})
            if 'source_type' not in fields:
                continue
            self.assertEqual({'switchable'}, fields['source_type']['class'])
            self.assertEqual('source', fields['source_type']['data-slug'])
            groups = {
                'repo_url': ('git',), 'ssh_url': ('private_git',),
                'key_mode': ('private_git',),
                'branch': ('git', 'private_git'),
                'build_pack': ('git', 'private_git'),
                'base_directory': ('git', 'private_git'),
                'image': ('image',), 'tag': ('image',),
                'dockerfile': ('dockerfile',),
                'dockerfile_file': ('dockerfile',),
                'compose': ('compose',), 'compose_file': ('compose',)}
            for name, kinds in groups.items():
                attrs = fields[name]
                self.assertEqual({'switchable', 'switched'}
                                 if name == 'key_mode' else {'switched'},
                                 attrs['class'])
                self.assertEqual('source', attrs['data-switch-on'])
                for kind in kinds:
                    self.assertEqual(str(form.fields[name].label),
                                     attrs['data-source-' + kind])
                self.assertEqual(
                    {'data-source-' + kind for kind in kinds},
                    {key for key in attrs if key.startswith('data-source-')})


class SourceApiTests(helpers.TestCase):
    @mock.patch.object(coast, 'coastclient')
    def test_compose_save_payload(self, client):
        client.return_value.adapter.request.return_value.json.return_value = {
            'compose': {'yaml': 'services: {}'}}
        coast.service_compose_update(self.request, 'svc', 'services: {}')
        call = client.return_value.adapter.request.call_args
        self.assertEqual(('/services/svc/compose', 'PUT'), call.args)
        self.assertEqual({'compose': {'yaml': 'services: {}'}},
                         call.kwargs['json'])
        self.assertEqual('1.12', call.kwargs['microversion'])

    @mock.patch.object(coast, 'coastclient')
    def test_source_versions_and_deploy(self, client):
        client.return_value.adapter.request.return_value.json.return_value = {
            'service': {'id': 'svc'}}
        client.return_value.request.return_value.json.return_value = {
            'service': {'id': 'svc'}}
        for source, version, deploy in (
                ({'type': 'git'}, '1.0', True),
                ({'type': 'image'}, '1.0', True),
                ({'type': 'git', 'deploy_key': {'generate': True}},
                 '1.30', False),
                ({'type': 'git', 'deploy_key': {'private_key': 'fake'}},
                 '1.30', True),
                ({'type': 'dockerfile', 'dockerfile': 'FROM scratch'},
                 '1.31', True),
                ({'type': 'compose', 'compose': 'services: {}'},
                 '1.31', True)):
            coast.service_create(self.request, 'web', 'a', 'e', 's', source)
            call = (client.return_value.request.call_args if version == '1.0'
                    else client.return_value.adapter.request.call_args)
            body = call.kwargs['json']['service']
            self.assertEqual(source, body['source'])
            self.assertEqual(deploy, body['deploy'])
            if version != '1.0':
                self.assertEqual(version, call.kwargs['microversion'])
                self.assertFalse(call.kwargs['log'])
        values = {'source': {'deploy_key': {'generate': True}}}
        coast.service_update(self.request, 'svc', values)
        self.assertEqual('1.30', client.return_value.adapter.request.
                         call_args.kwargs['microversion'])

    @mock.patch.object(coast, 'coastclient')
    def test_dockerfile_contract_and_older_server(self, client):
        adapter = client.return_value.adapter.request
        adapter.return_value.json.return_value = {
            'dockerfile': {'text': 'FROM scratch\n'}}
        self.assertEqual('FROM scratch\n', coast.service_dockerfile_get(
            self.request, 'svc'))
        self.assertEqual('FROM scratch\n', coast.service_dockerfile_update(
            self.request, 'svc', 'FROM scratch\n'))
        self.assertEqual([
            mock.call('/services/svc/dockerfile', 'GET', microversion='1.31',
                      log=False, connect_retries=0, status_code_retries=0),
            mock.call('/services/svc/dockerfile', 'PUT', microversion='1.31',
                      log=False, connect_retries=0, status_code_retries=0,
                      json={'dockerfile': {'text': 'FROM scratch\n'}})],
            adapter.call_args_list)
        adapter.side_effect = coast.client_exceptions.NotAcceptable()
        for source, version in (
                ({'type': 'git', 'deploy_key': {'generate': True}}, '1.30'),
                ({'type': 'compose', 'compose': 'services: {}'}, '1.31')):
            with self.assertRaises(coast.CoastError) as caught:
                coast.service_create(
                    self.request, 'web', 'a', 'e', 's', source)
            self.assertIn('needs API version ' + version,
                          coast.error_message(caught.exception, 'fallback'))


class SourceViewsTests(helpers.TestCase):
    def setUp(self):
        nav.NavigationSettingsTests.setUp(self)
        self.records = copy.deepcopy(self.records)

    list_services = nav.NavigationSettingsTests.list_services

    def get_service(self, request, service_id, **kwargs):
        return nav.NavigationSettingsTests.get_service(
            self, request, service_id)

    update_service = nav.NavigationSettingsTests.update_service
    url = nav.NavigationSettingsTests.url

    @mock.patch.object(coast, 'service_deploy')
    @mock.patch.object(coast, 'service_dockerfile_get',
                       return_value='FROM scratch\n')
    @mock.patch.object(coast, 'service_dockerfile_update')
    def test_dockerfile_editor_and_permissions(self, save, get, deploy):
        self.records['app-id']['source'] = {'type': 'dockerfile'}
        target = self.url('services', 'edit_dockerfile', ['app-id'])
        detail = self.client.get(self.url('services', 'detail', ['app-id']))
        self.assertContains(detail, 'Edit Dockerfile')
        self.assertIn(target, [attrs.get('href') for attrs in
                               nav.Links(detail).matching('Edit Dockerfile')])
        response = self.client.get(target)
        self.assertContains(response, 'FROM scratch')
        self.assertIn('no-store', response['Cache-Control'])
        response = self.client.post(target, {'text': 'FROM example\n'})
        self.assertEqual(302, response.status_code)
        save.assert_called_once_with(mock.ANY, 'app-id', 'FROM example\n')
        deploy.assert_not_called()
        with mock.patch.object(common, 'project_member', return_value=False):
            self.assertEqual(403, self.client.post(
                target, {'text': 'FROM example'}).status_code)
        self.records['app-id']['source'] = {'type': 'git'}
        self.assertEqual(403, self.client.get(target).status_code)

    @mock.patch.object(coast, 'service_compose_get',
                       return_value='services: {}')
    def test_pasted_compose_tabs(self, get):
        self.records['service-id']['source'] = {'type': 'compose'}
        response = self.client.get(self.url('oneclick', 'detail',
                                            ['service-id']) +
                                   '?tab=service_details__compose')
        self.assertContains(response, 'Compose configuration')
        self.assertContains(response, 'service_details__containers')

    @mock.patch.object(coast, 'service_deploy')
    @mock.patch.object(coast, 'service_compose_update')
    def test_pasted_compose_save_without_deployment(self, update, deploy):
        self.records['service-id']['source'] = {'type': 'compose'}
        target = (self.url('oneclick', 'detail', ['service-id']) +
                  '?tab=service_details__compose')
        yaml = 'services:\n  web:\n    image: nginx:stable\n'
        response = self.client.post(target,
                                    {'yaml': yaml, 'operation': 'save'})
        self.assertRedirects(response, target, fetch_redirect_response=False)
        update.assert_called_once_with(mock.ANY, 'service-id', yaml)
        deploy.assert_not_called()
        self.assertIn('no-store', response['Cache-Control'])

    @mock.patch.object(coast, 'service_container_list')
    def test_pasted_compose_container_rows(self, containers):
        self.records['service-id']['source'] = {'type': 'compose'}
        containers.return_value = [
            {'id': 'c-web', 'name': 'web', 'image': 'nginx:stable',
             'state': 'running', 'health': 'healthy', 'restart_count': 0},
            {'id': 'c-worker', 'name': 'worker', 'image': 'example/worker:v2',
             'state': 'exited', 'health': None, 'restart_count': 3}]
        response = self.client.get(
            self.url('oneclick', 'detail', ['service-id']) +
            '?tab=service_details__containers')
        containers.assert_called_once_with(mock.ANY, 'service-id')
        for name, image, status in (
                ('web', 'nginx:stable', 'running (healthy)'),
                ('worker', 'example/worker:v2', 'exited')):
            self.assertContains(response, image)
            self.assertContains(response, status)
            link = self.url('oneclick', 'container',
                            ['service-id', 'c-' + name])
            self.assertIn(link, [attrs.get('href') for attrs in
                                 nav.Links(response).matching(name)])
        self.assertIn('no-store', response['Cache-Control'])

    def test_key_details_template(self):
        html = render_to_string('project/coast_services/overview.html', {
            'item': {'source': {'type': 'git', 'deploy_key': {
                'public_key': 'ssh-ed25519 fake-public',
                'fingerprint': 'SHA256:fake'}},
                'replace_key_url': '/replace'}})
        for text in ('ssh-ed25519 fake-public', 'SHA256:fake',
                     'data-copy-value="ssh-ed25519 fake-public"',
                     'Add this key as a read-only deploy key in your '
                     'repository, then deploy', 'Replace deploy key'):
            self.assertIn(text, html)

    def test_private_details_and_replacement(self):
        self.records['app-id']['source'] = {
            'type': 'git', 'repo_url': 'git@example.com:org/repo.git',
            'deploy_key': {'public_key': 'ssh-ed25519 fake-public',
                           'fingerprint': 'SHA256:fake'}}
        target = self.url('services', 'replace_deploy_key', ['app-id'])
        response = self.client.get(self.url('services', 'detail', ['app-id']))
        self.assertContains(response, 'ssh-ed25519 fake-public')
        self.assertContains(response, target)
        self.service_get.assert_any_call(mock.ANY, 'app-id',
                                         microversion='1.30')
        response = self.client.get(target)
        self.assertContains(response, 'Generate a deploy key (recommended)')
        response = self.client.post(target, {'key_mode': 'generate'})
        self.assertEqual(302, response.status_code)
        self.service_update.assert_called_once_with(
            mock.ANY, 'app-id',
            {'source': {'deploy_key': {'generate': True}}})
        with mock.patch.object(common, 'project_member', return_value=False):
            self.assertEqual(403, self.client.post(
                target, {'key_mode': 'generate'}).status_code)
        self.records['app-id']['source'] = {'type': 'image'}
        self.assertEqual(403, self.client.get(target).status_code)

    def test_ssh_usernames_read_key_metadata(self):
        source = {'type': 'git', 'deploy_key': {
            'public_key': 'ssh-ed25519 fake-public',
            'fingerprint': 'SHA256:fake'}}
        for repo in ('deploy@host:org/repo.git', 'git@host:org/repo.git',
                     'ssh://deploy@host:2222/org/repo.git'):
            with self.subTest(repo=repo):
                self.records['app-id']['source'] = dict(source, repo_url=repo)

                def get(request, service_id, microversion=None):
                    item = copy.deepcopy(self.records[service_id])
                    if microversion != '1.30':
                        item['source'].pop('deploy_key')
                    return item

                self.service_get.side_effect = get
                self.service_get.reset_mock()
                response = self.client.get(self.url(
                    'services', 'detail', ['app-id']))
                self.service_get.assert_any_call(mock.ANY, 'app-id',
                                                 microversion='1.30')
                for value in ('ssh-ed25519 fake-public', 'SHA256:fake',
                              'Replace deploy key'):
                    self.assertContains(response, value)

    @mock.patch.object(coast, 'service_create')
    def test_generated_key_creation_redirect(self, create):
        create.return_value = {
            'id': 'new-app', 'kind': 'app',
            'source': {'type': 'git', 'deploy_key': {
                'public_key': 'ssh-ed25519 fake-public'}}}
        worker = {'id': 'worker', 'role': 'worker', 'status': 'ACTIVE',
                  'stack_id': 'stack-id', 'name': 'Worker'}
        data = dict(test_forms.SERVICE_DATA, source_type='private_git',
                    appgroup_id='group-id', environment_id='env-id',
                    server_id='worker', ssh_url='git@example.com:org/repo.git')
        with mock.patch.object(coast, 'stack_server_list',
                               return_value=[worker]):
            response = self.client.post(self.url('services', 'create'), data)
        self.assertRedirects(response, self.url('services', 'detail',
                                                ['new-app']),
                             fetch_redirect_response=False)
        self.assertEqual({'generate': True},
                         create.call_args.args[5]['deploy_key'])
