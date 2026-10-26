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

from urllib.parse import urlsplit

from django.middleware import csrf
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from horizon import exceptions
from horizon import tabs

from coast_dashboard.api import coast
from coast_dashboard.content import common
from coast_dashboard.content import details
from coast_dashboard.content.services import backups
from coast_dashboard.content.services import dotenv
from coast_dashboard.content.services import files
from coast_dashboard.content.services import forms as service_forms
from coast_dashboard.content.services import logs as service_logs
from coast_dashboard.content.services import tables


class Overview(details.Overview):
    template_name = 'project/coast_services/overview.html'


class Deployments(tabs.TableTab):
    name = _('Deployments')
    slug = 'deployments'
    table_classes = (tables.DeploymentsTable,)
    template_name = 'horizon/common/_detail_table.html'
    preload = False

    def get_deployments_data(self):
        try:
            return coast.service_deployment_list(
                self.request, self.tab_group.kwargs['service_id'])
        except Exception:
            exceptions.handle(self.request,
                              _('Unable to retrieve deployments.'))
            return []


def redeploy_target(service):
    """Where the Redeploy button posts: the table that lists this row."""
    if service.get('kind') == 'service':
        return {'index_url': reverse('horizon:project:coast.services:index'),
                'deploy_action': 'oneclick__deploy__%s' % service.get('id')}
    return {'index_url': reverse('horizon:project:coast.apps:index'),
            'deploy_action': 'services__deploy__%s' % service.get('id')}


def settings_context(request, service, service_id):
    return dict(
        service=service, service_id=service_id,
        pending=bool(service.get('pending_changes')),
        can_redeploy=common.can_redeploy(service),
        **redeploy_target(service))


class Domains(tabs.TableTab):
    name = _('Domains')
    slug = 'domains'
    table_classes = (tables.DomainsTable,)
    template_name = 'horizon/common/_detail_table.html'
    preload = False

    def get_domains_data(self):
        try:
            rows = [dict(row) for row in coast.service_domain_list(
                self.request, self.tab_group.kwargs['service_id'])]
        except Exception:
            exceptions.handle(self.request, _('Unable to retrieve domains.'))
            return []
        item = self.tab_group.kwargs.get('item') or {}
        address = item.get('worker_ip')
        for row in rows:
            row['worker_ip'] = address
            if coast.dns_available(self.request):
                row['manage_dns_url'] = reverse(
                    common.coast_ns(self.request) + 'edit_domain',
                    args=[self.tab_group.kwargs['service_id'], row['id']])
        url = urlsplit(item.get('default_url') or '')
        if url.hostname:
            rows.insert(0, {'id': 'default', 'is_default': True,
                            'primary': not any(r.get('primary') for r in rows),
                            'fqdn': url.hostname, 'status': 'Default',
                            'tls': ('letsencrypt' if url.scheme == 'https'
                                    else 'none')})
        return rows


class Storage(tabs.TableTab):
    name = _('Storage')
    slug = 'storage'
    table_classes = (tables.StorageTable,)
    template_name = 'horizon/common/_detail_table.html'
    preload = False

    def allowed(self, request):
        return coast.storage_supported(request)

    def get_storage_data(self):
        service_id = self.tab_group.kwargs['service_id']
        item = self.tab_group.kwargs.get('item') or {}
        if not item.get('stack_id'):
            return []
        try:
            return coast.storage_list(self.request, item['stack_id'],
                                      service_id)
        except Exception:
            exceptions.handle(self.request,
                              _('Unable to retrieve storage.'))
            return []


class Settings(tabs.TableTab):
    name = _('Env vars')
    # Keep existing environment variable links and redirects valid.
    slug = 'settings'
    table_classes = (tables.EnvTable,)
    template_name = 'project/coast_services/settings.html'
    preload = False

    def get_env_data(self):
        if hasattr(self, '_env_rows'):
            return self._env_rows
        try:
            self._env_rows = coast.service_env_list(
                self.request, self.tab_group.kwargs['service_id'])
        except Exception:
            exceptions.handle(self.request,
                              _('Unable to retrieve environment variables.'))
            self._env_rows = []
        return self._env_rows

    def get_context_data(self, request, **kwargs):
        context = super().get_context_data(request, **kwargs)
        service_id = self.tab_group.kwargs['service_id']
        context['developer_url'] = reverse(
            common.coast_ns(request) + 'env_developer',
            args=[service_id])
        context['env_app'] = (
            self.tab_group.kwargs.get('item', {}).get('kind') != 'service')
        context['dotenv_text'] = dotenv.render(
            self.get_env_data(), app=context['env_app'])
        # Tabs render without the request context processors, so the
        # inline Developer View form needs the CSRF token passed in.
        context['csrf_value'] = csrf.get_token(request)
        context['developer_active'] = request.GET.get('view') == 'developer'
        return context


