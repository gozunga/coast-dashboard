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

"""Designate DNS forms, API negotiation, and managed records."""
from html.parser import HTMLParser
from pathlib import Path
import re
import shutil
import subprocess
from unittest import mock

from django.contrib.messages.storage.fallback import FallbackStorage
from django.template.loader import render_to_string
from django.urls import reverse
from horizon import exceptions
from keystoneauth1 import exceptions as client_exceptions

from coast_dashboard.api import coast
from coast_dashboard.content import dns
from coast_dashboard.content.services import forms
from coast_dashboard.content.services import tables
from coast_dashboard.content.stacks.forms import DNSSettings
from coast_dashboard.tests import helpers
from coast_dashboard.tests.test_api import _resp


class VisibleHelpParser(HTMLParser):
    """Collect paragraph text, excluding attributes such as tooltip titles."""

    def __init__(self):
        super().__init__()
        self.stack = []
        self.paragraphs = []
        self.paragraph = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'p':
            self.paragraph = {'text': '', 'buttons': [],
                              'ancestors': self.stack[:], 'attrs': attrs}
            self.paragraphs.append(self.paragraph)
        if self.paragraph is not None and tag == 'button':
            self.paragraph['buttons'].append(attrs)
        if tag not in ('input', 'br', 'hr', 'img', 'meta', 'link'):
            self.stack.append((tag, attrs))

    def handle_endtag(self, tag):
        if tag == 'p':
            self.paragraph = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if self.paragraph is not None:
            for tag, attrs in self.stack:
                classes = attrs.get('class', '').split()
                if ('hidden' in attrs or 'hidden' in classes or
                        'hide' in classes or 'sr-only' in classes or
                        'display:none' in attrs.get(
                            'style', '').replace(' ', '') or
                        attrs.get('aria-hidden') == 'true'):
                    return
            self.paragraph['text'] += data


