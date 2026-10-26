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

from coast_dashboard.content.services import backups
from coast_dashboard.content.services import containers
from coast_dashboard.content.services import files
from coast_dashboard.content.services import views

urlpatterns = [
    re_path(r'^(?P<service_id>[^/]+)/deploy-key/$',
            views.ReplaceDeployKeyView.as_view(), name='replace_deploy_key'),
    re_path(r'^(?P<service_id>[^/]+)/dockerfile/$',
            views.EditDockerfileView.as_view(), name='edit_dockerfile'),
    re_path(r'^(?P<service_id>[^/]+)/backups/$',
            backups.PolicyView.as_view(), name='backups'),
    re_path(r'^(?P<service_id>[^/]+)/backups/(?P<backup_id>[^/]+)/restore/$',
            backups.RestoreView.as_view(), name='backup_restore'),
    re_path(r'^(?P<service_id>[^/]+)/backups/(?P<backup_id>[^/]+)/download/$',
            backups.DownloadView.as_view(), name='backup_download'),
    re_path(r'^(?P<service_id>[^/]+)/backups/(?P<backup_id>[^/]+)/delete/$',
            backups.DeleteView.as_view(), name='backup_delete'),
    re_path(r'^(?P<service_id>[^/]+)/metrics/$',
            views.MetricsView.as_view(), name='metrics'),
    re_path(r'^(?P<service_id>[^/]+)/image/$',
            views.ChangeImageView.as_view(), name='change_image'),
    re_path(r'^(?P<service_id>[^/]+)/files/add/$',
            files.AddFileView.as_view(), name='add_file'),
    re_path(r'^(?P<service_id>[^/]+)/files/(?P<mount_id>[^/]+)/edit/$',
            files.EditFileView.as_view(), name='edit_file'),
    re_path(r'^(?P<service_id>[^/]+)/containers/(?P<container_id>c-[^/]+)/$',
            containers.DetailView.as_view(), name='container'),
    re_path(r'^(?P<service_id>[^/]+)/containers/(?P<container_id>c-[^/]+)/'
            r'logs/fragment/$', containers.LogsFragmentView.as_view(),
            name='container_logs_fragment'),
    re_path(r'^$', views.IndexView.as_view(), name='index'),
    re_path(r'^create/$', views.CreateView.as_view(), name='create'),
    re_path(r'^(?P<service_id>[^/]+)/env-developer/$',
            views.EnvDeveloperView.as_view(), name='env_developer'),
    re_path(r'^(?P<service_id>[^/]+)/env/(?P<key>[A-Za-z_][A-Za-z0-9_]*)/'
            r'build-time/$', views.EnvBuildTimeView.as_view(),
            name='env_build_time'),
    re_path(r'^(?P<service_id>[^/]+)/env/add/$',
            views.SetEnvView.as_view(), name='add_env'),
    re_path(r'^(?P<service_id>[^/]+)/env/(?P<key>[A-Za-z_][A-Za-z0-9_]*)/$',
            views.SetEnvView.as_view(), name='edit_env'),
    re_path(r'^(?P<service_id>[^/]+)/settings/edit/$',
            views.EditSettingsView.as_view(), name='edit_settings'),
    re_path(r'^(?P<service_id>[^/]+)/domains/add/$',
            views.AddDomainView.as_view(), name='add_domain'),
    re_path(r'^(?P<service_id>[^/]+)/storage/create/$',
            views.CreateStorageView.as_view(), name='create_storage'),
    re_path(r'^(?P<service_id>[^/]+)/storage/(?P<storage_id>[^/]+)/edit/$',
            views.EditStorageView.as_view(), name='edit_storage'),
    re_path(r'^(?P<service_id>[^/]+)/webhooks/regenerate/$',
            views.WebhooksRegenerateView.as_view(),
            name='webhooks_regenerate'),
    re_path(r'^(?P<service_id>[^/]+)/console/$',
            views.ConsoleView.as_view(), name='console'),
    re_path(r'^(?P<service_id>[^/]+)/logs/$', views.LogsView.as_view(),
            name='logs'),
    re_path(r'^(?P<service_id>[^/]+)/logs/fragment/$',
            views.LogsFragmentView.as_view(), name='logs_fragment'),
    re_path(r'^(?P<service_id>[^/]+)/deployments/(?P<deployment_id>[^/]+)/'
            r'log/fragment/$', views.DeploymentLogFragmentView.as_view(),
            name='deployment_log_fragment'),
    re_path(r'^(?P<service_id>[^/]+)/deployments/(?P<deployment_id>[^/]+)/'
            r'log/$', views.DeploymentLogView.as_view(),
            name='deployment_log'),
    re_path(r'^(?P<service_id>[^/]+)/deployments/(?P<deployment_id>[^/]+)/'
            r'cancel/$', views.DeploymentCancelView.as_view(),
            name='deployment_cancel'),
    re_path(r'^(?P<service_id>[^/]+)/deployments/(?P<deployment_id>[^/]+)/$',
            views.DeploymentView.as_view(), name='deployment'),
    re_path(r'^(?P<service_id>[^/]+)/domains/(?P<domain_id>[^/]+)/$',
            views.EditDomainView.as_view(), name='edit_domain'),
    re_path(r'^(?P<service_id>[^/]+)/$', views.DetailView.as_view(),
            name='detail'),
]
