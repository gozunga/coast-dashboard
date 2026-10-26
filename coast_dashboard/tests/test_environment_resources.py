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


ENVIRONMENT = {'id': 'env', 'name': 'Production', 'status': 'ACTIVE',
               'appgroup_id': 'group'}
APP = {'id': 'app', 'name': 'Web', 'kind': 'app',
       'status': 'STOPPED', 'environment_id': 'env'}
SERVICE = {'id': 'service', 'name': 'Database', 'kind': 'service',
           'status': 'RUNNING', 'environment_id': 'env'}


@mock.patch.object(coast, 'environment_get', return_value=ENVIRONMENT)
class EnvironmentResourcesTests(helpers.TestCase):
    def url(self):
        return reverse('horizon:project:coast.environments:detail',
                       args=['env'])

    @mock.patch.object(coast, 'service_list', return_value=[
        APP, SERVICE, dict(APP, id='other', name='Other',
                           environment_id='else')])
    def test_related_resources(self, resources, environment):
        response = self.client.get(self.url())
        self.assertEqual([APP, SERVICE], response.context['resources'])
        for row in (APP, SERVICE):
            panel = 'services' if row.get('kind') == 'service' else 'apps'
            self.assertContains(response, reverse(
                'horizon:project:coast.%s:detail' % panel, args=[row['id']]))
        self.assertContains(response,
                            '<span class="label label-default">STOPPED</span>',
                            html=True)
        self.assertContains(response,
                            '<span class="label label-success">RUNNING</span>',
                            html=True)
        resources.assert_called_once_with(mock.ANY)

    @mock.patch.object(coast, 'service_list',
                       side_effect=[[APP], [], [SERVICE]])
    def test_live_data_on_each_load(self, resources, environment):
        first = self.client.get(self.url())
        self.assertEqual([APP], first.context['resources'])
        empty = self.client.get(self.url())
        self.assertContains(empty, 'No apps or services in this environment.')
        last = self.client.get(self.url())
        self.assertEqual([SERVICE], last.context['resources'])
        self.assertEqual(3, resources.call_count)

    @mock.patch.object(coast, 'service_list',
                       side_effect=coast.CoastError('Access denied'))
    def test_resource_error_keeps_environment(self, resources, environment):
        response = self.client.get(self.url())
        self.assertContains(response, 'Production')
        self.assertContains(response, 'Access denied')
        self.assertContains(response, 'Unable to retrieve apps and services.')
        self.assertNotContains(response,
                               'No apps or services in this environment.')
