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

"""Thin wrapper around python-coastclient for Horizon views."""

from urllib import parse

from django.conf import settings
from horizon import exceptions
from horizon.utils.memoized import memoized
from keystoneauth1 import exceptions as client_exceptions
from keystoneauth1.identity import v3
from keystoneauth1 import session as ks_session

from coast_dashboard import public_text

SERVICE_TYPE = 'app-hosting'
DNS_VERSION = '1.22'
RESIZE_VERSION = '1.26'
METRICS_VERSION = '1.21'
SERVER_FLAVOR_VERSION = '1.27'
METRICS_RANGES = ('15m', '1h', '6h', '24h', '7d', '30d')


def _interface():
    endpoint_type = getattr(settings, 'OPENSTACK_ENDPOINT_TYPE', 'public')
    return endpoint_type.replace('URL', '')


def _session(request):
    auth = v3.Token(auth_url=settings.OPENSTACK_KEYSTONE_URL,
                    token=request.user.token.id,
                    project_id=request.user.project_id)
    verify = not getattr(settings, 'OPENSTACK_SSL_NO_VERIFY', False)
    if verify and getattr(settings, 'OPENSTACK_SSL_CACERT', None):
        verify = settings.OPENSTACK_SSL_CACERT
    return ks_session.Session(auth=auth, verify=verify)


@memoized
def coastclient(request, microversion='1.0'):
    # Imported here so the plugin loads (and tests run) without the client.
    from coastclient.v1 import client
    return client.Client(_session(request),
                         region_name=request.user.services_region,
                         interface=_interface(), microversion=microversion)


def _get(request, path, microversion='1.0'):
    response = _request(request, path, 'GET', microversion=microversion)
    return response.json() if response.content else {}


def stack_list(request):
    return _list(request, '/stacks', 'stacks')


def stack_get(request, stack_id):
    return _get(request, '/stacks/' + stack_id, microversion=(
        DNS_VERSION if dns_supported(request) else '1.0'))['stack']


def appgroup_list(request, stack_id=None):
    """List appgroups for one stack, or for every visible stack."""
    stack_ids = [stack_id] if stack_id else [
        s['id'] for s in stack_list(request)]
    apps = []
    for sid in stack_ids:
        apps.extend(_list(request, '/stacks/%s/appgroups' % sid,
                          'appgroups'))
    return apps


def appgroup_get(request, appgroup_id):
    return _get(request, '/appgroups/' + appgroup_id)['appgroup']


def appgroup_create(request, stack_id, name):
    return _write(request, '/stacks/%s/appgroups' % stack_id,
                  'POST', {'appgroup': {'name': name}})['appgroup']


def appgroup_delete(request, appgroup_id):
    return _write(request, '/appgroups/' + appgroup_id, 'DELETE')


def _list(request, path, key, microversion='1.0'):
    """Follow markers without sending credentials to a supplied URL."""
    items = []
    seen = set()
    page_path = path
    while True:
        page = _get(request, page_path, microversion=microversion)
        items.extend(page.get(key, []))
        next_url = next((link['href'] for link in page.get('links', [])
                         if link.get('rel') == 'next'), None)
        if not next_url:
            return items
        query = parse.urlsplit(next_url).query
        if not query or query in seen:
            raise ValueError('Invalid Coast pagination link')
        seen.add(query)
        base, _sep, fixed = path.partition('?')
        params = dict(parse.parse_qsl(fixed))
        params.update(parse.parse_qsl(query))
        page_path = base + '?' + parse.urlencode(params)


def _write(request, path, method, body=None, microversion='1.0'):
    kwargs = {'json': body} if body is not None else {}
    response = _request(request, path, method, microversion=microversion,
                        **kwargs)
    return response.json() if response.content else {}


def stack_create(request, name, plan, worker_plan, worker_count=1,
                 build_server=False, build_server_plan=None):
    workers = [{'kind': 'vm', 'plan': worker_plan}
               for unused in range(worker_count)]
    stack = {'name': name, 'plan': plan, 'workers': workers,
             'build_server': build_server}
    if build_server and build_server_plan:
        # build_server_plan exists only in microversion 1.1 (any worker
        # count since Coast Q151).
        stack['build_server_plan'] = build_server_plan
        response = _request(request, '/stacks', 'POST',
                            microversion='1.1', json={'stack': stack})
        return response.json()['stack']
    return _write(request, '/stacks', 'POST', {'stack': stack})['stack']


