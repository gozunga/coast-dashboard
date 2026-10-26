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

from coast_dashboard.api import coast
from coast_dashboard.content import common
from coast_dashboard.content.services import forms as service_forms
from coast_dashboard.tests import helpers
from coast_dashboard.tests import test_navigation_settings as nav

IMAGE = dict(nav.APP, id='image-id', name='cache', kind='service')
ROWS = [
    {'id': 'bind-id', 'type': 'bind', 'source': '/srv/data',
     'container_path': '/data', 'read_only': False, 'origin': 'user'},
    {'id': 'volume-id', 'type': 'volume', 'source': 'pgdata',
     'size_gb': 10, 'container_path': '/var/lib/postgresql/data',
     'read_only': False, 'origin': 'user'},
    {'id': None, 'type': 'bind', 'source': '/var/run/docker.sock',
     'container_path': '/var/run/docker.sock', 'read_only': True,
     'origin': 'template'},
]


class StorageTests(helpers.TestCase):
    list_services = nav.NavigationSettingsTests.list_services
    get_service = nav.NavigationSettingsTests.get_service
    update_service = nav.NavigationSettingsTests.update_service
    url = nav.NavigationSettingsTests.url

    def setUp(self):
        nav.NavigationSettingsTests.setUp(self)
        roles = mock.patch(
            'coast_dashboard.content.common.project_roles',
            return_value={'member', 'manager'})
        roles.start()
        self.addCleanup(roles.stop)
        supported = mock.patch.object(coast, 'storage_supported',
                                      return_value=True)
        self.supported = supported.start()
        self.addCleanup(supported.stop)
        listing = mock.patch.object(coast, 'storage_list', return_value=ROWS)
        self.listing = listing.start()
        self.addCleanup(listing.stop)

    def tab(self, panel, service_id):
        return self.client.get(self.url(panel, 'detail', [service_id]) +
                               '?tab=service_details__storage')

    def test_list_types_paths_and_template_actions(self):
        self.records[IMAGE['id']] = dict(IMAGE)
        for panel, row in (('services', nav.APP), ('oneclick', IMAGE)):
            response = self.tab(panel, row['id'])
            self.listing.assert_called_with(mock.ANY, 'stack-id', row['id'])
            for text in ('Bind mount (host folder)', 'Named volume',
                         '/srv/data', 'pgdata', '/var/lib/postgresql/data',
                         '/var/run/docker.sock', 'from template'):
                self.assertContains(response, text)
            self.assertContains(response, 'bind-id/edit/')
            self.assertContains(response, 'volume-id/edit/')
            self.assertNotContains(response, 'template-2/edit/')
            self.assertNotContains(response, 'storage__delete__template-2')

    def test_template_service_user_mounts_are_editable(self):
        response = self.tab('oneclick', nav.SERVICE['id'])
        self.assertContains(response, 'Create Storage')
        self.assertContains(response, 'bind-id/edit/')
        self.assertContains(response, 'volume-id/edit/')
        self.assertNotContains(response, 'template-2/edit/')

    @mock.patch.object(coast, 'storage_create')
    def test_create_each_type(self, create):
        url = self.url('services', 'create_storage', [nav.APP['id']])
        response = self.client.get(url)
        self.assertEqual(200, response.status_code)
        self.assertEqual('type', next(iter(response.context['form'].fields)))
        for kind, extra in (('bind', {'host_path': '/srv/my data'}),
                            ('volume', {'name': 'pgdata', 'size_gb': 10})):
            data = dict(type=kind, container_path='/data', read_only=True,
                        **extra)
            response = self.client.post(url, data)
            self.assertEqual(302, response.status_code)
            create.assert_called_with(mock.ANY, 'stack-id',
                                      dict(data, service_id='app-id'))

    @mock.patch.object(coast, 'storage_create')
    def test_validation_and_inactive_fields(self, create):
        url = self.url('services', 'create_storage', [nav.APP['id']])
        for data, errors in (
                ({'type': 'bind', 'host_path': 'relative'},
                 ('host_path', 'container_path')),
                ({'type': 'volume', 'name': '-bad', 'size_gb': 0,
                  'container_path': 'relative'},
                 ('name', 'size_gb', 'container_path')),
                ({'type': 'invalid', 'container_path': '/data'}, ('type',)),
                ({'type': 'volume', 'container_path': '/data'},
                 ('name', 'size_gb'))):
            response = self.client.post(url, data)
            for field in errors:
                self.assertIn(field, response.context['form'].errors)
        create.assert_not_called()
        response = self.client.post(url, {
            'type': 'bind', 'host_path': '/', 'container_path': '/data',
            'name': '-bad', 'size_gb': 'bad'})
        self.assertEqual(302, response.status_code)
        create.assert_called_once_with(mock.ANY, 'stack-id', {
            'type': 'bind', 'host_path': '/', 'container_path': '/data',
            'read_only': False, 'service_id': 'app-id'})

    def test_merged_api_path_validation(self):
        invalid = {
            'host_path': ('//srv', '/srv//data', '/srv/', '/srv/../data',
                          '/srv/./data', '/srv:data', '/srv\\data',
                          '/srv\tdata', '/srv\x7fdata', '/srv\ndata'),
            'container_path': ('/', '/data/', '/data//child', '/data/..',
                               '/data/.', '/my data', '/data:child',
                               '/data\\child', '/data\n', '/' + 'a' * 255),
        }
        for field, paths in invalid.items():
            for path in paths:
                with self.subTest(field=field, path=path):
                    data = dict(type='bind', host_path='/srv',
                                container_path='/data')
                    data[field] = path
                    form = service_forms.CreateStorage(
                        mock.Mock(), data=data, service_id='app-id',
                        stack_id='stack-id')
                    self.assertFalse(form.is_valid())
                    self.assertIn(field, form.errors)
        for path in ('/', '/srv/my data', '/srv/data '):
            form = service_forms.CreateStorage(mock.Mock(), data={
                'type': 'bind', 'host_path': path, 'container_path': '/data'},
                service_id='app-id', stack_id='stack-id')
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(path, form.cleaned_data['host_path'])

    @mock.patch.object(coast, 'storage_delete')
    def test_delete_requires_manager_or_admin(self, delete):
        target = self.url('services', 'detail', [nav.APP['id']])
        for roles, allowed in (({'member'}, False), ({'reader'}, False),
                               ({'manager'}, True),
                               ({'admin'}, True)):
            with self.subTest(roles=roles), mock.patch(
                    'coast_dashboard.content.common.project_roles',
                    return_value=roles):
                delete.reset_mock()
                self.client.post(target, {
                    'action': 'storage__delete__bind-id'})
                self.assertEqual(allowed, delete.called)

    def test_anonymous_template_volume(self):
        self.listing.return_value = [dict(
            ROWS[2], type='volume', source=None)]
        response = self.tab('services', nav.APP['id'])
        self.assertContains(response, 'Anonymous volume')
        self.assertContains(response, 'from template')
        self.assertNotContains(response, 'storage__delete__template-0')

    @mock.patch.object(coast, 'storage_update')
    def test_edit_each_type(self, update):
        for row in ROWS[:2]:
            url = self.url('services', 'edit_storage',
                           [nav.APP['id'], row['id']])
            response = self.client.get(url)
            form = response.context['form']
            field = 'host_path' if row['type'] == 'bind' else 'name'
            self.assertEqual(row['source'], form.initial[field])
            data = dict(type=row['type'], container_path='/new',
                        read_only=True, **{field: row['source']})
            self.assertTrue(form.fields['type'].disabled)
            self.assertNotIn('size_gb', form.fields)
            self.assertEqual(302, self.client.post(url, data).status_code)
            expected = {key: value for key, value in data.items()
                        if key != 'type'}
            update.assert_called_with(mock.ANY, 'stack-id', row['id'],
                                      expected)

    @mock.patch.object(coast, 'storage_update')
    def test_edit_ignores_type_and_size_changes(self, update):
        for row in ROWS[:2]:
            url = self.url('oneclick', 'edit_storage',
                           [nav.SERVICE['id'], row['id']])
            field = 'host_path' if row['type'] == 'bind' else 'name'
            data = dict(type='volume' if row['type'] == 'bind' else 'bind',
                        container_path='/new', size_gb=999,
                        **{field: row['source']})
            self.assertEqual(302, self.client.post(url, data).status_code)
            update.assert_called_with(mock.ANY, 'stack-id', row['id'], {
                field: row['source'],
                'container_path': '/new', 'read_only': False})

    def test_paths_reject_control_characters(self):
        url = self.url('services', 'create_storage', [nav.APP['id']])
        for field in ('host_path', 'container_path'):
            for value in ('/data\nother', '/data\rother', '/data\x00other'):
                data = dict(type='bind', host_path='/srv',
                            container_path='/data')
                data[field] = value
                response = self.client.post(url, data)
                self.assertIn(field, response.context['form'].errors)

    def test_edit_read_failure_redirects_with_error(self):
        self.listing.side_effect = coast.CoastError('Storage unavailable')
        response = self.client.get(self.url(
            'services', 'edit_storage', [nav.APP['id'], 'bind-id']))
        self.assertEqual(302, response.status_code)
        self.assertEqual(self.url('services', 'detail', [nav.APP['id']]),
                         response.url)
        self.assertIn('Storage unavailable', ' '.join(
            str(message) for message in response.wsgi_request._messages))

    @mock.patch.object(coast, 'storage_update',
                       side_effect=coast.CoastError('Cannot update mount'))
    def test_edit_api_error_keeps_form(self, update):
        response = self.client.post(self.url(
            'services', 'edit_storage', [nav.APP['id'], 'bind-id']), {
                'host_path': '/srv/new', 'container_path': '/new'})
        self.assertEqual(200, response.status_code)
        self.assertContains(response, 'Cannot update mount')
        self.assertEqual('/srv/new',
                         response.context['form']['host_path'].value())

    @mock.patch.object(coast, 'storage_delete')
    def test_delete_each_type_and_protect_template(self, delete):
        url = self.url('services', 'detail', [nav.APP['id']])
        for row in ROWS[:2]:
            self.client.post(url, {'action': 'storage__delete__' + row['id']})
            delete.assert_called_with(mock.ANY, 'stack-id', row['id'])
        delete.reset_mock()
        self.client.post(url, {'action': 'storage__delete__template-2'})
        delete.assert_not_called()

    @mock.patch.object(coast, 'storage_update')
    @mock.patch.object(coast, 'storage_create')
    def test_direct_mutations_are_protected(self, create, update):
        url = self.url('services', 'edit_storage',
                       [nav.APP['id'], 'foreign-id'])
        self.assertEqual(403, self.client.post(url, {}).status_code)
        create.assert_not_called()
        update.assert_not_called()

    @mock.patch.object(coast, 'storage_update')
    @mock.patch.object(coast, 'storage_delete')
    def test_template_row_cannot_be_changed(self, delete, update):
        self.listing.return_value = [dict(ROWS[2], id='template-id')]
        url = self.url('services', 'edit_storage',
                       [nav.APP['id'], 'template-id'])
        self.assertEqual(403, self.client.post(url, {}).status_code)
        target = self.url('services', 'detail', [nav.APP['id']])
        self.client.post(target, {'action': 'storage__delete__template-id'})
        update.assert_not_called()
        delete.assert_not_called()

    @mock.patch('coast_dashboard.content.common.project_roles',
                return_value={'reader'})
    @mock.patch.object(coast, 'storage_delete')
    def test_reader_has_no_write_actions(self, delete, member):
        response = self.tab('services', nav.APP['id'])
        self.assertNotContains(response, 'Create Storage')
        self.assertNotContains(response, 'bind-id/edit/')
        target = self.url('services', 'detail', [nav.APP['id']])
        self.client.post(target, {'action': 'storage__delete__bind-id'})
        delete.assert_not_called()
        for action, args in (('create_storage', [nav.APP['id']]),
                             ('edit_storage', [nav.APP['id'], 'bind-id'])):
            self.assertEqual(403, self.client.post(
                self.url('services', action, args), {}).status_code)

    def test_lower_api_hides_tab_and_blocks_forms(self):
        self.supported.return_value = False
        response = self.tab('services', nav.APP['id'])
        self.assertNotContains(response, 'Create Storage')
        self.listing.assert_not_called()
        url = self.url('services', 'create_storage', [nav.APP['id']])
        self.assertEqual(403, self.client.get(url).status_code)

    @mock.patch.object(coast, 'storage_create',
                       side_effect=coast.CoastError('Cannot mount path'))
    def test_api_error_keeps_form(self, create):
        response = self.client.post(
            self.url('services', 'create_storage', [nav.APP['id']]),
            {'type': 'bind', 'host_path': '/srv', 'container_path': '/data'})
        self.assertEqual(200, response.status_code)
        self.assertContains(response, 'Cannot mount path')


