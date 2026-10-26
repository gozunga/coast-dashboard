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

from datetime import timedelta
from datetime import timezone as dt_timezone
import html
import re
from unittest import mock

from django.urls import reverse
from django.utils import timezone
from keystoneauth1 import adapter
from keystoneauth1 import session
import requests

from coast_dashboard.api import coast
from coast_dashboard.content import common
from coast_dashboard.content.stacks import activity
from coast_dashboard.tests import helpers
from coast_dashboard.tests.test_api import _resp

STACK = {'id': 's1', 'name': 'demo', 'status': 'ACTIVE',
         'created_at': '2026-10-18T12:30:00Z'}
EVENT = {'id': 'e1', 'stack_id': 's1', 'resource_type': 'server',
         'resource_id': 'w2', 'action': 'add', 'outcome': 'success',
         'message': 'Added worker', 'detail': None, 'request_id': 'r1',
         'created_at': '2026-10-18T12:31:00Z'}


class ActivityApiTests(helpers.TestCase):
    @mock.patch.object(coast, 'coastclient')
    def test_page_version_filters_and_untrusted_next_link(self, client):
        client.return_value.adapter.request.return_value = _resp({
            'events': [EVENT], 'links': [{'rel': 'next', 'href': (
                'https://evil.example/stacks/other/events?marker=e1')}]})
        self.assertEqual(([EVENT], 'e1'), coast.stack_event_list(
            self.request, 's1', limit=10, marker='new & first',
            resource_type='server'))
        client.assert_called_once_with(self.request, '1.0')
        client.return_value.adapter.request.assert_called_once_with(
            '/stacks/s1/events?limit=10&marker=new+%26+first&'
            'resource_type=server', 'GET', microversion='1.8', log=False,
            connect_retries=0, status_code_retries=0)
        client.return_value.request.assert_not_called()

    @mock.patch.object(coast, 'coastclient')
    @mock.patch.object(requests.sessions.Session, 'send')
    def test_wire_header_and_versioned_path(self, send, client):
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"events": []}'
        send.return_value = response
        client.return_value.adapter = adapter.Adapter(
            session=session.Session(), service_type='app-hosting',
            endpoint_override='https://coast.example/v1')
        self.assertEqual(
            ([], None), coast.stack_event_list(self.request, 's1'))
        sent = send.call_args.args[0]
        self.assertEqual('https://coast.example/v1/stacks/s1/events?limit=50',
                         sent.url)
        self.assertEqual('app-hosting 1.8',
                         sent.headers['OpenStack-API-Version'])

    @mock.patch.object(coast, 'coastclient')
    def test_unsupported_versions(self, client):
        for error in (coast.client_exceptions.NotFound,
                      coast.client_exceptions.NotAcceptable):
            with self.subTest(error=error):
                client.return_value.adapter.request.side_effect = error()
                with self.assertRaises(coast.ActivityUnavailable):
                    coast.stack_event_list(self.request, 's1')
        client.return_value.request.assert_not_called()

    @mock.patch.object(coast, 'coastclient')
    def test_other_errors_are_not_version_fallbacks(self, client):
        for error, expected in (
                (coast.client_exceptions.Forbidden, coast.CoastError),
                (coast.client_exceptions.InternalServerError,
                 coast.CoastError),
                (coast.client_exceptions.Unauthorized,
                 coast.exceptions.NotAuthorized)):
            with self.subTest(error=error):
                client.return_value.adapter.request.side_effect = error()
                with self.assertRaises(expected):
                    coast.stack_event_list(self.request, 's1')

    @mock.patch.object(coast, '_get')
    def test_last_page_and_repeated_marker(self, get):
        for links in ([], [{'rel': 'next', 'href': '?marker=e1'}]):
            get.return_value = {'events': [EVENT], 'links': links}
            self.assertEqual(([EVENT], None), coast.stack_event_list(
                self.request, 's1', marker='e1'))


