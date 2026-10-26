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
from horizon import tables

from coast_dashboard.content import common
from coast_dashboard.content.services.tables import detail_url


class EnvironmentsTable(common.ResourceTable):
    name = tables.Column(common.environment_link, verbose_name=_('Name'))

    class Meta:
        table_actions = (common.CreateEnvironment,)
        name = 'environments'
        verbose_name = _('Environments')
        no_data_message = _('No environments in this app group.')


class AppgroupsTable(common.ResourceTable):
    name = tables.Column(common.appgroup_link, verbose_name=_('Name'))

    class Meta:
        name = 'appgroups'
        verbose_name = _('App Groups')
        no_data_message = _('No app groups in this stack.')


class AppsTable(common.ResourceTable):
    name = tables.Column('name', verbose_name=_('Name'), link=detail_url)
    status = common.StatusColumn()

    class Meta:
        table_actions = (common.CreateApp,)
        name = 'apps'
        verbose_name = _('Apps')
        no_data_message = _('No apps in this app group.')


class ServicesTable(AppsTable):
    class Meta:
        table_actions = (common.CreateService,)
        name = 'related_services'
        verbose_name = _('Services')
        no_data_message = _('No services in this app group.')


class ResourcesTable(AppsTable):
    kind = tables.Column('kind', verbose_name=_('Kind'))

    class Meta:
        table_actions = (common.CreateApp, common.CreateService)
        name = 'resources'
        verbose_name = _('Apps and Services')
        columns = ('name', 'kind', 'status')
        no_data_message = _('No apps or services in this environment.')
