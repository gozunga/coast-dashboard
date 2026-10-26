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

from django import http
from django.middleware.csrf import get_token
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy
from horizon import exceptions
from horizon import messages
from horizon import tables

from coast_dashboard.api import coast
from coast_dashboard.content import common


def detail_url(datum):
    return reverse(common.coast_ns(kind=datum.get('kind')) + 'detail',
                   kwargs={'service_id': datum['id']})


class CreateService(tables.LinkAction):
    name = 'create'
    verbose_name = _('Create App')
    url = 'horizon:project:coast.apps:create'
    classes = ('ajax-modal',)
    icon = 'plus'
    policy_rules = ()


class EditSettings(tables.LinkAction):
    name = 'edit_settings'
    verbose_name = _('Edit Settings')
    url = 'horizon:project:coast.apps:edit_settings'
    classes = ('ajax-modal',)
    icon = 'pencil'
    policy_rules = ()

    def get_link_url(self, datum=None):
        return reverse(common.coast_ns(kind=(datum or {}).get('kind')) +
                       'edit_settings', args=[datum['id']])


class ChangeImage(EditSettings):
    name = 'change_image'
    verbose_name = _('Change image')
    classes = ()

    def allowed(self, request, datum=None):
        return bool(common.project_member(request) and datum and
                    (datum.get('source') or {}).get('type') == 'image' and
                    not common.is_template(datum) and
                    not common.is_compose(datum))

    def get_link_url(self, datum=None):
        return reverse(common.coast_ns(kind=datum.get('kind')) +
                       'change_image', args=[datum['id']])


class DeleteService(common.ApiErrorMixin, tables.DeleteAction):
    policy_rules = ()

    @staticmethod
    def action_present(count):
        return ngettext_lazy('Delete App', 'Delete Apps', count)

    @staticmethod
    def action_past(count):
        return ngettext_lazy('Scheduled deletion of App',
                             'Scheduled deletion of Apps', count)

    def delete(self, request, obj_id):
        coast.service_delete(request, obj_id)


class DeployService(tables.Action):
    name = 'deploy'
    verbose_name = _('Redeploy')
    requires_input = True
    policy_rules = ()

    def allowed(self, request, datum=None):
        return common.can_redeploy(datum)

    def single(self, table, request, obj_id):
        try:
            deployment = coast.service_deploy(request, obj_id)
        except Exception as exc:
            exceptions.handle(request, coast.error_message(
                exc, _('Unable to redeploy.')))
            return None
        messages.success(request, _('Redeployment requested.'))
        deployment_id = (deployment.get('id')
                         if isinstance(deployment, dict) else None)
        try:
            datum = table.get_object_by_id(obj_id)
        except Exception:
            datum = None
        service = dict(datum) if isinstance(datum, dict) else {}
        service['id'] = obj_id
        url = common.service_deploy_page(service, deployment_id)
        if url:
            return http.HttpResponseRedirect(url)
        return None


class ServiceStateAction(tables.Action):
    requires_input = True
    policy_rules = ()
    required_status = 'ACTIVE'

    def allowed(self, request, datum=None):
        return bool(datum and common.status(datum) == self.required_status
                    and not common.is_busy(datum))

    def single(self, table, request, obj_id):
        try:
            item = table.get_object_by_id(obj_id)
            if not self.allowed(request, item):
                messages.warning(request, _(
                    'This operation is not available in the current state.'))
                return
            coast.service_action(request, obj_id, self.name)
            messages.success(request, _('Operation requested.'))
        except Exception as exc:
            exceptions.handle(request, coast.error_message(
                exc, _('Unable to change service state.')))


class StartService(ServiceStateAction):
    name = 'start'
    verbose_name = _('Start')
    required_status = 'STOPPED'


class StopService(ServiceStateAction):
    name = 'stop'
    verbose_name = _('Stop')


class RestartService(ServiceStateAction):
    name = 'restart'
    verbose_name = _('Restart')


class UpdateRow(common.UpdateRow):
    def get_data(self, request, service_id):
        stacks, apps, envs = common.parent_maps(request)
        return common.add_names(common.service_status(
            request, coast.service_get(request, service_id)), apps, envs,
            stacks)