def plan_list(request):
    # Microversion 1.1 includes each plan's flavor (Coast Q150 interim).
    response = _request(request, '/plans', 'GET', microversion='1.1')
    return response.json().get('plans', [])


def stack_delete(request, stack_id):
    return _write(request, '/stacks/' + stack_id, 'DELETE')


def stack_server_list(request, stack_id):
    return _list(request, '/stacks/%s/servers' % stack_id, 'servers',
                 microversion=SERVER_FLAVOR_VERSION)


class ActivityUnavailable(Exception):
    """The Coast endpoint does not support stack events."""


def stack_event_list(request, stack_id, limit=50, marker=None,
                     resource_type=None):
    """Return one event page and its next marker, never follow remote URLs."""
    params = {'limit': limit}
    if marker:
        params['marker'] = marker
    if resource_type:
        params['resource_type'] = resource_type
    page = _get(request, '/stacks/%s/events?' % stack_id +
                parse.urlencode(params), microversion='1.8')
    next_url = next((link.get('href', '') for link in page.get('links', [])
                     if link.get('rel') == 'next'), '')
    next_marker = dict(parse.parse_qsl(parse.urlsplit(next_url).query)).get(
        'marker')
    if next_marker == marker:
        next_marker = None
    return page.get('events', []), next_marker


def stack_server_get(request, stack_id, server_id):
    return _get(request, '/stacks/%s/servers/%s' % (
        stack_id, server_id), microversion=SERVER_FLAVOR_VERSION)['server']


def environment_list(request, appgroup_id=None):
    apps = ([{'id': appgroup_id}] if appgroup_id else
            appgroup_list(request))
    return [env for app in apps for env in _list(
        request, '/appgroups/%s/environments' % app['id'], 'environments')]


def environment_get(request, environment_id):
    return _get(request, '/environments/' + environment_id)['environment']


def environment_create(request, appgroup_id, name):
    return _write(request, '/appgroups/%s/environments' % appgroup_id,
                  'POST', {'environment': {'name': name}})['environment']


def environment_delete(request, environment_id):
    return _write(request, '/environments/' + environment_id, 'DELETE')


PRIMARY_DOMAIN_VERSION = '1.23'
SERVICE_READ_VERSION = '1.24'
DEPLOY_KEY_VERSION = '1.30'
PASTED_SOURCE_VERSION = '1.31'


def service_list(request, kind=None):
    """kind='app' (engine application) or 'service' (one-click, Q148)."""
    path = '/services' + ('?kind=' + kind if kind else '')
    return _list(request, path, 'services',
                 microversion=SERVICE_READ_VERSION)


def service_update(request, service_id, values):
    version = (PRIMARY_DOMAIN_VERSION
               if 'default_domain_enabled' in values else
               '1.4' if 'health_check' in values else '1.0')
    if 'deploy_key' in values.get('source', {}):
        version = DEPLOY_KEY_VERSION
    return _write(request, '/services/%s' % service_id, 'PATCH',
                  {'service': values}, microversion=version)['service']


def service_get(request, service_id, microversion=SERVICE_READ_VERSION):
    response = _request(request, '/services/' + service_id, 'GET',
                        microversion=microversion)
    return response.json()['service']


def service_create(request, name, appgroup_id, environment_id, server_id,
                   source, ports='8080', health_check='none',
                   health_check_port=None, healthcheck_path='/'):
    probe = _probe_values(health_check, health_check_port, healthcheck_path)
    version = '1.4' if probe else '1.0'
    if 'deploy_key' in source:
        version = DEPLOY_KEY_VERSION
    if source['type'] in ('dockerfile', 'compose'):
        version = PASTED_SOURCE_VERSION
    deploy = not source.get('deploy_key', {}).get('generate', False)
    return _write(request, '/services', 'POST', {'service': {
        'name': name, 'appgroup_id': appgroup_id,
        'environment_id': environment_id, 'server_id': server_id,
        'source': source, 'ports': ports, 'deploy': deploy, **probe}},
        microversion=version)['service']


def service_deploy(request, service_id):
    return _write(request, '/services/%s/deployments' % service_id,
                  'POST', {'deployment': {}})['deployment']


