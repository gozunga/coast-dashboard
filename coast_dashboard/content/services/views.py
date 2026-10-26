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

import re
from urllib.parse import urlsplit

from django.contrib import messages
from django.http import HttpResponseForbidden
from django.http import JsonResponse
from django import shortcuts
from django.template.loader import render_to_string
from django.urls import reverse
from django.urls import reverse_lazy
from django.utils.cache import patch_cache_control
from django.utils.translation import gettext_lazy as _
from django.views import generic
from horizon import exceptions
from horizon import forms
from horizon import tables
from horizon import views

from coast_dashboard.api import coast
from coast_dashboard.content import common
from coast_dashboard.content import details
from coast_dashboard.content.services import dotenv
from coast_dashboard.content.services import forms as project_forms
from coast_dashboard.content.services import logs as service_logs
from coast_dashboard.content.services import tables as project_tables
from coast_dashboard.content.services import tabs as project_tabs


def service_breadcrumb(request, title):
    dashboard = request.horizon['dashboard']
    group = dashboard.get_panel_group('app_hosting')
    crumbs = [(dashboard.name, None)]
    if group is not None:
        crumbs.append((group.name, None))
    return crumbs + [
        (_('Services'), reverse('horizon:project:coast.services:index')),
        (title, None)]


class IndexView(common.AppgroupFilterMixin, tables.DataTableView):
    table_class = project_tables.ServicesTable
    template_name = 'project/coast_services/index.html'
    page_title = _('Apps')

    def get_data(self):
        try:
            stacks, apps, envs = common.parent_maps(self.request)
            return [common.add_names(common.service_status(self.request, item),
                                     apps, envs, stacks)
                    for item in self.filter_appgroup(
                        coast.service_list(self.request, kind='app'))]
        except Exception:
            exceptions.handle(self.request, _('Unable to retrieve apps.'))
            return []