class ServicesTable(common.ResourceTable):
    name = tables.Column('name', verbose_name=_('Name'),
                         link=detail_url)
    status = common.StatusColumn()
    stack_name = tables.Column('stack_name', verbose_name=_('Stack'))
    appgroup_name = tables.Column('appgroup_name',
                                  verbose_name=_('App Group'))
    environment_name = tables.Column('environment_name',
                                     verbose_name=_('Environment'))

    class Meta:
        name = 'services'
        verbose_name = _('Apps')
        row_class = UpdateRow
        status_columns = ('status',)
        table_actions = (CreateService, DeleteService)
        row_actions = (EditSettings, DeployService, StartService,
                       StopService, RestartService, DeleteService)


class UpdateDeploymentRow(common.UpdateRow):
    def get_data(self, request, deployment_id):
        return coast.service_deployment_get(
            request, self.table.kwargs['service_id'], deployment_id)


class ViewDeploymentLog(tables.LinkAction):
    name = 'log'
    verbose_name = _('View Build Log')
    policy_rules = ()

    def get_link_url(self, datum):
        return reverse(common.coast_ns(self.table.request) + 'deployment',
                       args=[self.table.kwargs['service_id'], datum['id']])


class CancelDeployment(tables.Action):
    name = 'cancel'
    verbose_name = _('Cancel Deployment')
    classes = ('btn-danger',)
    requires_input = True
    policy_rules = ()

    def allowed(self, request, datum=None):
        return bool(datum and datum.get('status') in (
            'PENDING', 'BUILDING', 'DEPLOYING'))

    def single(self, table, request, obj_id):
        try:
            coast.service_deployment_cancel(
                request, table.kwargs['service_id'], obj_id)
            messages.success(request, _('Cancellation requested.'))
        except Exception as exc:
            exceptions.handle(request, coast.error_message(
                exc, _('Unable to cancel the deployment.')))


class DeploymentsTable(common.ResourceTable):
    @property
    def filtered_data(self):
        # Preserve newest first even if the API ignores its sort parameters.
        return sorted(super().filtered_data,
                      key=lambda row: row.get('created_at') or '',
                      reverse=True)

    number = tables.Column('number', verbose_name=_('Number'))
    status = common.StatusColumn()
    source_ref = tables.Column('source_ref', verbose_name=_('Source ref'))
    resolved_ref = tables.Column('resolved_ref',
                                 verbose_name=_('Resolved ref'))
    started_at = tables.Column('started_at', verbose_name=_('Started'),
                               filters=(common.local_datetime,))
    finished_at = tables.Column('finished_at', verbose_name=_('Finished'),
                                filters=(common.local_datetime,))
    fault = tables.Column(lambda datum: common.friendly_fault(
        datum.get('fault')), verbose_name=_('Reason'))

    class Meta:
        name = 'deployments'
        verbose_name = _('Deployments')
        row_class = UpdateDeploymentRow
        status_columns = ('status',)
        row_actions = (ViewDeploymentLog, CancelDeployment)


class UpdateDomainRow(common.UpdateRow):
    def load_cells(self, datum=None):
        if (datum or self.datum).get('is_default'):
            self.ajax = False
        super().load_cells(datum)

    def get_data(self, request, domain_id):
        item = coast.service_domain_get(
            request, self.table.kwargs['service_id'], domain_id)
        if coast.dns_available(request):
            item['manage_dns_url'] = reverse(
                common.coast_ns(request) + 'edit_domain',
                args=[self.table.kwargs['service_id'], domain_id])
        return item


class AddDomain(tables.LinkAction):
    name = 'add_domain'
    verbose_name = _('Add Domain')
    classes = ('ajax-modal',)
    icon = 'plus'
    policy_rules = ()

    def get_link_url(self, datum=None):
        return reverse(common.coast_ns(self.table.request) + 'add_domain',
                       args=[self.table.kwargs['service_id']])


TLS_LABELS = {
    'letsencrypt': _("Let's Encrypt"),
    'none': _('None (HTTP only)'),
}


def tls_label(datum):
    value = datum.get('tls') or ''
    return TLS_LABELS.get(value, value or '-')


