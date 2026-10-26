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

from urllib.parse import urlencode

from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from horizon import tabs

from coast_dashboard.api import coast
from coast_dashboard.content.admin import resources
from coast_dashboard.content.admin import tables
from coast_dashboard.content.admin import topology
from coast_dashboard.content import common
from coast_dashboard.content import details


def load(tab, key, loader):
    return details.load_list(tab.tab_group, key, loader,
                             _('Unable to retrieve stack resources.')) or []


def stack_id(tab):
    return tab.tab_group.kwargs['item']['id']


def server_rows(tab):
    return load(tab, 'servers', lambda: coast.admin_resource_list(
        tab.request, stack_id(tab), 'servers'))


class Overview(tabs.Tab):
    name = _('Overview')
    slug = 'overview'
    template_name = 'admin/coast/overview.html'

    def get_context_data(self, request):
        names = load(self, 'projects', lambda: resources.projects(request))
        stack = self.tab_group.kwargs['item']
        groups = resources.security_groups(request, stack)
        worker = groups.get(stack.get('sg_ingress_id'))
        rules = None
        if coast.ingress_supported(request):
            rules = load(self, 'ingress_rules', lambda:
                         coast.stack_ingress_rule_list(request, stack['id']))
        return {'fields': resources.overview(stack, names or {}, groups),
                'worker_rules': resources.worker_rules(worker, rules),
                'ingress_rules': rules}


class Servers(tabs.Tab):
    name = _('Servers')
    slug = 'servers'
    template_name = 'admin/coast/servers.html'
    preload = False

    def get_context_data(self, request):
        rows = server_rows(self)
        volumes = load(self, 'volumes', lambda: coast.admin_resource_list(
            request, stack_id(self), 'volumes'))
        mapped = load(self, 'mapped_servers', lambda: resources.servers(
            request, self.tab_group.kwargs['item'], rows, volumes))
        return {'servers': mapped, 'servers_table': tables.ServersTable(
            request, data=mapped)}


class Volumes(tabs.Tab):
    name = _('Volumes')
    slug = 'volumes'
    template_name = 'admin/coast/volumes.html'
    preload = False

    def get_context_data(self, request):
        rows = load(self, 'volumes', lambda: coast.admin_resource_list(
            request, stack_id(self), 'volumes'))
        return {'volume_groups': resources.volume_groups(
            rows, server_rows(self))}


class Topology(tabs.Tab):
    name = _('Topology')
    slug = 'topology'
    template_name = 'admin/coast/topology.html'
    preload = False

    def get_context_data(self, request):
        rows = server_rows(self)
        volumes = load(self, 'volumes', lambda: coast.admin_resource_list(
            request, stack_id(self), 'volumes'))
        return topology.build(request, self.tab_group.kwargs['item'],
                              rows, volumes)


class Workloads(tabs.Tab):
    name = _('Workloads')
    slug = 'workloads'
    template_name = 'admin/coast/workloads.html'
    preload = False

    def get_context_data(self, request):
        workers = {s['id']: s for s in server_rows(self)}
        services = load(self, 'services', lambda: coast.admin_resource_list(
            request, stack_id(self), 'services'))
        rows = []
        for service in services:
            worker = workers.get(service.get('server_id'), {})
            service = dict(service, url=reverse(
                common.coast_ns(kind=service.get('kind')) + 'detail',
                args=[service['id']]))
            rows.append(dict(service, name=service.get('name') or '-',
                             worker=worker.get('name') or '-'))
        return {'workloads': rows}


class History(tabs.Tab):
    name = _('History')
    slug = 'history'
    template_name = 'admin/coast/history.html'
    preload = False

    def get_context_data(self, request):
        page = load(self, 'events', lambda: coast.admin_event_list(
            request, stack_id(self), marker=request.GET.get('marker')))
        events, marker = page if page else ([], None)
        rows = []
        for event in events:
            # Only show the relevant compute IDs, never raw engine details.
            detail = event.get('detail') or {}
            if not isinstance(detail, dict):
                detail = {}
            rows.append({
                'action': event.get('action') or '-',
                'outcome': event.get('outcome') or '-',
                'time': common.local_datetime(event.get('created_at')),
                'resource_id': event.get('resource_id'),
                'compute_id': detail.get('compute_id'),
                'old_compute_id': detail.get('old_compute_id'),
                'new_compute_id': detail.get('new_compute_id')})
        older = (request.path + '?' + urlencode({
            'tab': 'admin_stacks__history', 'marker': marker})
            if marker else '')
        return {'events': rows, 'older_url': older}


class StackTabs(tabs.TabGroup):
    template_name = 'admin/coast/_stack_tabs.html'
    slug = 'admin_stacks'
    tabs = (Overview, Servers, Volumes, Workloads, History, Topology)
    sticky = True
