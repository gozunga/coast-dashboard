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

"""Project zone choices and validation shared by DNS forms."""
import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from horizon import exceptions
from horizon import forms

from coast_dashboard.api import coast


class ZoneFormMixin:
    def __init__(self, request, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.dns_enabled = coast.dns_available(request)
        self.zones = {}
        if not self.dns_enabled:
            for name in ('zone_id', 'host', 'auto_dns'):
                self.fields.pop(name, None)
            return
        help_text = _('Coast will create DNS records in the selected zone. '
                      'Leave the zone blank to manage DNS yourself.')
        try:
            self.zones = {z['id']: z['name'].rstrip('.')
                          for z in coast.dns_zone_list(request)}
            if not self.zones:
                help_text = _('No DNS zones in this project. You can use '
                              'a domain with manual DNS records.')
        except Exception as exc:
            status = getattr(exc, 'http_status', None)
            help_text = (_('DNS access denied. Check project permissions.')
                         if status in (401, 403) or isinstance(
                             exc, exceptions.NotAuthorized) else
                         _('DNS service unavailable. Use manual DNS records '
                           'or contact your cloud operator.'))
        self.fields['zone_id'].choices = [('', _('Manual DNS / no zone'))] + [
            (key, value) for key, value in sorted(
                self.zones.items(), key=lambda item: item[1])]
        self.fields['zone_id'].help_text = help_text

    def clean(self):
        data = super().clean()
        zone = self.zones.get(data.get('zone_id'))
        host = data.get('host', '').lower().rstrip('.')
        if zone:
            if host == zone:
                host = ''
            elif host.endswith('.' + zone):
                host = host[:-len(zone) - 1]
            fqdn = '.'.join(filter(None, (host, zone)))
            if len(fqdn) > 253 or not all(re.fullmatch(
                    r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
                    for label in fqdn.split('.')):
                raise ValidationError(
                    _('Enter a valid host name in the zone.'))
            data['host'] = host
            data['fqdn'] = fqdn
        else:
            # A stale host must not block manual DNS or clearing a default.
            data.pop('host', None)
        return data


def zone_field(label=None):
    return forms.ChoiceField(
        label=label or _('DNS zone'), required=False,
        help_text=_('Coast creates records in the selected project zone.'))


def host_field(label=None, help_text=None):
    return forms.CharField(label=label or _('Host'), max_length=253,
                           required=False, help_text=help_text or _(
                               'For example shop or app.sd.example.com. '
                               'Used only with a selected zone. '
                               'Leave blank to use the zone itself.'))


def error_message(exc):
    if getattr(exc, 'api_message', None):
        return coast.error_message(exc, '')
    status = getattr(exc, 'http_status', None)
    if status == 409:
        return _('A DNS record already exists. Choose another host or remove '
                 'the conflicting record before you try again.')
    if status in (401, 403) or isinstance(exc, exceptions.NotAuthorized):
        return _('DNS access denied. Check your project permissions.')
    return _('Unable to save DNS settings. Check the zone and DNS records, '
             'then try again. Existing records can cause a collision.')
