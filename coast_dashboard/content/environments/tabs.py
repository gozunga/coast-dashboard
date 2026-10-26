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

from django.utils.translation import gettext_lazy as _
from horizon import tabs

from coast_dashboard.api import coast
from coast_dashboard.content import common
from coast_dashboard.content import details
from coast_dashboard.content import related_tables


class Overview(details.Overview):
    template_name = 'project/coast_environments/overview.html'


class Resources(tabs.TableTab):
    name = _('Apps & Services')
    slug = 'resources'
    table_classes = (related_tables.ResourcesTable,)
    template_name = 'project/coast_environments/resources.html'

    def get_resources_data(self):
        return self.tab_group.resources() or []

    def get_context_data(self, request, **kwargs):
        context = super().get_context_data(request, **kwargs)
        context['load_error'] = self.tab_group.resources() is None
        return context


class Databases(tabs.TableTab):
    name = _('Databases')
    slug = 'databases'
    from coast_dashboard.content.databases.tables import DatabasesTable
    table_classes = (DatabasesTable,)
    template_name = 'project/coast_common/related.html'

    def get_databases_data(self):
        def load():
            stacks, apps, envs = common.parent_maps(self.request)
            return [common.add_names(row, apps, envs, stacks)
                    for row in coast.database_list(
                        self.request,
                        environment_id=self.tab_group.kwargs['item']['id'])]

        return details.load_list(
            self.tab_group, 'databases', load,
            _('Unable to retrieve databases.')) or []


class EnvironmentTabs(tabs.TabGroup):
    slug = 'environment_details'
    tabs = (Overview, Resources, Databases)
    sticky = True

    def resources(self):
        environment_id = self.kwargs['item']['id']
        return details.load_list(self, 'resources', lambda: [
            row for row in coast.service_list(self.request)
            if row.get('environment_id') == environment_id],
            _('Unable to retrieve apps and services.'))
