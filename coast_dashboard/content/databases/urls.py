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

from coast_dashboard.content.databases import views
from coast_dashboard.content.services import backups

urlpatterns = [
    re_path(r'^(?P<database_id>[^/]+)/logs/fragment/$',
            views.LogsFragmentView.as_view(), name='logs_fragment'),
    re_path(r'^(?P<database_id>[^/]+)/public-access/$',
            views.PublicAccessView.as_view(), name='public_access'),
    re_path(r'^(?P<database_id>[^/]+)/limits/$',
            views.LimitsView.as_view(), name='limits'),
    re_path(r'^(?P<service_id>[^/]+)/backups/$',
            backups.PolicyView.as_view(), name='backups'),
    re_path(r'^(?P<service_id>[^/]+)/backups/(?P<backup_id>[^/]+)/restore/$',
            backups.RestoreView.as_view(), name='backup_restore'),
    re_path(r'^(?P<service_id>[^/]+)/backups/(?P<backup_id>[^/]+)/download/$',
            backups.DownloadView.as_view(), name='backup_download'),
    re_path(r'^(?P<service_id>[^/]+)/backups/(?P<backup_id>[^/]+)/delete/$',
            backups.DeleteView.as_view(), name='backup_delete'),
    re_path(r'^$', views.IndexView.as_view(), name='index'),
    re_path(r'^engines/$', views.EnginesView.as_view(), name='engines'),
    re_path(r'^create/$', views.CreateView.as_view(), name='create'),
    re_path(r'^(?P<database_id>[^/]+)/credentials/$',
            views.CredentialsView.as_view(), name='credentials'),
    re_path(r'^(?P<database_id>[^/]+)/delete/$',
            views.DeleteView.as_view(), name='delete'),
    re_path(r'^(?P<database_id>[^/]+)/$',
            views.DetailView.as_view(), name='detail'),
]
