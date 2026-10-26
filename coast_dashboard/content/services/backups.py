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

"""Database backup policy, history, and guarded operations."""

from django.contrib import messages
from django import forms
from django.http import Http404
from django.http import HttpResponseForbidden
from django.http import StreamingHttpResponse
from django.middleware import csrf
from django import shortcuts
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views import generic
from horizon import exceptions
from horizon import forms as horizon_forms
from horizon import tabs

from coast_dashboard.api import coast
from coast_dashboard.content import common


ENGINES = frozenset(('postgres', 'postgresql', 'mysql', 'mariadb', 'mongo',
                     'mongodb'))
READY = frozenset(('active',))


def is_database(service):
    source = service.get('source') or {}
    engine = service.get('engine') or service.get('template_id') or (
        source.get('template_id'))
    return (service.get('kind') == 'service' and common.is_template(service)
            and engine in ENGINES)


def native_database(request):
    return common.coast_ns(request).endswith('coast.databases:')


def supported_database(request, item):
    return any(e['engine'] == item.get('engine') and e.get('backups')
               for e in coast.database_engine_list(request))


def resource_api(request, operation, *args):
    prefix = 'database_backup_' if native_database(request) else 'backup_'
    return getattr(coast, prefix + operation)(request, *args)


def detail_url(request, service_id):
    return reverse(common.coast_ns(request) + 'detail', args=[service_id]) + (
        '?tab=%s__backups' % ('database_details' if native_database(request)
                              else 'service_details'))


def error_message(exc, default):
    message = coast.error_message(exc, default)
    if message == 'Object storage not available.':
        return _('Object storage not available. Contact your cloud operator '
                 'to enable database backups.')
    return message


class PolicyForm(forms.Form):
    engine = forms.ChoiceField(label=_('Database engine'), choices=(
        ('', _('Select a database engine')), ('postgres', _('Postgres')),
        ('mysql', _('MySQL')), ('mariadb', _('MariaDB')),
        ('mongodb', _('MongoDB'))))
    container = forms.RegexField(
        label=_('Database container'), max_length=128,
        regex=r'^[A-Za-z0-9][A-Za-z0-9_.-]*$',
        help_text=_('Enter the Compose container name shown on the '
                    'Containers tab.'))
    schedule = forms.ChoiceField(label=_('Schedule'), initial='off', choices=(
        ('off', _('Off')), ('daily', _('Daily'))))
    time = forms.TimeField(label=_('Time (UTC)'), initial='02:00',
                           required=False, input_formats=['%H:%M'],
                           widget=forms.TimeInput(format='%H:%M',
                                                  attrs={'type': 'time'}))
    keep_daily = forms.IntegerField(label=_('Daily backups to keep'),
                                    initial=14, min_value=0, max_value=365)
    keep_weekly = forms.IntegerField(label=_('Weekly backups to keep'),
                                     initial=8, min_value=0, max_value=104)

    def clean(self):
        data = super().clean()
        if data.get('schedule') == 'daily' and not data.get('time'):
            self.add_error('time', _('Enter a time for this schedule.'))
        return data

    def policy(self):
        data = self.cleaned_data
        time = data.get('time')
        return dict(enabled=data['schedule'] == 'daily',
                    hour=time.hour if time else 2,
                    minute=time.minute if time else 0,
                    **({key: data[key] for key in ('engine', 'container')
                        if key in data}),
                    keep_daily=data['keep_daily'],
                    keep_weekly=data['keep_weekly'])


