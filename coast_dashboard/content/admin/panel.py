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
import horizon
from openstack_auth import policy
from openstack_auth import utils


ADMIN_RULES = (('app-hosting', 'coast:stack:get_detail'),
               ('app-hosting', 'coast:server:get_detail'),
               ('app-hosting', 'coast:volume:get_detail'))


class Stacks(horizon.Panel):
    name = _('Stacks')
    slug = 'stacks'
    permissions = ('openstack.services.app-hosting',
                   tuple(utils.get_admin_permissions()))
    policy_rules = (ADMIN_RULES,)

    def allowed(self, context):
        request = context['request']
        return (request.user.is_superuser and
                policy.check(ADMIN_RULES, request) and
                super().allowed(context))