def service_action(request, service_id, action):
    if action not in ('start', 'stop', 'restart'):
        raise ValueError('Unsupported service action')
    return _write(request, '/services/%s/action' % service_id,
                  'POST', {action: {}})


def service_delete(request, service_id):
    return _write(request, '/services/' + service_id, 'DELETE')


def service_deployment_list(request, service_id):
    return _list(request, '/services/%s/deployments'
                 '?sort_key=created_at&sort_dir=desc' % service_id,
                 'deployments')


def service_deployment_get(request, service_id, deployment_id):
    return _get(request, '/services/%s/deployments/%s' % (
        service_id, deployment_id))['deployment']


def service_domain_list(request, service_id):
    return _list(request, '/services/%s/domains' % service_id, 'domains',
                 microversion=PRIMARY_DOMAIN_VERSION)


def service_domain_get(request, service_id, domain_id):
    return _get(request, '/services/%s/domains/%s' % (
        service_id, domain_id), microversion=PRIMARY_DOMAIN_VERSION)['domain']


def service_env_list(request, service_id):
    env = _get(request, '/services/%s/env' % service_id).get('env', {})
    return [dict(key=key, value='********' if item.get('secret') or
                 item.get('value') is None else item['value'],
                 secret=bool(item.get('secret')),
                 build_time=item.get('build_time'))
            for key, item in sorted(env.items())]


def service_env_update(request, service_id, env):
    # PATCH preserves unrelated keys and omitted flags. Never return values
    # from a write to the form or to a message.
    response = _request(request, '/services/%s/env' % service_id,
                        'PATCH', json={'env': env})
    return response.headers.get(
        'X-Coast-Redeploy-Required', '').lower() == 'true'


def service_env_delete(request, service_id, key):
    return service_env_update(request, service_id, {key: None})


# ``tls`` is absent from the 1.0 domain document. Coast accepts the field
# from microversion 1.2, so send that version only when the body includes it.
DOMAIN_TLS_VERSION = '1.2'


def service_domain_create(request, service_id, fqdn, tls=None, **dns):
    body = {'fqdn': fqdn}
    version = '1.0'
    if tls:
        body['tls'] = tls
        version = DOMAIN_TLS_VERSION
    if dns:
        if dns.get('zone_id'):
            body.pop('fqdn')
        body.update(dns)
        version = DNS_VERSION
    return _write(request, '/services/%s/domains' % service_id, 'POST',
                  {'domain': body}, microversion=version)['domain']


def service_domain_update(request, service_id, domain_id, tls, **dns):
    return _write(request, '/services/%s/domains/%s' % (
        service_id, domain_id), 'PATCH', {'domain': dict(tls=tls, **dns)},
        microversion=DNS_VERSION if dns else DOMAIN_TLS_VERSION)['domain']


def service_domain_make_primary(request, service_id, domain_id):
    return _write(
        request, '/services/%s/domains/%s' % (service_id, domain_id),
        'PATCH', {'domain': {'primary': True}},
        microversion=PRIMARY_DOMAIN_VERSION)['domain']


def service_domain_verify(request, service_id, domain_id):
    return _write(request, '/services/%s/domains/%s/action' % (
        service_id, domain_id), 'POST', {'verify': {}})


def service_domain_delete(request, service_id, domain_id):
    return _write(request, '/services/%s/domains/%s' % (
        service_id, domain_id), 'DELETE')


def service_logs(request, service_id, tail=None):
    path = '/services/%s/logs' % service_id
    if tail is not None:
        path += '?tail=%d' % int(tail)
    return _get(request, path).get('logs', {})


# Next microversion after 1.8. The client constructor accepts 1.0 or 1.1,
# so the console call sets 1.9 on the adapter.
CONSOLE_VERSION = '1.9'
# Typed service storage: Coast API 1.19.
STORAGE_VERSION = '1.19'
CONSOLE_KINDS = {'app': 'apps', 'service': 'services'}