class StorageApiTests(helpers.TestCase):
    def test_project_role_formats(self):
        for roles, member, manager in (
                (['MEMBER'], True, False),
                ([{'name': 'manager'}], False, True),
                ([SimpleNamespace(name='admin')], True, True),
                ([{'name': 'reader'}, {}], False, False),
                (None, False, False)):
            request = SimpleNamespace(user=SimpleNamespace(roles=roles))
            self.assertEqual(member, common.project_member(request))
            self.assertEqual(manager, common.project_manager(request))

    def test_version_discovery(self):
        for version, expected in (('1.18', False), ('1.19', True),
                                  ('1.20', True), ('invalid', False)):
            with mock.patch.object(coast, '_get', return_value={
                    'version': {'max_version': version}}):
                self.assertEqual(expected,
                                 coast.storage_supported(object()))
        with mock.patch.object(coast, '_get', side_effect=coast.CoastError):
            self.assertFalse(coast.storage_supported(object()))

    def test_pagination_keeps_service_filter(self):
        with mock.patch.object(coast, '_get', side_effect=[
                {'storages': [ROWS[0]], 'links': [
                    {'rel': 'next', 'href': '/storages?marker=bind-id'}]},
                {'storages': ROWS[1:]}]) as get:
            self.assertEqual(ROWS, coast.storage_list(None, 'st', 'sv'))
        self.assertEqual('/stacks/st/storages?service_id=sv&marker=bind-id',
                         get.call_args.args[1])

    def test_api_paths_and_payloads(self):
        with mock.patch.object(coast, '_request') as request:
            request.return_value.content = b''
            for kind, extra in (('bind', {'host_path': '/srv'}),
                                ('volume', {'name': 'pgdata', 'size_gb': 10})):
                values = dict(type=kind, container_path='/data',
                              read_only=False, **extra)
                coast.storage_create(None, 'st', dict(values, service_id='sv'))
                edits = {key: value for key, value in values.items()
                         if key not in ('type', 'size_gb')}
                coast.storage_update(None, 'st', 'id', edits)
                coast.storage_delete(None, 'st', 'id')
            coast.storage_list(None, 'st', 'sv')
        calls = request.call_args_list
        for call in calls:
            self.assertEqual(coast.STORAGE_VERSION,
                             call.kwargs['microversion'])
        self.assertEqual('/stacks/st/storages?service_id=sv',
                         calls[-1].args[1])
        self.assertEqual('GET', calls[-1].args[2])
        for offset, kind in ((0, 'bind'), (3, 'volume')):
            self.assertEqual('POST', calls[offset].args[2])
            body = calls[offset].kwargs['json']['storage']
            self.assertEqual(kind, body['type'])
            self.assertEqual('sv', body['service_id'])
            self.assertEqual('PATCH', calls[offset + 1].args[2])
            edits = calls[offset + 1].kwargs['json']['storage']
            self.assertEqual({'container_path', 'read_only',
                              'host_path' if kind == 'bind' else 'name'},
                             set(edits))
            self.assertEqual('/stacks/st/storages/id',
                             calls[offset + 1].args[1])
            self.assertEqual('DELETE', calls[offset + 2].args[2])
