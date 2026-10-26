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
from types import SimpleNamespace
from unittest import mock

from django.contrib.messages.storage.fallback import FallbackStorage
from django.template.loader import render_to_string
from openstack_dashboard.api import nova

from coast_dashboard.api import coast
from coast_dashboard.content.appgroups import forms as appgroup_forms
from coast_dashboard.content.environments import forms as environment_forms
from coast_dashboard.content.oneclick import forms as oneclick_forms
from coast_dashboard.content.services import forms as service_forms
from coast_dashboard.content.services import views as service_views
from coast_dashboard.content.stacks import forms as stack_forms
from coast_dashboard.tests import helpers


APPGROUPS = [
    {'id': 'a1', 'name': 'App', 'stack_id': 's1', 'status': 'ACTIVE'},
    {'id': 'a2', 'name': 'Other', 'stack_id': 's2', 'status': 'ACTIVE'}]
ENVIRONMENTS = [
    {'id': 'e1', 'name': 'Production', 'appgroup_id': 'a1',
     'status': 'ACTIVE'},
    {'id': 'e2', 'name': 'Other', 'appgroup_id': 'a2', 'status': 'ACTIVE'}]
SERVERS = [{'id': 'v1', 'name': 'worker', 'role': 'worker',
            'stack_id': 's1', 'status': 'ACTIVE'},
           {'id': 'v2', 'name': 'worker2', 'role': 'worker',
            'stack_id': 's2', 'status': 'ACTIVE'},
           {'id': 'control', 'name': 'control', 'role': 'control',
            'stack_id': 's1', 'status': 'ACTIVE'}]
SERVICE_DATA = {'health_check': 'none', 'source_type': 'git',
                'name': 'web', 'appgroup_id': 'a1',
                'environment_id': 'e1',
                'server_id': 'v1', 'repo_url': 'https://example.com/web.git',
                'branch': 'main', 'build_pack': 'nixpacks', 'ports': '8080'}
STACK_DATA = {'name': 'demo', 'plan': 'm1.small', 'worker_plan': 'm1.medium',
              'worker_count': 1, 'build_server': True,
              'build_server_plan': 'm1.large'}
FLAVORS = [
    SimpleNamespace(id='id-large', name='m1.large', ram=4096,
                    vcpus=4, disk=40),
    SimpleNamespace(id='id-medium', name='m1.medium', ram=1536,
                    vcpus=2, disk=20),
    SimpleNamespace(id='id-tiny', name='m1.tiny', ram=512, vcpus=1, disk=0),
    SimpleNamespace(id='id-small', name='m1.small', ram=1024,
                    vcpus=1, disk=10),
    SimpleNamespace(id='id-alt', name='a1.small', ram=1024, vcpus=2, disk=15)]