def console_session_url(value):
    """Return a wss session address, or None when the value is not one."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    parts = parse.urlsplit(text)
    if (parts.scheme != 'wss' or not parts.hostname or
            parts.username or parts.password):
        return None
    return text


def service_console(request, service_id, kind, command=None):
    """Open a console. ``kind`` is ``app`` or ``service``.

    ``command`` is an optional one-off exec. Omit it for a shell.
    """
    collection = CONSOLE_KINDS.get(kind)
    if collection is None:
        raise ValueError('Unsupported console resource')
    kwargs = {}
    if command is not None:
        if (not isinstance(command, (list, tuple)) or not command or
                not all(isinstance(part, str) and part for part in command)):
            raise ValueError('command must be a list of strings')
        kwargs['json'] = {'command': list(command)}
    response = _request(
        request, '/%s/%s/console' % (collection, service_id), 'POST',
        microversion=CONSOLE_VERSION, **kwargs)
    if not response.content:
        return {}
    body = response.json()
    return body if isinstance(body, dict) else {}


def service_deployment_cancel(request, service_id, deployment_id):
    return _write(request, '/services/%s/deployments/%s/action' % (
        service_id, deployment_id), 'POST', {'cancel': {}})


WEBHOOK_VERSION = '1.3'
WEBHOOK_KEYS = ('deploy', 'github', 'gitlab', 'bitbucket', 'gitea')


def service_webhooks(request, service_id):
    response = _request(request, '/services/%s/webhooks' % service_id,
                        'GET', microversion=WEBHOOK_VERSION)
    return response.json().get('webhooks', {})


def service_webhooks_regenerate(request, service_id):
    response = _request(request,
                        '/services/%s/webhooks/regenerate' % service_id,
                        'POST', microversion=WEBHOOK_VERSION)
    return response.json().get('webhooks', {})


def service_deployment_log(request, service_id, deployment_id):
    return _get(request, '/services/%s/deployments/%s/log' % (
        service_id, deployment_id)).get('log', {})


class CoastError(exceptions.RecoverableError):
    """A Coast API failure; ``api_message`` is the API's 4xx fault text."""

    def __init__(self, api_message=None, http_status=None):
        super().__init__(api_message or 'Coast request failed.')
        self.api_message = api_message
        self.http_status = http_status


def fault_message(exc):
    response = getattr(exc, 'response', None)
    status = getattr(response, 'status_code', None) or getattr(
        exc, 'http_status', None)
    if not isinstance(status, int) or not 400 <= status < 500:
        return None
    try:
        body = response.json()
    except Exception:
        return None
    if not isinstance(body, dict):
        return None
    for key in ('faultstring', 'detail', 'message'):
        text = body.get(key)
        if isinstance(text, str) and text.strip():
            return public_text.scrub(text)
    return None


def error_message(exc, default):
    """The Coast API's message for ``exc`` if it sent one, else default."""
    return getattr(exc, 'api_message', None) or default


# The client is built only at 1.0 or 1.1; newer versions are per call.
PER_CALL_VERSIONS = {'1.2': 'domain_tls_microversion',
                     '1.3': 'webhooks_microversion',
                     '1.4': 'health_check_microversion'}


def _admin_read(path):
    """True for the admin panel's all-projects reads, which keep detail."""
    query = parse.parse_qs(parse.urlsplit(path).query)
    return query.get('all_projects') == ['true']


class _PublicResponse(object):
    """A response whose JSON prose fields carry no engine names."""

    def __init__(self, response):
        self._response = response

    def __getattr__(self, name):
        return getattr(self._response, name)

    def json(self, *args, **kwargs):
        return public_text.scrub_tree(self._response.json(*args, **kwargs))


def _public(response):
    return _PublicResponse(response)


def _request(request, path, method, microversion='1.0', **kwargs):
    """Every Coast call; project reads and writes leave scrubbed."""
    response = _raw_request(request, path, method,
                            microversion=microversion, **kwargs)
    return response if _admin_read(path) else _public(response)


