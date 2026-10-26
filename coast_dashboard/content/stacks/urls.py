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

from django.urls import re_path

from coast_dashboard.content.stacks import resize_views
from coast_dashboard.content.stacks import views

urlpatterns = [
    re_path(r'^(?P<stack_id>[^/]+)/servers/add/$',
            views.AddServerView.as_view(), name='add_server'),
    re_path(r'^(?P<stack_id>[^/]+)/servers/(?P<server_id>[^/]+)/resize/$',
            resize_views.ResizeServerView.as_view(), name='resize_server'),
    re_path(r'^(?P<stack_id>[^/]+)/firewall/add/$',
            views.AddIngressRuleView.as_view(), name='add_ingress_rule'),
    re_path(r'^(?P<stack_id>[^/]+)/firewall/(?P<rule_id>[^/]+)/delete/$',
            views.delete_ingress_rule, name='delete_ingress_rule'),
    re_path(r'^$', views.IndexView.as_view(), name='index'),
    re_path(r'^create/$', views.CreateView.as_view(), name='create'),
    re_path(r'^(?P<stack_id>[^/]+)/dns/$',
            views.DNSSettingsView.as_view(), name='dns'),
    re_path(r'^(?P<stack_id>[^/]+)/$', views.DetailView.as_view(),
            name='detail'),
]
