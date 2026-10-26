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
from coast_dashboard.content.services import forms
from coast_dashboard.content.services import tables
from coast_dashboard.tests import helpers
from coast_dashboard.tests.test_api import _resp


class SettingsTests(helpers.TestCase):
    def setUp(self):
        super().setUp()
        self.request._messages = FallbackStorage(self.request)
        for method, value in [('service_get', {
                'id': 's', 'name': 'web', 'status': 'ACTIVE', 'kind': 'app'}),
                ('service_deployment_list', [])]:
            patcher = mock.patch.object(coast, method, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    @mock.patch.object(coast, 'coastclient')
    def test_env_patch_and_delete(self, client):
        response = _resp({'env': {}})
        client.return_value.request.return_value = response
        for header, expected in [('true', True), ('false', False),
                                 ('', False)]:
            response.headers = {'X-Coast-Redeploy-Required': header}
            env = {'KEY': {'value': '  value  ', 'secret': True}}
            self.assertEqual(expected, coast.service_env_update(
                self.request, 's', env))
            client.return_value.request.assert_called_with(
                '/services/s/env', 'PATCH', json={'env': env})
        coast.service_env_delete(self.request, 's', 'KEY')
        client.return_value.request.assert_called_with(
            '/services/s/env', 'PATCH', json={'env': {'KEY': None}})

    @mock.patch.object(coast, 'coastclient')
    def test_domain_writes(self, client):
        client.return_value.request.return_value = _resp(
            {'domain': {'id': 'd'}})
        self.assertEqual({'id': 'd'}, coast.service_domain_create(
            self.request, 's', 'app.example.com'))
        client.return_value.request.assert_called_with(
            '/services/s/domains', 'POST',
            json={'domain': {'fqdn': 'app.example.com'}})
        coast.service_domain_delete(self.request, 's', 'd')
        client.return_value.request.assert_called_with(
            '/services/s/domains/d', 'DELETE')
        client.reset_mock()
        client.return_value.request.return_value = _resp(
            {'domain': {'id': 'd', 'tls': 'none'}})
        self.assertEqual(
            {'id': 'd', 'tls': 'none'},
            coast.service_domain_create(
                self.request, 's', 'app.example.com', tls='none'))
        # The client only accepts 1.0/1.1 at construction; 1.2 is per call.
        self.assertEqual('1.0', client.call_args.args[1])
        client.return_value.request.assert_called_with(
            '/services/s/domains', 'POST',
            json={'domain': {'fqdn': 'app.example.com', 'tls': 'none'}},
            domain_tls_microversion='1.2')
        coast.service_domain_update(
            self.request, 's', 'd', 'letsencrypt')
        client.return_value.request.assert_called_with(
            '/services/s/domains/d', 'PATCH',
            json={'domain': {'tls': 'letsencrypt'}},
            domain_tls_microversion='1.2')
        coast.service_domain_verify(self.request, 's', 'd')
        client.return_value.request.assert_called_with(
            '/services/s/domains/d/action', 'POST', json={'verify': {}})

    @mock.patch.object(coast, 'service_env_update', return_value=True)
    def test_env_form(self, update):
        for value in ('', '  secret value  '):
            form = forms.SetEnv(self.request, service_id='s', data={
                'key': 'KEY', 'value': value, 'secret': True})
            self.assertTrue(form.is_valid(), form.errors)
            self.assertTrue(form.handle(self.request, form.cleaned_data))
            update.assert_called_with(self.request, 's', {
                'KEY': {'value': value, 'secret': True}})
        self.assertIn('Redeploy to apply',
                      ' '.join(str(m) for m in self.request._messages))
        for key in ('', 'bad-key', '1KEY', 'A' * 256):
            form = forms.SetEnv(self.request, service_id='s',
                                data={'key': key})
            self.assertFalse(form.is_valid())

    @mock.patch.object(coast, 'service_env_update', return_value=False)
    def test_edit_key_is_fixed(self, update):
        form = forms.SetEnv(self.request, service_id='s',
                            initial={'key': 'OLD', 'secret': True},
                            data={'key': 'NEW', 'value': 'v', 'secret': True})
        self.assertTrue(form.is_valid(), form.errors)
        form.handle(self.request, form.cleaned_data)
        update.assert_called_once_with(self.request, 's', {
            'OLD': {'value': 'v', 'secret': True}})
        self.assertNotIn('Redeploy to apply',
                         ' '.join(str(m) for m in self.request._messages))

    @mock.patch.object(coast, 'service_domain_create',
                       return_value={'id': 'd'})
    def test_domain_form(self, create):
        form = forms.AddDomain(self.request, service_id='s', data={
            'fqdn': 'app.example.com', 'tls': 'letsencrypt'})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(form.handle(self.request, form.cleaned_data))
        create.assert_called_once_with(
            self.request, 's', 'app.example.com', tls=None)
        create.reset_mock()
        form = forms.AddDomain(self.request, service_id='s', data={
            'fqdn': 'app.example.com', 'tls': 'none'})
        self.assertTrue(form.is_valid(), form.errors)
        form.handle(self.request, form.cleaned_data)
        create.assert_called_once_with(
            self.request, 's', 'app.example.com', tls='none')
        for fqdn in ('localhost', 'https://app.example.com',
                     '-bad.example.com'):
            form = forms.AddDomain(self.request, service_id='s',
                                   data={'fqdn': fqdn})
            self.assertFalse(form.is_valid())

    def test_form_errors_hide_api_details(self):
        for cls, method, data in [
                (forms.SetEnv, 'service_env_update', {'key': 'KEY'}),
                (forms.AddDomain, 'service_domain_create',
                 {'fqdn': 'app.example.com', 'tls': 'letsencrypt'})]:
            with mock.patch.object(coast, method,
                                   side_effect=RuntimeError('private-value')):
                form = cls(self.request, service_id='s', data=data)
                self.assertTrue(form.is_valid(), form.errors)
                self.assertFalse(form.handle(self.request, form.cleaned_data))
                self.assertNotIn('private-value', str(form.errors))

    @mock.patch.object(coast, 'service_domain_list', return_value=[])
    @mock.patch.object(coast, 'service_env_list', return_value=[
        {'key': 'PASSWORD', 'value': '********', 'secret': True}])
    def test_settings_tab_has_developer_view(self, env, domains):
        url = reverse('horizon:project:coast.apps:detail', args=['s'])
        res = self.client.get(url, {'tab': 'service_details__settings'})
        self.assertContains(res, 'Developer View')
        self.assertContains(res, 'PASSWORD=********')
        self.assertContains(res, 'are stripped.')
        self.assertContains(res, reverse(
            'horizon:project:coast.apps:env_developer', args=['s']))
        self.assertNotContains(res, 'Coolify')
        self.assertRegex(res.content.decode(),
                         r'name="csrfmiddlewaretoken" value="[^"]+"')
        res = self.client.get(url, {'tab': 'service_details__settings',
                                    'view': 'developer'})
        self.assertContains(res, 'class="coast-env-normal" style='
                            '"display:none;"')

    @mock.patch.object(coast, 'service_env_update', return_value=False)
    @mock.patch.object(coast, 'service_env_list', return_value=[])
    def test_developer_save_returns_to_env_tab(self, env, update):
        url = reverse('horizon:project:coast.apps:env_developer',
                      args=['s'])
        res = self.client.post(url, {'dotenv_text': 'A=1\n'})
        self.assertRedirects(
            res, reverse('horizon:project:coast.apps:detail',
                         args=['s']) +
            '?tab=service_details__settings&view=developer',
            fetch_redirect_response=False)

    @mock.patch.object(coast, 'service_domain_list', return_value=[])
    @mock.patch.object(coast, 'service_env_list', return_value=[
        {'key': 'PASSWORD', 'value': '********', 'secret': True}])
    def test_settings_tab(self, env, domains):
        url = reverse('horizon:project:coast.apps:detail', args=['s'])
        res = self.client.get(url, {'tab': 'service_details__settings'})
        self.assertEqual(200, res.status_code)
        self.assertContains(res, 'PASSWORD')
        self.assertContains(res, '********')
        env.assert_called_once_with(mock.ANY, 's')
        # The Overview lists custom domains as links, so domains load too.
        domains.reset_mock()
        self.client.get(url, {'tab': 'service_details__domains'})
        domains.assert_called_with(mock.ANY, 's')

    @mock.patch.object(coast, 'service_domain_list',
                       side_effect=RuntimeError())
    @mock.patch.object(coast, 'service_env_list', side_effect=RuntimeError())
    def test_tab_read_errors(self, env, domains):
        url = reverse('horizon:project:coast.apps:detail', args=['s'])
        res = self.client.get(url, {'tab': 'service_details__settings'})
        self.assertContains(res, 'Unable to retrieve environment variables.')
        res = self.client.get(url, {'tab': 'service_details__domains'})
        self.assertContains(res, 'Unable to retrieve domains.')

    @mock.patch.object(coast, 'service_env_list', return_value=[
        {'key': 'PASSWORD', 'value': 'private-value', 'secret': True}])
    def test_edit_secret_is_blank_with_placeholder(self, env):
        url = reverse('horizon:project:coast.apps:edit_env',
                      args=['s', 'PASSWORD'])
        res = self.client.get(url)
        self.assertEqual(200, res.status_code)
        self.assertNotContains(res, 'private-value')
        self.assertTrue(res.context['form'].initial['secret'])
        self.assertContains(res, 'Leave blank to keep the current value')

    @mock.patch.object(coast, 'service_env_update', return_value=True)
    @mock.patch.object(coast, 'service_env_list', return_value=[
        {'key': 'PASSWORD', 'value': '********', 'secret': True}])
    def test_edit_secret_blank_keeps_value(self, env, update):
        url = reverse('horizon:project:coast.apps:edit_env',
                      args=['s', 'PASSWORD'])
        res = self.client.post(url, {'value': '', 'secret': 'on'})
        self.assertEqual(302, res.status_code)
        update.assert_not_called()
        res = self.client.post(url, {'value': ''})
        self.assertEqual(200, res.status_code)
        update.assert_not_called()
        self.client.post(url, {'value': 'new', 'secret': 'on',
                               'build_time': 'on'})
        update.assert_called_once_with(mock.ANY, 's', {
            'PASSWORD': {'value': 'new', 'secret': True,
                         'build_time': True}})

    @mock.patch.object(coast, 'service_env_list', return_value=[
        {'key': 'PORT', 'value': '8080', 'secret': False}])
    def test_edit_plain_prefills_value(self, env):
        url = reverse('horizon:project:coast.apps:edit_env',
                      args=['s', 'PORT'])
        res = self.client.get(url)
        self.assertEqual('8080', res.context['form'].initial['value'])
        self.assertContains(res, 'value="8080"')

    @mock.patch.object(coast, 'service_env_delete', return_value=True)
    @mock.patch.object(coast, 'service_domain_delete')
    def test_delete_actions(self, domain, env):
        table = tables.EnvTable(self.request, service_id='s')
        action = tables.DeleteEnv()
        action.table = table
        action.delete(self.request, 'KEY')
        env.assert_called_once_with(self.request, 's', 'KEY')
        action = tables.RemoveDomain()
        action.table = tables.DomainsTable(self.request, service_id='s')
        action.delete(self.request, 'd')
        domain.assert_called_once_with(self.request, 's', 'd')

    @mock.patch.object(coast, 'service_env_update', return_value=True)
    def test_add_env_post_redirects_to_settings(self, update):
        url = reverse('horizon:project:coast.apps:add_env', args=['s'])
        res = self.client.post(url, {'key': 'KEY', 'value': 'v',
                                     'build_time': 'on'})
        self.assertEqual(302, res.status_code)
        self.assertTrue(res.url.endswith('?tab=service_details__settings'))
        update.assert_called_once_with(mock.ANY, 's', {
            'KEY': {'value': 'v', 'secret': False, 'build_time': True}})

    @mock.patch.object(coast, 'service_env_list', return_value=[
        {'key': 'KEY', 'value': 'v', 'secret': False}])
    @mock.patch.object(coast, 'service_domain_list', return_value=[])
    @mock.patch.object(coast, 'service_env_delete', return_value=True)
    def test_tab_delete_post(self, delete, domains, env):
        url = reverse('horizon:project:coast.apps:detail', args=['s'])
        res = self.client.post(url + '?tab=service_details__settings',
                               {'action': 'env__delete__KEY'})
        self.assertEqual(302, res.status_code)
        delete.assert_called_once_with(mock.ANY, 's', 'KEY')

    @mock.patch.object(coast, 'service_domain_list', return_value=[{
        'id': 'dom', 'fqdn': 'app.example.com',
        'status': 'PENDING_VERIFICATION', 'tls': 'letsencrypt',
        'dns_records': [{
            'type': 'TXT', 'name': '_coast-challenge.app.example.com',
            'value': 'token-1', 'purpose': 'verification'}]}])
    def test_pending_domain_guidance_and_verify(self, domains):
        url = reverse('horizon:project:coast.apps:detail', args=['s'])
        with mock.patch.object(
                coast, 'service_get', return_value={
                    'id': 's', 'name': 'web', 'status': 'ACTIVE',
                    'kind': 'app', 'server_id': 'worker', 'stack_id': 'stack',
                    'dns_records': [{'type': 'A', 'value': '192.0.2.58',
                                     'purpose': 'routing'}]}), \
                mock.patch.object(coast, 'stack_server_list', return_value=[{
                    'id': 'worker', 'name': 'worker-2',
                    'floating_ip': '192.0.2.58'}]):
            res = self.client.get(url, {'tab': 'service_details__domains'})
        self.assertContains(res, 'data-copy-value="192.0.2.58"')
        self.assertContains(res, 'data-copy-value="https://app.example.com"')
        self.assertContains(res, 'Waiting for DNS verification - create an '
                            'A record for app.example.com pointing to '
                            '192.0.2.58')
        self.assertContains(res, '_coast-challenge.app.example.com')
        self.assertContains(res, 'token-1')
        self.assertContains(res, 'Let&#x27;s Encrypt')
        self.assertContains(res, 'label-warning')
        with mock.patch.object(coast, 'service_domain_verify') as verify:
            posted = self.client.post(
                url + '?tab=service_details__domains',
                {'action': 'domains__verify__dom'}, follow=True)
        self.assertEqual(200, posted.status_code)
        self.assertNotContains(posted, 'Unable to verify the domain.')
        verify.assert_called_once_with(mock.ANY, 's', 'dom')

    @mock.patch.object(coast, 'service_domain_verify',
                       side_effect=coast.CoastError('DNS is not ready'))
    @mock.patch.object(coast, 'service_domain_list', return_value=[{
        'id': 'dom', 'fqdn': 'app.example.com',
        'status': 'PENDING_VERIFICATION', 'tls': 'none'}])
    def test_verify_shows_the_api_message(self, domains, verify):
        url = reverse('horizon:project:coast.apps:detail', args=['s'])
        res = self.client.post(url + '?tab=service_details__domains',
                               {'action': 'domains__verify__dom'},
                               follow=True)
        self.assertContains(res, 'DNS is not ready')
        self.assertNotContains(res, 'Unable to verify the domain.')

    @mock.patch.object(coast, 'service_domain_get', return_value={
        'id': 'dom', 'fqdn': 'app.example.com', 'tls': 'none'})
    @mock.patch.object(coast, 'service_domain_update',
                       return_value={'id': 'dom'})
    def test_edit_domain_certificate(self, update, get):
        url = reverse('horizon:project:coast.apps:edit_domain',
                      args=['s', 'dom'])
        res = self.client.get(url)
        self.assertEqual('none', res.context['form'].initial['tls'])
        self.assertContains(res, 'None (HTTP only)')
        self.assertContains(res, 'plain HTTP on port 80')
        posted = self.client.post(url, {
            'fqdn': 'app.example.com', 'tls': 'letsencrypt'})
        self.assertEqual(302, posted.status_code)
        update.assert_called_once_with(mock.ANY, 's', 'dom', 'letsencrypt')

    @mock.patch.object(coast, 'service_webhooks', return_value={
        'enabled': True, 'token': 'tok',
        'deploy': 'http://api/v1/apps/s/deploy?token=tok',
        'github': 'http://api/v1/hooks/s/github?token=tok',
        'gitlab': 'http://api/v1/hooks/s/gitlab?token=tok',
        'bitbucket': 'http://api/v1/hooks/s/bitbucket?token=tok',
        'gitea': 'http://api/v1/hooks/s/gitea?token=tok'})
    @mock.patch.object(coast, 'service_domain_list', return_value=[])
    def test_webhooks_tab(self, domains, hooks):
        url = reverse('horizon:project:coast.apps:detail', args=['s'])
        res = self.client.get(url, {'tab': 'service_details__webhooks'})
        for name in ('Coast deploy URL', 'GitHub', 'GitLab', 'Bitbucket',
                     'Gitea', '/v1/apps/s/deploy?token=tok',
                     'Regenerate token'):
            self.assertContains(res, name)
        for key in ('deploy', 'github', 'gitlab', 'bitbucket', 'gitea'):
            self.assertContains(res, 'data-copy-value="%s"' %
                                hooks.return_value[key])
        self.assertNotContains(res, 'Coolify')
        hooks.side_effect = coast.CoastError('forbidden')
        res = self.client.get(url, {'tab': 'service_details__webhooks'})
        self.assertContains(res, 'only shown to project members')

    @mock.patch.object(coast, 'service_webhooks_regenerate',
                       return_value={'enabled': True})
    def test_webhooks_regenerate(self, regen):
        url = reverse('horizon:project:coast.apps:webhooks_regenerate',
                      args=['s'])
        res = self.client.post(url)
        self.assertTrue(res.url.endswith('?tab=service_details__webhooks'))
        regen.assert_called_once_with(mock.ANY, 's')
        self.assertEqual(405, self.client.get(url).status_code)

    @mock.patch.object(coast, 'service_env_update', return_value=True)
    @mock.patch.object(coast, 'service_env_list', return_value=[
        {'key': 'PORT', 'value': '8080', 'secret': False},
        {'key': 'PASSWORD', 'value': '********', 'secret': True}])
    def test_mask_value_is_unchanged_in_edit_form(self, env, update):
        for key in ('PORT', 'PASSWORD'):
            url = reverse('horizon:project:coast.apps:edit_env',
                          args=['s', key])
            data = {'value': '********'}
            if key == 'PASSWORD':
                data['secret'] = 'on'
            self.assertEqual(302, self.client.post(url, data).status_code)
        update.assert_not_called()
        url = reverse('horizon:project:coast.apps:add_env', args=['s'])
        res = self.client.post(url, {'key': 'NEW', 'value': '********'})
        self.assertEqual(200, res.status_code)
        update.assert_not_called()

    @mock.patch.object(coast, 'service_env_update', return_value=True)
    @mock.patch.object(coast, 'service_env_list', return_value=[
        {'key': 'PORT', 'value': '8080', 'secret': False}])
    def test_mask_value_is_unchanged_in_developer_view(self, env, update):
        url = reverse('horizon:project:coast.apps:env_developer',
                      args=['s'])
        self.client.post(url, {'dotenv_text': 'PORT=********\n'})
        update.assert_not_called()
        res = self.client.post(url, {'dotenv_text':
                                     'PORT=8080\nNEW=********\n'})
        self.assertEqual(200, res.status_code)
        update.assert_not_called()


class BuildTimeSettingsTests(helpers.TestCase):
    def setUp(self):
        super().setUp()
        self.request._messages = FallbackStorage(self.request)
        patcher = mock.patch.object(coast, 'service_get',
                                    return_value={'kind': 'app'})
        patcher.start()
        self.addCleanup(patcher.stop)

    @mock.patch.object(coast, 'service_env_update', return_value=True)
    def test_app_form_flags_and_unchanged_secret(self, update):
        form = forms.SetEnv(self.request, service_id='s', app=True)
        self.assertTrue(form['build_time'].value())
        self.assertNotIn('build_time', forms.SetEnv(
            self.request, service_id='s').fields)
        for enabled in (True, False):
            form = forms.SetEnv(
                self.request, service_id='s', app=True,
                data={'key': 'A', 'value': 'x', 'build_time': enabled})
            self.assertTrue(form.is_valid(), form.errors)
            form.handle(self.request, form.cleaned_data)
            update.assert_called_with(self.request, 's', {
                'A': {'value': 'x', 'secret': False, 'build_time': enabled}})
        form = forms.SetEnv(
            self.request, service_id='s', app=True,
            initial={'key': 'S', 'secret': True, 'build_time': True},
            data={'secret': True, 'value': '', 'build_time': False})
        self.assertTrue(form.is_valid(), form.errors)
        form.handle(self.request, form.cleaned_data)
        update.assert_called_with(self.request, 's', {
            'S': {'build_time': False}})

    @mock.patch.object(coast, 'service_env_update', return_value=False)
    def test_edit_unknown_flag_only_sends_explicit_change(self, update):
        for initial_flag in ({}, {'build_time': None}):
            for checked in (False, True):
                with self.subTest(initial=initial_flag, checked=checked):
                    form = forms.SetEnv(
                        self.request, service_id='s', app=True,
                        initial=dict(key='A', value='old', secret=False,
                                     **initial_flag),
                        data={'value': 'new', 'build_time': checked})
                    self.assertTrue(form.is_valid(), form.errors)
                    self.assertTrue(form.handle(self.request,
                                                form.cleaned_data))
                    expected = {'value': 'new', 'secret': False}
                    if checked:
                        expected['build_time'] = True
                    update.assert_called_with(self.request, 's', {
                        'A': expected})

    @mock.patch.object(coast, 'service_env_update', return_value=False)
    def test_unknown_secret_without_changes_does_not_save(self, update):
        form = forms.SetEnv(
            self.request, service_id='s', app=True,
            initial={'key': 'S', 'secret': True, 'build_time': None},
            data={'value': '', 'secret': True})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(form.handle(self.request, form.cleaned_data))
        update.assert_not_called()

    def test_app_table_and_service_has_no_column(self):
        table = tables.EnvTable(self.request, service_id='s',
                                item={'kind': 'app'})
        self.assertIn('build_time', table.columns)
        html = table.build_time_control(dict(
            key='S', secret=True, build_time=True))
        self.assertIn('checked', html)
        self.assertIn('Secret values passed to builds can appear', html)
        table = tables.EnvTable(self.request, service_id='s',
                                item={'kind': 'service'})
        self.assertNotIn('build_time', table.columns)

    @mock.patch.object(coast, 'service_env_update', return_value=True)
    def test_toggle_endpoint_and_service_rejection(self, update):
        url = reverse('horizon:project:coast.apps:env_build_time',
                      args=['s', 'S'])
        self.assertEqual(200, self.client.post(
            url, {'build_time': 'false'}).status_code)
        update.assert_called_once_with(mock.ANY, 's', {
            'S': {'build_time': False}})
        update.reset_mock()
        with mock.patch.object(coast, 'service_get',
                               return_value={'kind': 'service'}):
            self.assertEqual(400, self.client.post(
                url, {'build_time': 'true'}).status_code)
        update.assert_not_called()

    @mock.patch.object(coast, 'service_env_list', return_value=[
        {'key': 'S', 'value': '********', 'secret': True,
         'build_time': False}])
    def test_app_and_service_views(self, env):
        for kind in ('app', 'service'):
            with mock.patch.object(coast, 'service_get', return_value={
                    'id': 's', 'name': 'test', 'kind': kind,
                    'status': 'ACTIVE'}):
                url = reverse('horizon:project:coast.apps:detail',
                              args=['s'])
                with mock.patch.object(coast, 'service_deployment_list',
                                       return_value=[]):
                    res = self.client.get(url, {
                        'tab': 'service_details__settings'})
                self.assertEqual(200, res.status_code)
                if kind == 'app':
                    self.assertContains(res, 'coast-build-time')
                    self.assertContains(
                        res, 'S=******** # secret, runtime-only')
                else:
                    self.assertNotContains(res, 'class="coast-build-time"')
                    self.assertNotContains(
                        res, 'S=******** # secret, runtime-only')
                url = reverse('horizon:project:coast.apps:add_env',
                              args=['s'])
                res = self.client.get(url)
                self.assertEqual(kind == 'app',
                                 'build_time' in res.context['form'].fields)