class ActivityViewTests(helpers.TestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse('horizon:project:coast.stacks:detail', args=['s1'])
        for name, value in (
                ('stack_get', STACK), ('stack_list', [STACK]),
                ('appgroup_list', []),
                ('stack_server_list', [{'id': 'w2', 'name': 'worker-2',
                                        'role': 'worker'},
                                       {'id': 'c1', 'name': 'internal',
                                        'role': 'control'}])):
            patcher = mock.patch.object(coast, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(coast, 'stack_event_list',
                                    return_value=([EVENT], None))
        self.events = patcher.start()
        self.addCleanup(patcher.stop)

    def activity_page(self, **params):
        return self.client.get(self.url, {'tab': 'stack_details__activity',
                                          **params})

    def test_created_table_and_overview(self):
        self.client.cookies['django_timezone'] = 'Europe/Paris'
        with timezone.override(dt_timezone(timedelta(hours=2))):
            formatted = common.local_datetime(
                STACK['created_at']).rsplit(' ', 1)[0]
        index = self.client.get(reverse(
            'horizon:project:coast.stacks:index'))
        overview = self.client.get(self.url)
        for response in (index, overview):
            self.assertContains(response, 'Created')
            self.assertContains(response, formatted)
        self.events.assert_not_called()

    def test_render_order_badge_and_marker_paging(self):
        older = dict(EVENT, id='e0', resource_type='stack', action='create',
                     created_at='2026-10-18T12:00:00Z')
        self.events.side_effect = [([EVENT, older], 'e0 & last'),
                                   ([older], None)]
        response = self.activity_page()
        self.assertContains(response, 'Server worker-2 added')
        self.assertContains(response, 'Stack created')
        self.assertContains(response, 'label-success')
        self.assertContains(response, 'Added worker')
        self.assertLess(response.content.index(b'Server worker-2 added'),
                        response.content.index(b'Stack created'))
        self.assertContains(response, 'marker=e0+%26+last')
        older_url = re.search(
            r'href="([^"]*marker=e0[^"]*)"', response.content.decode())[1]
        response = self.client.get(html.unescape(older_url))
        self.events.assert_called_with(mock.ANY, 's1', marker='e0 & last')
        self.assertContains(response, 'Stack created')
        self.assertNotContains(response, 'Load older')

    def test_scrub_all_visible_fields_and_escape_html(self):
        self.events.return_value = ([dict(
            EVENT, resource_id='c1', action='Coolify_update',
            outcome='TRAEFIK', message='<script>Coolify Traefik</script>',
            detail={'Coolify': {'nested': ['TRAEFIK', 'cOoLiFy']},
                    'reason': '<img src=x onerror=alert(1)>'})], None)
        response = self.activity_page()
        self.assertContains(response, 'App engine server')
        self.assertContains(response, 'proxy')
        self.assertNotIn(b'coolify', response.content.lower())
        self.assertNotIn(b'traefik', response.content.lower())
        self.assertNotContains(response, '<script>App engine server')
        self.assertContains(response, '&lt;img src=x')

    def test_unavailable_and_empty(self):
        self.events.side_effect = coast.ActivityUnavailable()
        response = self.activity_page()
        self.assertContains(response, 'Activity needs a newer Coast API')
        self.assertNotContains(response, 'No activity yet.')
        self.events.side_effect = None
        self.events.return_value = ([], None)
        self.assertContains(self.activity_page(), 'No activity yet.')

    def test_server_labels_without_live_server(self):
        for role in ('control', 'controller', 'engine'):
            with self.subTest(role=role):
                row = activity.present(dict(EVENT, detail={
                    'role': role, 'server_name': 'old-server'}), {})
                self.assertEqual('App engine server added', row['what'])
        row = activity.present(dict(EVENT, detail={'server_name': 'worker-2'}),
                               {})
        self.assertEqual('Server worker-2 added', row['what'])

    def test_engine_actions_use_public_resource_label(self):
        for resource_type in ('stack', 'server'):
            with self.subTest(resource_type=resource_type):
                row = activity.present(dict(EVENT, resource_type=resource_type,
                                            action='engine_install'), {})
                self.assertEqual('App engine server engine install',
                                 row['what'])

    def test_activity_failure_has_generic_message(self):
        self.events.side_effect = coast.CoastError('Coolify failed')
        response = self.activity_page()
        self.assertContains(response, 'Unable to retrieve activity.')
        self.assertNotContains(response, 'Activity needs a newer Coast API')
        self.assertNotIn(b'coolify', response.content.lower())

    def test_dates_use_user_timezone(self):
        with timezone.override(dt_timezone(timedelta(hours=2))):
            self.assertEqual(
                common.local_datetime('2026-10-18T14:30:00+02:00'),
                common.local_datetime(STACK['created_at']))
            self.assertEqual(common.local_datetime('2026-10-18T12:30:00'),
                             common.local_datetime(STACK['created_at']))
        self.assertEqual('-', common.local_datetime(None))
        self.assertEqual('-', common.local_datetime('invalid'))
