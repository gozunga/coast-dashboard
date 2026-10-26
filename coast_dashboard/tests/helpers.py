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

from openstack_dashboard.test import helpers

from coast_dashboard.api import coast


class TestCase(helpers.TestCase):
    """Horizon TestCase whose catalog includes the app-hosting service."""

    def setUp(self):
        super().setUp()
        # Database panels use a separate catalog and resource API.
        for name in ('database_engine_list', 'database_list'):
            catalog = mock.patch.object(coast, name, return_value=[])
            catalog.start()
            self.addCleanup(catalog.stop)
        self.service_catalog.append({
            'type': 'app-hosting', 'name': 'coast', 'id': 'coast',
            'endpoints': [{'region': 'RegionOne', 'interface': 'public',
                           'url': 'http://coast.example.com:9518',
                           'id': 'coast-public'}]})


PANEL_SLUGS = {'services': 'coast.apps', 'oneclick': 'coast.services'}


def panel_ns(name):
    """Map a short panel name to its nested panel slug."""
    return PANEL_SLUGS.get(name, 'coast.' + name)


def view_name(panel, view):
    """Return the URL name of a view in a Coast panel."""
    return 'horizon:project:%s:%s' % (panel_ns(panel), view)