def _raw_request(request, path, method, microversion='1.0', **kwargs):
    # The client's health_check_microversion option accepts writes only.
    # 1.4, 1.7 and 1.8 reads, and the 1.9 console write, set the version
    # on the adapter. The client constructor accepts 1.0 or 1.1.
    read_version = microversion if method == 'GET' else None
    adapter_version = None
    if (microversion in (CONSOLE_VERSION, STORAGE_VERSION, COMPOSE_VERSION,
                         CONTAINER_VERSION, IMAGE_VERSION,
                         FILE_MOUNTS_VERSION, ADMIN_VERSION, BACKUP_VERSION,
                         METRICS_VERSION, DNS_VERSION, PRIMARY_DOMAIN_VERSION,
                         SERVICE_READ_VERSION, INGRESS_VERSION,
                         SERVER_FLAVOR_VERSION, RESIZE_VERSION,
                         DATABASE_VERSION, DEPLOY_KEY_VERSION,
                         PASTED_SOURCE_VERSION)
            or read_version in ('1.4', '1.7', '1.8')):
        adapter_version = microversion
        microversion = '1.0'
    elif microversion in PER_CALL_VERSIONS:
        kwargs[PER_CALL_VERSIONS[microversion]] = microversion
        microversion = '1.0'
    try:
        client = coastclient(request, microversion)
        if adapter_version:
            try:
                return client.adapter.request(
                    path, method, microversion=adapter_version, log=False,
                    connect_retries=0, status_code_retries=0, **kwargs)
            except client_exceptions.NotAcceptable:
                if adapter_version != '1.7':
                    raise
                # Older Coast catalogs omit http_port at the default version.
        return client.request(path, method, **kwargs)
    except (client_exceptions.NotFound,
            client_exceptions.NotAcceptable) as exc:
        if read_version == '1.8':
            raise ActivityUnavailable() from None
        if isinstance(exc, client_exceptions.NotAcceptable):
            if adapter_version in (DEPLOY_KEY_VERSION, PASTED_SOURCE_VERSION):
                raise CoastError('This source needs API version %s.' %
                                 adapter_version) from None
            raise CoastError(fault_message(exc)) from None
        if path == '/dns/zones' and read_version == DNS_VERSION:
            raise CoastError(http_status=404) from None
        # Horizon removes AJAX rows when it receives a 404.
        raise exceptions.NotFound('Coast resource not found.') from None
    except client_exceptions.Unauthorized:
        raise exceptions.NotAuthorized(
            'Coast authentication failed.') from None
    except client_exceptions.ClientException as exc:
        # Only the API's own 4xx fault message reaches the user; other
        # bodies (5xx, proxies) stay generic.
        raise CoastError(fault_message(exc),
                         getattr(exc, 'http_status', None)) from None


def template_list(request, stack_id):
    return public_text.scrub_catalog(_list(
        request, '/templates?' + parse.urlencode({'stack_id': stack_id}),
        'templates', microversion='1.7'))


def oneclick_create(request, name, appgroup_id, environment_id, server_id,
                    template_id, health_check='none',
                    health_check_port=None, healthcheck_path='/'):
    probe = _probe_values(health_check, health_check_port, healthcheck_path)
    return _write(request, '/services', 'POST', {'service': {
        'name': name, 'appgroup_id': appgroup_id,
        'environment_id': environment_id, 'server_id': server_id,
        'source': {'type': 'template', 'template_id': template_id},
        'deploy': True, **probe}},
        microversion='1.4' if probe else '1.0')['service']


def _probe_values(health_check, port, path):
    if health_check == 'none':
        return {}
    values = {'health_check': health_check, 'healthcheck_path': path or '/'}
    if port is not None:
        values['health_check_port'] = port
    return values


@memoized
def storage_supported(request):
    """Hide typed mounts until the API advertises the required version."""
    try:
        version = _get(request, '/').get('version', {})
        maximum = tuple(map(int, version['max_version'].split('.')))
        return maximum >= tuple(map(int, STORAGE_VERSION.split('.')))
    except Exception:
        return False


def storage_list(request, stack_id, service_id):
    return _list(request, '/stacks/%s/storages?%s' % (
        stack_id, parse.urlencode({'service_id': service_id})),
        'storages', microversion=STORAGE_VERSION)


def storage_create(request, stack_id, values):
    return _write(request, '/stacks/%s/storages' % stack_id, 'POST',
                  {'storage': values},
                  microversion=STORAGE_VERSION).get('storage', {})


def storage_update(request, stack_id, storage_id, values):
    return _write(request, '/stacks/%s/storages/%s' % (stack_id, storage_id),
                  'PATCH', {'storage': values}, microversion=STORAGE_VERSION)


def storage_delete(request, stack_id, storage_id):
    return _write(request, '/stacks/%s/storages/%s' % (stack_id, storage_id),
                  'DELETE', microversion=STORAGE_VERSION)


