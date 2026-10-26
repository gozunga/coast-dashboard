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

from django.http import HttpResponseNotAllowed
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from horizon import exceptions
from horizon import forms
from horizon import messages
from horizon import tables

from coast_dashboard.api import coast
from coast_dashboard.content import details
from coast_dashboard.content.stacks import add_server
from coast_dashboard.content.stacks import forms as project_forms
from coast_dashboard.content.stacks import tables as project_tables
from coast_dashboard.content.stacks import tabs as project_tabs


class IndexView(tables.DataTableView):
    table_class = project_tables.StacksTable
    template_name = 'project/coast_stacks/index.html'
    page_title = _('Stacks')

    def get_data(self):
        try:
            return coast.stack_list(self.request)
        except Exception:
            exceptions.handle(self.request, _('Unable to retrieve stacks.'))
            return []


class DetailView(details.ResourceDetailView):
    resource = 'stack'
    index_url = 'horizon:project:coast.stacks:index'
    action_table = project_tables.StacksTable
    tab_group_class = project_tabs.StackTabs


class CreateView(forms.ModalFormView):
    form_class = project_forms.CreateStack
    template_name = 'project/coast_stacks/create.html'
    submit_url = reverse_lazy('horizon:project:coast.stacks:create')
    success_url = reverse_lazy('horizon:project:coast.stacks:index')
    submit_label = page_title = _('Create Stack')

    def get_object_id(self, item):
        return item['id']


class DNSSettingsView(CreateView):
    form_class = project_forms.DNSSettings
    page_title = _('Default domain')
    submit_label = _('Save')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['stack_id'] = self.kwargs['stack_id']
        return kwargs

    def get_initial(self):
        try:
            item = coast.stack_get(self.request, self.kwargs['stack_id'])
            return {'zone_id': item.get('dns_zone_id') or '',
                    'host': item.get('default_domain') or ''}
        except Exception:
            exceptions.handle(self.request, _('Unable to retrieve stack.'),
                              redirect=self.get_success_url())
            return {}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['submit_url'] = self.request.path
        return context

    def get_success_url(self):
        return reverse_lazy('horizon:project:coast.stacks:detail',
                            args=[self.kwargs['stack_id']])


class AddIngressRuleView(DNSSettingsView):
    form_class = project_forms.AddIngressRule
    submit_label = page_title = _('Add rule')

    def get_initial(self):
        return {}

    def get_success_url(self):
        return str(super().get_success_url()) + '?tab=stack_details__firewall'


def delete_ingress_rule(request, stack_id, rule_id):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    if coast.ingress_supported(request):
        try:
            rules = coast.stack_ingress_rule_list(request, stack_id)
            if any(r['id'] == rule_id and not r.get('managed') for r in rules):
                coast.stack_ingress_rule_delete(request, stack_id, rule_id)
                messages.success(request, _('Firewall rule deleted.'))
        except Exception as exc:
            messages.error(request, coast.error_message(
                exc, _('Unable to delete firewall rule.')))
    url = reverse_lazy('horizon:project:coast.stacks:detail', args=[stack_id])
    return redirect(str(url) + '?tab=stack_details__firewall')


class AddServerView(DNSSettingsView):
    form_class = add_server.AddServer
    submit_label = page_title = _('Add server')

    def get_initial(self):
        return {}

    def get_success_url(self):
        return str(super().get_success_url()) + '?tab=stack_details__servers'
