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

"""Public labels for stack events. Never mark API text as safe HTML."""

import json
import re

from django.utils.translation import gettext_lazy as _

from coast_dashboard import public_text


scrub = public_text.scrub


def present(event, servers):
    detail = event.get('detail') or {}
    server = servers.get(event.get('resource_id'), {})
    action = str(event.get('action') or '').replace('_', ' ')
    label = _('Stack')
    if event.get('resource_type') == 'server':
        name = (detail.get('server_name') or detail.get('resource_name') or
                detail.get('name') or
                server.get('name') or event.get('resource_id') or '')
        role = detail.get('role') or detail.get('server_role') or server.get(
            'role', '')
        text = '%s %s %s' % (role, name, action)
        engine = (public_text.contains_engine_name(text) or
                  re.search(r'engine|controller|control', text,
                            re.IGNORECASE))
        label = (_('App engine server') if engine else
                 _('Server %(name)s') % {'name': name})
    if (event.get('resource_type') == 'stack' and
            (public_text.contains_engine_name(action) or
             re.search(r'engine|controller', action, re.IGNORECASE))):
        label = _('App engine server')
    action = {'create': _('created'), 'add': _('added'),
              'delete': _('deleted'), 'remove': _('removed'),
              'update': _('updated')}.get(action, action)
    outcome = scrub(event.get('outcome') or _('Unknown'))
    color = {'success': 'success', 'succeeded': 'success',
             'error': 'danger', 'failed': 'danger',
             'failure': 'danger', 'pending': 'warning',
             'started': 'warning'}.get(outcome.lower(), 'default')
    fields = []
    for key, value in detail.items():
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        fields.append((scrub(key), scrub(value)))
    return {'time': event.get('created_at'),
            'what': scrub('%s %s' % (label, action)),
            'outcome': outcome, 'color': color,
            'message': scrub(event.get('message') or ''), 'fields': fields}
