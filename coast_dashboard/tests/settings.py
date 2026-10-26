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

from openstack_dashboard.test.settings import *  # noqa: F403,H303

import openstack_dashboard.enabled
from openstack_dashboard.utils import settings as settings_utils

import coast_dashboard.enabled

# Rebuild the app list from scratch so both enabled sets load once.
INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.auth',
    'django.contrib.sessions',
    'django.contrib.staticfiles',
    'django.contrib.messages',
    'django.contrib.humanize',
    'openstack_auth',
    'compressor',
    'horizon',
    'openstack_dashboard',
]
HORIZON_CONFIG.pop('dashboards', None)  # noqa: F405
HORIZON_CONFIG.pop('default_dashboard', None)  # noqa: F405
settings_utils.update_dashboards(
    [openstack_dashboard.enabled, coast_dashboard.enabled],
    HORIZON_CONFIG,  # noqa: F405
    INSTALLED_APPS,
)
