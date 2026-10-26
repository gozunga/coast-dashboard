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
from coast_dashboard.content.services import backups
from coast_dashboard.tests import helpers
from coast_dashboard.tests import test_api
from coast_dashboard.tests import test_navigation_settings as nav


POLICY = {'enabled': False, 'hour': 2, 'minute': 0,
          'keep_daily': 14, 'keep_weekly': 8,
          'engine': 'postgres', 'container': 'postgresql'}
POLICY_DATA = {'schedule': 'off', 'time': '02:00',
               'keep_daily': 14, 'keep_weekly': 8,
               'engine': 'postgres', 'container': 'postgresql'}
DEFAULT_POLICY = dict(POLICY, engine=None, container=None)
BACKUP = {'id': 'backup-id', 'service_id': 'service-id', 'kind': 'manual',
          'status': 'ACTIVE', 'size_bytes': 1024, 'duration_seconds': 3,
          'started_at': '2026-10-19T02:00:00Z',
          'finished_at': '2026-10-19T02:00:03Z', 'error': None,
          'engine': 'postgres', 'engine_version': '17'}


class BackupTests(helpers.TestCase):
    list_services = nav.NavigationSettingsTests.list_services
    get_service = nav.NavigationSettingsTests.get_service
    update_service = nav.NavigationSettingsTests.update_service
    url = nav.NavigationSettingsTests.url

    def setUp(self):
        nav.NavigationSettingsTests.setUp(self)
        for name, value in (('backups_supported', True),
                            ('backup_policy_get', POLICY),
                            ('backup_list', [dict(BACKUP)]),
                            ('backup_get', BACKUP)):
            patcher = mock.patch.object(coast, name, return_value=value)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def use_role(self, role):
        self.setActiveUser(
            id=self.user.id, token=self.token, username=self.user.name,
            tenant_id=self.tenant.id, service_catalog=self.service_catalog,
            roles=[{'name': role}])

    def action(self, name, backup=True):
        args = ['service-id', 'backup-id'] if backup else ['service-id']
        return self.url('oneclick', name, args)

    def tab(self):
        return self.client.get(self.action('detail', backup=False) +
                               '?tab=service_details__backups')

    def test_database_engines_only(self):
        for engine in ('postgres', 'postgresql', 'mysql', 'mariadb',
                       'mongo', 'mongodb'):
            for source in ({'template_id': engine},
                           {'source': {'type': 'template',
                                       'template_id': engine}},
                           {'engine': engine, 'template_id': engine}):
                self.assertTrue(backups.is_database(dict(
                    source, kind='service')))
        for row in (nav.APP, dict(nav.SERVICE, source={}),
                    dict(nav.SERVICE, source={}, engine='postgres'),
                    dict(nav.SERVICE, source={'template_id': 'redis'}),
                    dict(nav.SERVICE, kind='app')):
            self.assertFalse(backups.is_database(row))

    def test_database_policy_and_history_load(self):
        response = self.tab()
        self.assertEqual(200, response.status_code)
        self.backup_list.assert_called_once_with(mock.ANY, 'service-id')
        self.assertEqual('off', response.context['policy_form'].initial[
            'schedule'])
        row = response.context['backups'][0]
        self.assertTrue(row['ready'])
        self.assertTrue(row['can_delete'])

    def test_old_api_hides_tab_without_loading_data(self):
        self.backups_supported.return_value = False
        response = self.tab()
        self.assertEqual(200, response.status_code)
        self.backup_policy_get.assert_not_called()
        self.backup_list.assert_not_called()
        self.assertNotContains(response, 'service_details__backups')

    def test_other_service_does_not_probe_backup_api(self):
        self.records['service-id']['source'] = {'template_id': 'redis'}
        self.tab()
        self.backups_supported.assert_not_called()
        self.backup_list.assert_not_called()

    def test_unsaved_policy_and_empty_history(self):
        self.backup_policy_get.return_value = DEFAULT_POLICY
        response = self.tab()
        self.assertFalse(response.context['policy_configured'])
        form = response.context['policy_form']
        self.assertIsNone(form.initial['engine'])
        self.assertIsNone(form.initial['container'])
        self.backup_list.return_value = []
        self.assertEqual([], self.tab().context['backups'])

    def test_saved_policy_round_trip(self):
        self.backup_policy_get.return_value = dict(
            POLICY, enabled=True, hour=23, minute=59, engine='mariadb',
            container='database-main', keep_daily=0, keep_weekly=104)
        response = self.tab()
        self.assertTrue(response.context['policy_configured'])
        initial = response.context['policy_form'].initial
        self.assertEqual('daily', initial['schedule'])
        self.assertEqual('23:59', initial['time'])
        self.assertEqual('mariadb', initial['engine'])
        self.assertEqual('database-main', initial['container'])
        form = backups.PolicyForm(initial)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(self.backup_policy_get.return_value, form.policy())

    def test_history_failure_keeps_error_state(self):
        self.backup_list.side_effect = coast.CoastError()
        response = self.tab()
        self.assertEqual('Unable to retrieve backups.',
                         response.context['backups_error'])
        self.assertNotContains(response, 'Back up now')

    def test_readers_have_no_mutation_or_download_access(self):
        self.use_role('reader')
        response = self.tab()
        self.assertFalse(response.context['can_manage'])
        self.assertTrue(all(field.disabled for field in
                            response.context['policy_form'].fields.values()))
        for action in ('backup_restore', 'backup_delete', 'backup_download',
                       'backups'):
            url = self.action(action, backup=action != 'backups')
            self.assertEqual(403, self.client.post(url).status_code)
        self.assertEqual(403, self.client.get(self.action(
            'backup_download')).status_code)

    def test_direct_actions_require_database_and_supported_version(self):
        for unsupported in ('version', 'engine'):
            if unsupported == 'version':
                self.backups_supported.return_value = False
            else:
                self.backups_supported.return_value = True
                self.records['service-id']['source'] = {'template_id': 'redis'}
            self.assertEqual(404, self.client.post(self.action(
                'backups', backup=False), {'operation': 'create'}).status_code)

    def test_backup_ownership_required_for_every_action(self):
        self.backup_get.return_value = dict(BACKUP, service_id='other-service')
        for action in ('backup_restore', 'backup_delete', 'backup_download'):
            self.assertEqual(404, self.client.get(
                self.action(action)).status_code)
            self.assertEqual(404, self.client.post(
                self.action(action)).status_code)

    def test_lookup_failure_returns_to_tab(self):
        self.backup_get.side_effect = coast.CoastError()
        response = self.client.get(self.action('backup_restore'))
        self.assertEqual(302, response.status_code)
        self.assertIn('service_details__backups', response['Location'])
        self.backup_get.side_effect = coast.exceptions.NotFound()
        self.assertEqual(404, self.client.get(self.action(
            'backup_restore')).status_code)

    def test_history_order_and_failed_backup_actions(self):
        self.backup_list.return_value = [
            dict(BACKUP, started_at='2026-10-18T02:00:00Z'),
            dict(BACKUP, id='newest', kind='safety', status='ERROR')]
        rows = self.tab().context['backups']
        self.assertEqual('newest', rows[0]['id'])
        self.assertFalse(rows[0]['ready'])
        self.assertTrue(rows[0]['can_delete'])
        self.backup_list.return_value = [dict(BACKUP, status='unknown')]
        self.assertFalse(self.tab().context['backups'][0]['can_delete'])

    @mock.patch.object(coast, 'backup_policy_update')
    def test_policy_schedules_and_retention(self, update):
        for schedule in ('off', 'daily'):
            for engine in ('postgres', 'mysql', 'mariadb', 'mongodb'):
                data = dict(POLICY_DATA, operation='save', schedule=schedule,
                            engine=engine, time='19:35')
                response = self.client.post(
                    self.action('backups', False), data)
                self.assertEqual(302, response.status_code)
                expected = dict(POLICY, enabled=schedule == 'daily',
                                hour=19, minute=35, engine=engine)
                update.assert_called_with(mock.ANY, 'service-id', expected)

    @mock.patch.object(coast, 'backup_policy_update')
    def test_invalid_policy_never_writes(self, update):
        for change in ({'schedule': 'bad'}, {'schedule': 'hourly'},
                       {'schedule': 'weekly'}, {'time': '25:00'},
                       {'keep_daily': '-1'}, {'keep_daily': '366'},
                       {'keep_weekly': '105'}, {'time': ''},
                       {'engine': ''}, {'engine': 'redis'},
                       {'container': ''}, {'container': '../db'},
                       {'container': 'a' * 129}):
            data = dict(POLICY_DATA, operation='save', schedule='daily')
            data.update(change)
            self.client.post(self.action('backups', False), data)
        update.assert_not_called()

    def test_off_does_not_require_time(self):
        form = backups.PolicyForm(dict(POLICY_DATA, time=''))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(POLICY, form.policy())

    @mock.patch.object(coast, 'backup_create')
    def test_manual_backup_requires_saved_policy(self, create):
        self.backup_policy_get.return_value = DEFAULT_POLICY
        response = self.client.post(self.action('backups', False), {
            'operation': 'create'})
        self.assertEqual(302, response.status_code)
        create.assert_not_called()
        self.assertTrue(any('save the backup policy first' in str(message)
                            for message in response.wsgi_request._messages))

    @mock.patch.object(coast, 'backup_policy_update')
    @mock.patch.object(coast, 'backup_create')
    def test_storage_unavailable_from_mutation_fault(self, create, update):
        fault = coast.CoastError('Object storage not available.')
        create.side_effect = fault
        update.side_effect = fault
        for operation in ('save', 'create'):
            response = self.client.post(self.action('backups', False),
                                        dict(POLICY_DATA, operation=operation))
            self.assertEqual(302, response.status_code)
            self.assertTrue(any('Object storage not available. Contact your '
                                'cloud operator' in str(message) for message
                                in response.wsgi_request._messages))

    def test_overwrite_confirmation_display_and_escaping(self):
        from django.template.loader import render_to_string
        from django.utils.html import escape
        for native in (True, False):
            for name in ('postgresql', '<b>orders & apps</b>'):
                with mock.patch.object(backups, 'native_database',
                                       return_value=native):
                    for value in ('app', ' ' + name + ' ', name):
                        form = backups.RestoreForm(
                            self.request,
                            {'mode': 'overwrite', 'confirmation': value},
                            service={'name': name}, backup_id='backup-id')
                        self.assertEqual(value == name, form.is_valid())
                        self.assertEqual('Coast name' if native else
                                         'Service name',
                                         form.fields['confirmation'].label)
                        if value != name:
                            self.assertEqual(
                                ['Type %s to confirm overwrite.' % name],
                                form.errors['confirmation'])
                            self.assertIn(escape(name), str(form.errors))
                        html = render_to_string(
                            'project/coast_services/_restore.html',
                            {'form': form, 'page_title': 'Restore backup'},
                            request=self.request)
                        self.assertIn('<strong>%s</strong>' % escape(name),
                                      html)

    @mock.patch.object(coast, 'backup_restore')
    @mock.patch.object(coast, 'backup_delete')
    @mock.patch.object(coast, 'backup_download')
    def test_storage_fault_for_backup_actions(self, download, delete, restore):
        fault = coast.CoastError('Object storage not available.')
        for action in (download, delete, restore):
            action.side_effect = fault
        for action, data in (('backup_restore', {'mode': 'new_copy',
                                                 'name': 'db-copy'}),
                             ('backup_delete', {'confirm': 'on'})):
            response = self.client.post(self.action(action), data)
            self.assertEqual(200, response.status_code)
            self.assertIn('Object storage not available. Contact your cloud '
                          'operator', str(response.context['form']
                                          .non_field_errors()))
        response = self.client.get(self.action('backup_download'))
        self.assertEqual(302, response.status_code)
        self.assertTrue(any('Object storage not available. Contact your cloud '
                            'operator' in str(message) for message
                            in response.wsgi_request._messages))

    @mock.patch.object(coast, 'backup_create')
    def test_manual_backup_post_only_and_error(self, create):
        url = self.action('backups', False)
        self.assertEqual(405, self.client.get(url).status_code)
        response = self.client.post(url, {'operation': 'create'})
        self.assertEqual(302, response.status_code)
        create.assert_called_once_with(mock.ANY, 'service-id')
        create.side_effect = coast.CoastError()
        self.assertEqual(302, self.client.post(url, {
            'operation': 'create'}).status_code)
        self.assertEqual(403, self.client.post(url, {
            'operation': 'invalid'}).status_code)

    @mock.patch.object(coast, 'backup_restore')
    def test_restore_defaults_and_new_copy(self, restore):
        url = self.action('backup_restore')
        response = self.client.get(url)
        self.assertContains(response, '<strong>database</strong>')
        self.assertContains(response, 'Service name')
        ajax = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertContains(ajax, '<strong>database</strong>')
        self.assertEqual('new_copy', response.context['form'].initial['mode'])
        self.assertEqual('database-copy',
                         response.context['form'].initial['name'])
        response = self.client.post(url, {
            'mode': 'new_copy', 'name': 'db-copy'})
        self.assertEqual(302, response.status_code)
        restore.assert_called_once_with(mock.ANY, 'backup-id',
                                        'new_copy', 'db-copy', '')

    @mock.patch.object(coast, 'backup_restore')
    def test_restore_validation_and_overwrite_confirmation(self, restore):
        url = self.action('backup_restore')
        for data in ({'mode': 'new_copy', 'name': ''},
                     {'mode': 'new_copy', 'name': '../db'},
                     {'mode': 'new_copy', 'name': 'Bad_Name'},
                     {'mode': 'overwrite'},
                     {'mode': 'overwrite', 'confirmation': 'Database'},
                     {'mode': 'overwrite', 'confirmation': ' database '},
                     {'mode': 'invalid'}):
            response = self.client.post(url, data)
            self.assertEqual(200, response.status_code)
            self.assertTrue(response.context['form'].errors)
        restore.assert_not_called()
        response = self.client.post(url, {'mode': 'overwrite',
                                          'name': 'unused_name',
                                          'confirmation': 'database'})
        self.assertEqual(302, response.status_code)
        restore.assert_called_once_with(mock.ANY, 'backup-id',
                                        'overwrite', 'unused_name', 'database')

    @mock.patch.object(coast, 'backup_restore', side_effect=coast.CoastError())
    def test_restore_api_failure_keeps_form(self, restore):
        response = self.client.post(self.action('backup_restore'), {
            'mode': 'new_copy', 'name': 'copy'})
        self.assertEqual(200, response.status_code)
        self.assertTrue(response.context['form'].non_field_errors())

    def test_running_backup_blocks_restore_download_delete(self):
        self.backup_get.return_value = dict(BACKUP, status='running')
        for action in ('backup_restore', 'backup_download', 'backup_delete'):
            response = self.client.get(self.action(action))
            self.assertEqual(404, response.status_code)
        self.backup_list.return_value = [dict(BACKUP, status='running')]
        row = self.tab().context['backups'][0]
        self.assertFalse(row['ready'])
        self.assertFalse(row['can_delete'])

    @mock.patch.object(coast, 'backup_download')
    def test_download_stream_and_connection_cleanup(self, download):
        upstream = download.return_value
        upstream.iter_content.return_value = iter([b'first', b'second'])
        response = self.client.get(self.action('backup_download'))
        self.assertTrue(response.streaming)
        self.assertEqual(b'firstsecond', b''.join(response.streaming_content))
        self.assertEqual('no-store', response['Cache-Control'])
        self.assertEqual('no-referrer', response['Referrer-Policy'])
        self.assertEqual('attachment; filename="backup-id.dump.gz"',
                         response['Content-Disposition'])
        upstream.iter_content.assert_called_once_with(chunk_size=65536)
        upstream.close.assert_called_once_with()

    @mock.patch.object(coast, 'backup_download')
    def test_download_close_without_reading_and_api_error(self, download):
        upstream = download.return_value
        upstream.iter_content.return_value = iter([b'first', b'second'])
        response = self.client.get(self.action('backup_download'))
        response.close()
        upstream.close.assert_called_once_with()
        download.side_effect = coast.CoastError()
        response = self.client.get(self.action('backup_download'))
        self.assertEqual(302, response.status_code)
        self.assertIn('service_details__backups', response['Location'])

    @mock.patch.object(coast, 'backup_delete')
    def test_delete_requires_confirmation_and_handles_failure(self, delete):
        url = self.action('backup_delete')
        self.assertEqual(200, self.client.get(url).status_code)
        delete.assert_not_called()
        self.assertEqual(200, self.client.post(url).status_code)
        delete.assert_not_called()
        response = self.client.post(url, {'confirm': 'on'})
        self.assertEqual(302, response.status_code)
        delete.assert_called_once_with(mock.ANY, 'backup-id')
        delete.side_effect = coast.CoastError()
        response = self.client.post(url, {'confirm': 'on'})
        self.assertEqual(200, response.status_code)
        self.assertTrue(response.context['form'].non_field_errors())


