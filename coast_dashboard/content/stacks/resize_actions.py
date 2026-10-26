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

"""Server resize eligibility and row action."""
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from horizon import tables

from coast_dashboard.content import common


def idle_active(item):
    return (item.get('status') == 'ACTIVE' and
            item.get('task_state') in (None, '', 'NONE') and
            not common.is_busy(item))


def eligible(stack, server):
    return (idle_active(stack) and idle_active(server) and
            server.get('kind') == 'vm' and
            server.get('role') in ('control', 'controller', 'worker', 'build'))


class ResizeServer(tables.LinkAction):
    name = 'resize'
    verbose_name = _('Resize')
    classes = ('ajax-modal',)
    policy_rules = (("app-hosting", "coast:server:resize"),)

    def allowed(self, request, datum):
        return bool(datum and eligible(self.table.kwargs.get('item', {}),
                                       datum))

    def get_link_url(self, datum):
        return reverse('horizon:project:coast.stacks:resize_server',
                       args=[self.table.kwargs['item']['id'], datum['id']])
