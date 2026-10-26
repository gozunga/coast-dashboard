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

import ipaddress

from django.utils.translation import gettext_lazy as _
from horizon import exceptions
from horizon import forms

from coast_dashboard.api import coast
from coast_dashboard.content import common
from coast_dashboard.content.oneclick.forms import CreateOneClick
from coast_dashboard.content.services.forms import ServicePlacementForm


class CreateDatabase(ServicePlacementForm):
    engine = forms.CharField(widget=forms.HiddenInput)
    version = forms.ChoiceField(label=_('Version'))
    database = forms.CharField(
        label=_('Initial database'), initial='app', help_text=_(
            'The database created inside the engine for your app to use. '
            'Defaults to app.'))
    username = forms.CharField(
        label=_('Username'), initial='app',
        help_text=_('Database user for your app. Defaults to app.'))
    cpu_limit = forms.FloatField(label=_('CPU limit'), required=False,
                                 min_value=0.01)
    memory_limit_mb = forms.IntegerField(label=_('Memory limit (MB)'),
                                         required=False, min_value=1)
    field_order = ('name', 'appgroup_id', 'environment_id', 'server_id',
                   'engine', 'version', 'database', 'username',
                   'cpu_limit', 'memory_limit_mb')

    def __init__(self, request, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.fields['name'].help_text = _(
            'The name shown in Coast. You type it to confirm a delete.')
        self.fields['appgroup_id'].label = _('App group')
        for field in ('appgroup_id', 'environment_id', 'server_id'):
            choices = list(self.fields[field].choices)
            if len(choices) == 1 and field not in self.initial:
                self.initial[field] = choices[0][0]
        engines = coast.database_engine_list(request)
        selected = (self.data.get('engine') if self.is_bound else
                    self.initial.get('engine'))
        self.catalog_engine = next((e for e in engines
                                    if e['engine'] == selected), {})
        self.fields['engine'] = forms.ChoiceField(
            choices=[(e['engine'], e['display_name']) for e in engines],
            widget=forms.HiddenInput)
        self.fields['version'].choices = [
            (v, v) for v in self.catalog_engine.get('versions', [])]
        self.initial['version'] = self.catalog_engine.get('default_version')
        self.templates = {a['stack_id']: {e['engine'] for e in engines}
                          for a in self.appgroups.values()}
        self.template_http_ports = {}
        self.template_ports = {}
        CreateOneClick.set_defaults(
            self, request, {e['engine']: e['display_name'] for e in engines},
            selector='engine', listing=coast.database_list)

        for field in ('database', 'username'):
            if not self.catalog_engine.get('has_' + field):
                del self.fields[field]

    has_health_check = CreateOneClick.has_health_check

    def handle(self, request, data):
        if not common.project_member(request):
            self.api_error(_('Permission denied.'))
            return False
        try:
            return coast.database_create(request, **data)
        except Exception as exc:
            exceptions.handle(request, _('Coast request failed.'),
                              ignore=True, details='')
            self.api_error(coast.error_message(
                exc, _('Unable to create database.')))
            return False


class DeleteDatabase(forms.SelfHandlingForm):
    confirmation = forms.CharField(
        label=_('Coast name'), strip=False)

    def __init__(self, request, *args, **kwargs):
        self.item = kwargs.pop('item')
        super().__init__(request, *args, **kwargs)

    def clean_confirmation(self):
        value = self.cleaned_data['confirmation']
        if value != self.item['name']:
            raise forms.ValidationError(
                _('Type %(name)s to confirm deletion.'),
                params={'name': self.item['name']})
        return value

    def handle(self, request, data):
        if not common.project_member(request):
            return False
        try:
            coast.database_delete(request, self.item['id'])
            return True
        except Exception:
            self.api_error(_('Unable to delete database.'))
            return False


class EditLimits(forms.SelfHandlingForm):
    help_text = _('Changed limits take effect after a restart.')
    cpu_limit = forms.FloatField(label=_('CPU limit'), required=False,
                                 min_value=0.01)
    memory_limit_mb = forms.IntegerField(label=_('Memory limit (MB)'),
                                         required=False, min_value=1)

    def __init__(self, request, *args, **kwargs):
        self.item = kwargs.pop('item')
        super().__init__(request, *args, **kwargs)

    def values(self, data):
        return data

    def handle(self, request, data):
        if not common.project_member(request):
            self.api_error(_('Permission denied.'))
            return False
        try:
            coast.database_update(request, self.item['id'],
                                  **self.values(data))
            return True
        except Exception as exc:
            self.api_error(coast.error_message(
                exc, _('Unable to update database.')))
            return False


class PublicAccess(EditLimits):
    help_text = _(
        'Public access changes restart the database. Allow only the stack '
        'subnet for connections from other workers in this stack. IPv4 only.')
    enabled = forms.BooleanField(label=_('Public access'), required=False)
    port = forms.IntegerField(label=_('Port'), required=False,
                              min_value=1024, max_value=65535,
                              help_text=_(
                                  'Leave blank to choose a free port.'))
    allow_from = forms.ChoiceField(label=_('Allow from'), choices=(
        ('anywhere', _('Anywhere (0.0.0.0/0)')),
        ('stack', _('Only servers in this stack')),
        ('specific', _('Specific IPv4 range'))),
        help_text=_('IPv4 only. Anywhere allows connections from the entire '
                    'internet. Choose a restricted range when possible.'))
    source = forms.CharField(label=_('Specific IPv4 range'), required=False,
                             help_text=_(
                                 'IPv4 CIDR, for example 192.0.2.0/24.'))

    def __init__(self, request, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        for field in ('cpu_limit', 'memory_limit_mb'):
            del self.fields[field]
        self.stack_source = None
        try:
            from openstack_dashboard.api import neutron
            stack = coast.stack_get(request, self.item['stack_id'])
            subnets = neutron.subnet_list(
                request, network_id=stack['network_id'], ip_version=4)
            if len(subnets) == 1:
                self.stack_source = subnets[0].cidr
        except Exception:
            pass
        self.fields['source'].widget.attrs['data-stack-source'] = (
            self.stack_source or '')

    def clean(self):
        data = super().clean()
        source = data.get('source', '')
        if data.get('allow_from') == 'anywhere':
            source = '0.0.0.0/0'
        elif data.get('allow_from') == 'stack':
            source = self.stack_source
        try:
            source = str(ipaddress.IPv4Network(source, strict=False))
        except (ValueError, TypeError):
            if data.get('enabled'):
                self.add_error('source', _(
                    'Enter a valid IPv4 range. If the stack subnet is '
                    'unavailable, choose Specific IPv4 range.'))
            else:
                source = '0.0.0.0/0'
        data['source'] = source
        return data

    def values(self, data):
        if not data['enabled']:
            return {'public': {'enabled': False}}
        return {'public': {'enabled': data['enabled'], 'port': data['port'],
                           'source': data['source'] or '0.0.0.0/0'}}
