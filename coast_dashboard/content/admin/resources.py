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

"""Request-local resource mapping; no per-server cloud API calls."""

import re

from django.urls import NoReverseMatch
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from horizon import exceptions
from openstack_dashboard.api import glance
from openstack_dashboard.api import keystone
from openstack_dashboard.api import neutron
from openstack_dashboard.api import nova

from coast_dashboard.api import coast
from coast_dashboard.content import common


# Admin-only product naming exception approved by James.
ENGINE_NAME = 'Coolify'


def link(panel, value, label=None, title=""):
    if not value:
        return label or '-'
    try:
        url = reverse('horizon:admin:%s:detail' % panel, args=[value])
    except NoReverseMatch:
        return label or value
    return format_html('<a href="{}" target="_blank" rel="noopener" '
                       'title="{}">'
                       '{}</a>', url, title, label or value)


def projects(request):
    rows, more = keystone.tenant_list(request)
    return {p.id: p.name for p in rows}


def role(server):
    return {'control': _('App engine server'),
            'worker': _('Worker'), 'build': _('Build server')}.get(
                server.get('role'), '-')


def servers(request, stack, rows, volumes, cloud=None, ports=None,
            floating_ips=None):
    project_id = stack.get('service_project_id') or stack.get('project_id')
    compute_ids = {s.get('compute_id') for s in rows if s.get('compute_id')}
    instances = []
    nova_failed = False
    if cloud is not None:
        instances, images, flavors, ports, floating_ips = cloud
    elif compute_ids:
        try:
            # Nova's admin tenant filter includes service-project instances.
            # Match compute IDs locally; UUID regex is not a Nova list filter.
            instances, more = nova.server_list(request, search_opts={
                'all_tenants': True, 'tenant_id': project_id})
        except Exception:
            nova_failed = True
            exceptions.handle(request, _('Unable to retrieve Nova instances.'))
    if cloud is None:
        image_ids = {s.get('image_id') for s in rows if s.get('image_id')}
        images = cloud_images(request, image_ids)
        flavors = (safe(request, lambda: nova.flavor_list(request),
                        _('Unable to retrieve flavor names.'))
                   if any(s.get('flavor_id') for s in rows) else [])
        if ports is None:
            ports = port_list(request, compute_ids)
        if floating_ips is None:
            floating_ips = floating_ip_list(request, ports, rows)
    instances = {s.id: s for s in instances if s.id in compute_ids}
    images = {i.id: i.name for i in images}
    flavors = {f.id: f.name for f in flavors}
    result = []
    for server in sorted(rows, key=lambda s: (
            s.get('role') or '', s.get('created_at') or '',
            s.get('id') or '')):
        row = dict(server)
        instance = instances.get(row.get('compute_id'))
        row['role_label'] = role(row)
        row['role_name'] = ('controller' if row.get('role') == 'control' else
                            '%s-%s' % (row.get('role') or 'server',
                                       1 + sum(s.get('role') == row.get('role')
                                               for s in result)))
        addresses = [ip for port in ports
                     if port.device_id == row.get('compute_id')
                     for ip in port.fixed_ips]
        row['fixed_ips'] = ', '.join(sorted({ip['ip_address']
                                            for ip in addresses} | {
            value for value in (row.get('mgmt_ip'), row.get('private_ip'))
            if value})) or '-'
        port_ids = {p.id for p in ports
                    if p.device_id == row.get('compute_id')}
        row['floating_resources'] = [f for f in floating_ips
                                     if f.port_id in port_ids or
                                     f.id == row.get('floating_ip_id')]
        floating_addresses = {f.floating_ip_address
                              for f in row['floating_resources']}
        if row.get('floating_ip'):
            floating_addresses.add(row['floating_ip'])
        row['floating_ips'] = ', '.join(sorted(floating_addresses)) or '-'

        # The engine's generated server name may contain a product name.
        row['label'] = (row['role_label'] if row.get('role') == 'control'
                        else row.get('name') or row['role_label'])
        row['nova'] = (link('instances', instance.id, instance.name)
                       if instance else (_('Unavailable') if nova_failed else
                                         _('not found')))
        row['compute_id'] = row.get('compute_id')
        row['compute_link'] = (link('instances', instance.id) if instance
                               else row.get('compute_id') or '-')
        if not row.get('compute_id'):
            row['nova'] = '-'
        row['nova_status'] = getattr(instance, 'status', '-') or '-'
        # Horizon 25's Server wrapper does not expose this Nova attribute.
        row['host'] = getattr(
            getattr(instance, '_apiresource', instance),
            'OS-EXT-SRV-ATTR:hypervisor_hostname', '-') or '-'
        row['nova_name'] = getattr(instance, 'name', '')
        row['image_name'] = images.get(row.get('image_id'), '-')
        row['flavor_name'] = flavors.get(row.get('flavor_id'), '-')
        row['volumes'] = [dict(
            v, name=v.get('name') or '-',
            cinder_link=link('volumes', v.get('cinder_volume_id')))
            for v in volumes
            if v.get('server_id') and v['server_id'] == row.get('id')]
        result.append(row)
    return result