COMPOSE_VERSION = '1.12'


def service_compose_get(request, service_id):
    return _get(request, '/services/%s/compose' % service_id,
                microversion=COMPOSE_VERSION)['compose']['yaml']


def service_compose_update(request, service_id, yaml):
    return _write(request, '/services/%s/compose' % service_id, 'PUT',
                  {'compose': {'yaml': yaml}},
                  microversion=COMPOSE_VERSION)['compose']['yaml']


CONTAINER_VERSION = '1.13'


def service_container_list(request, service_id):
    return _get(request, '/services/%s/containers' % service_id,
                microversion=CONTAINER_VERSION).get('containers', [])


def service_container_get(request, service_id, container_id):
    return _get(request, '/services/%s/containers/%s' % (
        service_id, parse.quote(container_id, safe='')),
        microversion=CONTAINER_VERSION)['container']


def service_container_logs(request, service_id, container_id):
    return _get(request, '/services/%s/containers/%s/logs?tail=200' % (
        service_id, parse.quote(container_id, safe='')),
        microversion=CONTAINER_VERSION).get('logs', {})


IMAGE_VERSION = '1.14'


def service_image_update(request, service_id, image, tag):
    return _write(request, '/services/%s' % service_id, 'PATCH',
                  {'service': {'source': {'image': image, 'tag': tag}}},
                  microversion=IMAGE_VERSION)['service']


FILE_MOUNTS_VERSION = '1.15'


def file_mount_list(request, service_id):
    return _get(request, '/services/%s/file_mounts' % service_id,
                microversion=FILE_MOUNTS_VERSION).get('file_mounts', [])


def file_mount_get(request, service_id, mount_id):
    return _get(request, '/services/%s/file_mounts/%s' % (
        service_id, mount_id), microversion=FILE_MOUNTS_VERSION)['file_mount']


def file_mount_create(request, service_id, values):
    return _write(request, '/services/%s/file_mounts' % service_id, 'POST',
                  {'file_mount': values},
                  microversion=FILE_MOUNTS_VERSION).get('file_mount', {})


def file_mount_update(request, service_id, mount_id, values):
    return _write(request, '/services/%s/file_mounts/%s' % (
        service_id, mount_id), 'PATCH', {'file_mount': values},
        microversion=FILE_MOUNTS_VERSION).get('file_mount', {})


def file_mount_delete(request, service_id, mount_id):
    return _write(request, '/services/%s/file_mounts/%s' % (
        service_id, mount_id), 'DELETE', microversion=FILE_MOUNTS_VERSION)


# Admin stack inventory and explicit cross-project reads.
ADMIN_VERSION = '1.18'


def admin_stack_list(request):
    return _list(request, '/stacks?all_projects=true', 'stacks',
                 microversion=ADMIN_VERSION)


def admin_stack_get(request, stack_id):
    return _get(request, '/stacks/%s?all_projects=true' % stack_id,
                microversion=ADMIN_VERSION)['stack']


def admin_resource_list(request, stack_id, resource):
    if resource not in ('servers', 'volumes', 'services'):
        raise ValueError('Unsupported admin resource')
    if resource == 'services':
        path = '/services?' + parse.urlencode(
            {'stack_id': stack_id, 'all_projects': 'true'})
    else:
        path = '/stacks/%s/%s?all_projects=true' % (stack_id, resource)
    return _list(request, path, resource, microversion=ADMIN_VERSION)


def admin_event_list(request, stack_id, marker=None):
    params = {'all_projects': 'true', 'resource_type': 'server', 'limit': 50}
    if marker:
        params['marker'] = marker
    page = _get(request, '/stacks/%s/events?' % stack_id +
                parse.urlencode(params), microversion=ADMIN_VERSION)
    next_url = next((link.get('href', '') for link in page.get('links', [])
                     if link.get('rel') == 'next'), '')
    next_marker = dict(parse.parse_qsl(parse.urlsplit(next_url).query)).get(
        'marker')
    return page.get('events', []), (
        next_marker if next_marker != marker else None)


# Database backup control, merged in Coast MR !307.
BACKUP_VERSION = '1.20'