class FormTests(helpers.TestCase):
    def setUp(self):
        super().setUp()
        self.request._messages = FallbackStorage(self.request)
        patcher = mock.patch.object(nova, 'flavor_list', return_value=FLAVORS)
        self.flavor_list = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(coast, 'plan_list', return_value=[
            {'name': 'all', 'kind': 'vm',
             'roles': ['control', 'worker', 'build'],
             'flavor': flavor.name} for flavor in FLAVORS])
        self.plan_list = patcher.start()
        self.addCleanup(patcher.stop)
        for name, result in [('appgroup_list', APPGROUPS),
                             ('environment_list', ENVIRONMENTS),
                             ('stack_server_list', SERVERS)]:
            patcher = mock.patch.object(coast, name, return_value=result)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_create_app_field_order(self):
        form = service_forms.CreateService(self.request)
        self.assertEqual([
            'name', 'appgroup_id', 'environment_id', 'server_id',
            'source_type', 'repo_url', 'ssh_url', 'key_mode', 'private_key',
            'private_key_file', 'dockerfile', 'dockerfile_file',
            'compose', 'compose_file', 'branch', 'build_pack',
            'base_directory', 'image', 'tag', 'ports', 'health_check',
            'health_check_port',
            'healthcheck_path'], list(form.fields))

    def test_edit_settings_field_and_rendered_order(self):
        class FieldNames(HTMLParser):
            def __init__(self):
                super().__init__()
                self.names = []

            def handle_starttag(self, tag, attrs):
                name = dict(attrs).get('name')
                if tag in ('input', 'select', 'textarea') and name:
                    self.names.append(name)

        for source in ('git', 'image', 'template'):
            with self.subTest(source=source):
                form = service_forms.EditSettings(
                    self.request, service_id='app',
                    initial={'source_type': source})
                expected = [
                    'name', 'description', 'ports', 'health_check',
                    'health_check_port', 'healthcheck_path']
                if source == 'git':
                    expected.append('branch')
                expected.extend(['cpu_limit', 'memory_limit_mb'])
                self.assertEqual(expected, list(form.fields))
                html = render_to_string(
                    'project/coast_services/_settings_form.html',
                    {'form': form, 'page_title': 'Edit Settings'},
                    request=self.request)
                parser = FieldNames()
                parser.feed(html)
                self.assertEqual(expected, [name for name in parser.names
                                            if name in form.fields])
                self.assertIn('id="id_ports_help"', html)
                self.assertIn(str(form.fields['ports'].help_text), html)

    def test_health_check_optional_ports_and_http_validation(self):
        form = service_forms.CreateService(self.request)
        self.assertEqual('none', form.fields['health_check'].initial)
        for mode, ports, valid in [('none', '', True), ('http', '', False),
                                   ('http', '8080', True)]:
            with self.subTest(mode=mode, ports=ports):
                form = service_forms.CreateService(
                    self.request, data=dict(SERVICE_DATA, health_check=mode,
                                            ports=ports))
                self.assertEqual(valid, form.is_valid(), form.errors)
                if not valid:
                    self.assertIn('ports', form.errors)

    @mock.patch.object(coast, 'coastclient')
    def test_create_http_payload_and_microversion(self, client):
        client.return_value.request.return_value.content = b'x'
        client.return_value.request.return_value.json.return_value = {
            'service': {'id': 'new'}}
        form = service_forms.CreateService(self.request, data=dict(
            SERVICE_DATA, health_check='http', health_check_port='9000',
            healthcheck_path='/ready'))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual({'id': 'new'}, form.handle(
            self.request, form.cleaned_data))
        call = client.return_value.request.call_args.kwargs
        self.assertEqual('1.4', call['health_check_microversion'])
        self.assertEqual('http', call['json']['service']['health_check'])
        self.assertEqual(9000, call['json']['service']['health_check_port'])
        self.assertEqual('/ready', call['json']['service']['healthcheck_path'])
        client.assert_called_with(self.request, '1.0')

    def test_none_ignores_hidden_http_values(self):
        form = service_forms.CreateService(self.request, data=dict(
            SERVICE_DATA, health_check='none', ports='',
            health_check_port='invalid', healthcheck_path='invalid'))
        self.assertTrue(form.is_valid(), form.errors)

    def test_http_probe_defaults_and_invalid_values(self):
        for value in ('0', '65536', 'text'):
            form = service_forms.CreateService(self.request, data=dict(
                SERVICE_DATA, health_check='http', health_check_port=value))
            self.assertFalse(form.is_valid())
            self.assertIn('health_check_port', form.errors)
        form = service_forms.CreateService(self.request, data=dict(
            SERVICE_DATA, health_check='http', healthcheck_path=''))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual('/', form.cleaned_data['healthcheck_path'])
        self.assertIsNone(form.cleaned_data['health_check_port'])

    @mock.patch.object(coast, 'service_update')
    @mock.patch.object(coast, 'service_get', return_value={'id': 'app'})
    def test_edit_worker_without_ports(self, get, update):
        form = service_forms.EditSettings(
            self.request, service_id='app',
            initial={'name': 'worker', 'health_check': 'http', 'ports': '80'},
            data={'name': 'worker', 'health_check': 'none', 'ports': ''})
        self.assertTrue(form.is_valid(), form.errors)
        form.handle(self.request, form.cleaned_data)
        values = update.call_args.args[2]
        self.assertEqual('none', values['health_check'])
        self.assertIsNone(values['ports'])

    @mock.patch.object(coast, 'coastclient')
    def test_create_blank_port_sends_null(self, client):
        client.return_value.request.return_value.content = b'x'
        client.return_value.request.return_value.json.return_value = {
            'service': {'id': 'new'}}
        for source in ('git', 'image'):
            with self.subTest(source=source):
                form = service_forms.CreateService(self.request, data=dict(
                    SERVICE_DATA, source_type=source, image='worker',
                    tag='latest', ports='   '))
                self.assertTrue(form.is_valid(), form.errors)
                self.assertTrue(form.handle(self.request, form.cleaned_data))
                payload = client.return_value.request.call_args.kwargs['json']
                self.assertIsNone(payload['service']['ports'])

    def test_api_port_errors_on_field(self):
        for cls, method, kwargs, data in (
                (service_forms.CreateService, 'service_create', {},
                 SERVICE_DATA),
                (service_forms.EditSettings, 'service_update',
                 {'service_id': 'app'},
                 {'name': 'worker', 'ports': '', 'health_check': 'none'})):
            with self.subTest(form=cls.__name__):
                message = 'Port is required when the app has a domain.'
                with mock.patch.object(coast, method,
                                       side_effect=coast.CoastError(message)):
                    form = cls(self.request, data=data, **kwargs)
                    self.assertTrue(form.is_valid(), form.errors)
                    self.assertFalse(form.handle(
                        self.request, form.cleaned_data))
                    self.assertEqual([message], form.errors['ports'])
                    self.assertFalse(form.non_field_errors())

    @mock.patch.object(coast, 'service_get', return_value={
        'name': 'worker', 'ports': None, 'health_check': 'none'})
    @mock.patch.object(coast, 'service_domain_list')
    def test_settings_domain_requirement(self, domains, get):
        view = service_views.EditSettingsView()
        view.request = self.request
        view.kwargs = {'service_id': 'app'}
        for entries, expected in (([], 'false'),
                                  ([{'fqdn': 'app.example.com'}], 'true')):
            with self.subTest(domains=entries):
                domains.return_value = entries
                form = service_forms.EditSettings(
                    self.request, service_id='app', initial=view.get_initial())
                self.assertEqual(expected, form.fields['ports'].widget.attrs[
                    'data-has-domain'])
                self.assertFalse(form.fields['ports'].required)

    def test_settings_http_requires_port(self):
        form = service_forms.EditSettings(
            self.request, service_id='app',
            data={'name': 'worker', 'ports': '', 'health_check': 'http'})
        self.assertFalse(form.is_valid())
        self.assertIn('ports', form.errors)

    def test_create_form_help(self):
        for cls in (stack_forms.CreateStack, appgroup_forms.CreateAppgroup,
                    environment_forms.CreateEnvironment,
                    service_forms.CreateService, oneclick_forms.CreateOneClick,
                    service_forms.SetEnv, service_forms.AddDomain,
                    service_forms.CreateStorage):
            with self.subTest(form=cls.__name__):
                self.assertTrue(str(cls.help_text))
                for field in cls.base_fields.values():
                    self.assertTrue(str(field.help_text), field.label)

    def test_flavor_choices(self):
        form = stack_forms.CreateStack(self.request)
        expected = [
            ('m1.tiny', 'm1.tiny (1 vCPU, 512 MB RAM, 0 GB disk)'),
            ('a1.small', 'a1.small (2 vCPU, 1 GB RAM, 15 GB disk)'),
            ('m1.small', 'm1.small (1 vCPU, 1 GB RAM, 10 GB disk)'),
            ('m1.medium', 'm1.medium (2 vCPU, 1.5 GB RAM, 20 GB disk)'),
            ('m1.large', 'm1.large (4 vCPU, 4 GB RAM, 40 GB disk)')]
        for field in ('plan', 'worker_plan'):
            self.assertEqual(expected, list(form.fields[field].choices))
        self.assertEqual([('', 'Use default build server flavor')] + expected,
                         list(form.fields['build_server_plan'].choices))
        self.assertEqual('App engine server flavor', form.fields['plan'].label)
        self.assertEqual('Worker flavor', form.fields['worker_plan'].label)
        self.assertEqual('Build server flavor',
                         form.fields['build_server_plan'].label)
        self.flavor_list.assert_called_once_with(self.request)

    @mock.patch.object(nova, 'flavor_list',
                       side_effect=RuntimeError('private'))
    def test_flavor_api_failure(self, flavors):
        form = stack_forms.CreateStack(self.request, data=STACK_DATA)
        self.assertFalse(form.is_valid())
        for field in ('plan', 'worker_plan', 'build_server_plan'):
            self.assertEqual([], list(form.fields[field].choices))
        messages = [str(m) for m in self.request._messages]
        self.assertIn('Unable to retrieve flavors.', messages)
        self.assertNotIn('private', str(messages))

    @mock.patch.object(coast, 'stack_create', return_value={'id': 's'})
    def test_optional_build_flavor(self, create):
        for enabled, flavor in [(True, ''), (False, 'stale-flavor')]:
            data = dict(STACK_DATA, build_server=enabled,
                        build_server_plan=flavor)
            form = stack_forms.CreateStack(self.request, data=data)
            self.assertTrue(form.is_valid(), form.errors)
            form.handle(self.request, form.cleaned_data)
            self.assertNotIn('build_server_plan', create.call_args.kwargs)
            self.assertEqual(enabled, create.call_args.kwargs['build_server'])

    def test_build_flavor_with_many_workers(self):
        form = stack_forms.CreateStack(
            self.request, data=dict(STACK_DATA, worker_count=3))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual('m1.large', form.cleaned_data['build_server_plan'])
        self.assertEqual(3, form.cleaned_data['worker_count'])

    def test_only_usable_flavors_listed_with_default(self):
        self.plan_list.return_value = [
            {'name': 'ctl', 'kind': 'vm', 'roles': ['control'],
             'flavor': 'm1.medium'},
            {'name': 'wrk', 'kind': 'vm', 'roles': ['worker', 'build'],
             'flavor': 'id-small'},
            {'name': 'bm', 'kind': 'baremetal', 'roles': ['worker'],
             'flavor': 'm1.large'}]
        form = stack_forms.CreateStack(self.request)

        def values(field):
            return [value for value, unused in form.fields[field].choices]
        self.assertEqual(['m1.medium'], values('plan'))
        self.assertEqual('m1.medium', form.fields['plan'].initial)
        self.assertEqual(['m1.small'], values('worker_plan'))
        self.assertEqual('m1.small', form.fields['worker_plan'].initial)
        self.assertEqual(['', 'm1.small'], values('build_server_plan'))
        bad = stack_forms.CreateStack(self.request, data=dict(
            STACK_DATA, plan='m1.small', worker_plan='m1.small',
            build_server_plan='m1.large'))
        self.assertFalse(bad.is_valid())
        self.assertEqual({'plan', 'build_server_plan'}, set(bad.errors))

    def test_plan_list_failure_lists_no_flavors(self):
        self.plan_list.side_effect = RuntimeError('private')
        form = stack_forms.CreateStack(self.request)
        self.assertEqual([], list(form.fields['plan'].choices))
        messages = [str(m) for m in self.request._messages]
        self.assertIn('Unable to retrieve Coast plans.', messages)

    def test_invalid_flavor_selections(self):
        for field in ('plan', 'worker_plan', 'build_server_plan'):
            for value in ('unknown', FLAVORS[0].id):
                form = stack_forms.CreateStack(
                    self.request, data=dict(STACK_DATA, **{field: value}))
                self.assertFalse(form.is_valid())
                self.assertIn(field, form.errors)

    @mock.patch.object(coast, 'stack_create', return_value={'id': 's'})
    def test_create_stack(self, create):
        form = stack_forms.CreateStack(self.request, data=STACK_DATA)
        self.assertTrue(form.is_valid(), form.errors)
        item = form.handle(self.request, form.cleaned_data)
        self.assertEqual({'id': 's'}, item)
        create.assert_called_once_with(self.request, **STACK_DATA)

    @mock.patch.object(coast, 'coastclient')
    def test_stack_body_uses_flavor_names(self, client):
        client.return_value.request.return_value.json.return_value = {
            'stack': {'id': 's'}}
        for enabled in (True, False):
            form = stack_forms.CreateStack(
                self.request, data=dict(STACK_DATA, build_server=enabled))
            self.assertTrue(form.is_valid(), form.errors)
            form.handle(self.request, form.cleaned_data)
            expected = {
                'name': 'demo', 'plan': 'm1.small', 'build_server': enabled,
                'workers': [{'kind': 'vm', 'plan': 'm1.medium'}]}
            if enabled:
                expected['build_server_plan'] = 'm1.large'
            client.return_value.request.assert_called_with(
                '/stacks', 'POST', json={'stack': expected})

    def test_invalid_worker_count(self):
        for count in (0, -1, 'bad'):
            form = stack_forms.CreateStack(
                self.request, data=dict(STACK_DATA, worker_count=count))
            self.assertFalse(form.is_valid())
            self.assertIn('worker_count', form.errors)

    @mock.patch.object(coast, 'stack_create', side_effect=RuntimeError())
    def test_stack_api_failure(self, create):
        form = stack_forms.CreateStack(self.request, data=STACK_DATA)
        self.assertTrue(form.is_valid())
        self.assertFalse(form.handle(self.request, form.cleaned_data))
        self.assertIn('Unable to create stack.', str(form.errors))

    @mock.patch.object(coast, 'stack_create', side_effect=coast.CoastError(
        'Flavor m1.large is not available for build servers.'))
    def test_stack_api_message_shown(self, create):
        form = stack_forms.CreateStack(self.request, data=STACK_DATA)
        self.assertTrue(form.is_valid())
        self.assertFalse(form.handle(self.request, form.cleaned_data))
        self.assertIn('Flavor m1.large is not available for build servers.',
                      str(form.errors))
        self.assertNotIn('Unable to create stack.', str(form.errors))

    def test_env_form_keeps_password_managers_away(self):
        form = service_forms.SetEnv(self.request, service_id='s')
        html = str(form['key']) + str(form['value'])
        self.assertNotIn('type="password"', html)
        for attr in ('autocomplete="off"', 'data-1p-ignore',
                     'data-lpignore="true"', 'data-bwignore',
                     'coast-env-value'):
            self.assertIn(attr, html)
        # New values stay readable; the modal masks them only for secrets.
        self.assertNotIn('-webkit-text-security', str(form['value']))

    def test_env_form_masks_existing_secret(self):
        form = service_forms.SetEnv(
            self.request, service_id='s',
            initial={'key': 'TOKEN', 'secret': True})
        self.assertIn('-webkit-text-security: disc', str(form['value']))

    def test_create_service_preselects_only_a_single_choice(self):
        form = service_forms.CreateService(self.request)
        for field in ('appgroup_id', 'environment_id', 'server_id'):
            self.assertEqual('', form.fields[field].choices[0][0])
        with mock.patch.object(coast, 'appgroup_list',
                               return_value=APPGROUPS[:1]), \
                mock.patch.object(coast, 'environment_list',
                                  return_value=ENVIRONMENTS[:1]):
            form = service_forms.CreateService(self.request)
        self.assertEqual([('a1', 'App')], form.fields['appgroup_id'].choices)
        self.assertEqual('e1', form.fields['environment_id'].choices[0][0])

    @mock.patch.object(coast, 'service_create', return_value={'id': 'svc'})
    def test_create_service(self, create):
        form = service_forms.CreateService(self.request, data=SERVICE_DATA)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual({'id': 'svc'}, form.handle(self.request,
                                                    form.cleaned_data))
        create.assert_called_once_with(
            self.request, 'web', 'a1', 'e1', 'v1',
            {'type': 'git', 'repo_url': SERVICE_DATA['repo_url'],
             'branch': 'main', 'build_pack': 'nixpacks'}, ports='8080')

    @mock.patch.object(coast, 'service_create', return_value={'id': 'svc'})
    def test_worker_required(self, create):
        form = service_forms.CreateService(
            self.request, data=dict(SERVICE_DATA, server_id=''))
        self.assertFalse(form.is_valid())
        self.assertIn('server_id', form.errors)
        create.assert_not_called()

    def test_parent_and_worker_validation(self):
        for field, value in [('environment_id', 'e2'), ('server_id', 'v2'),
                             ('server_id', 'control'),
                             ('environment_id', 'not-visible')]:
            with self.subTest(field=field, value=value):
                form = service_forms.CreateService(
                    self.request, data=dict(SERVICE_DATA, **{field: value}))
                self.assertFalse(form.is_valid())
                self.assertIn(field, form.errors)

    def test_source_validation(self):
        for url in ['http://example.com/web.git',
                    'https://user:pass@example.com/web.git',
                    'https://example.com/web.git?token=secret']:
            form = service_forms.CreateService(
                self.request, data=dict(SERVICE_DATA, repo_url=url))
            self.assertFalse(form.is_valid())
            self.assertIn('repo_url', form.errors)

    @mock.patch.object(coast, 'service_create', side_effect=RuntimeError())
    def test_service_api_failure(self, create):
        form = service_forms.CreateService(self.request, data=SERVICE_DATA)
        self.assertTrue(form.is_valid())
        self.assertFalse(form.handle(self.request, form.cleaned_data))
        self.assertIn('Unable to create app.', str(form.errors))

    @mock.patch.object(coast, 'service_create', return_value={'id': 'svc'})
    def test_git_base_directory(self, create):
        for path in ('', '  ', '/apps/web'):
            with self.subTest(path=path):
                form = service_forms.CreateService(
                    self.request, data=dict(SERVICE_DATA, base_directory=path))
                self.assertTrue(form.is_valid(), form.errors)
                form.handle(self.request, form.cleaned_data)
                source = create.call_args.args[5]
                if path.strip():
                    self.assertEqual(path, source['base_directory'])
                else:
                    self.assertNotIn('base_directory', source)

    @mock.patch.object(coast, 'service_create', return_value={'id': 'svc'})
    def test_image_source(self, create):
        data = dict(SERVICE_DATA, source_type='image', image='nginx',
                    tag='stable', repo_url='invalid hidden value',
                    branch='', build_pack='invalid', base_directory='/ignored')
        form = service_forms.CreateService(self.request, data=data)
        self.assertTrue(form.is_valid(), form.errors)
        form.handle(self.request, form.cleaned_data)
        self.assertEqual({'type': 'image', 'image': 'nginx', 'tag': 'stable'},
                         create.call_args.args[5])

    def test_required_source_fields(self):
        for kind, fields in [('git', ('repo_url', 'branch', 'build_pack')),
                             ('image', ('image', 'tag'))]:
            for field in fields:
                data = dict(SERVICE_DATA, source_type=kind,
                            image='nginx', tag='stable')
                data[field] = ''
                form = service_forms.CreateService(self.request, data=data)
                self.assertFalse(form.is_valid())
                self.assertIn(field, form.errors)

    def test_invalid_source_type(self):
        form = service_forms.CreateService(
            self.request, data=dict(SERVICE_DATA, source_type='unknown'))
        self.assertFalse(form.is_valid())
        self.assertIn('source_type', form.errors)


