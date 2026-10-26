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

"""Stack topology: app groups, environments, apps/services and workers."""

from coast_dashboard.api import coast


def _by_name(rows):
    return sorted(rows, key=lambda row: (row.get('name') or '').lower())


def build(request, stack):
    """Return the nested topology for one stack.

    Every list is fetched once; nothing is fetched per row except the
    environments of each app group (the API has no stack-wide list).
    """
    stack_id = stack['id']
    servers = coast.stack_server_list(request, stack_id)
    by_server = {row['id']: row for row in servers}
    services = [row for row in coast.service_list(request)
                if row.get('stack_id') == stack_id]
    by_env = {}
    for row in services:
        by_env.setdefault(row.get('environment_id'), []).append(row)
    counts = {}
    groups = []
    for group in _by_name(coast.appgroup_list(request, stack_id=stack_id)):
        if group.get('stack_id', stack_id) != stack_id:
            continue
        envs = []
        for env in _by_name(coast.environment_list(
                request, appgroup_id=group['id'])):
            items = []
            for row in _by_name(by_env.pop(env['id'], [])):
                server = by_server.get(row.get('server_id'))
                if server:
                    kind = ('service' if row.get('kind') == 'service'
                            else 'app')
                    key = (server['id'], kind)
                    counts[key] = counts.get(key, 0) + 1
                items.append(dict(row, server=server))
            envs.append(dict(env, items=items))
        groups.append(dict(group, environments=envs))
    # Apps whose environment is not listed (e.g. deleted parents).
    orphans = [dict(row, server=by_server.get(row.get('server_id')))
               for rows in by_env.values() for row in _by_name(rows)]
    workers = [dict(row, app_count=counts.get((row['id'], 'app'), 0),
                    service_count=counts.get((row['id'], 'service'), 0))
               for row in sorted(servers, key=lambda r: (
                   r.get('role') != 'control', r.get('name') or ''))]
    return {'groups': groups, 'orphans': orphans, 'servers': workers}