def verification_guidance(datum):
    if datum.get('dns_mode') == 'designate':
        records = datum.get('managed_records') or []
        parts = [format_html('<div>{}</div>', _('DNS: managed by Coast'))]
        for record in records:
            if record.get('type') not in ('A', 'AAAA', 'CNAME', 'TXT'):
                continue
            parts.append(format_html(
                '<div>{} {} {}</div>', record.get('type', ''),
                record.get('name', ''), record.get('value', '')))
        return format_html('{}' * len(parts), *parts)
    if datum.get('status') != 'PENDING_VERIFICATION':
        return ''
    address = datum.get('worker_ip') or common.public_address(
        None, datum.get('dns_records')) or _('unavailable')
    text = _('Waiting for DNS verification - create an A record for '
             '%(fqdn)s pointing to %(ip)s') % {
                 'fqdn': datum.get('fqdn') or '', 'ip': address}
    button = common.copy_button(address) if address != _('unavailable') else ''
    parts = []
    if datum.get('manage_dns_url'):
        parts.append(format_html(
            '<div><a class="ajax-modal" href="{}">{}</a></div>',
            datum['manage_dns_url'],
            _('Let Coast create these records: choose a DNS zone')))
    parts.append(format_html('<div>{} {}</div>', text, button))
    for record in datum.get('dns_records') or []:
        if record.get('type') not in ('A', 'AAAA', 'CNAME', 'TXT'):
            continue
        parts.append(format_html(
            '<div>{} {} {} {} {}</div>',
            _('%s record') % record.get('type', ''), record.get('name') or '',
            _('value'), record.get('value') or '',
            common.copy_button(record.get('value') or '')))
    return format_html('{}' * len(parts), *parts)


class EditDomain(tables.LinkAction):
    name = 'edit_domain'
    verbose_name = _('Edit Domain')
    classes = ('ajax-modal',)
    icon = 'pencil'
    policy_rules = ()

    def allowed(self, request, datum=None):
        return bool(datum and not datum.get('is_default'))

    def get_link_url(self, datum):
        return reverse(common.coast_ns(self.table.request) + 'edit_domain',
                       args=[self.table.kwargs['service_id'], datum['id']])


class VerifyDomain(tables.Action):
    name = 'verify'
    verbose_name = _('Verify now')
    requires_input = True
    policy_rules = ()

    def allowed(self, request, datum=None):
        return bool(datum and not datum.get('is_default') and
                    datum.get('status') == 'PENDING_VERIFICATION')

    def single(self, table, request, obj_id):
        try:
            coast.service_domain_verify(
                request, table.kwargs['service_id'], obj_id)
            messages.success(request, _('Verification requested.'))
        except Exception as exc:
            exceptions.handle(request, coast.error_message(
                exc, _('Unable to verify the domain.')))


class MakePrimary(tables.Action):
    name = 'make_primary'
    verbose_name = _('Make primary')
    requires_input = True
    policy_rules = ()

    def allowed(self, request, datum=None):
        return bool(datum and not datum.get('is_default') and
                    not datum.get('primary') and
                    datum.get('status') in ('ACTIVE', 'VERIFIED'))

    def single(self, table, request, obj_id):
        try:
            if not self.allowed(request, table.get_object_by_id(obj_id)):
                return
            coast.service_domain_make_primary(
                request, table.kwargs['service_id'], obj_id)
            messages.success(request, _('Primary domain updated.'))
            return http.HttpResponseRedirect(request.get_full_path())
        except Exception as exc:
            exceptions.handle(request, coast.error_message(
                exc, _('Unable to make the domain primary.')))


class EnableDefaultAddress(tables.Action):
    name = 'enable_default_address'
    verbose_name = _('Turn default address on')
    verbose_name_plural = verbose_name

    @staticmethod
    def action_present(count):
        return _('Turn default address on')

    @staticmethod
    def action_past(count):
        return _('Turned default address on')

    requires_input = False
    policy_rules = ()
    enabled = True

    def allowed(self, request, datum=None):
        item = self.table.kwargs.get('item') or {}
        return item.get('default_domain_enabled') is not self.enabled

    def handle(self, table, request, obj_ids):
        try:
            coast.service_update(request, table.kwargs['service_id'],
                                 {'default_domain_enabled': self.enabled})
            messages.success(request, _('Default address updated.'))
            return http.HttpResponseRedirect(request.get_full_path())
        except Exception as exc:
            exceptions.handle(request, coast.error_message(
                exc, _('Unable to change the default address.')))


class DisableDefaultAddress(EnableDefaultAddress):
    name = 'disable_default_address'
    verbose_name = _('Turn default address off')
    verbose_name_plural = verbose_name

    @staticmethod
    def action_present(count):
        return _('Turn default address off')

    @staticmethod
    def action_past(count):
        return _('Turned default address off')

    enabled = False


