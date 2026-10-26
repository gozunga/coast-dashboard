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

from django import http
from django.test import SimpleTestCase

from coast_dashboard.content import common

SID = '4b9adff4-9ba9-4531-8d36-966cca8f210b'
DID = '199f0fd1-2c99-4bc1-9bd9-118c12c3197f'


class DeployLandingTests(SimpleTestCase):
    def test_template_service_opens_logs_tab(self):
        url = common.service_deploy_page(
            {'id': SID, 'template_id': 'uptime-kuma'}, DID)
        self.assertTrue(url.endswith(
            '/%s/?tab=service_details__logs' % SID))

    def test_built_service_opens_deployment(self):
        url = common.service_deploy_page(
            {'id': SID, 'source': {'type': 'git'}}, DID)
        self.assertIn('/deployments/%s/' % DID, url)

    def test_created_template_redirects_to_logs(self):
        response = common.redirect_created_deployment(
            http.HttpResponseRedirect('/x/'),
            {'id': SID, 'deployment_id': DID,
             'source': {'type': 'template'}})
        self.assertIn('tab=service_details__logs', response['Location'])

    def test_missing_id_has_no_page(self):
        self.assertIsNone(common.service_logs_page(None))