class DetailView(details.ResourceDetailView):
    resource = 'service'

    @property
    def index_url(self):
        return common.coast_ns(self.request) + 'index'
    tab_group_class = project_tabs.ServiceTabs

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        # Detail responses can include Compose secrets, including AJAX tabs.
        patch_cache_control(response, no_store=True)
        return response

    def post(self, request, *args, **kwargs):
        if 'operation' not in request.POST:
            return super().post(request, *args, **kwargs)
        if not (common.project_member(request) and
                common.is_compose(self.get_data())):
            return HttpResponseForbidden()
        form = project_forms.ComposeForm(
            request, request.POST,
            initial={'service_id': kwargs['service_id']})
        request.compose_form = form
        if form.is_valid() and form.handle(request, form.cleaned_data):
            if form.cleaned_data['operation'] == 'redeploy':
                return shortcuts.redirect(common.service_logs_page(
                    kwargs['service_id'], self.get_data().get('kind')))
            messages.success(request, _('Compose YAML saved. Redeploy to '
                                        'apply the changes.'))
            return shortcuts.redirect(
                reverse(common.coast_ns(request) + 'detail',
                        args=[kwargs['service_id']]) +
                '?tab=service_details__compose')
        return self.get(request, *args, **kwargs)

    def _worker(self, stack_id, server_id):
        server = None
        try:
            servers = coast.stack_server_list(self.request, stack_id)
            server = next((row for row in servers
                           if row.get('id') == server_id), None)
        except Exception:
            server = None
        # List rows include floating_ip. Show fills a partial row.
        if (server and 'floating_ip' not in server and
                'public_ip' not in server):
            try:
                shown = coast.stack_server_get(
                    self.request, stack_id, server_id)
                if shown:
                    server = dict(server, **shown)
            except Exception:
                pass
        return server

    def load_item(self):
        item = super().load_item()
        source = item.get('source') or {}
        repo = source.get('repo_url') or ''
        if (source.get('type') == 'git' and
                (repo.startswith('ssh://') or
                 re.fullmatch(r'[^@/:\s]+@[^/:\s]+:[^\s]+', repo))):
            item = coast.service_get(self.request, item['id'],
                                     microversion=coast.DEPLOY_KEY_VERSION)
        self.deployments = coast.service_deployment_list(
            self.request, item['id'])
        item = common.service_status(self.request, item, self.deployments)
        stacks, apps, envs = common.parent_maps(self.request)
        stack_id = item.get('stack_id')
        server_id = item.get('server_id')
        item['worker_name'] = _('Unavailable')
        item['worker_ip'] = None
        server = None
        if stack_id and server_id:
            item['worker_stack_url'] = reverse(
                'horizon:project:coast.stacks:detail', args=[stack_id])
            server = self._worker(stack_id, server_id)
            name = (server or {}).get('name') or _('Unavailable')
        else:
            name = _('Unavailable')
        address = common.public_address(server, item.get('dns_records'))
        item['worker_ip'] = address
        item['worker_name'] = name
        try:
            domains = coast.service_domain_list(self.request, item['id'])
        except Exception:
            domains = []
        links = []
        for domain in domains:
            href = common.domain_url(domain)
            if href:
                links.append({'fqdn': domain.get('fqdn'), 'href': href})
        item['domain_links'] = links
        item['domains_url'] = reverse(
            common.coast_ns(self.request) + 'detail', args=[item['id']]) + (
                '?tab=service_details__domains')
        return common.add_names(item, apps, envs, stacks)

    def get_action_table(self, item):
        if item.get('kind') == 'service':
            from coast_dashboard.content.oneclick.tables import OneClickTable
            return OneClickTable(self.request, data=[item])
        return project_tables.ServicesTable(self.request, data=[item])

    def get_actions(self, item):
        table = self.get_action_table(item)
        actions = table.get_row_actions(item)
        change_image = project_tables.ChangeImage()
        change_image.table = table
        if change_image.allowed(self.request, item):
            actions.append(change_image)
        deploy = next((action for action in actions
                       if action.name == 'deploy'), None)
        if deploy:
            deploy.action_type = 'primary'
        edit = next((action for action in actions
                     if action.name == 'edit_settings'), None)
        remaining = [action for action in actions
                     if action.name not in ('deploy', 'edit_settings')]
        latest = max(self.deployments, key=lambda row: row['number'],
                     default={})
        cancel = None
        if latest.get('id'):
            table = project_tables.DeploymentsTable(
                self.request, data=[latest], service_id=item['id'])
            cancel = next((action for action in table.get_row_actions(latest)
                           if action.name == 'cancel'), None)
            if cancel:
                cancel.attrs['formaction'] = reverse(
                    common.coast_ns(self.request) + 'detail', args=[item['id']]
                ) + '?tab=service_details__deployments'
        context = {
            'deploy': deploy, 'edit': edit, 'row_actions': remaining,
            'row_id': item['id'], 'cancel': cancel,
            'deployment_id': latest.get('id')}
        return render_to_string(
            'project/coast_services/_detail_actions.html', context,
            request=self.request)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        item = self.get_data()
        context.update(project_tabs.settings_context(
            self.request, item, item['id']))
        context['url'] = context['index_url']
        context['is_template'] = common.is_template(item)
        if project_tables.ChangeImage().allowed(self.request, item):
            item['change_image_url'] = reverse(
                common.coast_ns(self.request) + 'change_image',
                args=[item['id']])
        if common.project_member(self.request):
            source = item.get('source') or {}
            if source.get('deploy_key'):
                item['replace_key_url'] = reverse(
                    common.coast_ns(self.request) + 'replace_deploy_key',
                    args=[item['id']])
            if source.get('type') == 'dockerfile':
                item['edit_dockerfile_url'] = reverse(
                    common.coast_ns(self.request) + 'edit_dockerfile',
                    args=[item['id']])
        context['service_breadcrumb'] = service_breadcrumb(
            self.request, item.get('name') or item['id'])
        return context


class CreateView(common.CreateContextMixin, common.DeploymentRedirectMixin,
                 forms.ModalFormView):
    form_class = project_forms.CreateService
    template_name = 'project/coast_services/create.html'
    submit_url = reverse_lazy('horizon:project:coast.apps:create')
    success_url = reverse_lazy('horizon:project:coast.apps:index')
    submit_label = page_title = _('Create App')

    def form_valid(self, form):
        response = super().form_valid(form)
        item = getattr(form, 'created_item', None)
        if item and (item.get('source') or {}).get('deploy_key'):
            url = reverse('horizon:project:coast.apps:detail',
                          args=[item['id']])
            if 'X-Horizon-Location' in response:
                response['X-Horizon-Location'] = url
            if response.status_code in (301, 302):
                response['Location'] = url
        return response

    def get_object_id(self, item):
        return item['id']


