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

from django.template.loader import render_to_string
from django.utils.translation import gettext_lazy as _
from horizon import exceptions
from horizon import tables

from coast_dashboard.api import coast
from coast_dashboard.content.admin import resources
from coast_dashboard.content.admin import tables as admin_tables
from coast_dashboard.content.admin import tabs
from coast_dashboard.content import details


def stack_search_text(stack):
    """Collect searchable inventory values without rendered HTML."""
    values = [stack.get(key) for key in (
        'name', 'id', 'owner', 'project_id', 'status', 'engine_version')]
    values.extend(server.get(key) for server in stack.get('servers', [])
                  for key in ('role_name', 'id', 'nova_name', 'compute_id',
                              'host', 'image_name', 'flavor_name', 'fixed_ips',
                              'floating_ips', 'nova_status'))
    return ' '.join(str(value) for value in values
                    if value is not None).casefold()


class IndexView(tables.DataTableView):
    table_class = admin_tables.StacksTable
    template_name = 'admin/coast/index.html'
    page_title = _('Stacks')

    def get_data(self):
        try:
            stacks = coast.admin_stack_list(self.request)
            try:
                names = resources.projects(self.request)
            except Exception:
                names = {}
            rows = [dict(s, name=s.get('name') or '-',
                         owner=names.get(s.get('project_id'), '-'))
                    for s in stacks]
            rows = resources.inventory(self.request, rows)
            self.hosts = sorted({r['host'] for s in rows
                                 for r in s['servers'] if r['host'] != '-'})
            self.projects = sorted({(s.get('project_id') or '', s['owner'])
                                    for s in rows})
            self.statuses = sorted({s.get('status') for s in rows
                                    if s.get('status')})
            project = self.request.GET.get('project')
            status = self.request.GET.get('status')
            host = self.request.GET.get('host')
            query = self.request.GET.get('q', '').strip().casefold()
            return [s for s in rows if
                    (not host or any(r['host'] == host
                                     for r in s['servers'])) and
                    (not query or query in stack_search_text(s)) and
                    (not project or s.get('project_id') == project) and
                    (not status or s.get('status') == status)]
        except Exception as exc:
            exceptions.handle(self.request, coast.error_message(
                exc, _('Unable to retrieve stacks.')))
            return []

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(projects=getattr(self, 'projects', []),
                       statuses=getattr(self, 'statuses', []),
                       hosts=getattr(self, 'hosts', []))
        return context


class DetailView(details.ResourceDetailView):
    resource = 'stack'
    index_url = 'horizon:admin:stacks:index'
    action_table = admin_tables.StacksTable
    tab_group_class = tabs.StackTabs

    def load_item(self):
        item = coast.admin_stack_get(
            self.request, self.kwargs['stack_id'])
        return dict(item, name=item.get('name') or '-')

    def get_actions(self, item):
        return render_to_string('admin/coast/_actions.html',
                                request=self.request)
