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

from unittest import mock

from coast_dashboard.api import coast
from coast_dashboard.content.services import files
from coast_dashboard.tests import helpers
from coast_dashboard.tests import test_api
from coast_dashboard.tests import test_navigation_settings as nav


MOUNT = {'id': 'file-id', 'container_path': '/etc/site.conf',
         'resource_name': None}


class FilesTests(helpers.TestCase):
    setUp = nav.NavigationSettingsTests.setUp
    list_services = nav.NavigationSettingsTests.list_services
    get_service = nav.NavigationSettingsTests.get_service
    update_service = nav.NavigationSettingsTests.update_service
    url = nav.NavigationSettingsTests.url

    def use_role(self, role):
        self.setActiveUser(
            id=self.user.id, token=self.token, username=self.user.name,
            tenant_id=self.tenant.id, service_catalog=self.service_catalog,
            roles=[{'name': role}])

    @mock.patch.object(coast, 'file_mount_list', return_value=[MOUNT])
    def test_files_tab_on_apps_and_template_services(self, listing):
        for panel, row in (('services', nav.APP), ('oneclick', nav.SERVICE)):
            response = self.client.get(self.url(panel, 'detail', [row['id']]) +
                                       '?tab=service_details__files')
            self.assertEqual(200, response.status_code)
            listing.assert_called_with(mock.ANY, row['id'])
            self.assertEqual([MOUNT],
                             response.context['files_table'].data)

    @mock.patch.object(coast, 'file_mount_create', return_value=MOUNT)
    def test_create_empty_and_whitespace_content(self, create):
        for panel, row in (('services', nav.APP), ('oneclick', nav.SERVICE)):
            for content in ('', '  line\n\n'):
                values = {'container_path': '/etc/site.conf',
                          'content': content}
                if panel == 'oneclick':
                    values['resource_name'] = 'database'
                response = self.client.post(
                    self.url(panel, 'add_file', [row['id']]), values)
                self.assertEqual(302, response.status_code)
                self.assertIn('tab=service_details__files',
                              response['Location'])
                create.assert_called_with(mock.ANY, row['id'], values)
                self.assertTrue(any('Redeploy needed' in str(message)
                                    for message in response.wsgi_request
                                    ._messages))

    @mock.patch.object(coast, 'file_mount_get', return_value=MOUNT)
    @mock.patch.object(coast, 'file_mount_update', return_value=MOUNT)
    def test_edit_preserves_or_replaces_content(self, update, get):
        url = self.url('services', 'edit_file', ['app-id', 'file-id'])
        response = self.client.get(url)
        self.assertEqual('/etc/site.conf',
                         response.context['form'].initial['container_path'])
        self.assertNotIn('content', response.context['form'].initial)
        for replacement, content in ((False, ''), (True, ''),
                                     (True, '  new\n')):
            data = {'container_path': '/etc/renamed.conf', 'content': content}
            if replacement:
                data['replace_content'] = 'on'
            response = self.client.post(url, data)
            self.assertEqual(302, response.status_code)
            expected = {'container_path': '/etc/renamed.conf'}
            if replacement:
                expected['content'] = content
            update.assert_called_with(mock.ANY, 'app-id', 'file-id', expected)
        update.reset_mock()
        response = self.client.post(url, {
            'container_path': '/etc/site.conf', 'content': 'not selected'})
        self.assertEqual(200, response.status_code)
        self.assertIn('replace_content', response.context['form'].errors)
        update.assert_not_called()

    @mock.patch.object(coast, 'file_mount_create')
    def test_content_validation_uses_utf8_bytes(self, create):
        for content in ('é' * 32769, 'has\x00nul', '\ud800'):
            form = files.FileForm(self.request, service_id='app-id', data={
                'container_path': '/etc/file', 'content': content})
            self.assertFalse(form.is_valid())
            self.assertIn('content', form.errors)
        form = files.FileForm(self.request, service_id='app-id', data={
            'container_path': '/etc/file', 'content': 'é' * 32768})
        self.assertTrue(form.is_valid(), form.errors)
        create.assert_not_called()

    @mock.patch.object(coast, 'file_mount_create')
    def test_api_faults_are_shown_and_content_is_not_in_messages(self, create):
        create.side_effect = coast.CoastError('Container path is forbidden.')
        response = self.client.post(
            self.url('services', 'add_file', ['app-id']),
            {'container_path': '/proc/file', 'content': 'private value'})
        self.assertEqual(200, response.status_code)
        self.assertIn('Container path is forbidden.',
                      response.context['form'].non_field_errors())
        self.assertFalse(any('private value' in str(message)
                             for message in response.wsgi_request._messages))

    @mock.patch.object(coast, 'file_mount_delete')
    @mock.patch.object(coast, 'file_mount_list', return_value=[MOUNT])
    def test_delete_roles_and_faults(self, listing, delete):
        target = self.url('services', 'detail', ['app-id'])
        for role, allowed in (('reader', False), ('member', False),
                              ('manager', True)):
            self.use_role(role)
            delete.reset_mock()
            response = self.client.post(target, {
                'action': 'files__delete__file-id'})
            if allowed:
                delete.assert_called_once_with(mock.ANY, 'app-id', 'file-id')
            else:
                delete.assert_not_called()
        delete.side_effect = coast.CoastError('File is busy.')
        response = self.client.post(target, {
            'action': 'files__delete__file-id'}, follow=True)
        self.assertContains(response, 'File is busy.')

    @mock.patch.object(coast, 'file_mount_create')
    @mock.patch.object(coast, 'file_mount_update')
    def test_reader_cannot_post_forms(self, update, create):
        self.use_role('reader')
        for view, args in (('add_file', ['app-id']),
                           ('edit_file', ['app-id', 'file-id'])):
            response = self.client.post(self.url('services', view, args), {
                'container_path': '/etc/file', 'content': 'text'})
            self.assertNotEqual(200, response.status_code)
        update.assert_not_called()
        create.assert_not_called()

    @mock.patch.object(coast, 'file_mount_get', return_value=MOUNT)
    def test_template_container_field_only_on_templates(self, get):
        for panel, row, template in (('services', nav.APP, False),
                                     ('oneclick', nav.SERVICE, True)):
            response = self.client.get(self.url(panel, 'edit_file',
                                                [row['id'], 'file-id']))
            fields = response.context['form'].fields
            self.assertEqual(template, 'resource_name' in fields)