class DNSAPITests(helpers.TestCase):
    @mock.patch.object(coast, '_get')
    def test_version_gate(self, get):
        for maximum, expected in [('1.21', False), ('1.22', True),
                                  ('1.23', True), ('bad', False)]:
            get.return_value = {'version': {'max_version': maximum}}
            self.assertEqual(
                expected, coast.dns_supported.__wrapped__(self.request))

    @mock.patch.object(coast, 'coastclient')
    def test_dns_adapter_version(self, client):
        client.return_value.adapter.request.return_value = _resp({'zones': []})
        self.assertEqual([], coast.dns_zone_list(self.request))
        client.return_value.adapter.request.assert_called_once_with(
            '/dns/zones', 'GET', microversion=coast.DNS_VERSION, log=False,
            connect_retries=0, status_code_retries=0)

    @mock.patch.object(coast, 'dns_supported', return_value=True)
    @mock.patch.object(coast, 'coastclient')
    def test_adapter_404_is_availability_signal(self, client, supported):
        client.return_value.adapter.request.side_effect = (
            client_exceptions.NotFound())
        form = forms.AddDomain(self.request, service_id='s')
        self.assertNotIn('zone_id', form.fields)
        self.assertNotIn('host', form.fields)
        self.assertFalse(coast.dns_available(self.request))
        client.return_value.adapter.request.assert_called_once()

    @mock.patch.object(coast, 'dns_supported', return_value=True)
    @mock.patch.object(coast, 'coastclient')
    def test_adapter_409_reports_service_error(self, client, supported):
        client.return_value.adapter.request.side_effect = (
            client_exceptions.Conflict())
        form = forms.AddDomain(self.request, service_id='s')
        self.assertNotIn('dns_mode', form.fields)
        self.assertNotIn('host', form.fields)
        client.return_value.adapter.request.assert_called_once()

    @mock.patch.object(coast, 'dns_supported', return_value=True)
    @mock.patch.object(coast, '_get')
    def test_dns_reads(self, get, supported):
        get.return_value = {'domains': [{'dns_mode': 'designate'}]}
        self.assertEqual([{'dns_mode': 'designate'}],
                         coast.service_domain_list(self.request, 's'))
        self.assertEqual(coast.PRIMARY_DOMAIN_VERSION,
                         get.call_args.kwargs['microversion'])
        get.return_value = {'domain': {'zone_id': 'z'}}
        self.assertEqual({'zone_id': 'z'}, coast.service_domain_get(
            self.request, 's', 'd'))
        self.assertEqual(coast.PRIMARY_DOMAIN_VERSION,
                         get.call_args.kwargs['microversion'])
        get.return_value = {'stack': {'default_domain': 'example.com'}}
        self.assertEqual({'default_domain': 'example.com'},
                         coast.stack_get(self.request, 's'))
        self.assertEqual(coast.DNS_VERSION,
                         get.call_args.kwargs['microversion'])

    @mock.patch.object(coast, '_write')
    def test_dns_writes(self, write):
        write.return_value = {'domain': {'id': 'd'}, 'stack': {'id': 's'}}
        values = {'host': 'shop', 'zone_id': 'z', 'auto_dns': True}
        coast.service_domain_create(self.request, 's', 'shop.example.com',
                                    **values)
        self.assertEqual(coast.DNS_VERSION,
                         write.call_args.kwargs['microversion'])
        self.assertEqual(values,
                         write.call_args.args[3]['domain'])
        coast.service_domain_update(self.request, 's', 'd', 'none', **values)
        self.assertEqual(dict(tls='none', **values),
                         write.call_args.args[3]['domain'])
        coast.service_domain_create(self.request, 's', 'own.example.net',
                                    auto_dns=False)
        self.assertEqual({'fqdn': 'own.example.net', 'auto_dns': False},
                         write.call_args.args[3]['domain'])
        coast.service_domain_update(self.request, 's', 'd', 'none',
                                    auto_dns=False)
        self.assertEqual({'tls': 'none', 'auto_dns': False},
                         write.call_args.args[3]['domain'])
        coast.stack_dns_update(self.request, 's', '', '')
        self.assertEqual(
            {'stack': {'default_domain': None, 'dns_zone_id': None}},
            write.call_args.args[3])
        coast.stack_dns_update(self.request, 's', 'apps.example.com', 'z')
        self.assertEqual(
            {'stack': {'default_domain': 'apps.example.com',
                       'dns_zone_id': 'z'}}, write.call_args.args[3])


@mock.patch.object(coast, 'dns_supported', return_value=True)
@mock.patch.object(coast, 'dns_zone_list', return_value=[
    {'id': 'z', 'name': 'example.com.'},
    {'id': 'other', 'name': 'other.com.'}])
