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

from django.utils.translation import gettext_lazy as _
from horizon import exceptions
from horizon import forms
from horizon import messages

from coast_dashboard.api import coast
from coast_dashboard.content.services.forms import HealthCheckForm
from coast_dashboard.content.services.forms import ServicePlacementForm


PLACEMENT_SESSION_KEY = 'coast_oneclick_placement'
PLACEMENT_FIELDS = ('appgroup_id', 'environment_id', 'server_id')


def template_name(name):
    return re.sub('[^a-z0-9]+', '-', name.lower()).strip('-')[:63].rstrip(
        '-') or 'service'


def available_name(base, names):
    candidate = base
    number = 2
    while candidate in names:
        suffix = '-%s' % number
        candidate = base[:63 - len(suffix)].rstrip('-') + suffix
        number += 1
    return candidate


class CreateOneClick(HealthCheckForm, ServicePlacementForm):
    help_text = _(
        'Deploy a one-click template such as Postgres. '
        'Choose an environment and a worker in the app group stack.')

    template_id = forms.ChoiceField(
        label=_('Template'),
        help_text=_(
            'Choose a template available in the app group stack.'))
    field_order = ('name', 'template_id', 'appgroup_id', 'environment_id',
                   'server_id', 'health_check', 'health_check_port',
                   'healthcheck_path')

    def __init__(self, request, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.templates = {}
        choices = {}
        self.template_ports = {}
        self.template_http_ports = {}
        try:
            for stack_id in sorted({a['stack_id']
                                    for a in self.appgroups.values()}):
                items = coast.template_list(request, stack_id)
                self.template_ports.update(
                    (t['id'], t.get('ports')) for t in items)
                self.template_http_ports.update(
                    (t['id'], t.get('http_port')) for t in items)
                self.templates[stack_id] = {t['id'] for t in items}
                choices.update((t['id'], t['name']) for t in items)
            self.fields['template_id'].choices = sorted(
                choices.items(), key=lambda item: item[1])
            self.fields['template_id'].choices = [
                ('', _('Select a template'))] + list(
                    self.fields['template_id'].choices)
        except Exception:
            exceptions.handle(request, _('Unable to retrieve templates.'),
                              details='')
        self.set_defaults(request, choices)
        self.fields['health_check'].required = False
        if self.is_bound and not self.has_health_check(
                self.data.get(self.add_prefix('template_id'))):
            for name in ('health_check', 'health_check_port',
                         'healthcheck_path'):
                self.fields[name].disabled = True

    def has_health_check(self, template):
        return (self.template_http_ports.get(template) is not None or
                bool(self.template_ports.get(template)))

    def set_defaults(self, request, choices, selector="template_id",
                     listing=None):
        preferred = request.session.get(PLACEMENT_SESSION_KEY, {})
        project_id = getattr(request.user, 'project_id', None)
        if preferred.get('project_id') != project_id:
            preferred = {}

        def select(field, options, single_only=False):
            selected = self.initial.get(field) or ''
            if self.fields[field].disabled:
                return selected
            if selected not in options:
                if len(options) == 1:
                    selected = options[0]
                elif single_only:
                    selected = ''
                else:
                    selected = preferred.get(field) or ''
                    if selected not in options:
                        selected = next(iter(options), '')
            self.initial[field] = selected
            return selected

        for field, label in (
                ('appgroup_id', _('Select an app group')),
                ('environment_id', _('Select an environment')),
                ('server_id', _('Select a worker'))):
            self.fields[field].choices = [('', label)] + [
                item for item in self.fields[field].choices if item[0]]

        template = self.initial.get(selector, '')
        if template not in choices:
            template = ''
        self.initial[selector] = template
        if not self.is_bound:
            port = self.template_http_ports.get(template)
            self.initial.update(
                health_check='http' if port is not None else 'none',
                health_check_port=port if port is not None else '',
                healthcheck_path='/' if port is not None else '')
        groups = [key for key, _label in self.fields['appgroup_id'].choices
                  if key and (not template or template in self.templates.get(
                      self.appgroups[key]['stack_id'], set()))]
        group = select('appgroup_id', groups, single_only=True)
        select('environment_id', [
            key for key, _label in self.fields['environment_id'].choices
            if key and self.environments[key]['appgroup_id'] == group],
            single_only=True)
        stack = self.appgroups.get(group, {}).get('stack_id')
        select('server_id', [
            key for key, _label in self.fields['server_id'].choices
            if key and self.servers[key]['stack_id'] == stack],
            single_only=True)
        names = []
        try:
            for item in (listing or coast.service_list)(request):
                names.append({'name': item['name'],
                              'appgroup_id': item.get('appgroup_id')})
        except Exception as exc:
            exceptions.handle(request, coast.error_message(
                exc, _('Unable to retrieve existing service names.')))
        bases = {key: template_name(name) for key, name in choices.items()}
        used = [item['name'] for item in names
                if not group or item['appgroup_id'] == group]
        self.initial.setdefault('name', available_name(
            bases[template], used) if template else '')
        self.fields['name'].widget.attrs['data-user-edited'] = (
            'true' if self.is_bound else 'false')
        self.defaults = {
            'selector': selector,
            'templates': {stack: sorted(ids)
                          for stack, ids in self.templates.items()},
            'bases': bases, 'names': names, 'preferred': preferred,
            'groups': {key: self.appgroups[key]['stack_id']
                       for key, _label in self.fields['appgroup_id'].choices
                       if key},
            'environments': {
                key: self.environments[key]['appgroup_id']
                for key, _label in self.fields['environment_id'].choices
                if key},
            'workers': {key: self.servers[key]['stack_id']
                        for key, _label in self.fields['server_id'].choices
                        if key},
            'bound': self.is_bound,
            'ports': {key: self.has_health_check(key) for key in choices},
            'http_ports': self.template_http_ports}

    def clean(self):
        data = super().clean()
        if self.has_health_check(data.get('template_id')):
            data['health_check'] = data.get('health_check') or 'none'
        else:
            for name in ('health_check', 'health_check_port',
                         'healthcheck_path'):
                data.pop(name, None)
        app = self.appgroups.get(data.get('appgroup_id'))
        template_id = data.get('template_id')
        if app and template_id and template_id not in self.templates.get(
                app['stack_id'], set()):
            self.add_error('template_id',
                           _('Select a template in the app group stack.'))
        return data

    def handle(self, request, data):
        try:
            values = {key: data[key] for key in
                      ('name', 'template_id') + PLACEMENT_FIELDS}
            if data.get('health_check', 'none') != 'none':
                values.update(self.probe_values(data))
            item = coast.oneclick_create(request, **values)
            self.created_item = item
            request.session[PLACEMENT_SESSION_KEY] = {
                'project_id': getattr(request.user, 'project_id', None),
                **{key: data[key] for key in PLACEMENT_FIELDS}}
            messages.success(request, _('Service creation requested.'))
            return item
        except Exception as exc:
            exceptions.handle(request, _('Coast request failed.'),
                              ignore=True, details='')
            self.api_error(coast.error_message(
                exc, _('Unable to create service.')))
            return False
