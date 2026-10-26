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

from datetime import timezone as dt_timezone
from urllib.parse import urlencode

from django.template.defaultfilters import date
from django.template.loader import render_to_string
from django.urls import resolve
from django.urls import Resolver404
from django.urls import reverse
from django.utils.dateparse import parse_datetime
from django.utils.html import format_html
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from horizon import exceptions
from horizon import tables

from coast_dashboard.api import coast
from coast_dashboard.content.stacks import activity


def coast_ns(request=None, kind=None):
    """URL namespace for an app or a service.

    Services and apps share views, but a service's pages live under
    /project/coast/services/ and an app's under /project/coast/apps/.
    Without a kind, follow the panel of the current request.
    """
    if kind is None and request is not None:
        match = getattr(request, 'resolver_match', None)
        namespace = getattr(match, 'namespace', '') or ''
        if namespace.endswith('coast.databases'):
            return 'horizon:project:coast.databases:'
        kind = 'service' if namespace.endswith('coast.services') else 'app'
    return 'horizon:project:coast.%s:' % (
        'services' if kind == 'service' else 'apps')


def yes_no(value):
    return _('Yes') if value else _('No')


ENGINE_FAULT = 'Conductor operation failed; see the resource activity log.'


def friendly_fault(value):
    """Tenant wording for deployment failure reasons."""
    if not value:
        return ''
    if str(value).strip() == ENGINE_FAULT:
        return str(_("The deployment failed. See the stack's Activity tab "
                     "for details."))
    return activity.scrub(value)


def is_template(service):
    return bool(service.get('template_id') or
                (service.get('source') or {}).get('type') == 'template')


def is_compose(service):
    return ((service.get('source') or {}).get('type') == 'compose' or
            is_template(service) or
            (service.get('source') or {}).get('build_pack') == 'compose')


TRANSITIONAL = frozenset((
    'PENDING', 'BUILDING', 'CREATING', 'DELETING', 'DEPLOYING', 'STARTING',
    'STOPPING', 'RESTARTING', 'PROVISIONING', 'ADDING_SERVER', 'ROLLING_BACK',
    'UPGRADING',
    'FAILING_OVER', 'FAILOVER', 'RECONCILING', 'SNAPSHOTTING',
    'UPLOADING', 'PENDING_VERIFICATION', 'PENDING_DNS'))
# Horizon uses these states for row polling, separately from badge colors.
STATUS_CHOICES = tuple((state, None) for state in sorted(TRANSITIONAL)) + (
    ('ACTIVE', True), ('AVAILABLE', True), ('VERIFIED', True),
    ('RUNNING', True), ('STOPPED', True), ('SUPERSEDED', True),
    ('ROLLED_BACK', True),
    ('DELETED', True), ('CANCELLED', True), ('ERROR', False),
    ('FAILED', False), ('UNHEALTHY', False), ('DEGRADED', False))


def status(datum):
    task = datum.get('task_state')
    if task in TRANSITIONAL:
        return task
    return datum.get('deployment_status') or datum.get('status')


def service_status(request, item, deployments=None):
    # The public service response has no task_state. Deployment status is
    # the public source of build/deploy progress, including on ACTIVE rows.
    if deployments is None:
        deployments = coast.service_deployment_list(request, item['id'])
    latest = max(deployments, key=lambda row: row['number'], default={})
    item = dict(item)
    item['deployed'] = bool(deployments)
    item['deployment_in_progress'] = latest.get('status') in TRANSITIONAL
    if (item['status'] != 'DELETING' and
            latest.get('status') in TRANSITIONAL):
        item['deployment_status'] = latest['status']
    return item


# Redeploy stays hidden while a service is in one of these states.
BUSY = frozenset(('DEPLOYING', 'STARTING', 'PENDING', 'DELETING',
                  'BUILDING', 'STOPPING', 'RESTARTING', 'PROVISIONING',
                  'RECONCILING'))


