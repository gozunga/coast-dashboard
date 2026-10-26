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

from urllib import parse

from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy
from horizon import tables

from coast_dashboard.content import common
from coast_dashboard.content.services import tables as service_tables
from coast_dashboard import public_text


class CreateOneClick(tables.LinkAction):
    name = 'create'
    verbose_name = _('Create Service')
    url = 'horizon:project:coast.services:create'
    classes = ('ajax-modal',)
    icon = 'plus'
    policy_rules = ()


class DeployTemplate(CreateOneClick):
    name = 'deploy'
    verbose_name = _('Deploy')

    def get_link_url(self, datum):
        return reverse(self.url) + '?' + parse.urlencode(
            dict(template_id=datum['id'], **{
                key: self.table.request.GET[key] for key in
                ('appgroup_id', 'environment_id', 'next')
                if self.table.request.GET.get(key)}))


class DeleteOneClick(service_tables.DeleteService):
    @staticmethod
    def action_present(count):
        return ngettext_lazy('Delete Service', 'Delete Services', count)

    @staticmethod
    def action_past(count):
        return ngettext_lazy('Scheduled deletion of Service',
                             'Scheduled deletion of Services', count)


class OneClickTable(service_tables.ServicesTable):
    template_id = tables.Column('template_id', verbose_name=_('Template'),
                                filters=(public_text.display,))

    class Meta:
        name = 'oneclick'
        verbose_name = _('Services')
        row_class = tables.Row
        table_actions = (CreateOneClick, DeleteOneClick)
        row_actions = (service_tables.EditSettings,
                       service_tables.DeployService,
                       service_tables.StartService,
                       service_tables.StopService,
                       service_tables.RestartService,
                       DeleteOneClick)


class TemplatesTable(common.ResourceTable):
    name = tables.Column('name', verbose_name=_('Name'))
    description = tables.Column('description', verbose_name=_('Description'))
    category = tables.Column('category', verbose_name=_('Category'))

    class Meta:
        name = 'templates'
        verbose_name = _('Templates')
        table_actions = (CreateOneClick,)
        row_actions = (DeployTemplate,)
