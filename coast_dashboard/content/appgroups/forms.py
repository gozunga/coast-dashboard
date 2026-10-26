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

from django.utils.translation import gettext_lazy as _
from horizon import exceptions
from horizon import forms
from horizon import messages

from coast_dashboard.api import coast


class CreateAppgroup(forms.SelfHandlingForm):
    help_text = _(
        'An app group is a project for related apps and services. '
        'Choose the stack whose workers will run them.')

    stack_id = forms.ChoiceField(
        label=_('Stack'),
        help_text=_(
            'Choose the stack that will host this app group.'))
    name = forms.CharField(
        label=_('Name'),
        max_length=255,
        help_text=_(
            'Choose a name for this app group.'))

    def __init__(self, request, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        try:
            self.fields['stack_id'].choices = [
                (item['id'], item['name'])
                for item in coast.stack_list(request)
                if item['status'] == 'ACTIVE']
        except Exception:
            exceptions.handle(request, _('Unable to retrieve stacks.'))

    def handle(self, request, data):
        try:
            item = coast.appgroup_create(request, **data)
            messages.success(request, _('App Group creation requested.'))
            return item
        except Exception as exc:
            exceptions.handle(request, _('Coast request failed.'),
                              ignore=True, details='')
            self.api_error(coast.error_message(
                exc, _('Unable to create app group.')))
            return False
