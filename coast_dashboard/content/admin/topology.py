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

"""Read-only cloud topology, built from filtered batch inventory calls."""
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from openstack_dashboard.api import cinder
from openstack_dashboard.api import neutron

from coast_dashboard.content.admin import resources
from coast_dashboard import public_text


def build(request, stack, servers, volumes):
    compute_ids = sorted({s['compute_id'] for s in servers
                          if s.get('compute_id')})
    router_id = stack.get('router_id')
    devices = compute_ids + ([router_id] if router_id else [])
    ports = resources.port_list(request, devices)
    floating_ips = resources.floating_ip_list(request, ports, servers)
    # Share the port and floating IP results with the server mapper.
    mapped = resources.servers(request, stack, servers, volumes,
                               ports=ports, floating_ips=floating_ips)
    network_ids = {p.network_id for p in ports}
    if stack.get('network_id'):
        network_ids.add(stack['network_id'])
    networks = resources.safe(request, lambda: neutron.network_list(
        request, id=tuple(sorted(network_ids))),
        _('Unable to retrieve networks.')) \
        if network_ids else []
    routers = resources.safe(request, lambda: neutron.router_list(
        request, id=(router_id,)), _('Unable to retrieve routers.')) \
        if router_id else []
    volume_ids = {v['cinder_volume_id'] for v in volumes
                  if v.get('cinder_volume_id')}
    project = stack.get('service_project_id') or stack.get('project_id')
    cloud_volumes = resources.safe(request, lambda: cinder.volume_list(
        request, search_opts={'all_tenants': True, 'project_id': project}),
        _('Unable to retrieve volumes.')) if compute_ids or volume_ids else []
    nodes, edges = [], []
    keys = set()

    def friendly(value, fallback):
        value = str(value or '')
        if public_text.contains_engine_name(value):
            return fallback
        return value or fallback

    def node(kind, resource_id, name, panel, column, missing=False):
        key = (kind, resource_id)
        if key in keys:
            return key
        keys.add(key)
        nodes.append({'key': key, 'column': column,
                      'name': friendly(name, str(resource_id)),
                      'id': resource_id, 'items': [],
                      'color': {'instances': '#337ab7',
                                'networks': '#8541b5',
                                'routers': '#398439'}.get(panel, '#777'),
                      'kind': kind, 'missing': missing,
                      'url': reverse('horizon:admin:%s:detail' % panel,
                                     args=[resource_id])
                      if resource_id else ''})
        return key

    def edge(left, right):
        if left in keys and right in keys:
            edges.append(dict(left=left, right=right))

    router = next(iter(routers), None)
    if router_id:
        node(_('Router'), router_id, getattr(router, 'name', ''),
             'routers', 0, router is None)
    management_ips = {s.get('mgmt_ip') for s in servers if s.get('mgmt_ip')}
    management_nets = {p.network_id for p in ports if any(
        ip.get('ip_address') in management_ips for ip in p.fixed_ips)}
    by_network = {n.id: n for n in networks}
    for network_id in sorted(network_ids):
        network = by_network.get(network_id)
        kind = (_('Management / backplane network')
                if network_id in management_nets else _('Customer network'))
        fallback = (_('Management network') if network_id in management_nets
                    else str(network_id))
        name = friendly(getattr(network, 'name', ''), fallback)
        node(kind, network_id, name, 'networks', 1, network is None)
        for port in ports:
            if port.network_id != network_id:
                continue
            if port.device_id == router_id:
                edge((_('Router'), router_id), (kind, network_id))
    for server in mapped:
        key = node(_('Server'), server['compute_id'] or server['id'],
                   (_('App engine server') if server.get('role') == 'control'
                    else server['role_name']),
                   'instances', 2, not server['nova_name'])
        nodes[-1]['details'] = '%s · %s · %s' % (
            server['nova_status'], server['flavor_name'], server['fixed_ips'])
        nodes[-1]['tooltip'] = friendly(server['nova_name'], '')
        if not server.get('compute_id'):
            nodes[-1]['url'] = ''
        for port in ports:
            if port.device_id == server.get('compute_id'):
                for network_node in nodes:
                    if network_node['key'][1] == port.network_id:
                        edge(network_node['key'], key)
        for floating in server['floating_resources']:
            fip = node(_('Floating IP'), floating.id,
                       floating.floating_ip_address, 'floating_ips', 3)
            edge(key, fip)
        if server.get('floating_ip_id') and not server['floating_resources']:
            fip = node(_('Floating IP'), server['floating_ip_id'],
                       server.get('floating_ip'), 'floating_ips', 3, True)
            edge(key, fip)
    known_ips = {n['id'] for n in nodes if n['column'] == 3}
    for floating in floating_ips:
        if floating.id not in known_ips:
            node(_('Floating IP'), floating.id,
                 floating.floating_ip_address, 'floating_ips', 3)
    by_volume = {v.id: v for v in cloud_volumes}
    for volume in cloud_volumes:
        if any(a.get('server_id') in compute_ids
               for a in (volume.attachments or [])):
            volume_ids.add(volume.id)
    for volume_id in sorted(volume_ids):
        volume = by_volume.get(volume_id)
        key = node(_('Volume'), volume_id, getattr(volume, 'name', ''),
                   'volumes', 3, volume is None)
        attached = {a.get('server_id') for a in
                    (getattr(volume, 'attachments', []) or [])}
        attached.update(s.get('compute_id') or s['id']
                        for s in servers if any(
            v.get('cinder_volume_id') == volume_id and
            v.get('server_id') == s['id'] for v in volumes))
        for compute_id in attached:
            edge((_('Server'), compute_id), key)
    # Fold known attachments into their server, leaving missing or orphaned
    # resources visible as small standalone boxes.
    by_key = {n['key']: n for n in nodes}
    children = set()
    for right in nodes:
        if right['kind'] == _('Volume'):
            record = next((v for v in volumes if
                           v.get('cinder_volume_id') == right['id']), {})
            purpose = (record.get('purpose') or record.get('mount_point') or
                       record.get('mount_path') or record.get('name'))
            if purpose and 'docker' in purpose:
                purpose = _('docker disk')
            elif purpose and 'registry' in purpose:
                purpose = _('registry')
            right['name'] = friendly(purpose, right['name'])
            size = record.get('size_gb') or getattr(
                by_volume.get(right['id']), 'size', None)
            if size:
                right['name'] = '%s · %s GB' % (right['name'], size)
    for connection in edges:
        left = by_key[connection['left']]
        right = by_key[connection['right']]
        if right['column'] != 3:
            continue
        left['items'].append(right.copy())
        if not right['missing']:
            children.add(right['key'])
    nodes = [n for n in nodes if n['key'] not in children]
    # Stable attachment ordering keeps related servers and networks together.
    server_nodes = sorted((n for n in nodes if n['column'] == 2),
                          key=lambda n: (tuple(sorted(
                              p.network_id for p in ports
                              if p.device_id == n['id'])), n['name']))
    ranks = {n['id']: i for i, n in enumerate(server_nodes)}

    def network_order(n):
        attached = [ranks[p.device_id] for p in ports
                    if p.network_id == n['id'] and p.device_id in ranks]
        return (sum(attached) / len(attached) if attached else -1, n['id'])

    columns = []
    for column in range(4):
        column_nodes = [n for n in nodes if n['column'] == column]
        if column == 2:
            column_nodes = server_nodes
        elif column == 1:
            column_nodes.sort(key=network_order)
        for n in column_nodes:
            n['dom_id'] = 'topology-node-%s' % nodes.index(n)
            n['items'].sort(key=lambda child: (
                child['kind'] != _('Volume'), child['name']))
        columns.append(column_nodes)
    # Rebuild only router/network and network/server lines at box edges.
    edges = []
    connections = set()
    for port in ports:
        network = next((n for n in nodes if n['column'] == 1 and
                        n['id'] == port.network_id), None)
        target = next((n for n in nodes if n['column'] in (0, 2) and
                       n['id'] == port.device_id), None)
        if not network or not target:
            continue
        left, right = ((target, network) if target['column'] == 0 else
                       (network, target))
        pair = (left['key'], right['key'])
        if pair in connections:
            continue
        connections.add(pair)
        edges.append(dict(left=left['dom_id'], right=right['dom_id']))
    return {'nodes': nodes, 'edges': edges, 'columns': columns}
