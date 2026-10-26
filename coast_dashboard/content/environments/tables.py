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
from django.utils.translation import ngettext_lazy
from horizon import tables

from coast_dashboard.api import coast
from coast_dashboard.content import common


class CreateEnvironment(tables.LinkAction):
    name = 'create'
    verbose_name = _('Create Environment')
    url = 'horizon:project:coast.environments:create'
    classes = ('ajax-modal',)
    icon = 'plus'
    policy_rules = ()


class DeleteEnvironment(common.ApiErrorMixin, tables.DeleteAction):
    policy_rules = ()

    @staticmethod
    def action_present(count):
        return ngettext_lazy('Delete Environment', 'Delete Environments',
                             count)

    @staticmethod
    def action_past(count):
        return ngettext_lazy('Scheduled deletion of Environment',
                             'Scheduled deletion of Environments', count)

    def delete(self, request, obj_id):
        coast.environment_delete(request, obj_id)


class UpdateRow(common.InlineStatusRow):
    def get_data(self, request, environment_id):
        return common.add_parent_name(
            coast.environment_get(request, environment_id), 'appgroup',
            common.name_map(
                request, coast.appgroup_list, common.appgroup_link))


class EnvironmentsTable(common.ResourceTable):
    name = tables.Column(common.environment_link, verbose_name=_('Name'))
    appgroup_name = tables.Column('appgroup_name',
                                  verbose_name=_('App Group'))

    class Meta:
        name = 'environments'
        verbose_name = _('Environments')
        row_class = UpdateRow
        table_actions = (CreateEnvironment, DeleteEnvironment)
        row_actions = (DeleteEnvironment,)


class DetailActions(EnvironmentsTable):
    class Meta:
        name = 'environments'
        row_actions = (common.CreateApp, common.CreateService,
                       DeleteEnvironment)
