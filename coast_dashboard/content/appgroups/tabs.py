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
    template_name = 'project/coast_appgroups/overview.html'

    def get_context_data(self, request, **kwargs):
        context = super().get_context_data(request, **kwargs)
        item = context['item']
        context['stack_name'] = common.name_map(request, coast.stack_list).get(
            item.get('stack_id'), _('Unavailable'))
        context['fields'] = sorted(
            (key, value) for key, value in item.items()
            if key != 'id' and not key.endswith('_id')
            and not isinstance(value, (dict, list)))
        return context


class Environments(tabs.TableTab):
    name = _('Environments')
    slug = 'environments'
    table_classes = (related_tables.EnvironmentsTable,)
    template_name = 'project/coast_common/related.html'

    def get_environments_data(self):
        return self.tab_group.environments() or []

    def get_context_data(self, request, **kwargs):
        context = super().get_context_data(request, **kwargs)
        context['load_error'] = self.tab_group.environments() is None
        return context


class Apps(tabs.TableTab):
    name = _('Apps')
    slug = 'apps'
    table_classes = (related_tables.AppsTable,)
    template_name = 'project/coast_common/related.html'

    def get_apps_data(self):
        rows = self.tab_group.services() or []
        return [row for row in rows if row.get('kind') == 'app']

    def get_context_data(self, request, **kwargs):
        context = super().get_context_data(request, **kwargs)
        context['load_error'] = self.tab_group.services() is None
        return context


class Services(Apps):
    name = _('Services')
    slug = 'services'
    table_classes = (related_tables.ServicesTable,)

    def get_related_services_data(self):
        rows = self.tab_group.services() or []
        return [row for row in rows if row.get('kind') == 'service']


class Databases(tabs.TableTab):
    name = _('Databases')
    slug = 'databases'
    from coast_dashboard.content.databases.tables import RelatedDatabasesTable
    table_classes = (RelatedDatabasesTable,)
    template_name = 'project/coast_common/related.html'

    def get_databases_data(self):
        def load():
            stacks, apps, envs = common.parent_maps(self.request)
            return [common.add_names(row, apps, envs, stacks)
                    for row in coast.database_list(
                        self.request,
                        appgroup_id=self.tab_group.kwargs['item']['id'])]

        return details.load_list(
            self.tab_group, 'databases', load,
            _('Unable to retrieve databases.')) or []


class AppgroupTabs(tabs.TabGroup):
    slug = 'appgroup_details'
    tabs = (Overview, Environments, Apps, Databases, Services)
    sticky = True

    def environments(self):
        group_id = self.kwargs['item']['id']
        return details.load_list(self, 'environments', lambda: [
            row for row in coast.environment_list(self.request,
                                                  appgroup_id=group_id)
            if row.get('appgroup_id', group_id) == group_id],
            _('Unable to retrieve environments.'))

    def services(self):
        group_id = self.kwargs['item']['id']
        return details.load_list(self, 'services', lambda: [
            row for row in coast.service_list(self.request)
            if row.get('appgroup_id') == group_id],
            _('Unable to retrieve apps and services.'))
