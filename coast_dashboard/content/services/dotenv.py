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

"""Parse and render the .env text used by the Developer view."""
import re

from django.utils.translation import gettext_lazy as _

KEY = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
MASK = '********'
_ESCAPES = {'n': '\n', 't': '\t', 'r': '\r', '"': '"', '\\': '\\'}


def _double_quoted(text, number):
    out, i = [], 1
    while i < len(text):
        char = text[i]
        if char == '\\' and i + 1 < len(text):
            out.append(_ESCAPES.get(text[i + 1], '\\' + text[i + 1]))
            i += 2
            continue
        if char == '"':
            rest = text[i + 1:].strip()
            if rest and not rest.startswith('#'):
                raise ValueError(_('Line %d: unexpected text after the '
                                   'closing quote.') % number)
            return ''.join(out)
        out.append(char)
        i += 1
    raise ValueError(_('Line %d: missing closing quote.') % number)


def _single_quoted(text, number):
    end = text.find("'", 1)
    if end < 0:
        raise ValueError(_('Line %d: missing closing quote.') % number)
    rest = text[end + 1:].strip()
    if rest and not rest.startswith('#'):
        raise ValueError(_('Line %d: unexpected text after the closing '
                           'quote.') % number)
    return text[1:end]


MARKERS = ('secret', 'runtime-only', 'build-time')


def markers(comment):
    """Return the set of flag markers in a trailing comment, or None.

    A marker comment is "# " followed by known markers separated by commas,
    in any order, e.g. "# secret, runtime-only". Any other comment is a
    plain comment and returns None.
    """
    text = comment.strip()
    if not text.startswith('#'):
        return None
    words = [w.strip().lower() for w in text[1:].split(',')]
    if not words or not all(w in MARKERS for w in words):
        return None
    return set(words)


def parse(text, build_times=None, secrets=None):
    """Return (ordered dict of key -> value, list of line errors).

    build_times and secrets, when given, are filled from trailing markers:
    build_times[key] is True/False, secrets is a set of keys marked secret.
    """
    values, errors = {}, []
    for number, raw in enumerate((text or '').splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[len('export '):].lstrip()
        if '=' not in line:
            errors.append(_('Line %d: expected KEY=value.') % number)
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if not KEY.match(key) or len(key) > 255:
            errors.append(_('Line %(n)d: "%(key)s" is not a valid key. Use '
                            'letters, numbers and underscores, starting '
                            'with a letter or underscore.') %
                          {'n': number, 'key': key[:60]})
            continue
        unquoted = value
        value = value.strip()
        original = value
        try:
            if value.startswith('"'):
                value = _double_quoted(value, number)
            elif value.startswith("'"):
                value = _single_quoted(value, number)
            else:
                value = re.split(r'\s+#', unquoted, maxsplit=1)[0].strip()
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if key in values:
            errors.append(_('Line %(n)d: %(key)s is defined twice.') %
                          {'n': number, 'key': key})
            continue
        values[key] = value
        if build_times is not None or secrets is not None:
            # Find only comments outside quotes, never text in the value.
            if original.startswith(('"', "'")):
                quote, i = original[0], 1
                while i < len(original):
                    if quote == '"' and original[i] == '\\':
                        i += 2
                        continue
                    if original[i] == quote:
                        break
                    i += 1
                comment = original[i + 1:].strip()
            else:
                parts = re.split(r'\s+#', unquoted, maxsplit=1)
                comment = '#' + parts[1] if len(parts) > 1 else ''
            found = markers(comment)
            if not found:
                continue
            if {'runtime-only', 'build-time'} <= found:
                errors.append(_('Line %(n)d: %(key)s cannot be both '
                                'runtime-only and build-time.') %
                              {'n': number, 'key': key})
                continue
            if build_times is not None and found & {'runtime-only',
                                                    'build-time'}:
                build_times[key] = 'build-time' in found
            if secrets is not None and 'secret' in found:
                secrets.add(key)
    return values, errors


def _quote(value):
    if value == MASK:
        return value
    if value and re.match(r'^[A-Za-z0-9_./:@%+,-]*$', value):
        return value
    escaped = (value.replace('\\', '\\\\').replace('"', '\\"')
               .replace('\n', '\\n').replace('\r', '\\r')
               .replace('\t', '\\t'))
    return '"%s"' % escaped


def render(rows, app=False):
    """Render env rows; secret values stay masked."""
    lines = []
    for row in rows:
        value = MASK if row.get('secret') else (row.get('value') or '')
        marks = ['secret'] if row.get('secret') else []
        if app and row.get('build_time') is False:
            marks.append('runtime-only')
        suffix = ' # ' + ', '.join(marks) if marks else ''
        lines.append('%s=%s%s' % (row['key'], _quote(value), suffix))
    return '\n'.join(lines) + ('\n' if lines else '')


def diff(rows, values, build_times=None, secrets=None):
    """Return the PATCH body that turns rows into values.

    A value that is exactly the mask always means unchanged, so an existing
    row keeps its saved value and a new key with the mask is skipped (the
    form reports it). Removed keys are sent as None. New keys are not
    secret unless marked "# secret"; a "# secret" marker on an existing
    plain key makes it secret. Unmarked lines never un-secret a key.
    """
    secrets = secrets or set()
    current = {row['key']: row for row in rows}
    body = {}
    for key, value in values.items():
        row = current.get(key)
        flags = {}
        if build_times is not None:
            flag = build_times.get(key, row.get('build_time')
                                   if row else True)
            if row is None or flag != row.get('build_time'):
                flags['build_time'] = flag
        if value == MASK:
            if flags and row is not None:
                body[key] = flags
            continue
        secret = key in secrets
        if row is None:
            body[key] = {'value': value, 'secret': secret}
        elif row.get('secret'):
            if value != MASK:
                body[key] = {'value': value, 'secret': True}
        elif secret or value != (row.get('value') or ''):
            body[key] = {'value': value, 'secret': secret}
        if flags:
            body.setdefault(key, {}).update(flags)
    for key in current:
        if key not in values:
            body[key] = None
    return body