class LogsView(views.HorizonTemplateView):
    template_name = 'project/coast_services/logs.html'
    page_title = _('Logs')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(service_logs.log_context(self.request,
                                                kwargs['service_id']))
        context['service_id'] = kwargs['service_id']
        context['detail_url'] = reverse(
            common.coast_ns(self.request) + 'detail',
            args=[kwargs['service_id']])
        try:
            service = coast.service_get(self.request, kwargs['service_id'])
        except Exception:
            service = {}
        context['is_template'] = common.is_template(service)
        context['service_breadcrumb'] = service_breadcrumb(
            self.request, self.page_title)
        return context


class LogsFragmentView(views.HorizonTemplateView):
    """The log box only, for the Logs tab Refresh button."""
    template_name = 'project/coast_services/_log_box.html'

    def get_context_data(self, **kwargs):
        context = service_logs.log_context(self.request, kwargs['service_id'])
        context['tail'] = service_logs.LOG_TAIL
        return context


class DeploymentView(views.HorizonTemplateView):
    template_name = 'project/coast_services/deployment.html'
    page_title = _('Deployment')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        service_id = kwargs['service_id']
        deployment_id = kwargs['deployment_id']
        fallback = reverse(common.coast_ns(self.request) + 'detail',
                           args=[service_id]) + (
                               '?tab=service_details__deployments')
        try:
            item = coast.service_deployment_get(
                self.request, service_id, deployment_id)
        except Exception as exc:
            exceptions.handle(self.request, coast.error_message(
                exc, _('Unable to retrieve the deployment.')),
                redirect=fallback)
            raise exceptions.Http302(fallback)
        context.update(service_logs.deployment_log_context(
            self.request, service_id, deployment_id))
        context['deployment_breadcrumb'] = service_breadcrumb(
            self.request, self.page_title)
        context['deployments_url'] = fallback
        context['logs_url'] = common.service_logs_page(
            service_id, 'service' if 'coast.services' in common.coast_ns(
                self.request) else 'app')
        context.update(item=item,
                       service_id=service_id,
                       can_cancel=project_tables.CancelDeployment().allowed(
                           self.request, item),
                       cancel_url=reverse(
                           common.coast_ns(self.request) +
                           'deployment_cancel',
                           args=[service_id, deployment_id]),
                       fragment_url=reverse(
                           common.coast_ns(self.request) +
                           'deployment_log_fragment',
                           args=[service_id, deployment_id]))
        if item.get('number'):
            context['page_title'] = _('Deployment %s') % item['number']
            context['deployment_breadcrumb'][-1] = (
                context['page_title'], None)
        return context


class DeploymentCancelView(generic.View):
    """Request cancellation, then return to the same deployment."""

    def post(self, request, service_id, deployment_id):
        try:
            coast.service_deployment_cancel(request, service_id, deployment_id)
            messages.success(request, _('Cancellation requested.'))
        except Exception as exc:
            messages.error(request, coast.error_message(
                exc, _('Unable to cancel the deployment.')))
        return shortcuts.redirect(
            common.coast_ns(request) + 'deployment',
            service_id=service_id, deployment_id=deployment_id)


class DeploymentLogFragmentView(views.HorizonTemplateView):
    """The build log box only, polled while a deployment runs."""
    template_name = 'project/coast_services/_deployment_log_live.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(service_logs.deployment_log_context(
            self.request, kwargs['service_id'], kwargs['deployment_id']))
        return context


class DeploymentLogView(views.HorizonTemplateView):
    template_name = 'project/coast_services/deployment_log.html'
    page_title = _('Build Log')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(service_logs.deployment_log_context(
            self.request, kwargs['service_id'], kwargs['deployment_id']))
        context['service_id'] = kwargs['service_id']
        context['detail_url'] = reverse(
            common.coast_ns(self.request) + 'detail',
            args=[kwargs['service_id']])
        context['service_breadcrumb'] = service_breadcrumb(
            self.request, self.page_title)
        return context


class SetEnvView(forms.ModalFormView):
    form_class = project_forms.SetEnv
    template_name = 'project/coast_services/settings_form.html'
    modal_id = 'coast_settings_modal'
    form_id = 'coast_settings_form'
    submit_label = _('Save')
    page_title = _('Environment Variable')

    def is_app(self):
        if not hasattr(self, '_env_app'):
            self._env_app = coast.service_get(
                self.request, self.kwargs['service_id']
            ).get('kind') != 'service'
        return self._env_app

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['service_id'] = self.kwargs['service_id']
        if self.form_class in (project_forms.SetEnv,
                               project_forms.EnvDeveloperView):
            kwargs['app'] = self.is_app()
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        key = self.kwargs.get('key')
        if key:
            try:
                rows = coast.service_env_list(self.request,
                                              self.kwargs['service_id'])
                row = next(row for row in rows if row['key'] == key)
                initial.update(key=key, secret=row['secret'],
                               build_time=row.get('build_time'))
                if not row['secret']:
                    initial['value'] = row['value']
            except Exception:
                exceptions.handle(self.request,
                                  _('Unable to retrieve variable.'),
                                  redirect=self.get_success_url())
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['submit_url'] = self.request.path
        return context

    def get_cancel_url(self):
        return self.get_success_url()

    def get_success_url(self):
        return reverse_lazy(common.coast_ns(self.request) + 'detail',
                            args=[self.kwargs['service_id']]) + (
                                '?tab=service_details__settings')