def is_busy(datum):
    return bool({datum.get('status'), datum.get('deployment_status'),
                 datum.get('task_state')} & BUSY)


_MEMBER_ROLES = frozenset(('admin', 'member'))


def project_roles(request):
    """Return normalized role names from the project token."""
    names = set()
    for role in getattr(request.user, 'roles', None) or []:
        if isinstance(role, str):
            name = role
        elif isinstance(role, dict):
            name = role.get('name')
        else:
            name = getattr(role, 'name', None)
        if name:
            names.add(str(name).lower())
    return names


def project_member(request):
    """True when the token has the project member or admin role."""
    return bool(project_roles(request) & _MEMBER_ROLES)


def project_manager(request):
    """True when the token has the project manager or admin role."""
    return bool(project_roles(request) & {'manager', 'admin'})


def public_address(server=None, dns_records=None):
    """Return a server's public address, or an A record value."""
    if server:
        for key in ('floating_ip', 'public_ip'):
            value = server.get(key)
            if value:
                return value
    for record in dns_records or []:
        if (record.get('type') == 'A' and record.get('value') and
                record.get('purpose') in (None, 'routing')):
            return record['value']
    return None


def worker_label(name, address):
    if name and address:
        return '%s (%s)' % (name, address)
    return name


def domain_url(domain):
    fqdn = (domain or {}).get('fqdn')
    if not fqdn:
        return None
    scheme = 'http' if domain.get('tls') == 'none' else 'https'
    return '%s://%s' % (scheme, fqdn)


def deployment_page(service_id, deployment_id, kind=None):
    if not isinstance(service_id, str) or not service_id:
        return None
    if not isinstance(deployment_id, str) or not deployment_id:
        return None
    return reverse(coast_ns(kind=kind) + 'deployment',
                   args=[service_id, deployment_id])


def service_logs_page(service_id, kind=None):
    """Return the service Logs tab, which follows container logs live."""
    if not isinstance(service_id, str) or not service_id:
        return None
    return reverse(coast_ns(kind=kind) + 'detail',
                   args=[service_id]) + '?tab=service_details__logs'


def service_deploy_page(service, deployment_id):
    """Return where to land after a service deploy or redeploy.

    Template services have no build step, so they open the Logs tab.
    Built services keep the deployment page with its build log.
    """
    service = service if isinstance(service, dict) else {}
    if is_template(service):
        return service_logs_page(service.get('id'), service.get('kind'))
    return deployment_page(service.get('id'), deployment_id,
                           service.get('kind'))


def redirect_created_deployment(response, item):
    """Send create to the new deployment when the API returned an id."""
    if not isinstance(item, dict):
        return response
    if (is_template(item) or
            (item.get('source') or {}).get('type') == 'compose'):
        url = service_logs_page(item.get('id'), item.get('kind'))
    else:
        url = deployment_page(item.get('id'), item.get('deployment_id'),
                              item.get('kind'))
    if not url:
        return response
    if 'X-Horizon-Location' in response:
        response['X-Horizon-Location'] = url
    if response.status_code in (301, 302):
        response['Location'] = url
    return response


class DeploymentRedirectMixin:
    def form_valid(self, form):
        response = super().form_valid(form)
        return redirect_created_deployment(
            response, getattr(form, 'created_item', None))


def can_redeploy(datum):
    if not datum:
        return False
    progress = {datum.get('task_state'), datum.get('deployment_status')}
    if progress & TRANSITIONAL:
        return False
    state = datum.get('status')
    if state == 'PENDING':
        return not datum.get('deployment_in_progress',
                             bool(datum.get('current_deployment_id')))
    # A start still waiting on the engine never blocks a deploy: the API
    # allows STARTING -> DEPLOYING, and a failed start must not trap the app.
    return state == 'STARTING' or state not in TRANSITIONAL


def name_map(request, list_method, display=None):
    try:
        return {item['id']: display(item) if display else item['name']
                for item in list_method(request)}
    except Exception:
        # A missing cosmetic name must not hide the resource list.
        return {}


