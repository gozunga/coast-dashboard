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

from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.cache import patch_cache_control
from django.utils.translation import gettext_lazy as _
from horizon import exceptions
from horizon import tabs
from horizon import views

from coast_dashboard.api import coast
from coast_dashboard.content import common
from coast_dashboard.content import details


def log_context(request, service_id, container_id):
    context = {'tail': 200, 'empty_text': _('No container log lines yet.')}
    try:
        context['logs'] = coast.service_container_logs(
            request, service_id, container_id)
    except Exception as exc:
        context['log_error'] = coast.error_message(
            exc, _('Unable to retrieve container logs.'))
    return context


class Overview(details.Overview):
    template_name = 'project/coast_services/container_overview.html'


class Environment(details.Overview):
    name = _('Environment')
    slug = 'environment'
    template_name = 'project/coast_services/container_environment.html'

    def get_context_data(self, request, **kwargs):
        item = self.tab_group.kwargs['item']
        return {'environment': sorted(item.get('environment', {}).items())}


class Logs(tabs.Tab):
    name = _('Logs')
    slug = 'logs'
    preload = False
    template_name = 'project/coast_services/logs_tab.html'

    def get_context_data(self, request):
        kwargs = self.tab_group.kwargs
        context = log_context(request, kwargs['service_id'],
                              kwargs['container_id'])
        context['fragment_url'] = reverse(
            common.coast_ns(request) + 'container_logs_fragment',
            args=[kwargs['service_id'], kwargs['container_id']])
        return context


class ContainerTabs(tabs.TabGroup):
    slug = 'container_details'
    tabs = (Overview, Logs, Environment)
    sticky = True


class NoStoreMixin:
    def dispatch(self, request, *args, **kwargs):
        try:
            response = super().dispatch(request, *args, **kwargs)
        except exceptions.Http302 as exc:
            response = HttpResponseRedirect(exc.location)
        patch_cache_control(response, no_store=True)
        return response


class DetailView(NoStoreMixin, details.ResourceDetailView):
    resource = 'container'
    tab_group_class = ContainerTabs
    template_name = 'project/coast_services/container.html'

    @property
    def index_url(self):
        return common.coast_ns(self.request) + 'index'

    def load_item(self):
        self.service = coast.service_get(
            self.request, self.kwargs['service_id'])
        return coast.service_container_get(
            self.request, self.kwargs['service_id'],
            self.kwargs['container_id'])

    def get_actions(self, item):
        # The container API has no write actions.
        return ''

    def get_context_data(self, **kwargs):
        from coast_dashboard.content.services.views import service_breadcrumb
        context = super().get_context_data(**kwargs)
        service_url = reverse(common.coast_ns(self.request) + 'detail',
                              args=[self.kwargs['service_id']])
        crumbs = service_breadcrumb(self.request, self.service['name'])
        crumbs[-1] = (self.service['name'], service_url +
                      '?tab=service_details__containers')
        context['container_breadcrumb'] = crumbs + [
            (self.get_data()['name'], None)]
        return context


class LogsFragmentView(NoStoreMixin, views.HorizonTemplateView):
    template_name = 'project/coast_services/_log_box.html'

    def get_context_data(self, **kwargs):
        return log_context(self.request, kwargs['service_id'],
                           kwargs['container_id'])
