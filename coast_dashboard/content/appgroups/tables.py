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

from django.urls import reverse
from django.utils.html import format_html
from django.utils.html import format_html_join
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy
from horizon import tables

from coast_dashboard.api import coast
from coast_dashboard.content.appgroups import related
from coast_dashboard.content import common


def related_link(item, resource, panel):
    rows = item.get(resource)
    if rows is None:
        return _('Unavailable')
    url = reverse('horizon:project:%s:index' % panel)
    url += '?' + urlencode({'appgroup': item['id']})
    return format_html('<a href="{}">{}</a>', url, len(rows))


def environments(item):
    rows = item.get('environments')
    if rows and len(rows) <= 3:
        return format_html_join(', ', '{}', (
            (common.environment_link(row),) for row in rows))
    return related_link(item, 'environments', 'coast.environments')


def apps(item):
    return related_link(item, 'apps', 'coast.apps')


def services(item):
    return related_link(item, 'services', 'coast.services')


class CreateAppgroup(tables.LinkAction):
    name = 'create'
    verbose_name = _('Create App Group')
    url = 'horizon:project:coast.appgroups:create'
    classes = ('ajax-modal',)
    icon = 'plus'
    policy_rules = ()


class DeleteAppgroup(common.ApiErrorMixin, tables.DeleteAction):
    policy_rules = ()

    @staticmethod
    def action_present(count):
        return ngettext_lazy('Delete App Group', 'Delete App Groups',
                             count)

    @staticmethod
    def action_past(count):
        return ngettext_lazy('Scheduled deletion of App Group',
                             'Scheduled deletion of App Groups', count)

    def delete(self, request, obj_id):
        coast.appgroup_delete(request, obj_id)


class UpdateRow(common.InlineStatusRow):
    def get_data(self, request, appgroup_id):
        item = related.for_group(
            request, coast.appgroup_get(request, appgroup_id))
        return common.add_parent_name(
            item, 'stack', common.name_map(request, coast.stack_list))


class AppgroupsTable(common.ResourceTable):
    name = tables.Column(common.appgroup_link, verbose_name=_('Name'))
    environments = tables.Column(environments, verbose_name=_('Environments'))
    apps = tables.Column(apps, verbose_name=_('Apps'))
    services = tables.Column(services, verbose_name=_('Services'))
    stack_name = tables.Column('stack_name', verbose_name=_('Stack'))

    class Meta(object):
        name = 'appgroups'
        verbose_name = _('App Groups')
        row_class = UpdateRow
        table_actions = (CreateAppgroup, DeleteAppgroup)
        row_actions = (DeleteAppgroup,)


class DetailActions(AppgroupsTable):
    class Meta:
        name = 'appgroups'
        row_actions = (common.CreateApp, common.CreateService,
                       common.CreateEnvironment, DeleteAppgroup,)
