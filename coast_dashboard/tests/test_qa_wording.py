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

from django import test

from coast_dashboard.content import common
from coast_dashboard.content.services import logs


class QAWordingTests(test.SimpleTestCase):
    def test_engine_fault_is_tenant_wording(self):
        self.assertIn('Activity tab', str(common.friendly_fault(
            common.ENGINE_FAULT)))
        self.assertEqual('', common.friendly_fault(None))
        self.assertEqual('', common.friendly_fault(''))
        self.assertEqual('Other', common.friendly_fault('Other'))

    def test_friendly_fault_scrubs_vendor_names(self):
        for engine in ('Coolify', 'coolify', 'COOLIFY', 'cOoLiFy'):
            for proxy in ('Traefik', 'traefik', 'TRAEFIK', 'tRaEfIk'):
                with self.subTest(engine=engine, proxy=proxy):
                    self.assertEqual(
                        'App engine server failed; proxy unavailable',
                        common.friendly_fault(
                            '%s failed; %s unavailable' % (engine, proxy)))

    def test_yes_no(self):
        self.assertEqual('Yes', str(common.yes_no(True)))
        self.assertEqual('No', str(common.yes_no(False)))

    def test_coast_ns_follows_kind(self):
        self.assertEqual('horizon:project:coast.services:',
                         common.coast_ns(kind='service'))
        self.assertEqual('horizon:project:coast.apps:',
                         common.coast_ns(kind='app'))

    @mock.patch('coast_dashboard.api.coast.service_get',
                return_value={'id': 's', 'kind': 'app'})
    @mock.patch('coast_dashboard.api.coast.service_deployment_log',
                return_value=['using coollabsio/coolify-helper:1.0',
                              {'line': 'Traefik ready'}])
    def test_build_log_never_names_the_engine(self, *_):
        text = str(logs.deployment_log_context(None, 's', 'd')['logs'])
        self.assertNotIn('oolify', text)
        self.assertNotIn('raefik', text)


class ServicePanelUrlTests(test.SimpleTestCase):
    def test_service_pages_have_their_own_callbacks(self):
        from coast_dashboard.content.oneclick import urls as service_urls
        from coast_dashboard.content.services import urls as app_urls
        apps = {p.name: p.callback for p in app_urls.urlpatterns}
        for pattern in service_urls.urlpatterns:
            if pattern.name in ('index', 'create'):
                continue
            self.assertIn(pattern.name, apps)
            self.assertIsNot(apps[pattern.name], pattern.callback)
