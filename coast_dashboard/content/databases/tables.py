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

from urllib.parse import urlencode

from django.contrib import messages
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from horizon import exceptions
from horizon import tables

from coast_dashboard.api import coast

from coast_dashboard.content import common
from coast_dashboard.content.oneclick import tables as oneclick_tables
from coast_dashboard.content import related_tables
from coast_dashboard.content.services import tables as service_tables


NS = 'horizon:project:coast.databases:'


def name_link(item):
    return format_html('<a href="{}">{}</a>{}',
                       reverse(NS + 'detail', args=[item['id']]),
                       item['name'], common.inline_status_badge(item))


class Create(tables.LinkAction):
    name = 'create'
    verbose_name = _('Create database')
    url = NS + 'engines'
    icon = 'plus'

    def get_link_url(self, datum=None):
        params = self.table.request.GET.copy()
        if params.get("appgroup"):
            params["appgroup_id"] = params["appgroup"]
        return reverse(self.url) + ("?" + params.urlencode() if params else "")

    def allowed(self, request, datum=None):
        return common.project_member(request)


class Delete(Create):
    name = 'delete'
    verbose_name = _('Delete database')
    url = NS + 'delete'
    icon = 'trash'

    def get_link_url(self, datum=None):
        return tables.LinkAction.get_link_url(self, datum)


class StateAction(tables.Action):
    requires_input = True
    required_status = 'ACTIVE'

    def allowed(self, request, datum=None):
        return bool(common.project_member(request) and datum and
                    common.status(datum) == self.required_status and
                    not common.is_busy(datum) and not datum.get('task_owner'))

    def single(self, table, request, obj_id):
        if not self.allowed(request, table.get_object_by_id(obj_id)):
            return
        try:
            coast.database_action(request, obj_id, self.name)
            messages.success(request, _('Operation requested.'))
        except Exception as exc:
            exceptions.handle(request, coast.error_message(
                exc, _('Unable to change database state.')))


class Start(StateAction):
    name = 'start'
    verbose_name = _('Start')
    required_status = 'STOPPED'


class Stop(StateAction):
    name = 'stop'
    verbose_name = _('Stop')


class Restart(StateAction):
    name = 'restart'
    verbose_name = _('Restart')


class PublicAccess(Delete):
    name = 'public_access'
    verbose_name = _('Public access')
    url = NS + 'public_access'
    classes = ('ajax-modal',)
    icon = 'globe'


class Limits(PublicAccess):
    name = 'limits'
    verbose_name = _('Edit limits')
    url = NS + 'limits'
    icon = 'pencil'


class DatabaseStatusColumn(common.StatusColumn):
    def get_data(self, datum):
        badge = super().get_data(datum)
        if datum.get('status') == 'ERROR' and datum.get('fault'):
            return format_html('<span title="{}">{}</span>',
                               datum['fault'], badge)
        return badge


class DatabasesTable(service_tables.ServicesTable):
    name = tables.Column(name_link, verbose_name=_('Name'))
    engine = tables.Column('engine', verbose_name=_('Engine'))
    version = tables.Column('version', verbose_name=_('Version'))
    status = DatabaseStatusColumn()
    appgroup_name = tables.Column('appgroup_name', verbose_name=_('App group'))
    environment_name = tables.Column('environment_name',
                                     verbose_name=_('Environment'))
    server_id = tables.Column(
        lambda item: item.get('server_name') or item.get('server_id'),
        verbose_name=_('Server'))
    created_at = tables.Column('created_at', verbose_name=_('Created'))

    class Meta:
        name = 'databases'
        verbose_name = _('Databases')
        columns = ('name', 'engine', 'version', 'status', 'stack_name',
                   'appgroup_name', 'environment_name', 'server_id',
                   'created_at')
        row_class = tables.Row
        table_actions = (Create,)
        row_actions = (Start, Stop, Restart, PublicAccess, Limits, Delete,)


class DeployEngine(oneclick_tables.DeployTemplate):
    verbose_name = _('Create database')
    url = NS + 'create'

    def get_link_url(self, datum):
        params = dict(self.table.request.GET.items(), engine=datum['engine'])
        return reverse(self.url) + '?' + urlencode(params)


class EnginesTable(oneclick_tables.TemplatesTable):
    versions = tables.Column(lambda row: ', '.join(row['versions']),
                             verbose_name=_('Versions'))

    class Meta:
        name = 'engines'
        verbose_name = _('Database engines')
        columns = ('name', 'description', 'versions')
        table_actions = ()
        row_actions = (DeployEngine,)


class RelatedCreate(common.RelatedCreate, Create):
    classes = ()

    def get_link_url(self, datum=None):
        url = super().get_link_url(datum)
        environment = self.table.request.GET.get('environment_id')
        if environment:
            url += '&' + urlencode({'environment_id': environment})
        return url


class RelatedDatabasesTable(related_tables.ServicesTable):
    name = tables.Column(name_link, verbose_name=_('Name'))
    status = DatabaseStatusColumn()

    class Meta:
        name = 'databases'
        verbose_name = _('Databases')
        table_actions = (RelatedCreate,)
        row_actions = (Start, Stop, Restart, PublicAccess, Limits, Delete,)
        no_data_message = _('No databases in this app group.')