class DNSFormTests(helpers.TestCase):
    def setUp(self):
        super().setUp()
        self.request._messages = FallbackStorage(self.request)

    def form(self, **data):
        return forms.AddDomain(self.request, service_id='s', data={
            'tls': 'letsencrypt', 'dns_mode': 'zone', **data})

    def test_hosts_and_all_zones(self, zones, supported):
        self.assertEqual('zone', self.form().fields['dns_mode'].initial)
        for host, fqdn in [('shop', 'shop.example.com'),
                           ('app.sd.example.com', 'app.sd.example.com'),
                           ('', 'example.com')]:
            form = self.form(host=host, zone_id='z', auto_dns=True)
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(fqdn, form.cleaned_data['fqdn'])
            self.assertEqual(2, len(form.fields['zone_id'].choices))
            with mock.patch.object(coast, 'service_domain_create') as create:
                self.assertTrue(form.handle(self.request, form.cleaned_data))
                self.assertTrue(create.call_args.kwargs['auto_dns'])

    def test_invalid_host_and_zone(self, zones, supported):
        for host, zone in [('bad..host', 'z'), ('-bad', 'z'),
                           ('shop', 'foreign'), ('shop', '')]:
            self.assertFalse(self.form(host=host, zone_id=zone).is_valid())
        self.assertFalse(self.form().is_valid())

    def test_manual_and_opt_out(self, zones, supported):
        form = self.form(dns_mode='manual', fqdn='external.example.net',
                         zone_id='z', host='bad..host')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual({'auto_dns': False},
                         form.dns_values(form.cleaned_data))
        with mock.patch.object(coast, 'service_domain_create') as create:
            self.assertTrue(form.handle(self.request, form.cleaned_data))
            self.assertEqual(
                {'tls': None, 'auto_dns': False},
                create.call_args.kwargs)
        self.assertFalse(self.form(dns_mode='manual').is_valid())

    def test_older_api_hides_controls(self, zones, supported):
        supported.return_value = False
        form = self.form(fqdn='app.example.com', zone_id='z', auto_dns=True)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertNotIn('zone_id', form.fields)
        self.assertEqual({}, form.dns_values(form.cleaned_data))
        zones.assert_not_called()

    def test_zone_empty_and_failure(self, zones, supported):
        for failure in (None, RuntimeError('private'),
                        exceptions.NotAuthorized()):
            zones.return_value = []
            zones.side_effect = failure
            form = self.form(fqdn='app.example.net')
            self.assertTrue(form.is_valid(), form.errors)
            for name in ('dns_mode', 'zone_id', 'host'):
                self.assertNotIn(name, form.fields)

    def test_stack_default_and_clear(self, zones, supported):
        for data, expected in [({'host': 'sd', 'zone_id': 'z'},
                                ('sd.example.com', 'z')),
                               ({'host': '', 'zone_id': 'z'},
                                ('example.com', 'z')), ({}, (None, ''))]:
            form = DNSSettings(self.request, stack_id='s', data=data)
            self.assertTrue(form.is_valid(), form.errors)
            with mock.patch.object(coast, 'stack_dns_update') as update:
                self.assertTrue(form.handle(self.request, form.cleaned_data))
                self.assertEqual(expected, update.call_args.args[2:])

    def test_stack_post_and_older_api(self, zones, supported):
        url = reverse('horizon:project:coast.stacks:dns', args=['s'])
        with mock.patch.object(coast, 'stack_get', return_value={'id': 's'}), \
                mock.patch.object(coast, 'stack_dns_update') as update:
            response = self.client.post(url, {'zone_id': 'z', 'host': 'sd'})
            self.assertEqual(302, response.status_code)
            self.assertEqual(('s', 'sd.example.com', 'z'),
                             update.call_args.args[1:])
            update.reset_mock()
            supported.return_value = False
            response = self.client.post(url, {'zone_id': 'z', 'host': 'sd'})
            self.assertEqual(200, response.status_code)
            update.assert_not_called()

    def test_edit_managed_domain(self, zones, supported):
        form = forms.EditDomain(self.request, service_id='s', domain_id='d',
                                initial={'dns_mode': 'zone', 'zone_id': 'z'},
                                data={'dns_mode': 'zone', 'zone_id': 'z',
                                      'host': 'new',
                                      'auto_dns': True, 'tls': 'none'})
        self.assertTrue(form.is_valid(), form.errors)
        with mock.patch.object(coast, 'service_domain_update') as update:
            self.assertTrue(form.handle(self.request, form.cleaned_data))
            self.assertEqual('new', update.call_args.kwargs['host'])

    def test_clear_stack_zone_with_existing_host(self, zones, supported):
        form = DNSSettings(self.request, stack_id='s', initial={
            'zone_id': 'z', 'host': 'sd.example.com'}, data={
                'zone_id': '', 'host': 'sd.example.com'})
        self.assertTrue(form.is_valid(), form.errors)
        with mock.patch.object(coast, 'stack_dns_update') as update:
            self.assertTrue(form.handle(self.request, form.cleaned_data))
            self.assertEqual((None, ''), update.call_args.args[2:])

    def test_manual_domain_conversion_preserves_name(self, zones, supported):
        item = {'id': 'd', 'fqdn': 'shop.example.com', 'dns_mode': 'manual'}
        for panel in ('apps', 'services'):
            url = reverse('horizon:project:coast.%s:edit_domain' % panel,
                          args=['s', 'd'])
            with mock.patch.object(coast, 'service_domain_get',
                                   return_value=item):
                response = self.client.get(url)
                self.assertEqual(200, response.status_code)
                initial = response.context['form'].initial
                self.assertEqual('shop.example.com', initial['host'])
                self.assertEqual('manual', initial['dns_mode'])
                with mock.patch.object(coast, 'service_domain_update') as save:
                    response = self.client.post(url, {
                        'dns_mode': 'zone',
                        'host': initial['host'], 'zone_id': 'z',
                        'auto_dns': True, 'tls': 'letsencrypt'})
                    self.assertEqual(302, response.status_code)
                    self.assertEqual({'auto_dns': False},
                                     save.call_args.kwargs)

    def test_edit_cannot_unlink_zone(self, zones, supported):
        form = forms.EditDomain(
            self.request, service_id='s', domain_id='d', initial={
                'fqdn': 'shop.example.com', 'zone_id': 'z', 'host': 'shop',
                'dns_mode': 'zone'}, data={
                'dns_mode': 'manual', 'zone_id': 'z', 'host': 'shop',
                'tls': 'none'})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual('zone', form.mode)
        self.assertEqual('z', form.dns_values(form.cleaned_data)['zone_id'])

    def test_friendly_collision(self, zones, supported):
        form = self.form(host='shop', zone_id='z', auto_dns=True)
        self.assertTrue(form.is_valid())
        with mock.patch.object(
                coast, 'service_domain_create',
                side_effect=coast.CoastError(http_status=409)):
            self.assertFalse(form.handle(self.request, form.cleaned_data))
        self.assertIn('already exists', str(form.errors))
        self.assertNotIn('private', str(form.errors))
        self.assertIn('access denied', str(dns.error_message(
            coast.CoastError(http_status=403))))

    def test_stack_settings_view(self, zones, supported):
        for domain, host in [('sd.example.com', 'sd'), ('example.com', '')]:
            with self.subTest(domain=domain), mock.patch.object(
                    coast, 'stack_get', return_value={
                        'id': 's', 'default_domain': domain,
                        'dns_zone_id': 'z'}):
                response = self.client.get(reverse(
                    'horizon:project:coast.stacks:dns', args=['s']))
            self.assertEqual(200, response.status_code)
            form = response.context['form']
            self.assertEqual('z', form.initial['zone_id'])
            self.assertEqual(host, form.initial['host'])
            self.assertEqual('Save', str(response.context['submit_label']))
            self.assertEqual('Default domain',
                             str(response.context['page_title']))
            self.assertFalse(form.fields['host'].required)
            self.assertEqual(
                'Optional. A name inside the selected zone used as the '
                'default domain for new apps. For example, apps gives '
                'apps.<zone>. Leave blank to use the zone itself. Each new '
                'app gets its own hostname under this domain, and Coast '
                'creates its DNS records in the zone.',
                str(form.fields['host'].help_text))
            self.assertEqual(
                'New apps get hostnames under <host>.<zone>. Coast creates '
                'records in the selected zone. Choose "Manual DNS / no '
                'zone" to use sslip.io.', str(form.help_text))
            page = response.content.decode()
            preview = page.index('class="coast-dd-preview"')
            # The preview sits in the form column, under the Host field.
            self.assertLess(page.index('name="host"'), preview)
            self.assertLess(preview, page.index('Description</h3>'))
            self.assertIn('class="coast-dd-preview">%s.example.com</strong>'
                          % host if host else
                          'class="coast-dd-preview">example.com</strong>',
                          page)
            self.assertNotContains(response, 'Coolify')
            self.assertNotContains(response, 'Traefik')


