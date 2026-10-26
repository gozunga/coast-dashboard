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

from django.utils.translation import gettext_lazy as _
from horizon import exceptions
from horizon import tabs

from coast_dashboard.api import coast
from coast_dashboard.content import details
from coast_dashboard.content import related_tables
from coast_dashboard.content.stacks import activity
from coast_dashboard.content.stacks import firewall
from coast_dashboard.content.stacks import tables
from coast_dashboard.content.stacks import topology


class Overview(details.Overview):
    template_name = 'project/coast_stacks/overview.html'

    def get_context_data(self, request):
        context = super().get_context_data(request)
        context['dns_supported'] = coast.dns_available(request)
        rows = firewall.rules(self.tab_group, request)
        context['firewall_supported'] = rows is not None
        context['custom_rule_count'] = sum(not r.get('managed')
                                           for r in rows or [])
        return context


class Servers(tabs.TableTab):
    name = _('Servers')
    slug = 'servers'
    table_classes = (tables.ServersTable,)
    template_name = 'project/coast_common/related.html'

    def get_servers_data(self):
        return details.load_list(
            self.tab_group, 'servers', lambda: coast.stack_server_list(
                self.request, self.tab_group.kwargs['item']['id']),
            _('Unable to retrieve servers.')) or []


class Appgroups(tabs.TableTab):
    name = _('App Groups')
    slug = 'appgroups'
    table_classes = (related_tables.AppgroupsTable,)
    template_name = 'project/coast_common/related.html'

    def get_appgroups_data(self):
        stack_id = self.tab_group.kwargs['item']['id']
        return details.load_list(self.tab_group, 'appgroups', lambda: [
            row for row in coast.appgroup_list(self.request, stack_id=stack_id)
            if row.get('stack_id', stack_id) == stack_id],
            _('Unable to retrieve app groups.')) or []


class Topology(tabs.Tab):
    name = _('Topology')
    slug = 'topology'
    template_name = 'project/coast_stacks/topology.html'
    preload = False

    def get_context_data(self, request):
        stack = self.tab_group.kwargs['item']
        try:
            tree = topology.build(request, stack)
        except Exception:
            exceptions.handle(request, _('Unable to retrieve the topology.'))
            tree = None
        return {'stack': stack, 'tree': tree}


class Activity(tabs.Tab):
    name = _('Activity')
    slug = 'activity'
    template_name = 'project/coast_stacks/activity.html'
    preload = False

    def get_context_data(self, request):
        stack_id = self.tab_group.kwargs['item']['id']
        context = {'events': []}
        try:
            events, marker = coast.stack_event_list(
                request, stack_id, marker=request.GET.get('marker'))
        except coast.ActivityUnavailable:
            context['unavailable'] = True
            return context
        except Exception:
            # Horizon's error details can expose the original API message.
            context['failed'] = True
            return context
        servers = details.load_list(
            self.tab_group, 'servers', lambda: coast.stack_server_list(
                request, stack_id), _('Unable to retrieve servers.')) or []
        servers = {server['id']: server for server in servers}
        # The API returns newest first; preserve that order across pages.
        context['events'] = [activity.present(event, servers)
                             for event in events]
        if marker:
            context['older_url'] = request.path + '?' + urlencode({
                'tab': 'stack_details__activity', 'marker': marker})
        return context


class StackTabs(tabs.TabGroup):
    slug = 'stack_details'
    tabs = (Overview, Topology, Servers, Appgroups, Activity,
            firewall.Firewall)
    sticky = True