class DatabasePolicyForm(PolicyForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        del self.fields['engine']
        del self.fields['container']


class Backups(tabs.Tab):
    name = _('Backups')
    slug = 'backups'
    preload = False
    template_name = 'project/coast_services/backups.html'

    def allowed(self, request):
        if native_database(request):
            return True
        return (is_database(self.tab_group.kwargs.get('item') or {}) and
                coast.backups_supported(request))

    def get_context_data(self, request):
        service = self.tab_group.kwargs['item']
        service_id = service['id']
        context = {'service': service,
                   'can_manage': common.project_member(request)}
        context['action_url'] = reverse(
            common.coast_ns(request) + 'backups', args=[service_id])
        context['csrf_value'] = csrf.get_token(request)
        try:
            if (native_database(request) and
                    not supported_database(request, service)):
                return {'backups_error': _(
                    'Backups for this engine are coming in a later release.')}
            policy = resource_api(request, 'policy_get', service_id)
            context['policy_configured'] = bool(
                native_database(request) or
                (policy.get('engine') and policy.get('container')))
            initial = dict(
                policy, schedule='daily' if policy['enabled'] else 'off',
                time='%02d:%02d' % (policy['hour'], policy['minute']))
            form_class = (DatabasePolicyForm if native_database(request)
                          else PolicyForm)
            context['policy_form'] = form_class(initial=initial)
            if not context['can_manage']:
                for field in context['policy_form'].fields.values():
                    field.disabled = True
            rows = sorted(resource_api(request, 'list', service_id),
                          key=lambda row: row.get('started_at') or '',
                          reverse=True)
            for row in rows:
                row['ready'] = str(row.get('status', '')).lower() in READY
                row['can_delete'] = str(row.get('status', '')).lower() in (
                    READY | {'error'})
                for operation in ('restore', 'download', 'delete'):
                    row[operation + '_url'] = reverse(
                        common.coast_ns(request) + 'backup_' + operation,
                        args=[service_id, row['id']])
            context['backups'] = rows
        except exceptions.NotAuthorized:
            raise
        except Exception as exc:
            context['backups_error'] = error_message(
                exc, _('Unable to retrieve backups.'))
        return context


class AccessMixin:
    """Check access and ownership again for every direct action URL."""

    def dispatch(self, request, *args, **kwargs):
        if not common.project_member(request):
            return HttpResponseForbidden()
        try:
            loader = (coast.database_get if native_database(request)
                      else coast.service_get)
            self.service = loader(request, kwargs['service_id'])
            supported = (supported_database(request, self.service)
                         if native_database(request) else
                         is_database(self.service) and
                         coast.backups_supported(request))
            if not supported:
                raise Http404
            self.backup = None
            if kwargs.get('backup_id'):
                self.backup = coast.backup_get(request, kwargs['backup_id'])
                if self.backup.get('service_id') != kwargs['service_id']:
                    raise Http404
        except exceptions.NotAuthorized:
            raise
        except exceptions.NotFound:
            raise Http404
        except coast.CoastError:
            messages.error(request, _('Unable to retrieve backup details.'))
            return shortcuts.redirect(self.get_success_url())
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return detail_url(self.request, self.kwargs['service_id'])


class PolicyView(AccessMixin, generic.View):
    http_method_names = ['post']

    def post(self, request, service_id):
        operation = request.POST.get('operation')
        try:
            if operation == 'save':
                form_class = (DatabasePolicyForm if native_database(request)
                              else PolicyForm)
                form = form_class(request.POST)
                if not form.is_valid():
                    messages.error(request, _('Invalid backup policy: %s') %
                                   form.errors.as_text())
                    return shortcuts.redirect(self.get_success_url())
                resource_api(request, 'policy_update', service_id,
                             form.policy())
                messages.success(request, _('Backup policy saved.'))
            elif operation == 'create':
                policy = resource_api(request, 'policy_get', service_id)
                if not (native_database(request) or
                        (policy.get('engine') and policy.get('container'))):
                    messages.error(request, _('Select a database engine and '
                                              'container, then save the '
                                              'backup policy first.'))
                    return shortcuts.redirect(self.get_success_url())
                resource_api(request, 'create', service_id)
                messages.success(request, _('Backup requested.'))
            else:
                return HttpResponseForbidden()
        except Exception as exc:
            messages.error(request, error_message(
                exc, _('Unable to update backups.')))
        return shortcuts.redirect(self.get_success_url())


class RestoreForm(horizon_forms.SelfHandlingForm):
    mode = forms.ChoiceField(label=_('Restore'), initial='new_copy', choices=(
        ('new_copy', _('Into a new copy')),
        ('overwrite', _('Overwrite this database'))),
        widget=forms.RadioSelect)
    name = forms.CharField(label=_('New copy name'), required=False,
                           max_length=63)
    confirmation = forms.CharField(
        label=_('Service name'),
        required=False, strip=False)
    help_text = _(
        'A new copy uses fresh storage and template defaults. Custom '
        'environment settings and Compose changes are not copied. '
        'Overwrite stops this database and takes a safety backup first. '
        'Existing data is replaced.')

    def __init__(self, request, *args, service, backup_id, **kwargs):
        self.service = service
        self.backup_id = backup_id
        super().__init__(request, *args, **kwargs)
        if native_database(request):
            self.help_text = _(
                'A new database uses the same engine, version and placement, '
                'with fresh credentials and public access off. Overwrite '
                'replaces existing data after taking a safety backup.')
            self.fields['confirmation'].label = _('Coast name')

    def clean(self):
        data = super().clean()
        if data.get('mode') == 'new_copy':
            name_field = forms.RegexField(
                max_length=63,
                regex=r'^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$')
            try:
                name_field.clean(data.get('name', ''))
            except forms.ValidationError as exc:
                self.add_error('name', exc)
        if (data.get('mode') == 'overwrite' and
                data.get('confirmation') != self.service['name']):
            self.add_error('confirmation',
                           _('Type %(name)s to confirm overwrite.') %
                           {'name': self.service['name']})
        return data

    def handle(self, request, data):
        try:
            coast.backup_restore(request, self.backup_id, data['mode'],
                                 data.get('name'), data.get('confirmation'))
        except Exception as exc:
            self.api_error(error_message(
                exc, _('Unable to restore backup.')))
            return False
        messages.success(request, _('Restore requested.'))
        return True


class RestoreView(AccessMixin, horizon_forms.ModalFormView):
    form_class = RestoreForm
    template_name = 'project/coast_services/restore.html'
    page_title = submit_label = _('Restore backup')
    modal_id = 'coast_restore_backup'
    form_id = 'coast_restore_backup_form'

    def get_form_kwargs(self):
        if str(self.backup.get('status', '')).lower() not in READY:
            raise Http404
        return dict(super().get_form_kwargs(), service=self.service,
                    backup_id=self.kwargs['backup_id'])

    def get_initial(self):
        return {'mode': 'new_copy',
                'name': self.service['name'][:50] + '-copy'}

    def get_context_data(self, **kwargs):
        return dict(super().get_context_data(**kwargs),
                    submit_url=self.request.path)

    def get_cancel_url(self):
        return self.get_success_url()


class DownloadStream:
    """Transfer chunks and close the API connection on disconnect."""

    def __init__(self, response):
        self.response = response

    def __iter__(self):
        return self.response.iter_content(chunk_size=65536)

    def close(self):
        self.response.close()


class DownloadView(AccessMixin, generic.View):
    http_method_names = ['get']

    def get(self, request, service_id, backup_id):
        if str(self.backup.get('status', '')).lower() not in READY:
            raise Http404
        try:
            upstream = coast.backup_download(request, backup_id)
        except Exception as exc:
            messages.error(request, error_message(
                exc, _('Unable to download backup.')))
            return shortcuts.redirect(self.get_success_url())
        response = StreamingHttpResponse(DownloadStream(upstream),
                                         content_type='application/gzip')
        response['Content-Disposition'] = (
            'attachment; filename="%s.dump.gz"' % self.backup['id'])
        response['Cache-Control'] = 'no-store'
        response['Referrer-Policy'] = 'no-referrer'
        return response


class DeleteForm(horizon_forms.SelfHandlingForm):
    confirm = forms.BooleanField(label=_('Permanently delete this backup'))
    help_text = _('This removes the backup from object storage. '
                  'This action cannot be undone.')

    def __init__(self, request, *args, backup_id, **kwargs):
        self.backup_id = backup_id
        super().__init__(request, *args, **kwargs)

    def handle(self, request, data):
        try:
            coast.backup_delete(request, self.backup_id)
        except Exception as exc:
            self.api_error(error_message(
                exc, _('Unable to delete backup.')))
            return False
        messages.success(request, _('Backup deletion requested.'))
        return True


class DeleteView(AccessMixin, horizon_forms.ModalFormView):
    form_class = DeleteForm
    template_name = 'project/coast_services/settings_form.html'
    page_title = submit_label = _('Delete backup')
    modal_id = 'coast_delete_backup'
    form_id = 'coast_delete_backup_form'

    def get_form_kwargs(self):
        if str(self.backup.get('status', '')).lower() not in (
                READY | {'error'}):
            raise Http404
        return dict(super().get_form_kwargs(),
                    backup_id=self.kwargs['backup_id'])

    def get_context_data(self, **kwargs):
        return dict(super().get_context_data(**kwargs),
                    submit_url=self.request.path)

    def get_cancel_url(self):
        return self.get_success_url()
