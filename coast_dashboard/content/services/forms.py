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

import posixpath
import re

from django import forms as django_forms
from urllib import parse

from django.utils.translation import gettext_lazy as _
from horizon import exceptions
from horizon import forms
from horizon import messages

from coast_dashboard.api import coast
from coast_dashboard.content import common
from coast_dashboard.content import dns
from coast_dashboard.content.services import dotenv


class HealthCheckForm(forms.SelfHandlingForm):
    health_check = forms.ChoiceField(
        label=_('Health check'), initial='none',
        choices=[('none', _('None (container running is enough)')),
                 ('http', _('HTTP (wait for the app to answer on its port)'))],
        help_text=_(
            'Use None for background workers that do not listen on a port. '
            'The app becomes Active once its container keeps running for '
            'about 20 seconds.'))
    health_check_port = forms.IntegerField(
        label=_('Health check port'), min_value=1, max_value=65535,
        required=False, help_text=_('Leave blank to use the first app port.'))
    healthcheck_path = forms.CharField(
        label=_('Health check path'), initial='/', max_length=255,
        required=False, help_text=_('HTTP path to check, for example /.'))

    def __init__(self, request, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        if self.is_bound and self.data.get(
                self.add_prefix('health_check')) != 'http':
            for name in ('health_check_port', 'healthcheck_path'):
                self.fields[name].disabled = True

    def clean(self):
        data = super().clean()
        if data.get('health_check') == 'http':
            if 'ports' in self.fields and not data.get('ports'):
                self.add_error('ports', _('Enter a port for the HTTP check.'))
            data['healthcheck_path'] = data.get('healthcheck_path') or '/'
            if not data['healthcheck_path'].startswith('/'):
                self.add_error('healthcheck_path',
                               _('Start the path with /.'))
        return data

    def clean_ports(self):
        return self.cleaned_data['ports'] or None

    def port_api_error(self, exc, default):
        message = coast.error_message(exc, default)
        if getattr(exc, 'api_message', None) and 'port' in message.lower():
            self.add_error('ports', message)
        else:
            self.api_error(message)

    def probe_values(self, data):
        values = {'health_check': data['health_check']}
        if data['health_check'] == 'http':
            values.update(health_check_port=data.get('health_check_port'),
                          healthcheck_path=data.get('healthcheck_path') or '/')
        return values


class ServicePlacementForm(forms.SelfHandlingForm):
    name = forms.RegexField(
        label=_('Name'),
        max_length=63,
        regex='^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$',
        help_text=_(
            'Use lowercase letters, numbers and hyphens. Start and end with a '
            'letter or number.'))
    appgroup_id = forms.ChoiceField(
        label=_('App Group'),
        help_text=_(
            'Choose the app group for this app or service.'))
    environment_id = forms.ChoiceField(
        label=_('Environment'),
        help_text=_(
            'Choose an environment in the selected app group.'))
    server_id = forms.ChoiceField(
        label=_('Worker'),
        help_text=_(
            'Choose a worker in the app group stack to run this app or '
            'service.'))

    def __init__(self, request, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.appgroups = {}
        self.environments = {}
        self.servers = {}
        try:
            self.appgroups = {a['id']: a for a in
                              coast.appgroup_list(request)}
            self.environments = {e['id']: e for e in
                                 coast.environment_list(request)}
            stack_ids = {a['stack_id'] for a in self.appgroups.values()}
            stack_names = common.name_maps(request)[0]
            self.servers = {s['id']: s for stack_id in sorted(stack_ids)
                            for s in coast.stack_server_list(request, stack_id)
                            if s['role'] == 'worker' and
                            s['status'] == 'ACTIVE'}
            self.fields['appgroup_id'].choices = [
                (a['id'], a['name']) for a in self.appgroups.values()
                if a['status'] == 'ACTIVE']
            self.fields['environment_id'].choices = [
                (e['id'], '%s / %s' % (
                    self.appgroups[e['appgroup_id']]['name'], e['name']))
                for e in self.environments.values() if e['status'] == 'ACTIVE']
            # Coast's engine driver needs a worker; there is no placement.
            self.fields['server_id'].choices = [
                (s['id'], '%s / %s' % (
                    stack_names.get(s['stack_id'], s['stack_id']), s['name']))
                for s in self.servers.values()]
            # Preselect only when there is exactly one choice.
            for field, label in (
                    ('appgroup_id', _('Select an app group')),
                    ('environment_id', _('Select an environment')),
                    ('server_id', _('Select a worker'))):
                choices = list(self.fields[field].choices)
                if len(choices) != 1:
                    self.fields[field].choices = [('', label)] + choices
        except Exception:
            exceptions.handle(
                request, _('Unable to retrieve app choices.'))

        common.lock_placement(self, request)
        group = self.initial.get('appgroup_id')
        envs = [e['id'] for e in self.environments.values()
                if e['appgroup_id'] == group and e['status'] == 'ACTIVE']
        if group and len(envs) == 1 and not request.GET.get('environment_id'):
            self.initial['environment_id'] = envs[0]
        stack = self.appgroups.get(group, {}).get('stack_id')
        workers = [(key, label) for key, label in
                   self.fields['server_id'].choices
                   if key and self.servers[key]['stack_id'] == stack]
        if self.fields['appgroup_id'].disabled:
            self.fields['server_id'].choices = (
                workers if len(workers) == 1 else
                [('', _('Select a worker'))] + workers)
        if len(workers) == 1:
            self.initial['server_id'] = workers[0][0]
        self.appgroup_stacks = {
            a['id']: a['stack_id'] for a in self.appgroups.values()}
        self.worker_stacks = {
            key: self.servers[key]['stack_id']
            for key, _label in self.fields['server_id'].choices if key}
        self.environment_groups = {
            e['id']: e['appgroup_id'] for e in self.environments.values()}

    def clean(self):
        data = super().clean()
        app = self.appgroups.get(data.get('appgroup_id'))
        env = self.environments.get(data.get('environment_id'))
        server = self.servers.get(data.get('server_id'))
        if app and env and env['appgroup_id'] != app['id']:
            self.add_error('environment_id',
                           _('Select an environment in this app group.'))
        if app and server and (server['role'] != 'worker' or
                               server['stack_id'] != app['stack_id']):
            self.add_error('server_id',
                           _('Select a worker in the app group stack.'))
        return data


class PrivateText(django_forms.Textarea):
    """Accept sensitive input without ever redisplaying submitted text."""

    def format_value(self, value):
        return None


def uploaded_text(form, data, name):
    upload = data.get(name + '_file')
    text = data.get(name) or ''
    if upload and text:
        form.add_error(name, _('Choose a file or enter text, not both.'))
    if upload:
        try:
            text = upload.read(1048577).decode('utf-8')
            if len(text.encode('utf-8')) > 1048576:
                raise ValueError()
        except (UnicodeError, ValueError):
            form.add_error(name, _('Use a UTF-8 file up to 1 MiB.'))
            return ''
    return text


class DeployKeyFields(forms.SelfHandlingForm):
    key_mode = forms.ChoiceField(
        label=_('Deploy key'), initial='generate', required=False,
        help_text=_('Generate a key or provide an unencrypted private key.'),
        choices=[('generate', _('Generate a deploy key (recommended)')),
                 ('upload', _('Upload a private key'))],
        widget=forms.ThemableSelectWidget(attrs={
            'class': 'switchable', 'data-slug': 'key-mode'}))
    private_key = forms.CharField(
        label=_('Private key'), required=False, strip=False,
        widget=PrivateText(attrs={'autocomplete': 'off'}),
        help_text=_('Only unencrypted private keys are accepted.'))
    private_key_file = forms.FileField(
        label=_('Private key file'), required=False,
        help_text=_('Upload an unencrypted private key instead of '
                    'pasting it.'))

    def __init__(self, request, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        for name in ('private_key', 'private_key_file'):
            self.fields[name].widget.attrs.update({
                'class': 'switched', 'data-switch-on': 'key-mode',
                'data-key-mode-upload': self.fields[name].label})

    def key_options(self, data):
        if data.get('key_mode', 'generate') != 'upload':
            return {'generate': True}
        text = uploaded_text(self, data, 'private_key')
        if not text.strip():
            self.add_error('private_key', _('Enter or upload a private key.'))
        return {'private_key': text}


class CreateService(HealthCheckForm, ServicePlacementForm, DeployKeyFields):
    field_order = (
        'name', 'appgroup_id', 'environment_id', 'server_id',
        'source_type', 'repo_url', 'ssh_url', 'key_mode', 'private_key',
        'private_key_file', 'dockerfile', 'dockerfile_file',
        'compose', 'compose_file', 'branch', 'build_pack', 'base_directory',
        'image', 'tag', 'ports', 'health_check', 'health_check_port',
        'healthcheck_path')

    help_text = _(
        'Create an app from a public Git repository, a private Git '
        'repository, a container image, a Dockerfile or Docker Compose. '
        'Choose an environment and a '
        'worker in the app group stack.')

    source_type = forms.ChoiceField(
        label=_('Source'),
        choices=[('git', _('Public Git repository')),
                 ('private_git', _('Private Git repository (deploy key)')),
                 ('image', _('Container image')),
                 ('dockerfile', _('Dockerfile')),
                 ('compose', _('Docker Compose'))],
        widget=forms.ThemableSelectWidget(attrs={
            'class': 'switchable', 'data-slug': 'source'}),
        help_text=_(
            'Choose where the app code or container image comes from.'))
    ssh_url = forms.CharField(label=_('SSH repository URL'),
                              max_length=1024, required=False,
                              help_text=_('Use git@host:org/repo.git or '
                                          'ssh://git@host/org/repo.git.'))
    dockerfile = forms.CharField(label=_('Dockerfile'), required=False,
                                 strip=False, widget=PrivateText,
                                 help_text=_('Paste a Dockerfile or upload '
                                             'a file below.'))
    dockerfile_file = forms.FileField(label=_('Dockerfile file'),
                                      required=False,
                                      help_text=_('Upload a Dockerfile '
                                                  'instead of pasting text.'))
    compose = forms.CharField(label=_('Docker Compose'), required=False,
                              strip=False, widget=PrivateText,
                              help_text=_('Paste Compose YAML or upload '
                                          'a file below.'))
    compose_file = forms.FileField(
        label=_('Compose file'), required=False,
        help_text=_('Upload Compose YAML instead of pasting text.'))
    repo_url = forms.URLField(
        label=_('Public Git repository URL'),
        max_length=1024,
        required=False,
        help_text=_(
            'Enter a public HTTPS Git URL without passwords or tokens.'))
    branch = forms.CharField(
        label=_('Branch'),
        max_length=255,
        initial='main',
        required=False,
        help_text=_(
            'Enter the Git branch to build.'))
    build_pack = forms.ChoiceField(
        label=_('Build pack'),
        required=False,
        choices=[('nixpacks', 'Nixpacks'), ('dockerfile', 'Dockerfile'),
                 ('compose', 'Compose'), ('static', 'Static')],
        help_text=_(
            'Choose how Coast builds the app from your repository.'))
    base_directory = forms.CharField(
        label=_('Base directory'),
        max_length=255,
        required=False,
        help_text=_(
            'Optional path to the app inside the repository.'))
    image = forms.CharField(
        label=_('Image'),
        max_length=255,
        required=False,
        help_text=_(
            'Enter the container image name, for example nginx.'))
    tag = forms.CharField(
        label=_('Tag'),
        max_length=128,
        required=False,
        help_text=_(
            'Enter the image version, for example stable.'))
    ports = forms.CharField(
        label=_('Ports'),
        required=False, max_length=255,
        initial='8080',
        help_text=_(
            'Optional. Required only when the health check type is HTTP '
            'or the app has a domain.'))

    def __init__(self, request, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.data = self.data.copy()
        self.files = self.files.copy()
        source_type = self.data.get(self.add_prefix('source_type'), 'git')
        groups = {
            'repo_url': ('git',), 'ssh_url': ('private_git',),
            'key_mode': ('private_git',),
            'private_key': ('private_git',),
            'private_key_file': ('private_git',),
            'branch': ('git', 'private_git'),
            'build_pack': ('git', 'private_git'),
            'base_directory': ('git', 'private_git'),
            'image': ('image',), 'tag': ('image',),
            'dockerfile': ('dockerfile',),
            'dockerfile_file': ('dockerfile',),
            'compose': ('compose',), 'compose_file': ('compose',)}
        for name, kinds in groups.items():
            field = self.fields[name]
            if name in ('private_key', 'private_key_file'):
                if self.is_bound and source_type not in kinds:
                    self.data.pop(self.add_prefix(name), None)
                    self.files.pop(self.add_prefix(name), None)
                continue
            field.widget.attrs.update({
                'class': ('switchable switched' if name == 'key_mode' else
                          'switched'), 'data-switch-on': 'source',
                **{'data-source-' + kind: field.label for kind in kinds}})
            field.required = (source_type in kinds and name in (
                'repo_url', 'ssh_url', 'branch', 'build_pack', 'image', 'tag'))
            if self.is_bound and source_type not in kinds:
                self.data.pop(self.add_prefix(name), None)
                self.files.pop(self.add_prefix(name), None)

    def clean(self):
        data = super().clean()
        kind = data.get('source_type')
        if kind == 'private_git':
            url = data.get('ssh_url', '')
            if not re.fullmatch(
                    r'(?:[^@/:\s]+@[^/:\s]+:[^\s]+|'
                    r'ssh://[^@/:\s]+@[^/:\s]+(?::[0-9]+)?/[^\s]+)', url):
                self.add_error('ssh_url', _('Enter an SSH repository URL.'))
            data['deploy_key'] = self.key_options(data)
        if kind in ('dockerfile', 'compose'):
            text = uploaded_text(self, data, kind)
            if not text.strip():
                self.add_error(kind, _('Enter text or upload a file.'))
            data['source_text'] = text
        return data

    def clean_repo_url(self):
        value = self.cleaned_data['repo_url']
        if not value:
            return value
        parsed = parse.urlsplit(value)
        if (parsed.scheme != 'https' or parsed.username or parsed.password or
                parsed.query or parsed.fragment or not parsed.path.strip('/')):
            raise forms.ValidationError(_('Use a public HTTPS Git URL.'))
        return value

    def handle(self, request, data):
        if data['source_type'] in ('dockerfile', 'compose'):
            kind = data['source_type']
            source = {'type': kind, kind: data['source_text']}
        elif data['source_type'] == 'image':
            source = {'type': 'image', 'image': data['image'],
                      'tag': data['tag']}
        else:
            source = {'type': 'git', 'repo_url': (data['ssh_url']
                      if data['source_type'] == 'private_git' else
                      data['repo_url']),
                      'branch': data['branch'],
                      'build_pack': data['build_pack']}
            if data['base_directory']:
                source['base_directory'] = data['base_directory']
        if data['source_type'] == 'private_git':
            source['deploy_key'] = data['deploy_key']
        probe = (self.probe_values(data)
                 if data['health_check'] != 'none' else {})
        try:
            item = coast.service_create(
                request, data['name'], data['appgroup_id'],
                data['environment_id'], data['server_id'],
                source,
                ports=data['ports'], **probe)
            self.created_item = item
            messages.success(request, _('App creation requested.'))
            return item
        except Exception as exc:
            exceptions.handle(request, _('Coast request failed.'),
                              ignore=True, details='')
            self.port_api_error(exc, _('Unable to create app.'))
            return False


class EditSettings(HealthCheckForm):
    field_order = (
        'name', 'description', 'ports', 'health_check', 'health_check_port',
        'healthcheck_path', 'branch', 'cpu_limit', 'memory_limit_mb')

    help_text = _(
        'Change settings at any time, even during a deployment. Changes '
        'apply on the next redeploy.')

    name = forms.RegexField(
        label=_('Name'), max_length=63,
        regex='^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$')
    cpu_limit = forms.FloatField(
        label=_('CPU limit (cores)'), required=False,
        help_text=_('Leave blank for no limit.'))
    memory_limit_mb = forms.IntegerField(
        label=_('Memory limit (MB)'), min_value=1, required=False,
        help_text=_('Leave blank for no limit.'))
    branch = forms.CharField(label=_('Source branch'), max_length=255)
    ports = forms.CharField(
        label=_('Ports'), max_length=255, required=False,
        help_text=_(
            'Optional. Required only when the health check type is HTTP '
            'or the app has a domain.'))
    description = forms.CharField(
        label=_('Description'), max_length=255, required=False)

    def __init__(self, request, *args, service_id, **kwargs):
        self.service_id = service_id
        super().__init__(request, *args, **kwargs)
        self.fields['ports'].widget.attrs['aria-describedby'] = (
            self['ports'].auto_id + '_help')
        self.fields['ports'].widget.attrs['data-has-domain'] = (
            'true' if self.initial.get('has_domain') else 'false')
        if self.initial.get('source_type') != 'git':
            self.fields.pop('branch')

    def clean_cpu_limit(self):
        value = self.cleaned_data['cpu_limit']
        if value is not None and value <= 0:
            raise forms.ValidationError(
                _('CPU limit must be greater than zero.'))
        return value

    def handle(self, request, data):
        values = {'name': data['name'], 'ports': data['ports'],
                  'cpu_limit': data['cpu_limit'],
                  'memory_limit_mb': data['memory_limit_mb'],
                  'description': data['description'] or None}
        values.update(self.probe_values(data))
        changed = {key: value for key, value in values.items()
                   if (value or '') != (self.initial.get(key) or '')}
        if ('branch' in self.fields and
                data['branch'] != self.initial.get('branch')):
            changed['source'] = {'branch': data['branch']}
        if not changed:
            return True
        if {'health_check_port', 'healthcheck_path'} & changed.keys():
            changed['health_check'] = data['health_check']
        try:
            coast.service_update(request, self.service_id, changed)
            try:
                item = coast.service_get(request, self.service_id)
            except Exception:
                item = True
            messages.success(request, _('Changes saved.'))
            return item
        except Exception as exc:
            exceptions.handle(request, _('Coast request failed.'),
                              ignore=True, details='')
            self.port_api_error(exc, _('Unable to save settings.'))
            return False


# Keep password managers away from Coast settings inputs.
NO_AUTOFILL = {'autocomplete': 'off', 'data-1p-ignore': 'true',
               'data-lpignore': 'true', 'data-bwignore': 'true'}


class SetEnv(forms.SelfHandlingForm):
    help_text = _(
        'Environment variables provide settings to your app. Redeploy '
        'after saving to apply the changes.')

    key = forms.RegexField(
        label=_('Key'),
        max_length=255,
        regex='^[A-Za-z_][A-Za-z0-9_]*$',
        help_text=_(
            'Use letters, numbers and underscores. Start with a letter or '
            'underscore.'),
        widget=forms.TextInput(attrs=NO_AUTOFILL))
    value = forms.CharField(
        label=_('Value'),
        required=False,
        strip=False,
        # Plain text so password managers do not offer to save or fill it.
        # The modal masks it with CSS only while Secret is checked.
        widget=forms.TextInput(attrs=dict(
            NO_AUTOFILL, **{'class': 'form-control coast-env-value'})),
        help_text=_('Blank saves an empty value.'))
    secret = forms.BooleanField(
        label=_('Secret'),
        required=False,
        help_text=_(
            'Mark passwords and tokens as secret to hide their saved values.'))

    build_time = forms.BooleanField(
        label=_('Build-time'), required=False, initial=True,
        help_text=_('Also passed to builds. Turn off for runtime-only.'))

    def __init__(self, request, *args, service_id, app=False, **kwargs):
        self.app = app
        self.service_id = service_id
        super().__init__(request, *args, **kwargs)
        if not app:
            self.fields.pop('build_time')
        self.existing_secret = bool(self.initial.get('key') and
                                    self.initial.get('secret'))
        if self.initial.get('key'):
            if app:
                self.initial.setdefault('build_time', None)
            self.fields['key'].disabled = True
        if self.existing_secret:
            # Secret values are never returned, so blank keeps the value.
            field = self.fields['value']
            field.widget.attrs.update(
                style='-webkit-text-security: disc;',
                placeholder=_('Secret value hidden. Leave blank to keep '
                              'the current value.'))
            field.help_text = _('Leave blank to keep the current value, '
                                'or enter a new one.')

    def clean(self):
        data = super().clean()
        if data.get('value') == dotenv.MASK:
            if not self.initial.get('key'):
                self.add_error('value', _('******** means "unchanged" and '
                                          'cannot be a new value.'))
            elif self.existing_secret and not data.get('secret'):
                self.add_error('value', _('Enter the value to make this '
                                          'variable non-secret.'))
            else:
                data['unchanged'] = True
            return data
        if (self.existing_secret and data.get('value') == '' and
                not data.get('secret')):
            self.add_error('value', _('Enter the value to make this '
                                      'variable non-secret.'))
        return data

    def handle(self, request, data):
        unchanged = data.get('unchanged') or (self.existing_secret and
                                              data['value'] == '')
        item = {} if unchanged else {'value': data['value'],
                                     'secret': data['secret']}
        if self.app and (not self.initial.get('key') or
                         'build_time' in self.changed_data):
            item['build_time'] = data['build_time']
        if not item:
            messages.info(request, _('Value unchanged.'))
            return True
        try:
            redeploy = coast.service_env_update(request, self.service_id, {
                data['key']: item})
            messages.success(request, _('Environment variable saved.'))
            if redeploy:
                messages.info(request, _('Redeploy to apply environment '
                                         'variable changes.'))
            return True
        except Exception as exc:
            exceptions.handle(request, _('Coast request failed.'),
                              ignore=True, details='')
            self.api_error(coast.error_message(
                exc, _('Unable to save environment variable.')))
            return False


class EnvDeveloperView(forms.SelfHandlingForm):
    help_text = _(
        'Edit all environment variables as .env text: one KEY=value per '
        'line. Lines starting with # are comments and quoted values are '
        'supported. Saving replaces the full set: removed lines delete '
        'their variables. Secret values show as ******** and stay '
        'unchanged unless you replace them. Add # secret after a value to '
        'store it as a secret. Combine markers with commas in any order, '
        'for example KEY=value # secret, runtime-only. Redeploy after '
        'saving to apply the changes.')

    dotenv_text = forms.CharField(
        label=_('Variables'),
        required=False,
        strip=False,
        widget=forms.Textarea(attrs=dict(
            NO_AUTOFILL, rows=18, spellcheck='false',
            style='font-family: monospace;')))

    def __init__(self, request, *args, service_id, rows=None, app=False,
                 **kwargs):
        self.app = app
        self.service_id = service_id
        self.rows = rows or []
        super().__init__(request, *args, **kwargs)
        if app:
            self.help_text = str(self.help_text) + str(_(
                ' New keys use build-time by default. Plain lines keep '
                'existing flags. Add # runtime-only to turn build-time off, '
                'or # build-time to turn it on.'))

    def clean(self):
        data = super().clean()
        build_times = {} if self.app else None
        secrets = set()
        values, errors = dotenv.parse(data.get('dotenv_text', ''),
                                      build_times, secrets)
        data['build_times'] = build_times
        data['secrets'] = secrets
        for error in errors:
            self.add_error('dotenv_text', error)
        known = {row['key'] for row in self.rows}
        for key, value in values.items():
            if value == dotenv.MASK and key not in known:
                self.add_error('dotenv_text', _(
                    '%s: ******** means "unchanged" and cannot be a new '
                    'value.') % key)
        data['values'] = values
        return data

    def handle(self, request, data):
        body = dotenv.diff(self.rows, data['values'], data['build_times'],
                           data.get('secrets'))
        if not body:
            messages.info(request, _('No changes to save.'))
            return True
        try:
            redeploy = coast.service_env_update(request, self.service_id,
                                                body)
            messages.success(request, _('Environment variables saved.'))
            if redeploy:
                messages.info(request, _('Redeploy to apply environment '
                                         'variable changes.'))
            return True
        except Exception as exc:
            exceptions.handle(request, _('Coast request failed.'),
                              ignore=True, details='')
            self.api_error(coast.error_message(
                exc, _('Unable to save environment variables.')))
            return False


class AddDomain(dns.ZoneFormMixin, forms.SelfHandlingForm):
    dns_mode = forms.ChoiceField(
        label=_('How do you want to set up this domain?'), initial='zone',
        help_text=_('Choose who will create the DNS records.'),
        choices=(('zone', _('Use a DNS zone in this project')),
                 ('manual', _("Use my own domain (I'll set up DNS)"))),
        widget=forms.Select())
    zone_id = dns.zone_field()
    host = dns.host_field(label=_('Name'), help_text=_(
        'e.g. www or shop.api; leave blank for the zone itself'))
    help_text = _('Add another name for this app.')

    fqdn = forms.RegexField(
        label=_('Domain'),
        max_length=253,
        regex=(r'^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+'
               r'[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$'),
        help_text=_(
            'Use a full domain name, for example app.example.com. Configure '
            'DNS and verify ownership through Coast.'))
    tls = forms.ChoiceField(
        label=_('HTTPS certificate'),
        choices=(
            ('letsencrypt', _("Let's Encrypt")),
            ('none', _('None (HTTP only)'))),
        initial='letsencrypt',
        help_text=_(
            "Let's Encrypt issues a free certificate automatically once "
            "DNS points to the worker. Choose None to serve plain HTTP "
            "on port 80."))

    def __init__(self, request, *args, service_id, known_names=(),
                 existing_names=(), default_domain='', worker_ip='',
                 replace_default=False,
                 **kwargs):
        self.service_id = service_id
        self.worker_ip = worker_ip
        self.replace_default = replace_default
        self.known_names = sorted(set(known_names))
        self.existing_names = sorted({name.lower().rstrip('.')
                                      for name in existing_names})
        super().__init__(request, *args, **kwargs)
        self.has_zone_mode = bool(self.zones)
        self.mode = 'manual'
        if self.has_zone_mode:
            self.mode = (self.data.get(self.add_prefix('dns_mode'))
                         if self.is_bound else
                         self.initial.get('dns_mode', 'zone'))
            self.fields['zone_id'].choices = list(sorted(
                self.zones.items(), key=lambda item: item[1]))
            self.fields['zone_id'].help_text = (
                _('Default app names use %s') % default_domain
                if default_domain else '')
        else:
            for name in ('dns_mode', 'zone_id', 'host'):
                self.fields.pop(name, None)
        self.data = self.data.copy()
        if self.is_bound and self.mode == 'manual':
            key = self.add_prefix('fqdn')
            self.data[key] = self.data.get(key, '').strip().lower().rstrip('.')
        self.fields['fqdn'].help_text = _(
            'e.g. app.example.com. Point an A record for this domain to '
            'your worker IP, then verify it on the Domains tab.')
        for mode, names in (('zone', ('zone_id', 'host')),
                            ('manual', ('fqdn',))):
            for name in names:
                if name not in self.fields:
                    continue
                field = self.fields[name]
                if self.has_zone_mode:
                    field.widget.attrs.update({
                        'data-domain-mode': mode})
                field.required = (self.mode == mode and name != 'host' and
                                  not (name == 'fqdn' and
                                       hasattr(self, 'domain_id')))
                if self.is_bound and self.mode != mode:
                    self.data.pop(self.add_prefix(name), None)

    def clean(self):
        data = super().clean()
        fqdn = data.get('fqdn', '').lower().rstrip('.')
        if fqdn and fqdn in self.existing_names:
            self.add_error('host' if self.mode == 'zone' else 'fqdn',
                           _('This app already uses that name'))
        return data

    def dns_values(self, data):
        if not self.dns_enabled:
            return {}
        if self.mode == 'zone':
            return {'zone_id': data.get('zone_id'), 'auto_dns': True,
                    'host': data.get('host', '')}
        return {'auto_dns': False}

    def handle(self, request, data):
        # The API default is Let's Encrypt. Send tls only for another choice.
        tls = None if data['tls'] == 'letsencrypt' else data['tls']
        try:
            coast.service_domain_create(
                request, self.service_id, data['fqdn'], tls=tls,
                **self.dns_values(data))
            messages.success(request, _(
                'Domain added. See the Domains tab for DNS records and '
                'verification.'))
            return True
        except Exception as exc:
            exceptions.handle(request, _('Coast request failed.'),
                              ignore=True, details='')
            self.api_error(dns.error_message(exc) if self.dns_enabled else
                           coast.error_message(
                               exc, _('Unable to add domain.')))
            return False


class EditDomain(AddDomain):
    def __init__(self, request, *args, service_id, domain_id, **kwargs):
        self.domain_id = domain_id
        initial = kwargs.get('initial') or {}
        mode = initial.get('dns_mode',
                           'zone' if initial.get('zone_id') else 'manual')
        if kwargs.get('data') is not None:
            kwargs['data'] = kwargs['data'].copy()
            kwargs['data']['dns_mode'] = mode
        super().__init__(request, *args, service_id=service_id, **kwargs)
        self.edit_domain = self.initial.get('fqdn', '')
        if 'dns_mode' in self.fields:
            self.fields['dns_mode'].disabled = True
            self.fields['dns_mode'].initial = mode
        self.fields['fqdn'].disabled = True
        self.fields['fqdn'].required = False

    def handle(self, request, data):
        try:
            coast.service_domain_update(
                request, self.service_id, self.domain_id, data['tls'],
                **self.dns_values(data))
            messages.success(request, _('Domain updated.'))
            return True
        except Exception as exc:
            exceptions.handle(request, _('Coast request failed.'),
                              ignore=True, details='')
            self.api_error(dns.error_message(exc) if self.dns_enabled else
                           coast.error_message(
                               exc, _('Unable to update the domain.')))
            return False


MOUNT_PATH_HELP = _('Absolute path inside the container, for example '
                    '/data. The change applies on the next deployment.')


class StorageFormMixin:
    def __init__(self, request, *args, service_id, stack_id, **kwargs):
        self.service_id = service_id
        self.stack_id = stack_id
        super().__init__(request, *args, **kwargs)

    def fail(self, request, exc):
        exceptions.handle(request, _('Coast request failed.'),
                          ignore=True, details='')
        self.api_error(coast.error_message(
            exc, _('Coast request failed.')))
        return False


class CreateStorage(StorageFormMixin, forms.SelfHandlingForm):
    help_text = _('Storage keeps files across deployments.')
    type = forms.ChoiceField(
        label=_('Type'),
        help_text=_('Use a worker folder or a named volume.'),
        choices=(('bind', _('Bind mount (host folder)')),
                 ('volume', _('Named volume'))),
        widget=forms.Select(attrs={'class': 'switchable',
                                   'data-slug': 'storage-type'}))
    host_path = forms.RegexField(
        label=_('Host path'), regex=r'^/[^\x00\r\n]*$', max_length=4096,
        strip=False,
        required=False,
        help_text=_('Absolute path on the worker, for example /srv/data.'))
    name = forms.RegexField(
        label=_('Volume name'), max_length=63, required=False,
        regex=r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$',
        help_text=_('Letters, digits, dot, dash and underscore.'))
    size_gb = forms.IntegerField(label=_('Size (GB)'), min_value=1,
                                 initial=1, required=False,
                                 help_text=_(
                                     'Counts toward the project storage '
                                     'quota.'))
    container_path = forms.RegexField(
        label=_('Container path'), strip=False,
        regex=r'^/(?:[A-Za-z0-9._-]+)(?:/[A-Za-z0-9._-]+)*\Z',
        max_length=255, help_text=MOUNT_PATH_HELP)
    read_only = forms.BooleanField(
        label=_('Read-only'), required=False,
        help_text=_('Prevent the container from writing to this mount.'))

    def __init__(self, request, *args, storage_id=None, **kwargs):
        self.storage_id = storage_id
        super().__init__(request, *args, **kwargs)
        kind = (self.data.get(self.add_prefix('type')) if self.is_bound else
                self.initial.get('type', 'bind'))
        self.data = self.data.copy()
        if storage_id:
            self.help_text = _('Changing the source does not move or rename '
                               'data. Deploy the service to apply changes.')
            self.fields['type'].disabled = True
            self.fields.pop('size_gb')
            kind = self.initial['type']
        for field_type, names in (('bind', ('host_path',)),
                                  ('volume', ('name', 'size_gb'))):
            for name in names:
                if name not in self.fields:
                    continue
                field = self.fields[name]
                field.widget.attrs.update({
                    'class': 'switched', 'data-switch-on': 'storage-type',
                    'data-storage-type-' + field_type: field.label})
                field.required = kind == field_type
                if self.is_bound and kind != field_type:
                    self.data.pop(self.add_prefix(name), None)

    def clean_host_path(self):
        path = self.cleaned_data['host_path']
        if path and (path.startswith('//') or posixpath.normpath(path) != path
                     or any(ord(char) < 32 or ord(char) == 127
                            or char in ':\\' for char in path)
                     or any(part in ('.', '..') for part in path.split('/'))):
            raise forms.ValidationError(_(
                'Use an absolute, normalized worker path without control '
                'characters, colons or backslashes.'))
        return path

    def clean_container_path(self):
        path = self.cleaned_data['container_path']
        if any(part in ('.', '..') for part in path.split('/')):
            raise forms.ValidationError(_(
                'Container paths cannot contain dot or parent segments.'))
        return path

    def handle(self, request, data):
        values = {key: data[key] for key in
                  ('type', 'container_path', 'read_only')}
        if data['type'] == 'bind':
            values['host_path'] = data['host_path']
        else:
            values['name'] = data['name']
            if not self.storage_id:
                values['size_gb'] = data['size_gb']
        try:
            if self.storage_id:
                values.pop('type')
                coast.storage_update(request, self.stack_id,
                                     self.storage_id, values)
            else:
                values['service_id'] = self.service_id
                coast.storage_create(request, self.stack_id, values)
        except Exception as exc:
            return self.fail(request, exc)
        messages.success(request, _('Storage saved.'))
        return True


class ComposeForm(forms.SelfHandlingForm):
    yaml = forms.CharField(
        label=_('Compose YAML'), strip=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control', 'rows': 24,
            'style': 'font-family:monospace;', 'spellcheck': 'false',
            'autocomplete': 'off', 'aria-describedby': 'compose-help'}))
    operation = forms.ChoiceField(choices=(
        ('save', _('Save')), ('redeploy', _('Save and redeploy'))))

    def handle(self, request, data):
        service_id = self.initial['service_id']
        try:
            coast.service_compose_update(request, service_id, data['yaml'])
        except Exception as exc:
            self.add_error('yaml', coast.error_message(
                exc, _('Unable to save Compose YAML.')))
            return False
        if data['operation'] == 'redeploy':
            try:
                coast.service_deploy(request, service_id)
            except Exception as exc:
                self.add_error(None, _('Compose YAML was saved. %s') %
                               coast.error_message(
                                   exc, _('Unable to redeploy.')))
                return False
        return True


class ChangeImage(forms.SelfHandlingForm):
    help_text = _(
        'The service keeps its settings, variables, storage and domains. '
        'Save applies the image on the next redeploy. '
        'Save and redeploy applies it now.')
    image = forms.CharField(
        label=_('Image'), max_length=255,
        help_text=_('Enter the image repository, for example nginx. '
                    'Do not include a tag or digest.'))
    tag = forms.CharField(
        label=_('Tag'), max_length=128,
        help_text=_('Enter the image tag, for example stable.'))
    operation = forms.ChoiceField(
        choices=(('save', _('Save')), ('redeploy', _('Save and redeploy'))),
        widget=forms.HiddenInput)

    def handle(self, request, data):
        service_id = self.initial['service_id']
        try:
            coast.service_image_update(request, service_id,
                                       data['image'], data['tag'])
        except Exception as exc:
            self.add_error(None, coast.error_message(
                exc, _('Unable to save image.')))
            return False
        if data['operation'] == 'redeploy':
            try:
                coast.service_deploy(request, service_id)
            except Exception as exc:
                self.add_error(None, _('Image was saved. %s') %
                               coast.error_message(
                                   exc, _('Unable to redeploy.')))
                return False
            messages.success(request,
                             _('Image saved. Redeployment requested.'))
        else:
            messages.success(request, _('Image saved. Redeploy to apply it.'))
        return True


class ReplaceDeployKey(DeployKeyFields):
    def __init__(self, request, *args, service_id, **kwargs):
        self.service_id = service_id
        super().__init__(request, *args, **kwargs)

    def clean(self):
        data = super().clean()
        data['deploy_key'] = self.key_options(data)
        return data

    def handle(self, request, data):
        try:
            coast.service_update(
                request, self.service_id,
                {'source': {'deploy_key': data['deploy_key']}})
            messages.success(request, _('Deploy key replacement requested.'))
            return True
        except Exception as exc:
            self.api_error(coast.error_message(
                exc, _('Unable to replace deploy key.')))
            return False


class EditDockerfile(forms.SelfHandlingForm):
    text = forms.CharField(label=_('Dockerfile'), strip=False,
                           widget=forms.Textarea)

    def __init__(self, request, *args, service_id, **kwargs):
        self.service_id = service_id
        super().__init__(request, *args, **kwargs)

    def handle(self, request, data):
        try:
            coast.service_dockerfile_update(request, self.service_id,
                                            data['text'])
            messages.success(request, _('Dockerfile saved. Deploy to apply '
                                        'the changes.'))
            return True
        except Exception as exc:
            self.api_error(coast.error_message(
                exc, _('Unable to save Dockerfile.')))
            return False