def overview(stack, names, security_groups=None):
    version = stack.get('engine_version')
    engine = '%s %s' % (ENGINE_NAME, version) if version else '-'
    fields = [('Stack ID', common.copyable_value(stack.get('id'))),
              ('Owning project', names.get(stack.get('project_id'), '-')),
              ('Owning project ID', stack.get('project_id')),
              ('Service project', names.get(
                  stack.get('service_project_id'), '-')),
              ('Service project ID', stack.get('service_project_id')),
              ('Status', stack.get('status')),
              ('App engine', engine),
              ('Servers', stack.get('server_count')),
              ('Workloads', stack.get('workload_count'))]
    for label, field, panel in (
            ('Network', 'network_id', 'networks'),
            ('Subnet', 'subnet_id', 'networks:subnets'),
            ('Router', 'router_id', 'routers')):
        fields.append((label, link(panel, stack.get(field))))
    for label, field in (('Worker security group', 'sg_ingress_id'),
                         ('Management security group', 'sg_mgmt_id')):
        group_id = stack.get(field)
        group = (security_groups or {}).get(group_id)
        name = getattr(group, 'name', None)
        value = common.copyable_value(group_id) if group_id else '-'
        if name:
            value = format_html('{} {}', name, value)
        fields.append((label, value))
    return [(_(label), value if value is not None and value != ''
             else '-') for label, value in fields]


def safe(request, loader, message):
    try:
        return loader()
    except Exception:
        exceptions.handle(request, message)
        return []


def cloud_images(request, image_ids):
    if not image_ids:
        return []
    return safe(request, lambda: glance.image_list_detailed(
        request, filters={'id': 'in:' + ','.join(sorted(image_ids))})[0],
        _('Unable to retrieve image names.'))


def inventory(request, stacks):
    """Batch cloud reads across the list; no Nova/Glance calls per row."""
    rows = {s['id']: coast.admin_resource_list(request, s['id'], 'servers')
            for s in stacks}
    all_rows = [r for group in rows.values() for r in group]
    instances = []
    projects = {s.get('service_project_id') or s.get('project_id')
                for s in stacks if rows[s['id']]}
    for project in sorted(p for p in projects if p):
        instances.extend(safe(request, lambda: nova.server_list(
            request, search_opts={'all_tenants': True,
                                  'tenant_id': project})[0],
                              _('Unable to retrieve Nova instances.')))
    ids = sorted({r['compute_id'] for r in all_rows if r.get('compute_id')})
    ports = port_list(request, ids)
    floating_ips = floating_ip_list(request, ports, all_rows)
    images = cloud_images(request, {r['image_id'] for r in all_rows
                                    if r.get('image_id')})
    flavors = safe(request, lambda: nova.flavor_list(request),
                   _('Unable to retrieve flavors.')) if all_rows else []
    for stack in stacks:
        stack['servers'] = servers(request, stack, rows[stack['id']], [],
                                   (instances, images, flavors, ports,
                                    floating_ips))
        stack['worker_count'] = sum(r.get('role') == 'worker'
                                    for r in rows[stack['id']])
        stack['build_count'] = sum(r.get('role') == 'build'
                                   for r in rows[stack['id']])
        healthy = sum(r.get('status') == 'ACTIVE' and
                      r['nova_status'] == 'ACTIVE' for r in stack['servers'])
        stack['health'] = (_('%(healthy)s/%(total)s active') % {
            'healthy': healthy, 'total': len(stack['servers'])}
            if stack['servers'] else '-')
    return stacks


def port_list(request, device_ids):
    return safe(request, lambda: neutron.list_resources_with_long_filters(
        neutron.port_list, 'device_id', tuple(sorted(device_ids)),
        request=request), _('Unable to retrieve server ports.')) \
        if device_ids else []