class ReplaceDefaultDomain(AddDomain):
    name = 'replace_default'
    verbose_name = _('Use my own domain instead')

    def allowed(self, request, datum=None):
        return bool(datum and datum.get('is_default'))

    def get_link_url(self, datum=None):
        return super().get_link_url(datum) + '?replace_default=1'


class RemoveDomain(common.ApiErrorMixin, tables.DeleteAction):
    policy_rules = ()

    def allowed(self, request, datum=None):
        return bool(datum and not datum.get('is_default'))

    @staticmethod
    def action_present(count):
        return ngettext_lazy('Remove Domain', 'Remove Domains', count)

    @staticmethod
    def action_past(count):
        return ngettext_lazy('Requested removal of Domain',
                             'Requested removal of Domains', count)

    def delete(self, request, obj_id):
        coast.service_domain_delete(request, self.table.kwargs['service_id'],
                                    obj_id)


class AddEnv(tables.LinkAction):
    name = 'add_env'
    verbose_name = _('Add Variable')
    classes = ('ajax-modal',)
    icon = 'plus'
    policy_rules = ()

    def get_link_url(self, datum=None):
        return reverse(common.coast_ns(self.table.request) + 'add_env',
                       args=[self.table.kwargs['service_id']])


class EditEnv(AddEnv):
    name = 'edit_env'
    verbose_name = _('Edit Variable')
    icon = 'pencil'

    def get_link_url(self, datum):
        return reverse(common.coast_ns(self.table.request) + 'edit_env',
                       args=[self.table.kwargs['service_id'], datum['key']])


class DeleteEnv(common.ApiErrorMixin, tables.DeleteAction):
    policy_rules = ()

    @staticmethod
    def action_present(count):
        return ngettext_lazy('Delete Variable', 'Delete Variables', count)

    @staticmethod
    def action_past(count):
        return ngettext_lazy('Deleted Variable', 'Deleted Variables', count)

    def delete(self, request, obj_id):
        if coast.service_env_delete(request, self.table.kwargs['service_id'],
                                    obj_id):
            messages.info(request, _('Redeploy to apply environment '
                                     'variable changes.'))


def domain_link(item):
    url = common.domain_url(item)
    if not url:
        return item.get('fqdn') or ''
    return format_html('<a href="{}" target="_blank" '
                       'rel="noopener noreferrer">'
                       '{}</a> {}', url, item['fqdn'], common.copy_button(url))


class DomainsTable(common.ResourceTable):
    fqdn = tables.Column(domain_link, verbose_name=_('Domain'))
    primary = tables.Column('primary', verbose_name=_('Primary'),
                            filters=(common.yes_no,))
    status = common.StatusColumn()
    tls = tables.Column(tls_label, verbose_name=_('HTTPS certificate'))
    verification = tables.Column(verification_guidance,
                                 verbose_name=_('Verification'))

    class Meta:
        name = 'domains'
        verbose_name = _('Domains')
        row_class = UpdateDomainRow
        status_columns = ('status',)
        table_actions = (AddDomain, EnableDefaultAddress,
                         DisableDefaultAddress)
        row_actions = (ReplaceDefaultDomain, MakePrimary, EditDomain,
                       VerifyDomain, RemoveDomain)


