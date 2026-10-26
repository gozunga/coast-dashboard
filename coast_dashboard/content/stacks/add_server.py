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

from types import SimpleNamespace

from django.conf import settings
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from horizon import forms
from horizon import messages
from horizon import tables
from openstack_dashboard.api import cinder
from openstack_dashboard.api import nova

from coast_dashboard.api import coast
from coast_dashboard.content import common
from coast_dashboard.content.stacks import activity
from coast_dashboard.content.stacks.forms import flavor_choices


class AddServerAction(tables.LinkAction):
    name = 'add_server'
    verbose_name = _('Add server')
    classes = ('ajax-modal',)
    icon = 'plus'
    policy_rules = ()

    def get_link_url(self, datum=None):
        return reverse('horizon:project:coast.stacks:add_server',
                       args=[self.table.kwargs['item']['id']])

    def allowed(self, request, datum=None):
        stack = self.table.kwargs.get('item', {})
        return (stack.get('status') == 'ACTIVE' and
                stack.get('task_state') in (None, '', 'NONE') and
                not any(common.status(server) in common.TRANSITIONAL
                        for server in self.table.data or []))


class AddServer(forms.SelfHandlingForm):
    help_text = _('Add a worker to run apps, or a build server to compile '
                  'them. The new server can use a different flavor from '
                  'the rest of the stack.')

    role = forms.ChoiceField(label=_('Role'), choices=[
        ('worker', _('Worker')), ('build', _('Build server'))],
        widget=forms.ThemableSelectWidget(attrs={
            'class': 'switchable', 'data-slug': 'server-role'}))
    plan = forms.ChoiceField(
        label=_('Flavor'), required=False,
        widget=forms.ThemableSelectWidget(attrs={
            'class': 'switched', 'data-switch-on': 'server-role',
            'data-server-role-worker': _('Flavor')}))
    build_plan = forms.ChoiceField(
        label=_('Flavor'), required=False,
        widget=forms.ThemableSelectWidget(attrs={
            'class': 'switched', 'data-switch-on': 'server-role',
            'data-server-role-build': _('Flavor')}))
    name = forms.CharField(label=_('Name'), required=False, max_length=255)

    def __init__(self, request, *args, stack_id, **kwargs):
        self.stack_id = stack_id
        super().__init__(request, *args, **kwargs)
        self.catalog_error = None
        try:
            catalog = coast.flavor_list(request)
        except Exception:
            catalog = []
            self.catalog_error = _(
                'Unable to retrieve flavors. Please try again.')
        flavors, choices = flavor_choices(request, [
            SimpleNamespace(**entry) for entry in catalog])
        self.flavors = {f.plan: f for f in flavors}
        labels = dict(choices)
        for field, role in (('plan', 'worker'), ('build_plan', 'build')):
            self.fields[field].choices = [
                (f.plan, labels[f.name]) for f in flavors if role in f.roles]
        if self.is_bound:
            self.data = self.data.copy()
            hidden = ('plan' if self.data.get('role') == 'build'
                      else 'build_plan')
            self.data.pop(self.add_prefix(hidden), None)

    def non_field_errors(self):
        # Unbound forms do not run clean(), but catalog errors must still
        # appear inline when the modal first opens.
        if not self.is_bound and self.catalog_error:
            return self.error_class(
                [self.catalog_error], error_class='nonfield')
        return super().non_field_errors()

    def clean(self):
        data = super().clean()
        if self.catalog_error:
            raise forms.ValidationError(self.catalog_error)
        role = data.get('role')
        field = 'build_plan' if role == 'build' else 'plan'
        plan = data.get(field)
        if not role:
            return data
        if not plan:
            self.add_error(field, _('Choose a flavor.'))
            return data
        if role not in self.flavors[plan].roles:
            self.add_error(field, _(
                'This flavor is unavailable for this role.'))
            return data
        try:
            stack = coast.stack_get(self.request, self.stack_id)
            if (stack.get('status') != 'ACTIVE' or
                    stack.get('task_state') not in (None, '', 'NONE')):
                raise forms.ValidationError(_('The stack is busy. Try again '
                                              'when it is ACTIVE.'))
            flavor = self.flavors[plan]
            limits = nova.tenant_absolute_limits(self.request, reserved=True)
            storage = cinder.tenant_absolute_limits(self.request)
        except forms.ValidationError:
            raise
        except Exception:
            raise forms.ValidationError(_('Unable to check project quota. '
                                          'Please try again.'))
        # ServerAdd creates a data and Docker volume (100 + 20 GB by
        # default). Operators can match their Coast volume size overrides.
        checks = [(limits, 'maxTotalInstances', 'totalInstancesUsed', 1),
                  (limits, 'maxTotalCores', 'totalCoresUsed', flavor.vcpus),
                  (limits, 'maxTotalRAMSize', 'totalRAMUsed', flavor.ram),
                  (storage, 'maxTotalVolumes', 'totalVolumesUsed', 2),
                  (storage, 'maxTotalVolumeGigabytes',
                   'totalGigabytesUsed', getattr(
                       settings, 'COAST_SERVER_VOLUME_GB', 120))]
        for quota, maximum, used, needed in checks:
            limit = quota.get(maximum, -1)
            if limit >= 0 and quota.get(used, 0) + needed > limit:
                raise forms.ValidationError(_(
                    'The selected flavor exceeds your project quota '
                    '(cores, RAM, instances, or volume storage). '
                    'Choose a smaller flavor or request more quota.'))
        data['plan'] = plan
        return data

    def handle(self, request, data):
        try:
            item = coast.stack_server_create(
                request, self.stack_id, data['role'], data['plan'],
                data.get('name'))
            messages.success(request, _('Server creation requested.'))
            return item
        except Exception as exc:
            self.api_error(activity.scrub(coast.error_message(
                exc, _('Unable to add server.'))))
            return False
