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

"""Customer-visible text boundary: no application engine product names.

Coast API text (faults, events, log notes) can quote the engine's own
errors. Project pages show it only after ``scrub``. The admin panel keeps
full detail because it reads with ``all_projects`` (see ``api.coast``).
"""

import re

from django.utils.translation import gettext_lazy as _

# The only place in the plugin that spells the engine and proxy names.
_ENGINE = 'coolify'
_PROXY = 'traefik'
ENGINE_NAME = re.compile('%s|%s' % (_ENGINE, _PROXY), re.IGNORECASE)

# Keys whose string values are prose, at any depth of an API body.
# template_name is the engine catalog's name for a one-click service.
TEXT_KEYS = frozenset((
    'detail', 'error', 'fault', 'faultstring', 'message', 'note', 'reason',
    'status_reason', 'template_name', 'unavailable'))
TEXT_SUFFIXES = ('_error', '_fault', '_message', '_note', '_reason')
# Customer data and engine-provided output; shown as is.
# ("environment" is a resource envelope, not data; variables are "env".)
DATA_KEYS = frozenset((
    'compose', 'env', 'labels', 'lines', 'output', 'stderr', 'stdout',
    'variables', 'yaml'))
# Engine-provided catalog prose; unlike customer resources, also scrubbed.
CATALOG_KEYS = ('name', 'description', 'category')


def contains_engine_name(value):
    return bool(ENGINE_NAME.search(str(value or '')))


def scrub(value):
    """Replace engine and proxy names with neutral wording."""
    value = re.sub(_ENGINE, str(_('App engine server')), str(value),
                   flags=re.IGNORECASE)
    return re.sub(_PROXY, str(_('proxy')), value, flags=re.IGNORECASE)


def display(value):
    """``value`` for a page; identifiers such as template ids included."""
    return scrub(value) if contains_engine_name(value) else value


def is_text_key(key):
    key = str(key)
    return key in TEXT_KEYS or key.endswith(TEXT_SUFFIXES)


def _scrub_all(value):
    if isinstance(value, str):
        return scrub(value) if contains_engine_name(value) else value
    if isinstance(value, list):
        return [_scrub_all(item) for item in value]
    if isinstance(value, dict):
        return {key: _scrub_all(item) for key, item in value.items()}
    return value


def scrub_tree(value):
    """Scrub prose fields of a decoded API body; leave data fields alone."""
    if isinstance(value, list):
        return [scrub_tree(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key in DATA_KEYS:
            result[key] = item
        elif is_text_key(key):
            result[key] = _scrub_all(item)
        else:
            result[key] = scrub_tree(item)
    return result


def scrub_catalog(templates):
    """Scrub the engine's own one-click catalog names and descriptions."""
    result = []
    for template in templates:
        if isinstance(template, dict):
            template = dict(template)
            for key in CATALOG_KEYS:
                if isinstance(template.get(key), str):
                    template[key] = _scrub_all(template[key])
        result.append(template)
    return result
