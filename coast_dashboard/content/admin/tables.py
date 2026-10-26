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

from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from horizon import tables

from coast_dashboard.content import common


def project_link(row):
    if not row.get('project_id'):
        return row.get('owner') or '-'
    return format_html('<a href="{}">{}</a>', reverse(
        'horizon:identity:projects:detail', args=[row['project_id']]),
        row.get('owner') or '-')


def server_count_link(row):
    count = row.get('server_count') or 0
    if not count:
        return 0
    return format_html(
        '<a href="{}?tab=admin_stacks__servers" '
        'target="_blank" rel="noopener">{}</a>',
        reverse('horizon:admin:stacks:detail', args=[row['id']]), count)


class StacksTable(common.ResourceTable):
    name = tables.Column('name', verbose_name=_('Stack'),
                         link='horizon:admin:stacks:detail')
    owner = tables.Column(project_link, verbose_name=_('Project'))
    status = tables.Column('status', verbose_name=_('Status'))
    created_at = tables.Column('created_at', verbose_name=_('Created'),
                               filters=(common.local_datetime,))
    server_count = tables.Column(server_count_link, verbose_name=_('Servers'))
    workload_count = tables.Column('workload_count',
                                   verbose_name=_('Workloads'))

    workers = tables.Column('worker_count', verbose_name=_('Workers'))
    builds = tables.Column('build_count', verbose_name=_('Build servers'))
    version = tables.Column('engine_version',
                            verbose_name=_('App engine server version'))
    health = tables.Column(
        'health', verbose_name=_('Health'),
        help_text=_('Active in stack inventory and Nova / total servers.'))

    def get_empty_message(self):
        if any(self.request.GET.get(key, '').strip()
               for key in ('q', 'project', 'status', 'host')):
            return _('No stacks match these filters.')
        return super().get_empty_message()

    class Meta:
        name = 'stacks'
        verbose_name = _('Stacks')
        multi_select = False


class ServersTable(common.ResourceTable):
    def get_object_display(self, datum):
        return datum.get('label') or datum['id']

    name = tables.Column('label', verbose_name=_('Name'))
    hostname = tables.Column('hostname', verbose_name=_('Hostname'))
    role = tables.Column('role_label', verbose_name=_('Role'))
    status = tables.Column('status', verbose_name=_('Status'))
    floating_ip = tables.Column('floating_ips', verbose_name=_('Public IP'))

    class Meta:
        name = 'servers'
        verbose_name = _('Servers')
        multi_select = False