def name_maps(request):
    """Return parent display maps with inline status links."""
    return (name_map(request, coast.stack_list),
            name_map(request, coast.appgroup_list, appgroup_link),
            name_map(request, coast.environment_list, environment_link))


def add_parent_name(item, parent, names):
    item[parent + '_name'] = names.get(item.get(parent + '_id'),
                                       _('Unavailable'))
    return item


def add_names(item, apps, envs, stacks=None):
    if stacks is not None:
        add_parent_name(item, 'stack', stacks)
    add_parent_name(item, 'appgroup', apps)
    return add_parent_name(item, 'environment', envs)


def stack_link(item):
    return format_html('<a href="{}">{}</a>', reverse(
        'horizon:project:coast.stacks:detail',
        kwargs={'stack_id': item['id']}),
        item.get('name') or item['id'])


def parent_maps(request):
    """Return linked stack, appgroup and environment display maps."""
    return (name_map(request, coast.stack_list, stack_link),
            name_map(request, coast.appgroup_list, appgroup_link),
            name_map(request, coast.environment_list, environment_link))


class ApiErrorMixin:
    """Show the Coast API's reason when a batch action fails."""

    def action(self, request, obj_id):
        try:
            return super().action(request, obj_id)
        except Exception as exc:
            message = coast.error_message(exc, coast.fault_message(exc))
            if message is None:
                raise
            # Escalate as HandledException so Horizon skips its generic text.
            try:
                raise exceptions.Conflict(message) from exc
            except exceptions.Conflict:
                exceptions.handle(request, message, escalate=True)


class UpdateRow(tables.Row):
    ajax = True

    def load_cells(self, datum=None):
        super().load_cells(datum)
        self.attrs['data-update-interval'] = 5000


class InlineStatusRow(UpdateRow):
    """Keep row polling independent of the visible name and parent columns."""

    @property
    def status(self):
        return dict(STATUS_CHOICES).get(status(self.datum))

    @property
    def status_class(self):
        return self.table.get_row_status_class(self.status)


class ResourceTable(tables.DataTable):
    def get_object_id(self, datum):
        return datum['id']

    def get_object_display(self, datum):
        return datum.get('name') or self.get_object_id(datum)


def status_color(value, fault=None):
    """Return the Bootstrap label color for a Coast status."""
    if value in ('FAILED', 'ERROR') or (value == 'CANCELLED' and fault):
        return 'danger'
    if value in ('ACTIVE', 'RUNNING', 'VERIFIED'):
        return 'success'
    if value in ('PENDING', 'DEPLOYING', 'STARTING', 'PROVISIONING',
                 'RECONCILING', 'DELETING', 'STOPPING', 'RESTARTING',
                 'BUILDING', 'PENDING_VERIFICATION', 'PENDING_DNS'):
        return 'warning'
    return 'default'


def status_badge(value):
    if isinstance(value, dict):
        fault = value.get('fault') or value.get('error')
        value = status(value)
    else:
        fault = None
    return format_html('<span class="label label-{}">{}</span>',
                       status_color(value, fault), value or _('Unknown'))


def inline_status_badge(item):
    value = status(item)
    if value == 'ACTIVE':
        return ''
    label = {'PENDING': _('Creating'), 'DELETING': _('Deleting'),
             'ERROR': _('Error')}.get(value)
    if label is None:
        label = value.replace('_', ' ').title() if value else _('Unknown')
    fault = item.get('fault') or item.get('error')
    # Horizon renders table rows inside {% spaceless %}, which drops a
    # leading space, so the gap after the name is a margin.
    return format_html(
        '<span class="label label-{}" style="margin-left:0.4em">{}</span>',
        status_color(value, fault), label)


def environment_link(item):
    return format_html('<a href="{}">{}</a>{}', reverse(
        'horizon:project:coast.environments:detail',
        kwargs={'environment_id': item['id']}),
        item.get('name') or item['id'], inline_status_badge(item))


