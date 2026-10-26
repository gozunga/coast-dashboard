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
from coast_dashboard.content.stacks import add_server
from coast_dashboard.content.stacks import resize_actions


class CreateStack(tables.LinkAction):
    name = 'create'
    verbose_name = _('Create Stack')
    url = 'horizon:project:coast.stacks:create'
    classes = ('ajax-modal',)
    icon = 'plus'
    policy_rules = ()


class DeleteStack(common.ApiErrorMixin, tables.DeleteAction):
    policy_rules = ()

    @staticmethod
    def action_present(count):
        return ngettext_lazy('Delete Stack', 'Delete Stacks', count)

    @staticmethod
    def action_past(count):
        return ngettext_lazy('Scheduled deletion of Stack',
                             'Scheduled deletion of Stacks', count)

    def delete(self, request, obj_id):
        coast.stack_delete(request, obj_id)


class UpdateRow(common.UpdateRow):
    def get_data(self, request, stack_id):
        return coast.stack_get(request, stack_id)


class StacksTable(common.ResourceTable):
    name = tables.Column('name', verbose_name=_('Name'),
                         link='horizon:project:coast.stacks:detail')
    status = common.StatusColumn()
    plan = tables.Column('plan', verbose_name=_('Plan'))
    engine_version = tables.Column('engine_version',
                                   verbose_name=_('Engine version'))

    created_at = tables.Column('created_at', verbose_name=_('Created'),
                               filters=(common.local_datetime,))

    class Meta:
        name = 'stacks'
        verbose_name = _('Stacks')
        row_class = UpdateRow
        status_columns = ('status',)
        table_actions = (CreateStack, DeleteStack)
        row_actions = (DeleteStack,)


class UpdateServerRow(common.UpdateRow):
    def get_data(self, request, server_id):
        return coast.stack_server_get(request, self.table.kwargs['item']['id'],
                                      server_id)


def server_role(item):
    return {'control': _('App engine server'), 'worker': _('Worker'),
            'build': _('Build server')}.get(item['role'], item['role'])


class ServersTable(common.ResourceTable):
    hostname = tables.Column(
        lambda item: (item.get('hostname') or '').split('.')[0],
        verbose_name=_('Hostname'))
    name = tables.Column('name', verbose_name=_('Name'))
    role = tables.Column(server_role, verbose_name=_('Role'))
    status = common.StatusColumn()
    flavor = tables.Column(
        lambda item: ((item.get('flavor') or {}).get('name') or
                      (item.get('flavor') or {}).get('id')),
        verbose_name=_('Flavor'))
    kind = tables.Column('kind', verbose_name=_('Kind'))
    floating_ip = tables.Column(
        lambda item: common.copyable_value(item.get('floating_ip')),
        verbose_name=_('Public IP'))

    class Meta:
        table_actions = (add_server.AddServerAction,)
        name = 'servers'
        verbose_name = _('Servers')
        row_class = UpdateServerRow
        status_columns = ('status',)
        row_actions = (resize_actions.ResizeServer,)
