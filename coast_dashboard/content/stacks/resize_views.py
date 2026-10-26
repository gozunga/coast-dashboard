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

"""Modal entry point kept separate from other server operations."""
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from horizon import forms

from coast_dashboard.content.stacks.resize_forms import ResizeServer


class ResizeServerView(forms.ModalFormView):
    form_class = ResizeServer
    template_name = 'project/coast_stacks/create.html'
    submit_label = page_title = _('Resize server')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update(stack_id=self.kwargs['stack_id'],
                      server_id=self.kwargs['server_id'])
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['submit_url'] = self.request.path
        return context

    def get_success_url(self):
        return reverse('horizon:project:coast.stacks:detail',
                       args=[self.kwargs['stack_id']]) + (
                           '?tab=stack_details__servers')
