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

"""Runtime log helpers shared by the Logs tab and views."""
from django.utils.translation import gettext_lazy as _

from coast_dashboard.api import coast
from coast_dashboard.content import common
from coast_dashboard.content.stacks import activity


def _scrub(value):
    # Build output can name the engine's helper images; never show them.
    if isinstance(value, str):
        return activity.scrub(value)
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    if isinstance(value, dict):
        return {key: _scrub(item) for key, item in value.items()}
    return value


LOG_TAIL = 200


def log_context(request, service_id, loader=None):
    """Return the last LOG_TAIL runtime lines, or a friendly error."""
    try:
        logs = (loader or coast.service_logs)(
            request, service_id, tail=LOG_TAIL)
    except Exception as exc:
        return {'log_error': coast.error_message(
            exc, _('Unable to retrieve logs.'))}
    # The API explains why the engine has no logs (e.g. restarting).
    if isinstance(logs, dict) and logs.get('unavailable'):
        return {'log_error': logs['unavailable']}
    return {'logs': logs}


def deployment_log_context(request, service_id, deployment_id):
    """Return build logs, with a normal empty state for templates."""
    try:
        service = coast.service_get(request, service_id)
    except Exception:
        service = {}
    template = common.is_template(service)
    context = {'is_template': template,
               'empty_text': (_('Template services have no build log')
                              if template else _('No build log lines yet.'))}
    try:
        context['logs'] = _scrub(coast.service_deployment_log(
            request, service_id, deployment_id))
    except Exception as exc:
        if not template:
            context['log_error'] = coast.error_message(
                exc, _('Unable to retrieve the build log.'))
    return context
