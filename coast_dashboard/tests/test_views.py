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

from django.urls import reverse

from coast_dashboard.api import coast
from coast_dashboard.tests import helpers

STACK = {'id': 's-1', 'name': 'demo', 'status': 'ACTIVE',
         'servers': [{'id': 'x'}]}
APP = {'id': 'a-1', 'name': 'web', 'status': 'ACTIVE', 'stack_id': 's-1'}


class StackViewTests(helpers.TestCase):

    @mock.patch.object(coast, 'stack_list', return_value=[STACK])
    def test_index(self, mocked):
        res = self.client.get(reverse('horizon:project:coast.stacks:index'))
        self.assertEqual(200, res.status_code)
        self.assertContains(res, 'demo')
        self.assertContains(
            res, reverse('horizon:project:coast.stacks:detail',
                         args=['s-1']))
        mocked.assert_called_once()

    @mock.patch.object(coast, 'stack_list', side_effect=Exception('boom'))
    def test_index_error(self, mocked):
        res = self.client.get(reverse('horizon:project:coast.stacks:index'))
        self.assertEqual(200, res.status_code)
        self.assertContains(res, 'Unable to retrieve stacks')

    @mock.patch.object(coast, 'stack_server_list', return_value=[])
    @mock.patch.object(coast, 'stack_get',
                       return_value=dict(STACK, engine_version='4.4.3'))
    def test_detail(self, mocked, servers):
        res = self.client.get(reverse('horizon:project:coast.stacks:detail',
                                      args=['s-1']))
        self.assertEqual(200, res.status_code)
        self.assertContains(res, 'ACTIVE')
        self.assertContains(res, '<dt>Engine version</dt><dd>4.4.3</dd>',
                            html=True)
        for label in ('ID', 'Name', 'Status', 'Created', 'Plan',
                      'Engine version'):
            self.assertContains(res, '<dt>%s</dt>' % label, html=True)
        content = res.content.decode().lower()
        self.assertNotIn('coolify', content)
        self.assertNotIn('traefik', content)
        self.assertContains(res, 'dl-horizontal coast-detail-dl')
        self.assertContains(res, '.coast-detail-dl dt')
        self.assertContains(res, 'white-space: normal;')
        self.assertContains(res, 'overflow: visible;')
        self.assertContains(res, 'text-overflow: clip;')
        self.assertContains(res, 'width: 15em;')
        self.assertNotContains(res, 'text-overflow: ellipsis')
        mocked.assert_called_once_with(mock.ANY, 's-1')


class AppgroupViewTests(helpers.TestCase):

    def setUp(self):
        super().setUp()
        for name in ('environment_list', 'service_list'):
            patcher = mock.patch.object(coast, name, return_value=[])
            patcher.start()
            self.addCleanup(patcher.stop)

    @mock.patch.object(coast, 'appgroup_list', return_value=[APP])
    def test_index(self, mocked):
        res = self.client.get(
            reverse('horizon:project:coast.appgroups:index'))
        self.assertEqual(200, res.status_code)
        self.assertContains(res, 'web')

    @mock.patch.object(coast, 'appgroup_get', return_value=APP)
    def test_detail(self, mocked):
        res = self.client.get(
            reverse('horizon:project:coast.appgroups:detail',
                    args=['a-1']))
        self.assertEqual(200, res.status_code)
        self.assertContains(res, 's-1')