class EnvDeveloperView(SetEnvView):
    form_class = project_forms.EnvDeveloperView
    template_name = 'project/coast_services/settings_form.html'
    form_id = 'coast_env_developer_form'
    page_title = _('Environment Variables (Developer view)')

    def _rows(self):
        if not hasattr(self, '_env_rows'):
            try:
                self._env_rows = coast.service_env_list(
                    self.request, self.kwargs['service_id'])
            except Exception:
                exceptions.handle(self.request,
                                  _('Unable to retrieve environment '
                                    'variables.'),
                                  redirect=self.get_success_url())
                self._env_rows = []
        return self._env_rows

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['rows'] = self._rows()
        return kwargs

    def get_initial(self):
        return {'dotenv_text': dotenv.render(self._rows(), app=self.is_app())}

    def get_success_url(self):
        return super().get_success_url() + '&view=developer'


class EditSettingsView(SetEnvView):
    form_class = project_forms.EditSettings
    page_title = _('Edit Settings')
    submit_label = _('Save')

    def get_initial(self):
        try:
            item = coast.service_get(self.request, self.kwargs['service_id'])
            domains = coast.service_domain_list(
                self.request, self.kwargs['service_id'])
        except Exception:
            exceptions.handle(self.request, _('Unable to retrieve settings.'),
                              redirect=self.get_cancel_url())
        return {key: item.get(key) or '' for key in (
            'name', 'ports', 'cpu_limit', 'memory_limit_mb',
            'description')} | {
                'has_domain': bool(domains),
                'health_check': item.get('health_check') or 'none',
                'healthcheck_path': (item.get('health_check_path') or
                                     item.get('healthcheck_path') or '/'),
                'health_check_port': item.get('health_check_port'),
                'source_type': (item.get('source') or {}).get('type'),
                'branch': (item.get('source') or {}).get('branch', '')}

    def get_cancel_url(self):
        return reverse_lazy(common.coast_ns(self.request) + 'detail',
                            args=[self.kwargs['service_id']])

    def get_success_url(self):
        return self.get_cancel_url()


class AddDomainView(SetEnvView):
    form_class = project_forms.AddDomain
    page_title = submit_label = _('Add Domain')

    template_name = 'project/coast_services/domain_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.form_class not in (project_forms.AddDomain,
                                   project_forms.EditDomain):
            return kwargs
        names, existing = set(), set()
        default_domain = ''
        worker_ip = ''
        try:
            item = coast.service_get(self.request, self.kwargs['service_id'])
            hostname = urlsplit(item.get('default_url') or '').hostname
            if hostname:
                names.add(hostname)
                existing.add(hostname)
            if item.get('stack_id') and item.get('server_id'):
                server = DetailView._worker(
                    self, item['stack_id'], item['server_id'])
                worker_ip = common.public_address(
                    server, item.get('dns_records')) or ''
            if item.get('stack_id'):
                try:
                    stack = coast.stack_get(self.request, item['stack_id'])
                    default_domain = stack.get('default_domain') or ''
                except Exception:
                    pass
        except Exception:
            pass
        try:
            domains = coast.service_domain_list(
                self.request, self.kwargs['service_id'])
            for domain in domains:
                name = domain.get('fqdn')
                if name:
                    if domain.get('id') != self.kwargs.get('domain_id'):
                        names.add(name)
                        existing.add(name)
        except Exception:
            pass
        kwargs.update(known_names=names, existing_names=existing,
                      default_domain=default_domain, worker_ip=worker_ip,
                      replace_default=bool(
                          self.request.GET.get('replace_default')))
        return kwargs

    def get_initial(self):
        return {}

    def get_success_url(self):
        return reverse_lazy(common.coast_ns(self.request) + 'detail',
                            args=[self.kwargs['service_id']]) + (
                                '?tab=service_details__domains')


