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

from urllib.parse import unquote
from urllib.parse import urlsplit

from django.http import JsonResponse
from django.urls import reverse
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views import generic
from horizon import exceptions
from horizon import forms
from horizon import tables
from horizon import tabs
from horizon import views

from coast_dashboard.api import coast
from coast_dashboard.content import common
from coast_dashboard.content.databases import forms as db_forms
from coast_dashboard.content.databases.tables import DatabasesTable
from coast_dashboard.content.databases.tables import EnginesTable
from coast_dashboard.content.databases.tables import NS
from coast_dashboard.content import details
from coast_dashboard.content.oneclick.views import CatalogMixin
from coast_dashboard.content.services import backups
from coast_dashboard.content.services import logs


class IndexView(common.AppgroupFilterMixin, tables.DataTableView):
    table_class = DatabasesTable
    template_name = 'project/coast_databases/index.html'
    page_title = _('Databases')

    def get_data(self):
        try:
            stacks, apps, envs = common.parent_maps(self.request)
            servers = {s['id']: s['name'] for stack in stacks
                       for s in coast.stack_server_list(self.request, stack)}
            return [dict(common.add_names(item, apps, envs, stacks),
                         server_name=servers.get(item.get('server_id'),
                                                 item.get('server_id')))
                    for item in self.filter_appgroup(
                        coast.database_list(self.request))]
        except Exception:
            exceptions.handle(self.request, _('Unable to retrieve databases.'))
            return []


ENGINE_DESCRIPTIONS = {
    'postgresql': _(
        'Relational SQL database with strong consistency and extensions'),
    'mysql': _('Relational SQL database for web applications'),
    'mariadb': _(
        'Community-developed relational SQL database compatible with MySQL'),
    'mongodb': _('Document database for flexible JSON-like data'),
    'redis': _('In-memory key-value store for caches, queues and sessions'),
    'keydb': _(
        'Multithreaded in-memory key-value store compatible with Redis'),
    'dragonfly': _(
        'In-memory data store compatible with Redis for high throughput'),
    'clickhouse': _('Column-oriented SQL database for real-time analytics'),
}


class EnginesView(CatalogMixin, tables.DataTableView):
    table_class = EnginesTable
    template_name = 'project/coast_databases/engines.html'
    page_title = _('Create database')

    def get_data(self):
        try:
            items = [dict(e, id=e['engine'], name=e['display_name'],
                          description=ENGINE_DESCRIPTIONS.get(e['engine'], ''))
                     for e in coast.database_engine_list(self.request)]
            return self.filter_catalog(items)
        except Exception:
            exceptions.handle(self.request, _('Unable to retrieve engines.'))
            return []


class CreateView(common.CreateContextMixin, forms.ModalFormView):
    form_class = db_forms.CreateDatabase
    template_name = 'project/coast_databases/create.html'
    submit_url = reverse_lazy(NS + 'create')
    success_url = reverse_lazy(NS + 'index')
    page_title = submit_label = _('Create database')

    def get_initial(self):
        return dict(super().get_initial(),
                    engine=self.request.GET.get('engine', ''))


class Overview(details.Overview):
    template_name = 'project/coast_databases/overview.html'

    def get_context_data(self, request, **kwargs):
        context = super().get_context_data(request, **kwargs)
        item = context['item']
        url = urlsplit(item.get('internal_url') or '')
        context['connection'] = [
            (_('Internal host'), item.get('internal_host')),
            (_('Port'), item.get('port')),
            (_('Initial database'), unquote(url.path.lstrip('/'))),
            (_('Username'), unquote(url.username or '')),
            (_('Internal URL'), item.get('internal_url'))]
        context['can_reveal'] = common.project_member(request)
        return context


class Logs(tabs.Tab):
    name = _('Logs')
    slug = 'logs'
    preload = False
    template_name = 'project/coast_services/logs_tab.html'

    def get_context_data(self, request):
        database_id = self.tab_group.kwargs['item']['id']
        return dict(logs.log_context(
            request, database_id, coast.database_logs),
                    tail=logs.LOG_TAIL, fragment_url=reverse(
                        NS + 'logs_fragment', args=[database_id]))


class LogsFragmentView(views.HorizonTemplateView):
    template_name = 'project/coast_services/_log_box.html'

    def get_context_data(self, **kwargs):
        return dict(logs.log_context(self.request, kwargs['database_id'],
                                     coast.database_logs), tail=logs.LOG_TAIL)


class DatabaseTabs(tabs.TabGroup):
    slug = 'database_details'
    tabs = (Overview, backups.Backups, Logs,)
    sticky = True


class DetailView(details.ResourceDetailView):
    resource = 'database'
    index_url = NS + 'index'
    action_table = DatabasesTable
    tab_group_class = DatabaseTabs


class CredentialsView(generic.View):
    def get(self, request, database_id):
        if not common.project_member(request):
            response = JsonResponse(
                {'error': 'Permission denied.'}, status=403)
        else:
            try:
                credentials = coast.database_credentials(request, database_id)
                response = JsonResponse({'credentials': credentials})
            except Exception:
                response = JsonResponse(
                    {'error': 'Unable to retrieve credentials.'}, status=404)
        response['Cache-Control'] = 'no-store'
        return response


class DeleteView(forms.ModalFormView):
    form_class = db_forms.DeleteDatabase
    template_name = 'project/coast_databases/delete.html'
    success_url = reverse_lazy(NS + 'index')
    page_title = submit_label = _('Delete database')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['item'] = coast.database_get(
            self.request, self.kwargs['database_id'])
        return kwargs

    def get_context_data(self, **kwargs):
        return dict(super().get_context_data(**kwargs),
                    submit_url=self.request.path)


class LimitsView(DeleteView):
    form_class = db_forms.EditLimits
    template_name = 'project/coast_services/settings_form.html'
    page_title = submit_label = _('Edit limits')

    def get_initial(self):
        item = coast.database_get(self.request, self.kwargs['database_id'])
        return {key: item.get(key) for key in ('cpu_limit', 'memory_limit_mb')}

    def get_success_url(self):
        return reverse(NS + 'detail', args=[self.kwargs['database_id']])


class PublicAccessView(LimitsView):
    template_name = 'project/coast_databases/public_access.html'
    form_class = db_forms.PublicAccess
    page_title = submit_label = _('Public access')

    def get_initial(self):
        item = coast.database_get(self.request, self.kwargs['database_id'])
        public = item.get('public') or {}
        return dict(public, allow_from=(
            'anywhere' if public.get('source', '0.0.0.0/0') == '0.0.0.0/0'
            else 'specific'))