@memoized
def backups_supported(request):
    """Fail closed on older APIs without requesting unsupported resources."""
    try:
        version = _get(request, '/').get('version', {})
        maximum = tuple(int(p) for p in version['max_version'].split('.'))
        minimum = tuple(int(p) for p in BACKUP_VERSION.split('.'))
        return len(maximum) == 2 and maximum >= minimum
    except exceptions.NotAuthorized:
        raise
    except Exception:
        return False


def backup_policy_get(request, service_id):
    return _get(request, '/services/%s/backup_policy' % service_id,
                microversion=BACKUP_VERSION)['backup_policy']


def backup_policy_update(request, service_id, values):
    return _write(request, '/services/%s/backup_policy' % service_id,
                  'PUT', {'backup_policy': values},
                  microversion=BACKUP_VERSION)


def backup_list(request, service_id):
    return _list(request, '/services/%s/backups' % service_id, 'backups',
                 microversion=BACKUP_VERSION)


def backup_create(request, service_id):
    return _write(request, '/services/%s/backups' % service_id, 'POST', {},
                  microversion=BACKUP_VERSION)


def backup_get(request, backup_id):
    version = DATABASE_VERSION if _database_panel(request) else BACKUP_VERSION
    return _get(request, '/backups/' + backup_id,
                microversion=version)['backup']


def backup_delete(request, backup_id):
    return _write(request, '/backups/' + backup_id, 'DELETE',
                  microversion=(DATABASE_VERSION if _database_panel(request)
                                else BACKUP_VERSION))


def backup_download(request, backup_id):
    return _request(request, '/backups/%s/download' % backup_id, 'GET',
                    microversion=(DATABASE_VERSION if _database_panel(request)
                                  else BACKUP_VERSION), stream=True)


def backup_restore(request, backup_id, mode, name=None, confirmation=None):
    values = {'mode': mode}
    if mode == 'new_copy':
        values['name'] = name
    else:
        values['confirmation'] = confirmation
    return _write(request, '/backups/%s/restore' % backup_id, 'POST', values,
                  microversion=(DATABASE_VERSION if _database_panel(request)
                                else BACKUP_VERSION))


@memoized
def service_metrics_supported(request):
    """Discover once per request; older APIs do not expose the tab."""
    try:
        version = _get(request, '/')['version']['max_version']
        parts = tuple(int(part) for part in version.split('.'))
        return parts >= tuple(int(part) for part in METRICS_VERSION.split('.'))
    except Exception:
        return False


def service_metrics(request, service_id, range_='1h'):
    if range_ not in METRICS_RANGES:
        raise ValueError('Invalid metrics range')
    return _get(request, '/services/%s/metrics?%s' % (
        parse.quote(service_id, safe=''), parse.urlencode({'range': range_})),
        microversion=METRICS_VERSION)['metrics']


@memoized
def dns_supported(request):
    try:
        version = _get(request, '/')['version']['max_version']
        parts = tuple(int(part) for part in version.split('.'))
        return len(parts) == 2 and parts >= tuple(
            int(part) for part in DNS_VERSION.split('.'))
    except Exception:
        return False


def dns_zone_list(request):
    """Cache both zones and failures for the lifetime of this request."""
    if not hasattr(request, '_coast_dns_zones'):
        try:
            request._coast_dns_zones = _list(
                request, '/dns/zones', 'zones', microversion=DNS_VERSION)
        except Exception as exc:
            request._coast_dns_zones = exc
    result = request._coast_dns_zones
    if isinstance(result, Exception):
        raise result
    return result


def dns_available(request):
    """Only a zones 404 at the DNS microversion signals no DNS service."""
    if not dns_supported(request):
        return False
    try:
        dns_zone_list(request)
    except Exception as exc:
        return getattr(exc, 'http_status', None) != 404
    return True


def stack_dns_update(request, stack_id, default_domain, zone_id):
    return _write(request, '/stacks/' + stack_id, 'PATCH', {'stack': {
        'default_domain': default_domain or None,
        'dns_zone_id': zone_id or None}}, microversion=DNS_VERSION)['stack']


INGRESS_VERSION = '1.25'


@memoized
def ingress_supported(request):
    try:
        version = _get(request, '/')['version']['max_version']
        parts = tuple(int(part) for part in version.split('.'))
        return len(parts) == 2 and parts >= (1, 25)
    except Exception:
        return False


def stack_ingress_rule_list(request, stack_id):
    return _list(request, '/stacks/%s/ingress_rules' % stack_id,
                 'ingress_rules', microversion=INGRESS_VERSION)