class EditDomainView(AddDomainView):
    form_class = project_forms.EditDomain
    page_title = submit_label = _('Edit Domain')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['domain_id'] = self.kwargs['domain_id']
        return kwargs

    def get_initial(self):
        try:
            item = coast.service_domain_get(
                self.request, self.kwargs['service_id'],
                self.kwargs['domain_id'])
        except Exception:
            exceptions.handle(self.request, _('Unable to retrieve domain.'),
                              redirect=self.get_success_url())
            return {}
        return {'fqdn': item.get('fqdn') or '',
                'tls': item.get('tls') or 'letsencrypt',
                'zone_id': item.get('zone_id') or '',
                'host': item.get('fqdn') or '',
                'dns_mode': 'zone' if item.get('zone_id') else 'manual'}


class ConsoleView(generic.View):
    """POST: return a one-time console address for this browser."""

    def post(self, request, service_id):
        if not common.project_member(request):
            return _console_denied()
        try:
            item = coast.service_get(request, service_id)
            kind = item.get('kind')
            if kind not in ('app', 'service'):
                return JsonResponse(
                    {'error': _('Unable to open a console session.')},
                    status=400)
            body = coast.service_console(request, service_id, kind)
        except exceptions.NotAuthorized:
            return _console_denied()
        except exceptions.NotFound:
            return JsonResponse(
                {'error': _('Unable to open a console session.')},
                status=404)
        except Exception as exc:
            return JsonResponse({'error': coast.error_message(
                exc, _('Unable to open a console session.'))}, status=400)
        if not isinstance(body, dict):
            body = {}
        url = coast.console_session_url(body.get('url'))
        if not url:
            return JsonResponse(
                {'error': _(
                    'The console session did not return a secure address.')},
                status=502)
        payload = {'url': url}
        expires = body.get('expires_at')
        if isinstance(expires, str):
            payload['expires_at'] = expires
        return JsonResponse(payload)


def _console_denied():
    return JsonResponse(
        {'error': _('You cannot open a console session.')}, status=403)


class WebhooksRegenerateView(generic.View):
    """POST only: issue a new webhook token, then show the Webhooks tab."""

    def post(self, request, service_id):
        try:
            coast.service_webhooks_regenerate(request, service_id)
            messages.success(request, _('Webhook token regenerated. Update '
                                        'your Git host webhooks.'))
        except Exception as exc:
            messages.error(request, coast.error_message(
                exc, _('Unable to regenerate the webhook token.')))
        return shortcuts.redirect(reverse(
            common.coast_ns(request) + 'detail', args=[service_id]) +
            '?tab=service_details__webhooks')


class EnvBuildTimeView(generic.View):
    def post(self, request, service_id, key):
        try:
            if coast.service_get(request, service_id).get('kind') == 'service':
                return JsonResponse({'error': 'Runtime-only service.'},
                                    status=400)
            flag = request.POST.get('build_time')
            if flag not in ('true', 'false'):
                return JsonResponse({'error': 'Invalid build_time.'},
                                    status=400)
            coast.service_env_update(request, service_id, {
                key: {'build_time': flag == 'true'}})
            return JsonResponse({'build_time': flag == 'true'})
        except Exception:
            return JsonResponse({'error': 'Unable to save variable.'},
                                status=400)


class CreateStorageView(AddDomainView):
    template_name = SetEnvView.template_name
    form_class = project_forms.CreateStorage
    page_title = submit_label = _('Create Storage')

    def dispatch(self, request, *args, **kwargs):
        if (not common.project_member(request) or
                not coast.storage_supported(request)):
            return HttpResponseForbidden()
        self.storage_item = None
        try:
            item = coast.service_get(request, kwargs['service_id'])
            if 'storage_id' in kwargs:
                rows = coast.storage_list(
                    request, item['stack_id'], item['id'])
                self.storage_item = next((
                    row for row in rows
                    if row.get('id') == kwargs['storage_id']
                    and row.get('origin') == 'user'), None)
                if self.storage_item is None:
                    return HttpResponseForbidden()
        except Exception as exc:
            exceptions.handle(request, coast.error_message(
                exc, _('Unable to retrieve storage.')),
                redirect=reverse(common.coast_ns(request) + 'detail',
                                 args=[kwargs['service_id']]))
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        row = self.storage_item
        if row is None:
            return {}
        values = dict(row)
        field = 'host_path' if row['type'] == 'bind' else 'name'
        values[field] = row['source']
        return values

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['stack_id'] = coast.service_get(
            self.request, self.kwargs['service_id']).get('stack_id')
        if 'storage_id' in self.kwargs:
            kwargs['storage_id'] = self.kwargs['storage_id']
        return kwargs

    def get_success_url(self):
        return reverse_lazy(common.coast_ns(self.request) + 'detail',
                            args=[self.kwargs['service_id']]) + (
                                '?tab=service_details__storage')


