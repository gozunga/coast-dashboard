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

"""Container config files: metadata tables and write-only content forms."""

from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy
from horizon import exceptions
from horizon import forms
from horizon import messages
from horizon import tables
from horizon import tabs

from coast_dashboard.api import coast
from coast_dashboard.content import common


REDEPLOY = _('Redeploy needed. File changes apply on the next deploy.')


def mount_service(table):
    return table.kwargs['service_id']


class AddFile(tables.LinkAction):
    name = 'add_file'
    verbose_name = _('Add File')
    classes = ('ajax-modal',)
    icon = 'plus'
    policy_rules = ()

    def allowed(self, request, datum=None):
        return common.project_member(request)

    def get_link_url(self, datum=None):
        return reverse(common.coast_ns(self.table.request) + 'add_file',
                       args=[mount_service(self.table)])


class EditFile(AddFile):
    name = 'edit_file'
    verbose_name = _('Edit')
    icon = 'pencil'

    def get_link_url(self, datum):
        return reverse(common.coast_ns(self.table.request) + 'edit_file',
                       args=[mount_service(self.table), datum['id']])


class DeleteFile(common.ApiErrorMixin, tables.DeleteAction):
    help_text = _('The file is removed from the container on the next deploy. '
                  'Redeploy needed after deletion.')

    @staticmethod
    def action_present(count):
        return ngettext_lazy('Delete File', 'Delete Files', count)

    @staticmethod
    def action_past(count):
        return ngettext_lazy('Deleted File', 'Deleted Files', count)

    def allowed(self, request, datum=None):
        return any((role if isinstance(role, str) else role.get('name', '')
                    ).lower() in ('manager', 'admin')
                   for role in (getattr(request.user, 'roles', None) or []))

    def delete(self, request, obj_id):
        coast.file_mount_delete(request, mount_service(self.table), obj_id)
        messages.success(request, REDEPLOY)


def unavailable(datum):
    return _('Not available')


class FilesTable(common.ResourceTable):
    container_path = tables.Column('container_path',
                                   verbose_name=_('Container path'))
    resource_name = tables.Column('resource_name',
                                  verbose_name=_('Container name'))
    size = tables.Column(unavailable, verbose_name=_('Size'))
    mode = tables.Column(unavailable, verbose_name=_('Mode'))

    def get_object_display(self, datum):
        return datum['container_path']

    class Meta:
        name = 'files'
        verbose_name = _('Files')
        table_actions = (AddFile,)
        row_actions = (EditFile, DeleteFile)


class Files(tabs.TableTab):
    name = _('Files')
    slug = 'files'
    table_classes = (FilesTable,)
    template_name = 'project/coast_services/files.html'
    preload = False

    def get_files_data(self):
        try:
            return coast.file_mount_list(
                self.request, self.tab_group.kwargs['service_id'])
        except Exception as exc:
            exceptions.handle(self.request, coast.error_message(
                exc, _('Unable to retrieve files.')))
            return []


class FileForm(forms.SelfHandlingForm):
    help_text = _(
        'The file is placed inside the container only. Changes apply on '
        'the next deploy. Content is stored securely and cannot be read '
        'back. Size is not returned by the API. File mode cannot be set.')
    container_path = forms.CharField(
        label=_('Container path'), max_length=255,
        help_text=_('Absolute file path inside the container, for example '
                    '/etc/nginx/conf.d/site.conf.'))
    resource_name = forms.CharField(
        label=_('Container name'), max_length=255, required=False,
        help_text=_('For templates with several containers, enter the '
                    'application or database container name.'))
    replace_content = forms.BooleanField(
        label=_('Replace stored content'), required=False,
        help_text=_('Select to replace content, including with an empty '
                    'file. Leave clear to keep the stored content.'))
    content = forms.CharField(
        label=_('Content'), required=False, strip=False,
        widget=forms.Textarea(attrs={
            'rows': 16, 'style': 'font-family:monospace;',
            'spellcheck': 'false', 'autocomplete': 'off'}),
        help_text=_('UTF-8 text, up to 64 KiB. Empty files are allowed.'))

    def __init__(self, request, *args, service_id, template=False,
                 mount_id=None, **kwargs):
        self.service_id = service_id
        self.mount_id = mount_id
        super().__init__(request, *args, **kwargs)
        if not template:
            self.fields.pop('resource_name')
        if not mount_id:
            self.fields.pop('replace_content')

    def clean_content(self):
        content = self.cleaned_data['content']
        try:
            size = len(content.encode('utf-8'))
        except UnicodeError:
            raise forms.ValidationError(_('Content must be valid UTF-8.'))
        if '\x00' in content or size > 65536:
            raise forms.ValidationError(
                _('Content must have no NUL characters and be at most '
                  '64 KiB in UTF-8.'))
        return content

    def clean(self):
        data = super().clean()
        if (self.mount_id and data.get('content') and
                not data.get('replace_content')):
            self.add_error('replace_content', _(
                'Select Replace stored content to save the entered text.'))
        return data

    def handle(self, request, data):
        values = {'container_path': data['container_path']}
        if 'resource_name' in self.fields and data.get('resource_name'):
            values['resource_name'] = data['resource_name']
        if not self.mount_id or data.get('replace_content'):
            values['content'] = data['content']
        try:
            if self.mount_id:
                coast.file_mount_update(request, self.service_id,
                                        self.mount_id, values)
            else:
                coast.file_mount_create(request, self.service_id, values)
        except Exception as exc:
            exceptions.handle(request, _('Unable to save file.'),
                              ignore=True, details='')
            self.api_error(coast.error_message(exc, _('Unable to save file.')))
            return False
        messages.success(request, REDEPLOY)
        return True


class AddFileView(forms.ModalFormView):
    form_class = FileForm
    template_name = 'project/coast_services/settings_form.html'
    page_title = submit_label = _('Add File')
    modal_id = 'coast_file_modal'
    form_id = 'coast_file_form'

    def dispatch(self, request, *args, **kwargs):
        if not common.project_member(request):
            raise exceptions.NotAuthorized(_('You cannot change files.'))
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        service = coast.service_get(self.request, self.kwargs['service_id'])
        kwargs.update(service_id=self.kwargs['service_id'],
                      template=common.is_template(service),
                      mount_id=self.kwargs.get('mount_id'))
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['submit_url'] = self.request.path
        return context

    def get_success_url(self):
        return reverse(common.coast_ns(self.request) + 'detail',
                       args=[self.kwargs['service_id']]) + (
                           '?tab=service_details__files')

    def get_cancel_url(self):
        return self.get_success_url()


class EditFileView(AddFileView):
    page_title = _('Edit File')
    submit_label = _('Save')

    def get_initial(self):
        try:
            row = coast.file_mount_get(self.request,
                                       self.kwargs['service_id'],
                                       self.kwargs['mount_id'])
        except Exception as exc:
            exceptions.handle(self.request, coast.error_message(
                exc, _('Unable to retrieve file.')),
                redirect=self.get_success_url())
            return {}
        return {key: row.get(key) or ''
                for key in ('container_path', 'resource_name')}