def stack_ingress_rule_create(request, stack_id, values):
    return _write(request, '/stacks/%s/ingress_rules' % stack_id,
                  'POST', {'ingress_rule': values},
                  microversion=INGRESS_VERSION)['ingress_rule']


def stack_ingress_rule_delete(request, stack_id, rule_id):
    return _write(request, '/stacks/%s/ingress_rules/%s' % (
        stack_id, rule_id), 'DELETE', microversion=INGRESS_VERSION)


def stack_server_create(request, stack_id, role, plan, name=None):
    server = {'kind': 'vm', 'role': role, 'plan': plan}
    if name:
        server['name'] = name
    return _write(request, '/stacks/%s/servers' % stack_id,
                  'POST', {'server': server},
                  microversion=SERVER_FLAVOR_VERSION)['server']


def flavor_list(request):
    return _get(request, '/flavors',
                microversion=SERVER_FLAVOR_VERSION).get('flavors', [])


def stack_server_resize(request, stack_id, server_id, plan):
    return _write(request, '/stacks/%s/servers/%s/action' % (
        stack_id, server_id), 'POST', {'resize': {'flavor': plan}},
        microversion=RESIZE_VERSION)


DATABASE_VERSION = '1.29'


def database_engine_list(request):
    return _list(request, '/database_engines', 'database_engines',
                 microversion=DATABASE_VERSION)


def database_list(request, **filters):
    path = '/databases'
    if filters:
        path += '?' + parse.urlencode(filters)
    return _list(request, path, 'databases', microversion=DATABASE_VERSION)


def database_get(request, database_id):
    return _get(request, '/databases/' + database_id,
                microversion=DATABASE_VERSION)['database']


def database_create(request, **values):
    return _write(request, '/databases', 'POST', {'database': values},
                  microversion=DATABASE_VERSION)['database']


def database_delete(request, database_id):
    return _write(request, '/databases/' + database_id, 'DELETE',
                  microversion=DATABASE_VERSION)


def database_credentials(request, database_id):
    # Preserve opaque credentials exactly; transport logging is disabled.
    response = _raw_request(
        request, '/databases/' + database_id + '/credentials', 'GET',
        microversion=DATABASE_VERSION)
    return response.json()['credentials']


def database_update(request, database_id, **values):
    return _write(request, '/databases/' + database_id, 'PATCH',
                  {'database': values}, microversion=DATABASE_VERSION)


def database_action(request, database_id, action):
    return _write(request, '/databases/%s/action' % database_id, 'POST',
                  {action: {}}, microversion=DATABASE_VERSION)


def database_logs(request, database_id, tail=None, since=None):
    params = {k: v for k, v in {'tail': tail, 'since': since}.items()
              if v is not None}
    path = '/databases/%s/logs' % database_id
    if params:
        path += '?' + parse.urlencode(params)
    return _get(request, path, microversion=DATABASE_VERSION).get('logs', {})


def database_backup_policy_get(request, database_id):
    return _get(request, '/databases/%s/backup_policy' % database_id,
                microversion=DATABASE_VERSION)['backup_policy']


def database_backup_policy_update(request, database_id, values):
    return _write(request, '/databases/%s/backup_policy' % database_id, 'PUT',
                  {'backup_policy': values}, microversion=DATABASE_VERSION)


def database_backup_list(request, database_id):
    return _list(request, '/databases/%s/backups' % database_id, 'backups',
                 microversion=DATABASE_VERSION)


def database_backup_create(request, database_id):
    return _write(request, '/databases/%s/backups' % database_id, 'POST',
                  {}, microversion=DATABASE_VERSION)


def _database_panel(request):
    match = getattr(request, 'resolver_match', None)
    return (getattr(match, 'namespace', '') or '').endswith('coast.databases')


def service_dockerfile_get(request, service_id):
    return _get(request, '/services/%s/dockerfile' % service_id,
                microversion=PASTED_SOURCE_VERSION)['dockerfile']['text']


def service_dockerfile_update(request, service_id, text):
    return _write(request, '/services/%s/dockerfile' % service_id, 'PUT',
                  {'dockerfile': {'text': text}},
                  microversion=PASTED_SOURCE_VERSION)['dockerfile']['text']
