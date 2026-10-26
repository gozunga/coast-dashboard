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

"""Load app group relationships once for each request."""

from collections import defaultdict

from django.utils.translation import gettext_lazy as _
from horizon import exceptions

from coast_dashboard.api import coast


def grouped_resources(request):
    if hasattr(request, '_appgroup_resources'):
        return request._appgroup_resources
    result = {}
    for name, loader, message in (
            ('environments', coast.environment_list,
             _('Unable to retrieve environments.')),
            ('resources', coast.service_list,
             _('Unable to retrieve apps and services.'))):
        try:
            groups = defaultdict(list)
            for item in loader(request):
                groups[item.get('appgroup_id')].append(item)
            result[name] = groups
        except Exception as exc:
            exceptions.handle(request, coast.error_message(exc, message))
            result[name] = None
    request._appgroup_resources = result
    return result


def for_group(request, item):
    resources = grouped_resources(request)
    envs = resources['environments']
    services = resources['resources']
    rows = services.get(item['id'], []) if services is not None else []
    environments = envs.get(item['id'], []) if envs is not None else None
    return dict(item, environments=environments,
                apps=([row for row in rows if row.get('kind') == 'app']
                      if services is not None else None),
                services=([row for row in rows if row.get('kind') == 'service']
                          if services is not None else None))
