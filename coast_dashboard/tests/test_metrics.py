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
from coast_dashboard.content.services import tabs
from coast_dashboard.tests import helpers
from coast_dashboard.tests import test_navigation_settings as navigation


METRICS = {'service_id': 'svc', 'range': '1h', 'step_seconds': 30,
           'containers': [{'name': 'web', 'points': [
               {'timestamp': '2026-10-19T05:00:00Z', 'cpu_percent': 12.5,
                'memory_bytes': 104857600, 'memory_limit_bytes': None}]}]}


class MetricsApiTests(helpers.TestCase):
    @mock.patch.object(coast, 'coastclient')
    def test_discovery_compares_numeric_versions_and_memoizes(self, client):
        for version, supported in [('1.18', False), ('1.19', False),
                                   ('1.20', False), ('1.21', True),
                                   ('1.22', True), ('1.100', True),
                                   ('broken', False)]:
            request = mock.Mock()
            response = client.return_value.request.return_value
            response.json.return_value = {'version': {'max_version': version}}
            client.reset_mock()
            self.assertEqual(
                supported, coast.service_metrics_supported(request))
            self.assertEqual(
                supported, coast.service_metrics_supported(request))
            client.return_value.request.assert_called_once_with('/', 'GET')
        response.json.return_value = {}
        self.assertFalse(coast.service_metrics_supported(mock.Mock()))
        client.side_effect = RuntimeError('unavailable')
        self.assertFalse(coast.service_metrics_supported(mock.Mock()))

    @mock.patch.object(coast, 'coastclient')
    def test_contract_all_ranges_and_default(self, client):
        adapter = client.return_value.adapter.request
        adapter.return_value.json.return_value = {'metrics': METRICS}
        for range_ in coast.METRICS_RANGES:
            self.assertEqual(METRICS, coast.service_metrics(
                self.request, 'svc', range_))
            adapter.assert_called_with(
                '/services/svc/metrics?range=' + range_, 'GET',
                microversion='1.21', log=False,
                connect_retries=0, status_code_retries=0)
        coast.service_metrics(self.request, 'svc')
        self.assertEqual('/services/svc/metrics?range=1h',
                         adapter.call_args.args[0])
        client.assert_called_with(self.request, '1.0')
        client.return_value.request.assert_not_called()
        with self.assertRaises(ValueError):
            coast.service_metrics(self.request, 'svc', 'invalid')
        adapter.side_effect = coast.client_exceptions.NotAcceptable()
        with self.assertRaises(coast.CoastError):
            coast.service_metrics(self.request, 'svc')


class MetricsViewTests(helpers.TestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(coast, 'service_metrics_supported',
                                    return_value=True)
        self.supported = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(coast, 'service_metrics',
                                    return_value=METRICS)
        self.metrics = patcher.start()
        self.addCleanup(patcher.stop)

    def url(self, panel='apps'):
        return reverse('horizon:project:coast.%s:metrics' % panel,
                       args=['svc'])

    def test_json_for_apps_services_readers_and_all_ranges(self):
        self.setActiveUser(
            id=self.user.id, token=self.token, username=self.user.name,
            tenant_id=self.tenant.id, service_catalog=self.service_catalog,
            roles=[{'name': 'reader'}])
        for panel in ('apps', 'services'):
            for range_ in coast.METRICS_RANGES:
                response = self.client.get(self.url(panel), {'range': range_})
                self.assertEqual(200, response.status_code)
                self.assertEqual({'metrics': METRICS}, response.json())
                self.assertIn('no-store', response['Cache-Control'])
                self.metrics.assert_called_with(mock.ANY, 'svc', range_)
        self.client.get(self.url())
        self.metrics.assert_called_with(mock.ANY, 'svc', '1h')

    def test_bad_range_and_post_do_not_fetch(self):
        self.assertEqual(400, self.client.get(
            self.url(), {'range': 'bad'}).status_code)
        self.assertEqual(405, self.client.post(self.url()).status_code)
        self.metrics.assert_not_called()

    def test_unsupported_api_is_hidden_and_endpoint_does_not_fetch(self):
        self.supported.return_value = False
        group = mock.Mock(kwargs={'service_id': 'svc'})
        self.assertFalse(
            tabs.Metrics(group, self.request).allowed(self.request))
        response = self.client.get(self.url())
        self.assertEqual(404, response.status_code)
        self.assertIn('no-store', response['Cache-Control'])
        self.metrics.assert_not_called()

    def test_allowed_tab_context_order_and_render(self):
        group = mock.Mock(kwargs={'service_id': 'svc'})
        tab = tabs.Metrics(group, self.request)
        self.assertTrue(tab.allowed(self.request))
        self.assertFalse(tab.preload)
        self.assertEqual({'metrics_url': self.url()},
                         tab.get_context_data(self.request))
        order = list(tabs.ServiceTabs.tabs)
        self.assertEqual(order.index(tabs.Console) + 1,
                         order.index(tabs.Metrics))

    def test_empty_and_errors_do_not_leak_internal_details(self):
        self.metrics.return_value = dict(METRICS, containers=[])
        self.assertEqual([], self.client.get(
            self.url()).json()['metrics']['containers'])
        for error, status in [(RuntimeError('secret internal product'), 502),
                              (coast.exceptions.NotAuthorized(), 403),
                              (coast.exceptions.NotFound(), 404)]:
            self.metrics.side_effect = error
            response = self.client.get(self.url())
            self.assertEqual(status, response.status_code)
            self.assertNotIn('secret', response.content.decode())
            self.assertIn('no-store', response['Cache-Control'])


class MetricsPanelTests(helpers.TestCase):
    setUp = navigation.NavigationSettingsTests.setUp
    list_services = (
        navigation.NavigationSettingsTests.list_services)
    get_service = navigation.NavigationSettingsTests.get_service
    update_service = (
        navigation.NavigationSettingsTests.update_service)

    @mock.patch.object(coast, 'service_metrics_supported', return_value=True)
    @mock.patch.object(coast, 'service_metrics')
    def test_lazy_tab_in_both_panels(self, metrics, supported):
        for panel, service in [('apps', 'app-id'), ('services', 'service-id')]:
            url = reverse('horizon:project:coast.%s:detail' % panel,
                          args=[service])
            response = self.client.get(
                url, {'tab': 'service_details__metrics'})
            self.assertEqual(200, response.status_code)
            self.assertTemplateUsed(
                response, 'project/coast_services/metrics.html')
            self.assertContains(response, reverse(
                'horizon:project:coast.%s:metrics' % panel, args=[service]))
        metrics.assert_not_called()

    @mock.patch.object(coast, 'service_metrics_supported', return_value=False)
    def test_detail_hides_unsupported_direct_link(self, supported):
        url = reverse('horizon:project:coast.apps:detail', args=['app-id'])
        response = self.client.get(url, {'tab': 'service_details__metrics'})
        self.assertEqual(200, response.status_code)
        self.assertNotContains(response, 'coast-metrics')
        self.assertNotContains(response, 'service_details__metrics')