def floating_ip_list(request, ports, servers):
    # Use the authenticated SDK list directly. Horizon's floating IP wrapper
    # performs a second, unfiltered port list and can fetch missing ports.
    ids = tuple(sorted({s['floating_ip_id'] for s in servers
                        if s.get('floating_ip_id')}))
    port_ids = tuple(sorted({p.id for p in ports}))
    rows = []
    if port_ids:
        rows = safe(request, lambda: list(
            neutron.networkclient(request).ips(port_id=port_ids)),
                    _('Unable to retrieve floating IPs.'))
    missing = tuple(i for i in ids if i not in {f.id for f in rows})
    if missing:
        rows += safe(request, lambda: list(
            neutron.networkclient(request).ips(id=missing)),
                     _('Unable to retrieve floating IPs.'))
    return rows


def volume_groups(rows, servers):
    """Map recorded volumes without extra cloud reads."""
    groups, by_server, counts = [], {}, {}
    for server in sorted(servers, key=lambda s: (
            s.get('role') or '', s.get('created_at') or '',
            s.get('id') or '')):
        kind = server.get('role') or 'server'
        counts[kind] = counts.get(kind, 0) + 1
        label = (role(server) if kind == 'control' else
                 server.get('role_name') or '%s-%s' % (kind, counts[kind]))
        group = {'link': link('instances', server.get('compute_id'), label),
                 'volumes': [], 'order': (
                     {'control': 0, 'build': 1, 'worker': 2}.get(kind, 3),
                     str(label))}
        groups.append(group)
        by_server[server['id']] = group
    unattached = {'link': _('Unattached'), 'volumes': []}
    for volume in rows:
        group = by_server.get(volume.get('server_id'), unattached)
        name = volume.get('name') or '-'
        purpose = re.split(r'[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}'
                           r'[0-9a-fA-F]{12}-', name)[-1]
        for suffix, label in (('-data', _('data')),
                              ('-docker', _('docker disk')),
                              ('-registry', _('registry'))):
            if name.endswith(suffix):
                purpose = label
                break
        status = (volume.get('status') or '').lower().replace('-', '_')
        if group is not unattached and status == 'in_use':
            badge = format_html(_('Attached to {}'), group['link'])
        elif status.startswith('error'):
            badge = _('Error')
        elif status in ('available', 'creating', 'deleting', 'attaching',
                        'detaching'):
            badge = _(status.title())
        elif not status or status == 'in_use':
            badge = _('Not attached')
        else:
            badge = status.replace('_', ' ').title()
        identity = '%s — %s' % (name, volume.get('cinder_volume_id') or '-')
        device = volume.get('device')
        for attachment in volume.get('attachments') or []:
            device = device or attachment.get('device')
        group['volumes'].append(dict(
            volume, cloud_link=link('volumes', volume.get('cinder_volume_id'),
                                    purpose, title=identity),
            identity=identity, copyable_name=common.copyable_value(
                volume.get('name')), badge=badge,
            device=device))
    ordered = [g for g in sorted(groups, key=lambda g: g['order'])
               if g['volumes']]
    return ordered + ([unattached] if unattached['volumes'] else [])


def security_groups(request, stack):
    result = {}
    for field in ('sg_ingress_id', 'sg_mgmt_id'):
        group_id = stack.get(field)
        if group_id:
            try:
                result[group_id] = neutron.security_group_get(
                    request, group_id)
            except Exception:
                # IDs remain available even when Neutron cannot resolve names.
                pass
    return result


def worker_rules(group, ingress_rules):
    """Mark applied Neutron rules by their Coast ingress tuple."""
    customer = {(r.get('protocol'), r.get('port_range_min'),
                 r.get('port_range_max'), r.get('source'))
                for r in ingress_rules or [] if not r.get('managed')}
    result = []
    for rule in getattr(group, 'rules', []):
        key = (rule.ip_protocol, rule.from_port, rule.to_port,
               rule.ip_range.get('cidr'))
        result.append({'direction': rule.direction,
                       'ip_protocol': rule.ip_protocol,
                       'from_port': rule.from_port, 'to_port': rule.to_port,
                       'source': rule.ip_range.get('cidr') or
                       rule.group.get('name') or '-',
                       'description': rule.description,
                       'customer_added': rule.direction == 'ingress' and
                       key in customer})
    return result