@mock.patch.object(coast, 'dns_supported', return_value=True)
@mock.patch.object(coast, '_list')
class DNSAvailabilityTests(helpers.TestCase):
    def test_missing_service_hides_controls_and_caches_failure(
            self, zones, supported):
        zones.side_effect = coast.CoastError(
            'DNS zones are not available on this cloud.', http_status=404)
        for form_class, kwargs in [
                (forms.AddDomain, {'service_id': 's'}),
                (forms.EditDomain, {'service_id': 's', 'domain_id': 'd'}),
                (DNSSettings, {'stack_id': 's'})]:
            form = form_class(self.request, **kwargs)
            for field in ('zone_id', 'host', 'auto_dns'):
                self.assertNotIn(field, form.fields)
        form = forms.AddDomain(self.request, service_id='s', data={
            'fqdn': 'app.sslip.io', 'tls': 'none'})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual({}, form.dns_values(form.cleaned_data))
        self.assertFalse(coast.dns_available(self.request))
        zones.assert_called_once()

    def test_empty_project_keeps_controls_and_caches_zones(
            self, zones, supported):
        zones.return_value = []
        for unused in range(2):
            form = forms.AddDomain(self.request, service_id='s')
            self.assertNotIn('host', form.fields)
            self.assertNotIn('dns_mode', form.fields)
        zones.assert_called_once()

    def test_service_failure_keeps_controls_and_reports_error(
            self, zones, supported):
        zones.side_effect = coast.CoastError(http_status=409)
        form = forms.AddDomain(self.request, service_id='s')
        self.assertNotIn('host', form.fields)
        self.assertNotIn('dns_mode', form.fields)
        zones.assert_called_once()

    def test_old_api_does_not_probe_zones(self, zones, supported):
        supported.return_value = False
        self.assertFalse(coast.dns_available(self.request))
        zones.assert_not_called()

    def test_domain_row_hides_managed_dns_prompt(self, zones, supported):
        zones.side_effect = coast.CoastError(http_status=404)
        row = tables.UpdateDomainRow.__new__(tables.UpdateDomainRow)
        row.table = mock.Mock(kwargs={'service_id': 's'})
        with mock.patch.object(coast, 'service_domain_get', return_value={
                'id': 'd', 'status': 'PENDING_VERIFICATION',
                'fqdn': 'app.example.com'}):
            item = row.get_data(self.request, 'd')
        self.assertNotIn('manage_dns_url', item)
        rendered = str(tables.verification_guidance(item))
        self.assertNotIn('choose a DNS zone', rendered)
        self.assertIn('create an A record', rendered)