class Logs(tabs.Tab):
    name = _('Logs')
    slug = 'logs'
    template_name = 'project/coast_services/logs_tab.html'
    preload = False

    def get_context_data(self, request):
        service_id = self.tab_group.kwargs['service_id']
        context = service_logs.log_context(request, service_id)
        context.update(tail=service_logs.LOG_TAIL, fragment_url=reverse(
            common.coast_ns(request) + 'logs_fragment',
            args=[service_id]))
        return context


class Metrics(tabs.Tab):
    name = _('Metrics')
    slug = 'metrics'
    template_name = 'project/coast_services/metrics.html'
    preload = False

    def allowed(self, request):
        return coast.service_metrics_supported(request)

    def get_context_data(self, request):
        return {'metrics_url': reverse(
            common.coast_ns(request) + 'metrics',
            args=[self.tab_group.kwargs['service_id']])}


class Console(tabs.Tab):
    name = _('Console')
    slug = 'console'
    template_name = 'project/coast_services/console.html'
    preload = False

    def allowed(self, request):
        # Readers can open the detail page. The console API allows members.
        return common.project_member(request)

    def get_context_data(self, request):
        service_id = self.tab_group.kwargs['service_id']
        return {
            'console_url': reverse(
                common.coast_ns(request) + 'console', args=[service_id]),
            'csrf_value': csrf.get_token(request)}


class Webhooks(tabs.Tab):
    name = _('Webhooks')
    slug = 'webhooks'
    template_name = 'project/coast_services/webhooks.html'
    preload = False

    def allowed(self, request):
        # Deploy and Git push webhooks are for apps, not services.
        item = self.tab_group.kwargs.get('item') or {}
        return item.get('kind') != 'service'

    LABELS = (('deploy', _('Coast deploy URL')), ('github', _('GitHub')),
              ('gitlab', _('GitLab')), ('bitbucket', _('Bitbucket')),
              ('gitea', _('Gitea')))

    def get_context_data(self, request):
        service_id = self.tab_group.kwargs['service_id']
        context = {'regenerate_url': reverse(
            common.coast_ns(request) + 'webhooks_regenerate',
            args=[service_id]), 'csrf_value': csrf.get_token(request)}
        try:
            hooks = coast.service_webhooks(request, service_id)
        except exceptions.NotAuthorized:
            raise
        except Exception:
            context['hooks_error'] = _(
                'Webhook URLs are only shown to project members.')
            return context
        context['enabled'] = hooks.get('enabled')
        context['urls'] = [(label, hooks.get(key))
                           for key, label in self.LABELS if hooks.get(key)]
        return context


class Compose(tabs.Tab):
    name = _('Compose')
    slug = 'compose'
    template_name = 'project/coast_services/compose.html'
    preload = False

    def allowed(self, request):
        return (common.project_member(request) and
                common.is_compose(self.tab_group.kwargs.get('item') or {}))

    def get_context_data(self, request):
        service_id = self.tab_group.kwargs['service_id']
        form = getattr(request, 'compose_form', None)
        error = None
        if form is None:
            try:
                yaml = coast.service_compose_get(request, service_id)
                form = service_forms.ComposeForm(
                    request, initial={'yaml': yaml, 'service_id': service_id})
            except Exception as exc:
                error = coast.error_message(
                    exc, _('Unable to retrieve Compose YAML.'))
        return {'compose_form': form, 'compose_error': error,
                'csrf_value': csrf.get_token(request),
                'compose_url': reverse(common.coast_ns(request) + 'detail',
                                       args=[service_id]) +
                '?tab=service_details__compose'}


class Containers(tabs.TableTab):
    name = _('Containers')
    slug = 'containers'
    table_classes = (tables.ContainersTable,)
    template_name = 'project/coast_services/containers.html'
    preload = False

    def allowed(self, request):
        return common.is_compose(self.tab_group.kwargs.get('item') or {})

    def get_containers_data(self):
        service_id = self.tab_group.kwargs['service_id']
        try:
            rows = coast.service_container_list(self.request, service_id)
            for row in rows:
                row['detail_url'] = reverse(
                    common.coast_ns(self.request) + 'container',
                    args=[service_id, row['id']])
            return rows
        except Exception as exc:
            exceptions.handle(self.request, coast.error_message(
                exc, _('Unable to retrieve containers.')))
            return []


class ServiceTabs(tabs.TabGroup):
    slug = 'service_details'
    tabs = (Overview, backups.Backups, Deployments, Logs, Console, Metrics,
            Domains, Storage, files.Files, Settings, Compose, Containers,
            Webhooks)
    sticky = True
