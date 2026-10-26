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
from openstack_dashboard.api import nova

from coast_dashboard.api import coast
from coast_dashboard.content import dns


def flavor_choices(request, catalog=None):
    try:
        catalog = nova.flavor_list(request) if catalog is None else catalog
        flavors = sorted(catalog,
                         key=lambda flavor: (flavor.ram, flavor.name))
        choices = []
        for flavor in flavors:
            if flavor.ram < 1024:
                ram = _('%s MB') % flavor.ram
            else:
                gb = flavor.ram / 1024
                amount = int(gb) if gb.is_integer() else '%.1f' % gb
                ram = _('%s GB') % amount
            label = _('%(name)s (%(cpus)s vCPU, %(ram)s RAM, '
                      '%(disk)s GB disk)') % {
                          'name': flavor.name, 'cpus': flavor.vcpus,
                          'ram': ram, 'disk': flavor.disk}
            choices.append((flavor.name, label))
    except Exception:
        exceptions.handle(request, _('Unable to retrieve flavors.'),
                          details='')
        choices = []
    return flavors if choices else [], choices


def flavor_plans(request, flavors):
    usable = {'control': {}, 'worker': {}, 'build': {}}
    try:
        plans = coast.plan_list(request)
    except Exception:
        exceptions.handle(request, _('Unable to retrieve Coast plans.'),
                          details='')
        return usable
    for plan in plans:
        if plan.get('kind') != 'vm':
            continue
        for flavor in flavors:
            if plan.get('flavor') not in (flavor.name, flavor.id):
                continue
            for role in plan.get('roles', []):
                if role in usable:
                    usable[role].setdefault(flavor.name, []).append(
                        plan['name'])
    return usable


