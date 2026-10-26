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

from unittest import mock

from django.contrib.messages.storage.fallback import FallbackStorage
from django.urls import reverse

from coast_dashboard.api import coast
from coast_dashboard.content.services import dotenv
from coast_dashboard.content.services import forms as service_forms
from coast_dashboard.tests import helpers

ROWS = [{'key': 'DEBUG', 'value': 'true', 'secret': False},
        {'key': 'GREETING', 'value': 'hi there', 'secret': False},
        {'key': 'PASSWORD', 'value': '********', 'secret': True}]


class DotenvTest(helpers.TestCase):
    def test_parse_comments_quotes_and_export(self):
        values, errors = dotenv.parse(
            '# comment\n\nexport A=1\nB = two  # trailing\n'
            'C="quoted # not comment\\nline"\nD=\'single $x\'\nE=\n')
        self.assertEqual([], errors)
        self.assertEqual({'A': '1', 'B': 'two',
                          'C': 'quoted # not comment\nline',
                          'D': 'single $x', 'E': ''}, values)

    def test_parse_reports_line_errors(self):
        values, errors = dotenv.parse(
            'GOOD=1\n1BAD=x\nnoequals\nQ="open\nGOOD=2\n')
        text = ' '.join(str(e) for e in errors)
        for fragment in ('Line 2', 'Line 3', 'Line 4', 'Line 5'):
            self.assertIn(fragment, text)
        self.assertEqual(4, len(errors))

    def test_render_round_trips_and_masks_secrets(self):
        text = dotenv.render(ROWS)
        self.assertIn('PASSWORD=********', text)
        self.assertIn('GREETING="hi there"', text)
        values, errors = dotenv.parse(text)
        self.assertEqual([], errors)
        self.assertEqual({}, dotenv.diff(ROWS, values))

    def test_diff_replaces_the_full_set(self):
        body = dotenv.diff(ROWS, {'DEBUG': 'false', 'PASSWORD': 'new',
                                  'NEW': 'x'})
        self.assertEqual({
            'DEBUG': {'value': 'false', 'secret': False},
            'PASSWORD': {'value': 'new', 'secret': True},
            'NEW': {'value': 'x', 'secret': False},
            'GREETING': None}, body)

    @mock.patch.object(coast, 'service_env_update', return_value=True)
    def test_form_saves_diff_and_rejects_errors(self, update):
        self.request.session = {}
        self.request._messages = FallbackStorage(self.request)
        form = service_forms.EnvDeveloperView(
            self.request, service_id='s', rows=ROWS,
            data={'dotenv_text': 'DEBUG=true\nBAD KEY=1\n'})
        self.assertFalse(form.is_valid())
        self.assertIn('Line 2', str(form.errors))
        update.assert_not_called()
        form = service_forms.EnvDeveloperView(
            self.request, service_id='s', rows=ROWS,
            data={'dotenv_text': 'DEBUG=true\nPASSWORD=********\n'})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(form.handle(self.request, form.cleaned_data))
        update.assert_called_once_with(mock.ANY, 's', {'GREETING': None})
        html = str(form['dotenv_text'])
        for attr in ('autocomplete="off"', 'data-1p-ignore',
                     'data-lpignore="true"', 'data-bwignore'):
            self.assertIn(attr, html)

    @mock.patch.object(coast, 'service_get', return_value={'kind': 'app'})
    @mock.patch.object(coast, 'service_env_list', return_value=ROWS)
    def test_view_prefills_text(self, env, service):
        url = reverse('horizon:project:coast.apps:env_developer',
                      args=['s'])
        res = self.client.get(url)
        self.assertEqual(200, res.status_code)
        self.assertContains(res, 'PASSWORD=********')
        self.assertContains(res, 'data-lpignore')


