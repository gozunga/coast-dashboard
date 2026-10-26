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

from coast_dashboard.content.oneclick import views
from coast_dashboard.content.services import urls as service_urls

urlpatterns = [
    re_path(r'^create/$', views.CreateView.as_view(), name='create'),
    re_path(r'^$', views.IndexView.as_view(), name='index'),
]
# A service's own pages (detail, logs, console, deployments, env, domains)
# live under /project/coast/services/<id>/, not under apps.
# New view callables: Horizon tags each callback with its panel, and a
# shared callback would keep the Apps panel (sidebar and breadcrumb).
urlpatterns += [
    re_path(pattern.pattern.regex.pattern,
            pattern.callback.view_class.as_view(), name=pattern.name)
    for pattern in service_urls.urlpatterns
    if pattern.name not in ('index', 'create')]