class CreateStack(forms.SelfHandlingForm):
    help_text = _(
        'A stack contains an app engine server, an optional build server, '
        'and workers on a private network. Create app groups and environments '
        'here, then deploy apps and services on the workers.')

    name = forms.CharField(label=_('Name'), max_length=255,
                           help_text=_('Choose a name for this stack.'))
    plan = forms.ChoiceField(
        label=_('App engine server flavor'),
        help_text=_('Runs the app engine that builds and runs your apps.'))
    worker_plan = forms.ChoiceField(
        label=_('Worker flavor'),
        help_text=_('Choose the flavor of each server that runs your apps.'))
    worker_count = forms.IntegerField(
        label=_('Worker count'), min_value=1, initial=1,
        help_text=_('Choose how many worker servers to create. '
                    'Each worker uses the selected worker flavor.'))
    build_server = forms.BooleanField(
        label=_('Add a build server'), required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'switchable', 'data-slug': 'build-server',
            'data-hide-on-checked': 'false'}),
        help_text=_('A build server compiles apps from Git so builds '
                    "don't slow your workers."))
    build_server_plan = forms.ChoiceField(
        label=_('Build server flavor'), required=False,
        widget=forms.ThemableSelectWidget(attrs={
            'class': 'switched', 'data-switch-on': 'build-server'}),
        help_text=_('Choose a flavor if you add a build server. Leave blank '
                    'to use the default build server flavor.'))

    def __init__(self, request, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        # Ignore a stale selection when the optional build server is disabled.
        build_enabled = self.fields['build_server'].widget.value_from_datadict(
            self.data, self.files, self.add_prefix('build_server'))
        if self.is_bound and not build_enabled:
            self.data = self.data.copy()
            self.data.pop(self.add_prefix('build_server_plan'), None)
        flavors, choices = flavor_choices(request)
        usable = self._usable_flavors(request, flavors if choices else [])
        for field, role in (('plan', 'control'), ('worker_plan', 'worker'),
                            ('build_server_plan', 'build')):
            # Only flavors with a Coast plan for the role (Q150, James).
            allowed = [choice for choice in choices
                       if choice[0] in usable[role]]
            self.fields[field].choices = allowed
            if allowed:
                self.fields[field].initial = allowed[0][0]
        if self.fields['build_server_plan'].choices:
            self.fields['build_server_plan'].choices = [
                ('', _('Use default build server flavor'))] + list(
                    self.fields['build_server_plan'].choices)

    @staticmethod
    def _usable_flavors(request, flavors):
        plans = flavor_plans(request, flavors)
        return {role: set(mapping) for role, mapping in plans.items()}

    def clean(self):
        data = super().clean()
        if not data.get('build_server') or not data.get('build_server_plan'):
            data.pop('build_server_plan', None)
        return data

    def handle(self, request, data):
        try:
            item = coast.stack_create(request, **data)
            messages.success(request, _('Stack creation requested.'))
            return item
        except Exception as exc:
            exceptions.handle(request, _('Coast request failed.'),
                              ignore=True, details='')
            self.api_error(coast.error_message(
                exc, _('Unable to create stack.')))
            return False


class DNSSettings(dns.ZoneFormMixin, forms.SelfHandlingForm):
    zone_id = dns.zone_field(_('Default domain zone'))
    host = dns.host_field(help_text=_(
        'Optional. A name inside the selected zone used as the default '
        'domain for new apps. For example, apps gives apps.<zone>. Leave '
        'blank to use the zone itself. Each new app gets its own hostname '
        'under this domain, and Coast creates its DNS records in the zone.'))
    help_text = _('New apps get hostnames under <host>.<zone>. Coast '
                  'creates records in the selected zone. Choose "Manual DNS '
                  '/ no zone" to use sslip.io.')
    dns_preview = True

    def __init__(self, request, *args, stack_id, **kwargs):
        self.stack_id = stack_id
        super().__init__(request, *args, **kwargs)
        # The API stores the full default domain; edit only the host part.
        zone = self.zones.get(self.initial.get('zone_id'))
        host = (self.initial.get('host') or '').lower().rstrip('.')
        if zone and 'host' in self.fields:
            if host == zone:
                self.initial['host'] = ''
            elif host.endswith('.' + zone):
                self.initial['host'] = host[:-len(zone) - 1]

    @property
    def dns_preview_value(self):
        zone = self.zones.get(self.initial.get('zone_id'))
        host = self.initial.get('host')
        return '%s.%s' % (host, zone) if zone and host else zone or ''

    def handle(self, request, data):
        if not self.dns_enabled:
            self.api_error(_('Default domain settings are unavailable.'))
            return False
        try:
            coast.stack_dns_update(request, self.stack_id,
                                   data.get('fqdn'), data.get('zone_id'))
            messages.success(request, _('Default domain updated.'))
            return True
        except Exception as exc:
            self.api_error(dns.error_message(exc))
            return False


class AddIngressRule(forms.SelfHandlingForm):
    help_text = _(
        'Allow inbound traffic to your workers from a source network. '
        'For one port, enter it as First port and leave Last port blank. '
        'ICMP takes no ports. HTTP (80), HTTPS (443) and SSH are managed '
        'for you.')
    protocol = forms.ChoiceField(label=_('Protocol'), choices=[
        ('tcp', 'TCP'), ('udp', 'UDP'), ('icmp', 'ICMP')])
    port_range_min = forms.IntegerField(label=_('First port'), required=False,
                                        min_value=1, max_value=65535)
    port_range_max = forms.IntegerField(
        label=_('Last port'), required=False, min_value=1, max_value=65535,
        help_text=_('Optional. Leave blank to allow only the first port.'))
    source = forms.IPField(
        label=_('Source (IPv4 CIDR)'), initial='0.0.0.0/0',
        version=forms.IPv4, mask=True,
        help_text=_('IPv4 only, for example 203.0.113.0/24, or 0.0.0.0/0 '
                    'for anywhere.'))
    description = forms.CharField(label=_('Description'), required=False,
                                  max_length=255)

    def __init__(self, request, *args, stack_id, **kwargs):
        self.stack_id = stack_id
        super().__init__(request, *args, **kwargs)

    def clean(self):
        data = super().clean()
        low, high = data.get('port_range_min'), data.get('port_range_max')
        if data.get('protocol') == 'icmp':
            if low is not None or high is not None:
                raise forms.ValidationError(_('ICMP does not take ports.'))
            data.pop('port_range_min', None)
            data.pop('port_range_max', None)
        else:
            if low is not None and high is None:
                # One port: a blank Last port means the First port only.
                high = data['port_range_max'] = low
            if low is None or low > high:
                raise forms.ValidationError(
                    _('Enter a valid first and last port.'))
        return data

    def handle(self, request, data):
        if not coast.ingress_supported(request):
            self.api_error(_('Firewall rules are unavailable.'))
            return False
        try:
            rule = coast.stack_ingress_rule_create(
                request, self.stack_id, data)
            messages.success(request, _('Firewall rule added.'))
            return rule
        except Exception as exc:
            self.api_error(coast.error_message(
                exc, _('Unable to add firewall rule.')))
            return False