class BuildTimeDotenvTests(helpers.TestCase):
    def test_app_round_trip_preserves_runtime_and_masked_secret(self):
        rows = [dict(key='A', value='x # build-time', secret=False,
                     build_time=False),
                dict(key='S', value=dotenv.MASK, secret=True,
                     build_time=False)]
        text = dotenv.render(rows, app=True)
        self.assertIn(' # runtime-only', text)
        flags = {}
        values, errors = dotenv.parse(text, flags)
        self.assertEqual([], errors)
        self.assertEqual({'A': False, 'S': False}, flags)
        self.assertEqual({}, dotenv.diff(rows, values, flags))
        self.assertNotIn('# runtime-only', dotenv.render(rows))

    @mock.patch.object(coast, 'service_env_update', return_value=False)
    def test_unknown_flags_round_trip_and_value_edits_omit_flag(self, update):
        self.request._messages = FallbackStorage(self.request)
        rows = [dict(key='A', value='old', secret=False),
                dict(key='B', value='old', secret=False, build_time=None),
                dict(key='S', value=dotenv.MASK, secret=True,
                     build_time=None)]
        text = dotenv.render(rows, app=True)
        flags = {}
        values, errors = dotenv.parse(text, flags)
        self.assertEqual([], errors)
        self.assertEqual({}, flags)
        self.assertEqual({}, dotenv.diff(rows, values, flags))
        form = service_forms.EnvDeveloperView(
            self.request, service_id='s', app=True, rows=rows,
            data={'dotenv_text': text.replace('=old', '=new')})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(form.handle(self.request, form.cleaned_data))
        update.assert_called_once_with(self.request, 's', {
            'A': {'value': 'new', 'secret': False},
            'B': {'value': 'new', 'secret': False}})
        for flag in (True, False):
            self.assertEqual({'S': {'build_time': flag}}, dotenv.diff(
                rows, values, {'S': flag}))

    def test_directives_and_plain_lines(self):
        flags = {}
        values, errors = dotenv.parse(
            'A=x # build-time\nB="x # runtime-only"\n'
            "C='z' # runtime-only\nD=new\nE= # runtime-only\n", flags)
        self.assertEqual([], errors)
        self.assertEqual({'A': True, 'C': False, 'E': False}, flags)
        self.assertEqual('', values['E'])
        rows = [dict(key='B', value='old', secret=False, build_time=False)]
        body = dotenv.diff(rows, values, flags)
        self.assertNotIn('build_time', body['B'])
        self.assertTrue(body['D']['build_time'])
        self.assertFalse(body['C']['build_time'])

    def test_masked_secret_can_change_only_flag(self):
        rows = [dict(key='S', value=dotenv.MASK, secret=True, build_time=True)]
        self.assertEqual({'S': {'build_time': False}}, dotenv.diff(
            rows, {'S': dotenv.MASK}, {'S': False}))

    @mock.patch.object(coast, 'service_env_update', return_value=False)
    def test_app_editor_saves_flags_service_ignores_them(self, update):
        self.request._messages = FallbackStorage(self.request)
        for app, expected in [(True, {'build_time': False}), (False, {})]:
            form = service_forms.EnvDeveloperView(
                self.request, service_id='s', app=app,
                data={'dotenv_text': 'A=x # runtime-only'})
            self.assertTrue(form.is_valid(), form.errors)
            self.assertTrue(form.handle(self.request, form.cleaned_data))
            update.assert_called_with(self.request, 's', {
                'A': dict(value='x', secret=False, **expected)})


class MarkerDotenvTests(helpers.TestCase):
    def test_markers_combine_in_any_order(self):
        flags, secrets = {}, set()
        values, errors = dotenv.parse(
            'A=1 # secret, runtime-only\nB=2 # runtime-only,secret\n'
            'C=3 # secret\nD=4 # build-time , secret\nE=5 # a note\n'
            'F="x # secret"\n', flags, secrets)
        self.assertEqual([], errors)
        self.assertEqual({'A', 'B', 'C', 'D'}, secrets)
        self.assertEqual({'A': False, 'B': False, 'D': True}, flags)
        self.assertEqual('x # secret', values['F'])
        self.assertEqual('5', values['E'])

    def test_conflicting_build_markers_error(self):
        values, errors = dotenv.parse('A=1 # runtime-only, build-time',
                                      {}, set())
        self.assertEqual(1, len(errors))
        self.assertIn('both runtime-only and build-time', str(errors[0]))

    def test_secret_marker_without_tracking_is_a_comment(self):
        values, errors = dotenv.parse('A=1 # secret')
        self.assertEqual({'A': '1'}, values)
        self.assertEqual([], errors)

    def test_diff_secret_marker_new_and_existing_keys(self):
        rows = [dict(key='P', value='plain', secret=False, build_time=True),
                dict(key='S', value=dotenv.MASK, secret=True,
                     build_time=True)]
        flags, secrets = {}, set()
        values, errors = dotenv.parse(
            'N=new # secret, runtime-only\nP=plain # secret\n'
            'S=******** # secret\n', flags, secrets)
        self.assertEqual([], errors)
        body = dotenv.diff(rows, values, flags, secrets)
        self.assertEqual({'value': 'new', 'secret': True,
                          'build_time': False}, body['N'])
        self.assertEqual({'value': 'plain', 'secret': True}, body['P'])
        self.assertNotIn('S', body)

    def test_render_emits_combined_markers_and_round_trips(self):
        rows = [dict(key='S', value=dotenv.MASK, secret=True,
                     build_time=False),
                dict(key='T', value=dotenv.MASK, secret=True,
                     build_time=True)]
        text = dotenv.render(rows, app=True)
        self.assertIn('S=******** # secret, runtime-only', text)
        self.assertIn('T=******** # secret\n', text)
        flags, secrets = {}, set()
        values, errors = dotenv.parse(text, flags, secrets)
        self.assertEqual([], errors)
        self.assertEqual({}, dotenv.diff(rows, values, flags, secrets))
