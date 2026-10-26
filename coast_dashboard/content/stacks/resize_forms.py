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

"""Larger-only server resize form."""
from django.utils.translation import gettext_lazy as _
from horizon import forms
from horizon import messages

from coast_dashboard.api import coast
from coast_dashboard.content.stacks import activity
from coast_dashboard.content.stacks.resize_actions import eligible


DIMENSIONS = ('vcpus', 'ram', 'disk')


def larger(current, candidate):
    try:
        old = [float(current[key]) for key in DIMENSIONS]
        new = [float(candidate[key]) for key in DIMENSIONS]
        return all(b >= a for a, b in zip(old, new)) and any(
            b > a for a, b in zip(old, new))
    except (KeyError, TypeError, ValueError):
        return False


def flavor_label(flavor):
    if not flavor or any(key not in flavor for key in DIMENSIONS):
        return _('Current flavor details are unavailable.')
    return _('%(name)s: %(vcpus)s vCPU, %(ram)s MiB RAM, '
             '%(disk)s GiB disk') % flavor


class ResizeServer(forms.SelfHandlingForm):
    current_flavor = forms.CharField(label=_('Current flavor'),
                                     required=False, disabled=True)
    flavor = forms.ChoiceField(label=_('Larger flavor'))
    help_text = _('The server is replaced with its data kept; apps may be '
                  'briefly unavailable, and shrinking is not supported '
                  '(add a smaller worker instead).')

    def __init__(self, request, *args, stack_id, server_id, **kwargs):
        super().__init__(request, *args, **kwargs)
        # Retrieval errors can be added before an unbound form is validated.
        self.cleaned_data = {}
        self.stack_id, self.server_id = stack_id, server_id
        self.available = False
        self.fields['flavor'].choices = []
        try:
            stack = coast.stack_get(request, stack_id)
            server = coast.stack_server_get(request, stack_id, server_id)
            current = server.get('flavor') or {}
            self.fields['current_flavor'].initial = flavor_label(current)
            if not eligible(stack, server):
                self.api_error(_('Only idle, ACTIVE VM servers on an idle, '
                                 'ACTIVE stack can be resized.'))
                return
            role = server['role']
            if role == 'controller':
                role = 'control'
            choices = [(f['plan'], flavor_label(f))
                       for f in coast.flavor_list(request)
                       if role in f.get('roles', []) and f.get('plan') and
                       larger(current, f)]
            self.fields['flavor'].choices = choices
            self.available = bool(choices)
            if not choices:
                self.fields['flavor'].help_text = _(
                    'No larger flavors are available for this server.')
                self.fields['flavor'].disabled = True
        except Exception as exc:
            self.api_error(activity.scrub(coast.error_message(
                exc, _('Unable to retrieve resize options.'))))

    def handle(self, request, data):
        if not self.available:
            return False
        try:
            coast.stack_server_resize(request, self.stack_id,
                                      self.server_id, data['flavor'])
            messages.success(request, _('Server resize scheduled.'))
            return True
        except Exception as exc:
            self.api_error(activity.scrub(coast.error_message(
                exc, _('Unable to resize server.'))))
            return False
