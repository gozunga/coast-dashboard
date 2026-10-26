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
from coast_dashboard.content.appgroups import forms as project_forms
from coast_dashboard.content.appgroups import related
from coast_dashboard.content.appgroups import tables as project_tables
from coast_dashboard.content.appgroups import tabs as project_tabs
from coast_dashboard.content import common
from coast_dashboard.content import details


class IndexView(tables.DataTableView):
    table_class = project_tables.AppgroupsTable
    template_name = 'project/coast_appgroups/index.html'
    page_title = _('App Groups')

    def get_data(self):
        try:
            stacks = common.name_map(self.request, coast.stack_list)
            return [common.add_parent_name(
                related.for_group(self.request, item), 'stack', stacks)
                    for item in coast.appgroup_list(self.request)]
        except Exception:
            exceptions.handle(self.request,
                              _('Unable to retrieve app groups.'))
            return []


class DetailView(details.ResourceDetailView):
    resource = 'appgroup'
    index_url = 'horizon:project:coast.appgroups:index'
    action_table = project_tables.DetailActions
    tab_group_class = project_tabs.AppgroupTabs


class CreateView(forms.ModalFormView):
    form_class = project_forms.CreateAppgroup
    template_name = 'project/coast_appgroups/create.html'
    submit_url = reverse_lazy('horizon:project:coast.appgroups:create')
    success_url = reverse_lazy('horizon:project:coast.appgroups:index')
    submit_label = page_title = _('Create App Group')

    def get_object_id(self, item):
        return item['id']