class FileMountApiTests(helpers.TestCase):
    @mock.patch.object(coast, 'coastclient')
    def test_crud_uses_adapter_at_115_without_retries_or_logging(self, client):
        adapter = client.return_value.adapter.request
        adapter.return_value = test_api._resp({'file_mounts': [MOUNT],
                                               'file_mount': MOUNT})
        self.assertEqual([MOUNT], coast.file_mount_list(self.request, 'svc'))
        self.assertEqual(MOUNT, coast.file_mount_get(self.request, 'svc', 'f'))
        values = {'container_path': '/etc/site.conf', 'content': ''}
        self.assertEqual(MOUNT, coast.file_mount_create(
            self.request, 'svc', values))
        self.assertEqual(MOUNT, coast.file_mount_update(
            self.request, 'svc', 'f', values))
        adapter.return_value = mock.Mock(content=b'')
        coast.file_mount_delete(self.request, 'svc', 'f')
        base = '/services/svc/file_mounts'
        version = dict(microversion='1.15', log=False,
                       connect_retries=0, status_code_retries=0)
        self.assertEqual([
            mock.call(base, 'GET', **version),
            mock.call(base + '/f', 'GET', **version),
            mock.call(base, 'POST', json={'file_mount': values}, **version),
            mock.call(base + '/f', 'PATCH', json={'file_mount': values},
                      **version),
            mock.call(base + '/f', 'DELETE', **version)],
            adapter.call_args_list)
        client.return_value.request.assert_not_called()
        for call in client.call_args_list:
            self.assertEqual(mock.call(self.request, '1.0'), call)

    @mock.patch.object(coast, 'coastclient')
    def test_fault_is_preserved_without_logging_content(self, client):
        response = mock.Mock(status_code=400)
        response.json.return_value = {
            'faultstring': 'Container path rejected.'}
        adapter = client.return_value.adapter.request
        adapter.side_effect = coast.client_exceptions.BadRequest(
            response=response)
        with self.assertRaises(coast.CoastError) as raised:
            coast.file_mount_create(self.request, 'svc', {'content': 'secret'})
        self.assertEqual('Container path rejected.',
                         raised.exception.api_message)
        self.assertFalse(adapter.call_args.kwargs['log'])
