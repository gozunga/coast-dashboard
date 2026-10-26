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

from django.core.paginator import Paginator
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from horizon import exceptions
from horizon import forms
from horizon import tables

from coast_dashboard.api import coast
from coast_dashboard.content import common
from coast_dashboard.content.oneclick import forms as project_forms
from coast_dashboard.content.oneclick import tables as project_tables


class CatalogMixin:
    """Shared search form and filtering for deployable catalogs."""

    search_fields = ('name', 'description')

    def filter_catalog(self, items):
        search = self.request.GET.get('q', '').strip().casefold()
        return [item for item in items if search in ' '.join(
            str(item.get(field) or '') for field in self.search_fields
        ).casefold()]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['catalog_url'] = self.request.path
        context['template_search'] = self.request.GET.get('q', '')
        params = self.request.GET.copy()
        params.pop('templates_page', None)
        params.pop('q', None)
        context['template_search_params'] = list(params.items())
        return context


class IndexView(CatalogMixin, common.AppgroupFilterMixin,
                tables.MultiTableView):
    search_fields = ('name', 'description', 'category')
    table_classes = (project_tables.OneClickTable,
                     project_tables.TemplatesTable)
    template_name = 'project/coast_oneclick/index.html'
    page_title = _('Services')

    def get_oneclick_data(self):
        try:
            stacks, apps, envs = common.parent_maps(self.request)
            return [common.add_names(
                        dict(item, deployed=bool(
                            item.get('current_deployment_id'))), apps, envs,
                        stacks)
                    for item in self.filter_appgroup(
                        coast.service_list(self.request, kind='service'))]
        except Exception:
            exceptions.handle(self.request, _('Unable to retrieve services.'))
            return []

    def get_templates_data(self):
        catalog = {}
        try:
            versions = set()
            for stack in coast.stack_list(self.request):
                version = stack.get('engine_version')
                if version in versions:
                    continue
                versions.add(version)
                for item in coast.template_list(self.request, stack['id']):
                    catalog.setdefault(item['id'], item)
        except Exception:
            exceptions.handle(self.request, _('Unable to retrieve templates.'),
                              details='')
            catalog = {}
        items = sorted(catalog.values(), key=lambda item: (
            item['name'].casefold(), item['id']))
        items = self.filter_catalog(items)
        self.templates_page = Paginator(items, 50).get_page(
            self.request.GET.get('templates_page'))
        return self.templates_page.object_list

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        page = self.templates_page
        context['templates_page'] = page
        params = self.request.GET.copy()
        params.pop('templates_page', None)
        params.pop('q', None)
        params['q'] = context['template_search']
        for direction in ('previous', 'next'):
            if getattr(page, 'has_' + direction)():
                params['templates_page'] = getattr(
                    page, direction + '_page_number')()
                context['templates_' + direction + '_url'] = (
                    '?' + params.urlencode())
        return context


class CreateView(common.CreateContextMixin, common.DeploymentRedirectMixin,
                 forms.ModalFormView):
    form_class = project_forms.CreateOneClick
    template_name = 'project/coast_oneclick/create.html'
    submit_url = reverse_lazy('horizon:project:coast.services:create')
    success_url = reverse_lazy('horizon:project:coast.services:index')
    submit_label = _('Deploy')
    page_title = _('Create Service')

    def get_initial(self):
        initial = super().get_initial()
        initial['template_id'] = self.request.GET.get('template_id', '')
        return initial

    def get_object_id(self, item):
        return item['id']
