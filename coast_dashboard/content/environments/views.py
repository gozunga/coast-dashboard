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

from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from horizon import exceptions
from horizon import forms
from horizon import tables

from coast_dashboard.api import coast
from coast_dashboard.content import common
from coast_dashboard.content import details
from coast_dashboard.content.environments import forms as project_forms
from coast_dashboard.content.environments import tables as project_tables
from coast_dashboard.content.environments import tabs as project_tabs


class IndexView(common.AppgroupFilterMixin, tables.DataTableView):
    table_class = project_tables.EnvironmentsTable
    template_name = 'project/coast_environments/index.html'
    page_title = _('Environments')

    def get_data(self):
        try:
            names = common.name_map(
                self.request, coast.appgroup_list, common.appgroup_link)
            return [common.add_parent_name(item, 'appgroup', names)
                    for item in self.filter_appgroup(
                        coast.environment_list(self.request))]
        except Exception:
            exceptions.handle(self.request,
                              _('Unable to retrieve environments.'))
            return []


class DetailView(details.ResourceDetailView):
    resource = 'environment'
    index_url = 'horizon:project:coast.environments:index'
    action_table = project_tables.DetailActions
    tab_group_class = project_tabs.EnvironmentTabs

    def load_item(self):
        return common.add_parent_name(
            super().load_item(), 'appgroup', common.name_map(
                self.request, coast.appgroup_list, common.appgroup_link))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['resources'] = context['tab_group'].resources()
        return context


class CreateView(common.CreateContextMixin, forms.ModalFormView):
    form_class = project_forms.CreateEnvironment
    template_name = 'project/coast_environments/create.html'
    submit_url = reverse_lazy('horizon:project:coast.environments:create')
    success_url = reverse_lazy('horizon:project:coast.environments:index')
    submit_label = page_title = _('Create Environment')

    def get_object_id(self, item):
        return item['id']