class WorkerLabelTests(FormTests):
    def test_worker_choices_use_stack_name(self):
        with mock.patch.object(coast, 'stack_list', return_value=[
                {'id': 's1', 'name': 'teststack'}]):
            form = service_forms.CreateService(self.request)
        labels = dict(form.fields['server_id'].choices)
        self.assertEqual('teststack / worker', labels['v1'])
        self.assertEqual('s2 / worker2', labels['v2'])


class ParentFormTests(helpers.TestCase):
    cases = [
        (appgroup_forms.CreateAppgroup, 'stack', 'appgroup'),
        (environment_forms.CreateEnvironment, 'appgroup', 'environment')]

    def setUp(self):
        super().setUp()
        self.request._messages = FallbackStorage(self.request)

    def test_create_and_parent_validation(self):
        for cls, parent, resource in self.cases:
            rows = [{'id': 'active', 'name': 'Ready', 'status': 'ACTIVE'},
                    {'id': 'pending', 'name': 'Busy', 'status': 'PENDING'}]
            with mock.patch.object(
                    coast, parent + '_list', return_value=rows), \
                    mock.patch.object(coast, resource + '_create',
                                      return_value={'id': 'new'}) as create:
                data = {parent + '_id': 'active', 'name': 'demo'}
                form = cls(self.request, data=data)
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual({'id': 'new'},
                                 form.handle(self.request, form.cleaned_data))
                create.assert_called_once_with(self.request, **data)
                for value in ('pending', 'unknown', ''):
                    form = cls(self.request, data=dict(
                        data, **{parent + '_id': value}))
                    self.assertFalse(form.is_valid())
                    self.assertIn(parent + '_id', form.errors)
                for name in ('', 'x' * 256):
                    form = cls(self.request, data=dict(data, name=name))
                    self.assertFalse(form.is_valid())
                    self.assertIn('name', form.errors)

    def test_create_failure(self):
        for cls, parent, resource in self.cases:
            with mock.patch.object(coast, parent + '_list', return_value=[
                    {'id': 'p', 'name': 'Ready', 'status': 'ACTIVE'}]), \
                    mock.patch.object(coast, resource + '_create',
                                      side_effect=RuntimeError('private')):
                form = cls(self.request, data={parent + '_id': 'p',
                                               'name': 'demo'})
                self.assertTrue(form.is_valid(), form.errors)
                self.assertFalse(form.handle(self.request, form.cleaned_data))
                label = resource.replace('appgroup', 'app group')
                self.assertIn('Unable to create ' + label, str(form.errors))
                self.assertNotIn('private', str(form.errors))

    def test_choices_failure(self):
        for cls, parent, resource in self.cases:
            with mock.patch.object(coast, parent + '_list',
                                   side_effect=RuntimeError()):
                form = cls(self.request, data={parent + '_id': 'p',
                                               'name': 'demo'})
                self.assertFalse(form.is_valid())
                self.assertIn(parent + '_id', form.errors)