class BackupApiTests(helpers.TestCase):
    @mock.patch.object(coast, '_get')
    def test_version_gate(self, get):
        for version, expected in (('1.9', False), ('1.18', False),
                                  ('1.19', False),
                                  (coast.BACKUP_VERSION, True),
                                  ('2.0', True), ('bad', False), ('', False)):
            get.return_value = {'version': {'max_version': version}}
            self.assertEqual(expected, coast.backups_supported.__wrapped__(
                self.request))
        get.side_effect = coast.CoastError()
        self.assertFalse(coast.backups_supported.__wrapped__(self.request))

    @mock.patch.object(coast, 'coastclient')
    def test_documented_storage_fault_survives_api_wrapper(self, client):
        response = test_api._resp({
            'faultstring': 'Object storage not available.'})
        response.status_code = 409
        client.return_value.adapter.request.side_effect = (
            coast.client_exceptions.Conflict(response=response))
        with self.assertRaises(coast.CoastError) as error:
            coast.backup_create(self.request, 'service-id')
        self.assertIn('Object storage not available. Contact your cloud '
                      'operator', backups.error_message(error.exception, ''))

    @mock.patch.object(coast, 'coastclient')
    def test_backup_api_adapter_contract(self, client):
        adapter = client.return_value.adapter.request
        calls = (
            (coast.backup_policy_get, ('s',), 'GET',
             '/services/s/backup_policy', None, {'backup_policy': POLICY}),
            (coast.backup_policy_update, ('s', POLICY), 'PUT',
             '/services/s/backup_policy', {'backup_policy': POLICY}, {}),
            (coast.backup_list, ('s',), 'GET', '/services/s/backups', None,
             {'backups': [BACKUP]}),
            (coast.backup_create, ('s',), 'POST',
             '/services/s/backups', {}, {}),
            (coast.backup_get, ('b',), 'GET', '/backups/b', None,
             {'backup': BACKUP}),
            (coast.backup_delete, ('b',), 'DELETE', '/backups/b', None, {}),
            (coast.backup_download, ('b',), 'GET',
             '/backups/b/download', None, {}),
            (coast.backup_restore, ('b', 'new_copy', 'copy'), 'POST',
             '/backups/b/restore', {'mode': 'new_copy', 'name': 'copy'}, {}),
            (coast.backup_restore, ('b', 'overwrite', 'ignored', 'database'),
             'POST', '/backups/b/restore',
             {'mode': 'overwrite', 'confirmation': 'database'}, {}))
        for function, args, method, path, body, result in calls:
            adapter.reset_mock()
            adapter.return_value = test_api._resp(result)
            function(self.request, *args)
            kwargs = {'microversion': coast.BACKUP_VERSION, 'log': False,
                      'connect_retries': 0, 'status_code_retries': 0}
            if function == coast.backup_download:
                kwargs['stream'] = True
            if body is not None:
                kwargs['json'] = body
            adapter.assert_called_once_with(path, method, **kwargs)
        client.return_value.request.assert_not_called()
