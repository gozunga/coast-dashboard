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

from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from horizon import exceptions
from horizon import tabs

from coast_dashboard.api import coast


class ResourceDetailView(tabs.TabbedTableView):
    template_name = 'project/coast_common/detail.html'
    page_title = '{{ item.name|default:item.id }}'

    def load_item(self):
        return getattr(coast, self.resource + '_get')(
            self.request, self.kwargs[self.resource + '_id'])

    def get_data(self):
        if not hasattr(self, '_item'):
            try:
                self._item = self.load_item()
            except Exception as exc:
                url = reverse(self.index_url)
                exceptions.handle(self.request, coast.error_message(
                    exc, _('Unable to retrieve resource details.')),
                    redirect=url)
                raise exceptions.Http302(url)
        return self._item

    def get_tabs(self, request, **kwargs):
        return super().get_tabs(request, item=self.get_data(), **kwargs)

    def get_action_table(self, item):
        return self.action_table(self.request, data=[item])

    def get_actions(self, item):
        return self.get_action_table(item).render_row_actions(item)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        item = self.get_data()
        context.update(item=item, actions=self.get_actions(item),
                       url=reverse(self.index_url))
        return context


class Overview(tabs.Tab):
    name = _('Overview')
    slug = 'overview'

    def get_context_data(self, request, **kwargs):
        return {'item': self.tab_group.kwargs['item']}


def load_list(group, key, loader, message):
    if not hasattr(group, '_lists'):
        group._lists = {}
    if key not in group._lists:
        try:
            group._lists[key] = loader()
        except Exception as exc:
            exceptions.handle(group.request, coast.error_message(exc, message))
            group._lists[key] = None
    return group._lists[key]