class EnvTable(common.ResourceTable):
    key = tables.Column('key', verbose_name=_('Key'))
    value = tables.Column('value', verbose_name=_('Value'))
    secret = tables.Column('secret', verbose_name=_('Secret'),
                           filters=(common.yes_no,))

    build_time = tables.Column('build_time', verbose_name=_('Build-time'))

    def __init__(self, request, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        if kwargs.get('item', {}).get('kind') == 'service':
            self.columns.pop('build_time', None)
        else:
            self.columns['build_time'].transform = self.build_time_control

    def build_time_control(self, row):
        enabled = row.get('build_time')
        if enabled is None:
            return format_html(
                '<input type="checkbox" class="coast-build-time" disabled '
                'aria-label="{}" title="{}">',
                _('Build-time'), _('Unknown (refresh)'))
        warning = (_('Secret values passed to builds can appear in build '
                     'output.') if enabled and row.get('secret') else '')
        return format_html(
            '<input type="checkbox" class="coast-build-time" {} '
            'aria-label="{}" title="{}" data-url="{}" data-csrf="{}"> '
            '<span class="label label-warning coast-build-warning" '
            'style="margin-left:0.4em" {}>{}</span>',
            'checked' if enabled else '', _('Build-time'),
            _('Also passed to builds. Turn off for runtime-only.'),
            reverse(common.coast_ns(self.request) + 'env_build_time',
                    args=[self.kwargs['service_id'], row['key']]),
            get_token(self.request), '' if warning else 'hidden', warning)

    def get_object_id(self, datum):
        return datum['key']

    class Meta:
        name = 'env'
        verbose_name = _('Environment Variables')
        table_actions = (AddEnv,)
        row_actions = (EditEnv, DeleteEnv)


def logs_url(service_id, kind=None):
    return reverse(common.coast_ns(kind=kind) + 'logs', args=[service_id])


def storage_stack(table):
    return (table.kwargs.get('item') or {}).get('stack_id')


def storage_editable(table, datum=None):
    if not coast.storage_supported(table.request):
        return False
    return datum is None or datum.get('origin') == 'user'


class CreateStorage(tables.LinkAction):
    name = 'create_storage'
    verbose_name = _('Create Storage')
    classes = ('ajax-modal',)
    icon = 'plus'
    policy_rules = ()

    def allowed(self, request, datum=None):
        return (common.project_member(request) and
                storage_editable(self.table))

    def get_link_url(self, datum=None):
        return reverse(common.coast_ns(self.table.request) + 'create_storage',
                       args=[self.table.kwargs['service_id']])


class EditStorage(tables.LinkAction):
    name = 'edit_storage'
    verbose_name = _('Edit')
    classes = ('ajax-modal',)
    policy_rules = ()

    def allowed(self, request, datum=None):
        return (common.project_member(request) and datum is not None
                and datum.get('id') and storage_editable(self.table, datum))

    def get_link_url(self, datum):
        return reverse(common.coast_ns(self.table.request) + 'edit_storage',
                       args=[self.table.kwargs['service_id'], datum['id']])


class DeleteStorage(common.ApiErrorMixin, tables.DeleteAction):
    policy_rules = ()
    help_text = _('Remove this storage mount from the service. The data is '
                  'kept. Deploy the service to apply the change.')

    @staticmethod
    def action_present(count):
        return ngettext_lazy('Delete Storage', 'Delete Storage', count)

    @staticmethod
    def action_past(count):
        return ngettext_lazy('Deleted Storage', 'Deleted Storage', count)

    def allowed(self, request, datum=None):
        if not common.project_manager(request):
            return False
        if datum is None:
            return storage_editable(self.table)
        return bool(datum.get('id') and
                    storage_editable(self.table, datum))

    def delete(self, request, obj_id):
        coast.storage_delete(request, storage_stack(self.table), obj_id)


def storage_type(datum):
    return (_('Bind mount (host folder)') if datum['type'] == 'bind'
            else _('Named volume'))


def storage_read_only(value):
    return _('Yes') if value else _('No')


def storage_source(datum):
    return datum.get('source') or _('Anonymous volume')


def storage_origin(datum):
    return _('from template') if datum.get('origin') == 'template' else ''


class StorageTable(common.ResourceTable):
    type = tables.Column(storage_type, verbose_name=_('Type'))
    source = tables.Column(storage_source, verbose_name=_('Source'))
    container_path = tables.Column('container_path',
                                   verbose_name=_('Container path'))
    read_only = tables.Column('read_only', verbose_name=_('Read-only'),
                              filters=(storage_read_only,))
    origin = tables.Column(storage_origin, verbose_name=_('Origin'))

    def get_object_id(self, datum):
        return datum['id'] or 'template-' + str(self.data.index(datum))

    def get_object_display(self, datum):
        return storage_source(datum)

    class Meta:
        name = 'storage'
        verbose_name = _('Storage')
        table_actions = (CreateStorage,)
        row_actions = (EditStorage, DeleteStorage)


def container_status(row):
    state = row.get('state') or _('Unknown')
    health = row.get('health')
    return '%s (%s)' % (state, health) if health else state


class ContainersTable(common.ResourceTable):
    name = tables.Column('name', verbose_name=_('Name'),
                         link=lambda row: row['detail_url'])
    image = tables.Column('image', verbose_name=_('Image'))
    status = tables.Column(container_status, verbose_name=_('Status'))
    restarts = tables.Column('restart_count', verbose_name=_('Restarts'))

    class Meta:
        name = 'containers'
        verbose_name = _('Containers')
        table_actions = ()
        row_actions = ()