def appgroup_link(item):
    return format_html('<a href="{}">{}</a>{}', reverse(
        'horizon:project:coast.appgroups:detail',
        kwargs={'appgroup_id': item['id']}),
        item.get('name') or item['id'], inline_status_badge(item))


class StatusColumn(tables.Column):
    def __init__(self):
        super().__init__(status, verbose_name=_('Status'), status=True,
                         status_choices=STATUS_CHOICES)

    def get_data(self, datum):
        # Preserve raw status for Horizon row updates; display needs the fault.
        return status_badge(datum)


class AppgroupFilterMixin:
    """Filter resource lists by app group."""

    def filter_appgroup(self, items):
        group = self.request.GET.get('appgroup')
        return [item for item in items
                if not group or item.get('appgroup_id') == group]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        group = self.request.GET.get('appgroup')
        if group:
            context['filtered_appgroup'] = group
            params = self.request.GET.copy()
            params.pop('appgroup', None)
            context['clear_appgroup_url'] = self.request.path
            if params:
                context['clear_appgroup_url'] += '?' + params.urlencode()
        return context


class CreateContextMixin:
    """Keep placement context in the form action, including modal POSTs."""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = {key: self.request.GET[key] for key in
                  ('appgroup_id', 'environment_id', 'next')
                  if self.request.GET.get(key)}
        if params:
            context['submit_url'] = (
                str(self.submit_url) + '?' + urlencode(params))
        return context

    def get_success_url(self):
        target = self.request.GET.get('next', '')
        if (target.startswith('/') and
                url_has_allowed_host_and_scheme(target, allowed_hosts=set())):
            try:
                match = resolve(target)
                if match.view_name in (
                        'horizon:project:coast.appgroups:detail',
                        'horizon:project:coast.environments:detail'):
                    return target
            except Resolver404:
                pass
        return super().get_success_url()


def lock_placement(form, request):
    for name in ('appgroup_id', 'environment_id'):
        if name in form.fields and request.GET.get(name):
            form.initial[name] = request.GET[name]
            form.fields[name].disabled = True


class RelatedCreate(tables.LinkAction):
    classes = ('ajax-modal',)
    icon = 'plus'
    policy_rules = ()

    def get_link_url(self, datum=None):
        match = self.table.request.resolver_match
        params = {'next': self.table.request.path}
        if 'environment_id' in match.kwargs:
            item = datum or coast.environment_get(
                self.table.request, match.kwargs['environment_id'])
            params.update(environment_id=item['id'],
                          appgroup_id=item['appgroup_id'])
        else:
            params['appgroup_id'] = match.kwargs['appgroup_id']
        return reverse(self.url) + '?' + urlencode(params)


class CreateApp(RelatedCreate):
    name = 'create_app'
    verbose_name = _('Create App')
    url = 'horizon:project:coast.apps:create'


class CreateService(RelatedCreate):
    name = 'create_service'
    verbose_name = _('Create Service')
    url = 'horizon:project:coast.services:create'


class CreateEnvironment(RelatedCreate):
    name = 'create_environment'
    verbose_name = _('Create Environment')
    url = 'horizon:project:coast.environments:create'


def copy_button(value):
    return render_to_string('project/coast_common/_copy_button.html',
                            {'copy_value': value})


def copyable_value(value):
    return format_html('{} {}', value, copy_button(value)) if value else ''


def local_datetime(value):
    """Format Coast ISO timestamps with the user's timezone and locale."""
    if not value:
        return '-'
    if isinstance(value, str):
        try:
            value = parse_datetime(value)
        except ValueError:
            return '-'
    if value is None:
        return '-'
    if timezone.is_naive(value):
        value = timezone.make_aware(value, dt_timezone.utc)
    local = timezone.localtime(value)
    # Always say which timezone the time is in.
    return '%s %s' % (date(local, 'DATETIME_FORMAT'), local.tzname() or '')
