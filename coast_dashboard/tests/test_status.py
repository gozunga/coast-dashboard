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

from django.test import RequestFactory
from django.test import SimpleTestCase

from coast_dashboard.content.appgroups import tables as appgroup_tables
from coast_dashboard.content import common
from coast_dashboard.content.environments import tables as environment_tables
from coast_dashboard.content.services import tables


class StatusTests(SimpleTestCase):
    def test_status_colors(self):
        groups = {
            'success': ('ACTIVE', 'RUNNING', 'VERIFIED'),
            'default': ('STOPPED', 'CANCELLED', 'UNKNOWN', 'NEW_STATE',
                        '', None),
            'warning': ('PENDING', 'DEPLOYING', 'STARTING', 'PROVISIONING',
                        'RECONCILING', 'DELETING', 'STOPPING', 'RESTARTING',
                        'BUILDING', 'PENDING_VERIFICATION', 'PENDING_DNS'),
            'danger': ('FAILED', 'ERROR'),
        }
        for color, states in groups.items():
            for state in states:
                with self.subTest(state=state):
                    self.assertEqual(color, common.status_color(state))

    def test_cancelled_fault_or_error(self):
        for field in ('fault', 'error'):
            for error, color in [(None, 'default'), ('', 'default'),
                                 ('Deployment failed', 'danger')]:
                with self.subTest(field=field, error=error):
                    badge = common.status_badge(
                        {'status': 'CANCELLED', field: error})
                    self.assertIn('label-' + color, badge)
                    self.assertIn('CANCELLED', badge)

    def test_status_badge_escapes_unknown_status(self):
        badge = common.status_badge('<script>')
        self.assertIn('label-default', badge)
        self.assertIn('&lt;script&gt;', badge)
        self.assertNotIn('<script>', badge)

    def test_services_table_uses_full_record_and_keeps_raw_status(self):
        request = RequestFactory().get('/')
        for state, fault, color in [('STOPPED', None, 'default'),
                                    ('ACTIVE', None, 'success'),
                                    ('CANCELLED', None, 'default'),
                                    ('CANCELLED', 'Failed build', 'danger'),
                                    ('DEPLOYING', None, 'warning')]:
            with self.subTest(state=state, fault=fault):
                item = {'id': 'app', 'name': 'Web', 'status': state,
                        'fault': fault}
                table = tables.ServicesTable(request, data=[item])
                column = table.columns['status']
                self.assertEqual(state, column.get_raw_data(item))
                self.assertIn('label-' + color, column.get_data(item))

    def test_stopping_and_restarting_override_active_status(self):
        for task in ('STOPPING', 'RESTARTING'):
            item = {'status': 'ACTIVE', 'task_state': task}
            self.assertEqual(task, common.status(item))
            self.assertIn('label-warning', common.status_badge(item))

    def test_inline_status_badge_labels_and_shared_colors(self):
        self.assertEqual('', common.inline_status_badge({'status': 'ACTIVE'}))
        cases = [('PENDING', 'Creating'), ('DELETING', 'Deleting'),
                 ('ERROR', 'Error'), ('STOPPED', 'Stopped'),
                 ('RESTARTING', 'Restarting'), ('NEW_STATE', 'New State')]
        for value, label in cases:
            with self.subTest(value=value):
                badge = common.inline_status_badge({'status': value})
                self.assertIn('label-' + common.status_color(value), badge)
                self.assertIn('>%s</span>' % label, badge)
        self.assertIn('label-danger', common.inline_status_badge(
            {'status': 'CANCELLED', 'fault': 'Failure'}))

    def test_environment_name_link_escapes_name_and_state(self):
        rendered = common.environment_link({
            'id': 'env', 'name': '<script>', 'status': '<UNKNOWN>'})
        self.assertIn('&lt;script&gt;', rendered)
        self.assertIn('&lt;Unknown&gt;', rendered)
        self.assertNotIn('<script>', rendered)
        self.assertIn('/env/', rendered)

    def test_row_polling_without_status_column(self):
        request = RequestFactory().get('/')
        for module in (environment_tables, appgroup_tables):
            for value, expected in [('PENDING', None), ('DELETING', None),
                                    ('ACTIVE', True), ('ERROR', False)]:
                with self.subTest(resource=module.__name__, value=value):
                    item = {'id': 'resource', 'name': 'Example',
                            'status': value}
                    table_class = (environment_tables.EnvironmentsTable
                                   if module is environment_tables else
                                   appgroup_tables.AppgroupsTable)
                    table = table_class(request)
                    self.assertNotIn('status', table.columns)
                    row = module.UpdateRow(table)
                    row.datum = item
                    self.assertIs(expected, row.status)

    def test_appgroup_name_link_and_inline_status(self):
        for value, label in [('ACTIVE', None), ('PENDING', 'Creating'),
                             ('DELETING', 'Deleting'), ('ERROR', 'Error')]:
            with self.subTest(value=value):
                rendered = common.appgroup_link({
                    'id': 'group', 'name': '<Group>', 'status': value})
                self.assertIn('/coast/appgroups/group/', rendered)
                self.assertIn('&lt;Group&gt;</a>', rendered)
                self.assertNotIn('<Group>', rendered)
                if label:
                    self.assertIn('>%s</span>' % label, rendered)
                    self.assertIn('label-' + common.status_color(value),
                                  rendered)
                else:
                    self.assertNotIn('<span', rendered)