class EditStorageView(CreateStorageView):
    page_title = submit_label = _('Edit Storage')


class ChangeImageView(forms.ModalFormView):
    form_class = project_forms.ChangeImage
    template_name = 'project/coast_services/change_image.html'
    page_title = _('Change image')

    def dispatch(self, request, *args, **kwargs):
        try:
            self.item = coast.service_get(request, kwargs['service_id'])
        except Exception as exc:
            exceptions.handle(request, coast.error_message(
                exc, _('Unable to retrieve service.')),
                redirect=reverse(common.coast_ns(request) + 'index'))
        if not (common.project_member(request) and
                (self.item.get('source') or {}).get('type') == 'image' and
                not common.is_template(self.item) and
                not common.is_compose(self.item)):
            return HttpResponseForbidden()
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        return {'service_id': self.kwargs['service_id'],
                'image': self.item['source'].get('image', ''),
                'tag': self.item['source'].get('tag', '')}

    def get_cancel_url(self):
        return reverse(common.coast_ns(self.request) + 'detail',
                       args=[self.kwargs['service_id']])

    def get_success_url(self):
        if self.request.POST.get('operation') == 'redeploy':
            return common.service_logs_page(self.kwargs['service_id'],
                                            self.item.get('kind'))
        return self.get_cancel_url()


class MetricsView(generic.View):
    http_method_names = ['get']

    def get(self, request, service_id):
        range_ = request.GET.get('range', '1h')
        if range_ not in coast.METRICS_RANGES:
            response = JsonResponse({'error': _('Invalid metrics range.')},
                                    status=400)
        elif not coast.service_metrics_supported(request):
            response = JsonResponse({'error': _('Metrics are unavailable.')},
                                    status=404)
        else:
            try:
                response = JsonResponse({'metrics': coast.service_metrics(
                    request, service_id, range_)})
            except exceptions.NotAuthorized:
                response = JsonResponse({'error': _('Access denied.')},
                                        status=403)
            except exceptions.NotFound:
                response = JsonResponse({'error': _('Service not found.')},
                                        status=404)
            except Exception:
                response = JsonResponse(
                    {'error': _('Unable to retrieve metrics. Try again.')},
                    status=502)
        patch_cache_control(response, no_store=True)
        return response


class ReplaceDeployKeyView(SetEnvView):
    form_class = project_forms.ReplaceDeployKey
    page_title = _('Replace deploy key')

    def dispatch(self, request, *args, **kwargs):
        self.item = coast.service_get(request, kwargs['service_id'])
        source = self.item.get('source') or {}
        if (not common.project_member(request) or
                source.get('type') != 'git' or
                (source.get('repo_url') or '').startswith('https://')):
            return HttpResponseForbidden()
        response = super().dispatch(request, *args, **kwargs)
        patch_cache_control(response, no_store=True)
        return response

    def get_initial(self):
        return {}

    def get_success_url(self):
        return reverse(common.coast_ns(self.request) + 'detail',
                       args=[self.kwargs['service_id']])


class EditDockerfileView(SetEnvView):
    form_class = project_forms.EditDockerfile
    page_title = _('Edit Dockerfile')

    def dispatch(self, request, *args, **kwargs):
        self.item = coast.service_get(request, kwargs['service_id'])
        if (not common.project_member(request) or
                (self.item.get('source') or {}).get('type') != 'dockerfile'):
            return HttpResponseForbidden()
        response = super().dispatch(request, *args, **kwargs)
        patch_cache_control(response, no_store=True)
        return response

    def get_initial(self):
        if self.request.method == 'POST':
            return {}
        try:
            return {'text': coast.service_dockerfile_get(
                self.request, self.kwargs['service_id'])}
        except Exception as exc:
            exceptions.handle(self.request, coast.error_message(
                exc, _('Unable to retrieve Dockerfile.')),
                redirect=self.get_success_url())
            return {}

    def get_success_url(self):
        return reverse(common.coast_ns(self.request) + 'detail',
                       args=[self.kwargs['service_id']])