class DNSPresentationTests(helpers.TestCase):
    def test_overview_address_links(self):
        rendered = render_to_string(
            'project/coast_services/overview.html', {'item': {
                'id': 's', 'primary_url': 'https://app.example.com',
                'domain_links': [{'fqdn': 'shop.example.com',
                                  'href': 'https://shop.example.com'}],
                'domains_url': '/apps/s?tab=service_details__domains',
                'worker_ip': '203.0.113.10',
                'manage_dns_url': '/unused/'}})
        for text in ('Address', 'https://app.example.com',
                     'https://shop.example.com', 'Manage domains',
                     '?tab=service_details__domains'):
            self.assertIn(text, rendered)
        for text in ('ajax-modal', 'Create DNS records', 'For manual DNS',
                     '203.0.113.10'):
            self.assertNotIn(text, rendered)

    def test_managed_records_without_manual_instructions(self):
        rendered = str(tables.verification_guidance({
            'dns_mode': 'designate', 'status': 'ACTIVE', 'managed_records': [
                {'type': 'AAAA', 'name': 'shop.example.com',
                 'value': '::1'},
                {'type': 'PTR', 'name': 'reverse', 'value': 'excluded'}]}))
        self.assertIn('DNS: managed by Coast', rendered)
        self.assertIn('AAAA', rendered)
        self.assertIn('::1', rendered)
        self.assertNotIn('create an A', rendered)
        self.assertNotIn('excluded', rendered)

    def test_manage_link_and_manual_records(self):
        rendered = str(tables.verification_guidance({
            'status': 'PENDING_VERIFICATION', 'manage_dns_url': '/edit/',
            'dns_records': [{'type': 'CNAME', 'name': 'shop',
                             'value': 'target'}]}))
        self.assertIn('/edit/', rendered)
        self.assertIn('CNAME', rendered)
        self.assertIn('target', rendered)


