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

"""Worker ingress presentation shared by project and admin details."""
from django.utils.translation import gettext_lazy as _
from horizon import exceptions
from horizon import tabs

from coast_dashboard.api import coast


def rules(group, request):
    if not hasattr(group, '_ingress_rules'):
        group._ingress_rules = None
        if coast.ingress_supported(request):
            try:
                group._ingress_rules = coast.stack_ingress_rule_list(
                    request, group.kwargs['item']['id'])
            except Exception:
                exceptions.handle(
                    request, _('Unable to retrieve firewall rules.'),
                    details='')
    return group._ingress_rules


class Firewall(tabs.Tab):
    name = _('Firewall')
    slug = 'firewall'
    template_name = 'project/coast_stacks/firewall.html'

    def allowed(self, request):
        return coast.ingress_supported(request)

    def get_context_data(self, request):
        return {'item': self.tab_group.kwargs['item'],
                'rules': rules(self.tab_group, request)}