@mock.patch.object(coast, 'dns_available', return_value=True)
@mock.patch.object(coast, 'dns_zone_list', return_value=[
    {'id': 'z', 'name': 'example.com.'}])
class DomainRedesignTests(helpers.TestCase):
    def test_modes_duplicates_and_hidden_values(self, zones, available):
        for mode, data, field in (
                ('zone', {'host': 'SHOP', 'zone_id': 'z',
                          'fqdn': 'stale.invalid'}, 'host'),
                ('manual', {'fqdn': 'SHOP.example.com.',
                            'zone_id': 'invalid', 'host': 'bad..name'},
                 'fqdn')):
            form = forms.AddDomain(
                self.request, service_id='s',
                existing_names=['shop.example.com.'],
                data=dict(data, dns_mode=mode, tls='none'))
            self.assertFalse(form.is_valid())
            self.assertEqual(['This app already uses that name'],
                             form.errors[field])
        form = forms.AddDomain(self.request, service_id='s', data={
            'dns_mode': 'zone', 'host': 'shop', 'zone_id': 'z',
            'fqdn': 'bad..name', 'tls': 'none'})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual('shop.example.com', form.cleaned_data['fqdn'])
        self.assertEqual('zone', form.fields['host'].widget.attrs[
            'data-domain-mode'])
        edit = forms.EditDomain(
            self.request, service_id='s', domain_id='d',
            initial={'fqdn': 'shop.example.com'},
            data={'dns_mode': 'manual', 'tls': 'none'})
        self.assertTrue(edit.is_valid(), edit.errors)

    def test_visible_dns_help(self, zones, available):
        form = forms.AddDomain(
            self.request, service_id='s', worker_ip='203.0.113.10',
            default_domain='apps.example.com', initial={
                'dns_mode': 'manual', 'fqdn': 'shop.example.net'})
        rendered = render_to_string(
            'project/coast_services/_domain_form.html',
            {'form': form, 'page_title': 'Add Domain'})
        parser = VisibleHelpParser()
        parser.feed(rendered)

        def paragraph(text, mode):
            matches = [p for p in parser.paragraphs
                       if ' '.join(p['text'].split()) == text]
            self.assertEqual(1, len(matches), text)
            found = matches[0]
            ancestors = [attrs for tag, attrs in found['ancestors']]
            self.assertIn({'data-domain-section': mode}, ancestors)
            for attrs in ancestors + [found['attrs']]:
                self.assertNotIn('hidden', attrs)
                self.assertNotIn('display:none',
                                 attrs.get('style', '').replace(' ', ''))
                self.assertNotIn('hide', attrs.get('class', '').split())
                self.assertNotIn('hidden', attrs.get('class', '').split())
                self.assertNotEqual('true', attrs.get('aria-hidden'))
            return found

        manual = paragraph(
            'Point an A record for shop.example.net to 203.0.113.10, '
            'then verify it on the Domains tab.', 'manual')
        self.assertEqual(['203.0.113.10'], [
            button['data-copy-value'] for button in manual['buttons']])
        for button in manual['buttons']:
            self.assertNotIn('hidden', button)
            self.assertNotIn('display:none',
                             button.get('style', '').replace(' ', ''))
            self.assertNotIn('hidden', button.get('class', '').split())
        for text in ('Default app names use apps.example.com',
                     'e.g. www or shop.api; leave blank for the zone itself'):
            hint = paragraph(text, 'zone')
            classes = hint['attrs']['class'].split()
            self.assertIn('coast-domain-hint', classes)
            # Horizon converts help-block content to tooltips on page init.
            self.assertNotIn('help-block', classes)

    def test_modal_and_page_initializer(self, zones, available):
        form = forms.AddDomain(self.request, service_id='s',
                               worker_ip='203.0.113.10')
        rendered = render_to_string(
            'project/coast_services/_domain_form.html',
            {'form': form, 'page_title': 'Add Domain'})
        self.assertNotIn('document.currentScript', rendered)
        self.assertIn('data-copy-value="203.0.113.10"', rendered)
        script = re.findall(r'<script>(.*?)</script>', rendered, re.S)[-1]
        if not shutil.which('node'):
            self.skipTest('Node.js is needed to execute the modal regression')
        test_script = Path(__file__).with_name('domain_form.js')
        subprocess.run(['node', str(test_script)], input=script, text=True,
                       check=True, capture_output=True)

    def test_switch_after_manual_validation_error(self, zones, available):
        form = forms.AddDomain(self.request, service_id='s', data={
            'dns_mode': 'manual', 'fqdn': '', 'tls': 'none'})
        self.assertFalse(form.is_valid())
        self.assertIn('fqdn', form.errors)
        self.assertIn('required', str(form['fqdn']))
        rendered = render_to_string(
            'project/coast_services/_domain_form.html',
            {'form': form, 'page_title': 'Add Domain'})
        script = re.findall(r'<script>(.*?)</script>', rendered, re.S)[-1]
        if not shutil.which('node'):
            self.skipTest('Node.js is needed to execute the modal regression')
        subprocess.run(
            ['node', str(Path(__file__).with_name('domain_form.js'))],
            input=script, text=True, check=True, capture_output=True)

    def test_form_context(self, zones, available):
        with mock.patch.object(coast, 'service_get', return_value={
                'default_url': 'https://app.apps.example.com',
                'stack_id': 'stack', 'server_id': 'worker'}), \
                mock.patch.object(coast, 'stack_server_list', return_value=[{
                    'id': 'worker', 'floating_ip': '203.0.113.10'}]), \
                mock.patch.object(
                coast, 'stack_get', return_value={
                    'default_domain': 'apps.example.com'}), mock.patch.object(
                coast, 'service_domain_list', return_value=[]):
            response = self.client.get(reverse(
                'horizon:project:coast.apps:add_domain', args=['s']) +
                '?replace_default=1')
        self.assertContains(response, 'This app is already reachable at:')
        self.assertContains(response, 'app.apps.example.com')
        self.assertContains(response, 'Default app names use apps.example.com')
        self.assertContains(response, 'After this domain is active')
        self.assertContains(response, 'data-copy-value="203.0.113.10"')
        self.assertEqual('zone', response.context['form'].mode)
        with mock.patch.object(coast, 'service_get', return_value={}), \
                mock.patch.object(coast, 'service_domain_list', return_value=[
                    {'id': 'd', 'fqdn': 'shop.example.com'}]), \
                mock.patch.object(coast, 'service_domain_get', return_value={
                    'id': 'd', 'fqdn': 'shop.example.com', 'zone_id': 'z'}):
            response = self.client.get(reverse(
                'horizon:project:coast.apps:edit_domain', args=['s', 'd']))
        self.assertEqual('zone', response.context['form'].initial['dns_mode'])
        self.assertEqual([], response.context['form'].existing_names)
        self.assertEqual([], response.context['form'].known_names)
        self.assertContains(response, 'Change how shop.example.com is set up.')
        self.assertNotContains(response, 'Add another name for this app.')
        self.assertNotContains(response, 'document.currentScript')

    def test_default_row(self, zones, available):
        from coast_dashboard.content.services import tabs
        tab = tabs.Domains.__new__(tabs.Domains)
        tab.request = self.request
        tab.tab_group = mock.Mock(kwargs={
            'service_id': 's', 'item': {'default_url': 'https://app.test'}})
        with mock.patch.object(coast, 'service_domain_list', return_value=[]):
            rows = tab.get_domains_data()
            table = tables.DomainsTable(self.request, data=rows,
                                        service_id='s')
            rendered = table.render()
            self.assertIn('Default', rendered)
            self.assertIn('Use my own domain instead', rendered)
            self.assertIn('replace_default=1', rendered)
            self.assertNotIn('ajax-update', rendered)
            self.assertEqual(['replace_default'], [
                action.name for action in table.get_row_actions(rows[0])])
            tab.tab_group.kwargs['item']['default_url'] = None
            self.assertEqual([], tab.get_domains_data())
