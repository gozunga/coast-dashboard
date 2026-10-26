===============
coast-dashboard
===============

Horizon plugin for Coast, OpenStack application hosting. It gives
project users a web UI for the same public Coast API that the
``openstack coast`` CLI uses, and gives cloud admins a read-only
cross-project stack inventory. It adds an **App Hosting** panel group to
the Project dashboard:

* **Stacks**: list, create (app engine server flavor, worker flavor and count,
  optional build server) and delete. Detail tabs: Overview (status, engine
  version, default domain zone), Topology, Servers (add server, resize to a
  larger flavor), App Groups, Activity (stack events) and Firewall (worker
  ingress rules: list, add, delete; Coast managed rules cannot be deleted).
* **App Groups**: list, create and delete. Detail shows environments, apps and
  services.
* **Environments**: list, create and delete. Each app group starts with a
  ``production`` environment. Detail lists its apps and services.
* **Apps** (slug ``coast.apps``): create from a public HTTPS or private SSH Git
  repository, a container image, a pasted or uploaded Dockerfile, or Docker
  Compose; edit settings, change image, redeploy, start, stop,
  restart and delete. Detail tabs: Overview, Deployments (build log, cancel),
  Logs, Console, Metrics, Domains (add, edit, verify, make primary, default
  address on/off), Storage, Files, Env vars (add, edit, delete; developer
  ``.env`` view), Compose, Containers and Webhooks (show and regenerate deploy
  and Git push URLs).
* **Databases** (slug ``coast.databases``): engine catalog, creation,
  connection details, credential reveal, resource limits, IPv4 public access,
  start, stop, restart, logs and deletion with name confirmation. Supported
  engines and versions are shown in the create form and come from Coast's
  ``coast/common/engine_versions.py``. Supported engines offer scheduled and
  manual backups, downloads and restore into a new database. Backups require
  a Swift-compatible object-storage endpoint on the cloud and are not verified
  end to end in 0.1.0; full verification is tracked for 0.1.1 (#124).
* **Services** (slug ``coast.services``): one-click bundled application
  templates. Pick a template and deploy it; the detail page is the same as for
  apps. Recognized database templates add backup policy, manual backups,
  restore (new copy or overwrite), download and delete under Backups. Backups
  need a Swift-compatible object-storage endpoint in the cloud;
  backups are not verified end to end in 0.1.0; full verification is tracked
  for 0.1.1 (gozunga/coast#124). Services
  do not show Webhooks. Compose and Containers are shown only for Compose
  workloads, including templates. Backups, Metrics and Storage require the
  corresponding API support.

Private Git apps can generate an ed25519 deploy key pair or accept an uploaded
private key. Only the public key is returned; private keys are stored in
Barbican and never appear in API responses, the CLI or dashboard. Creation
with a generated key does not deploy: add the public key to the Git host,
then deploy. App details let you copy the public key and rotate the deploy
key; authorize the replacement public key at the Git host before deploying.

Dockerfile and Compose edits save without deploying. Compose also offers
Save and redeploy. On redeploy, an unchanged Dockerfile is skipped and its
image reused. A changed Dockerfile is refused with: "This app can't use a
changed Dockerfile. Create a new app from the new Dockerfile, or deploy from
a Git repository."

Stacks, Servers, App Groups, Environments and Apps tables refresh rows every
five seconds while Coast reports a transitional state. The Services list does
not poll rows. Creation, deployment, resize and deletion are asynchronous: a
successful request does not mean the operation has finished.

The Project panels call the public Coast API (catalog type ``app-hosting``)
through ``python-coastclient`` with the logged-in user's token. They appear
only when that service is in the catalog. Coast enforces access policy. Horizon
also checks roles for console, Compose, files, storage, backups and image
changes; Resize checks Coast policy locally. Other actions can be visible even
when Coast will reject them. Stack creation reads Nova flavors; adding a server
checks Nova and Cinder project quotas. Each feature uses the microversion it
needs (for example 1.3 webhooks, 1.9 console, 1.19 storage, 1.26 server resize,
1.27 server flavors).

Secret environment values are replaced with ``********`` in the API wrapper
before they reach a template. Coast stores environment values in Barbican using
its configured service credentials; secret values are write-only through the
public API. Barbican also stores deploy private keys, database passwords,
Dockerfile and Compose text, configuration file contents and deployment
snapshots of those values. Coast deletes owned secrets on workload or stack
teardown, retrying failed cleanup. The conductor retrieves values for
deployment and runtime updates.
Apps offer Build-time (on by default for new variables in the form) to also
pass variables to builds; turn it off for runtime-only exposure. Template
service variables are runtime-only. Marking a value Secret hides it on API
reads and in the dashboard; the container still receives it, as does the build
when Build-time is on. Logs reads ``GET /services/{id}/logs`` with the user's
token; it does not put a token in a URL. Log text is escaped. Paginated
resource lists follow API pagination markers.

Console (project members and admins) opens a browser terminal (xterm.js) into
the app or service container. Coast records when the session opens and closes,
not keystrokes or screen text. By default, Coast closes the session after 15
minutes without terminal data in either direction, or after four hours total;
operators can change these limits. A reader does not see the tab.

Install
-------

Into the Horizon environment::

    pip install python-coastclient coast-dashboard

Or from the public repositories::

    pip install git+https://github.com/gozunga/python-coastclient.git
    pip install git+https://github.com/gozunga/coast-dashboard.git

The dashboard uses ``coastclient.v1.client.Client`` and its
``request(path, method, **kwargs)`` interface. Unit tests mock the client.

Enable the panels by copying the enabled files into Horizon's
``openstack_dashboard/local/enabled`` directory::

    cp coast_dashboard/enabled/_19*.py \
        <horizon>/openstack_dashboard/local/enabled/

Then restart Horizon. The enabled files are ``_1900`` (panel group),
``_1910`` (Stacks), ``_1920`` (App Groups), ``_1930`` (Environments),
``_1940`` (Apps, slug ``coast.apps``), ``_1942`` (Databases), ``_1945`` (Services, slug
``coast.services``) and ``_1950``/``_1951`` (Admin App Hosting).

Kolla Horizon image
-------------------

For Kolla deployments, build our own Horizon image instead of copying files
into a running container. ``kolla-ansible reconfigure`` or ``deploy`` of
Horizon recreates the container from its image, so hand-copied files are
lost. ``docker/horizon/Dockerfile`` starts from the stock Kolla Horizon image
and installs python-coastclient and coast-dashboard into the Kolla venv, then
enables the ``_19*`` panels. Stock panels such as Designate stay managed by
Kolla. Kolla's start script compresses static files on each fresh container.

On a host whose docker is logged in to the registry::

    REGISTRY=registry.example.com:5000 \
        COASTCLIENT_SRC=~/python-coastclient tools/build-horizon-image.sh

This pushes ``<registry>/kolla/horizon:2026.1-ubuntu-noble-coast-<sha>`` and
the moving tag ``2026.1-ubuntu-noble-coast``. Point Kolla at it in
``globals.yml``::

    horizon_tag: "2026.1-ubuntu-noble-coast"

Then run ``kolla-ansible deploy -t horizon``. To roll back, remove
``horizon_tag`` (or set a previous ``-coast-<sha>`` tag) and deploy again.

Admin App Hosting panel
-----------------------

The ``_1950`` and ``_1951`` enabled files add **Admin -> App Hosting -> Stacks**.
This read-only panel lists stacks across projects and has Overview, Servers,
Volumes, Workloads, History and Topology tabs. The Actions menu only refreshes the detail page.
It does not call a write endpoint. IDs are shown in details, not table cells.

Access requires Horizon admin roles, the app-hosting catalog entry, and these
Coast policy checks: ``coast:stack:get_detail``, ``coast:server:get_detail`` and
``coast:volume:get_detail``. To apply the operator's Coast policy overrides in
Horizon, copy the Coast policy file to Horizon's ``POLICY_FILES_PATH`` and add
``POLICY_FILES['app-hosting'] = 'coast_policy.yaml'`` to local settings. Coast
also enforces policy on every API call. Without a local Coast policy file,
Horizon still requires admin permissions; the API remains authoritative.

Admin inventory reads use ``coast_dashboard.api.coast.ADMIN_VERSION`` through
the existing adapter at **1.18**, the admin stack-inventory API version. The
Overview also reads worker ingress rules at 1.25 when supported. The endpoints
are ``GET /v1/stacks?all_projects=true``, ``GET
/v1/stacks/{id}?all_projects=true``, ``GET /v1/stacks/{id}/servers``, ``GET
/v1/stacks/{id}/volumes``, ``GET /v1/services?stack_id={id}``, and ``GET
/v1/stacks/{id}/events``. Collection reads include ``all_projects=true``; stack
detail also includes that flag. History is paged and filtered to server events.
Create/delete events show ``compute_id``; failover events show
``old_compute_id`` and ``new_compute_id`` when supplied. Fields can be absent
or null; the display uses a dash. An absent service project means cloud lookups
use the owning project.

Admin URLs are ``/admin/stacks/`` and ``/admin/stacks/{id}/``. The list has
project, status and host filters and case-insensitive search for stack names,
Nova names/IDs and IPs. Expand a stack row to see its servers. Health counts
servers ACTIVE in both the stack inventory and Nova; it is not an application
health probe. Worker/build numbers follow creation time and ID for stable
ordering. ``engine_version`` supplies the App engine server version, or a dash.

Topology is a server-rendered SVG with Horizon-style resource boxes and
links; it needs no new JavaScript dependency. Edges come from Neutron ports
and Cinder attachments, with inventory references retained for deleted
resources. Missing resources have dashed borders and a "not found" label.
The API has no management/backplane network ID: Neutron port addresses are
matched to server ``mgmt_ip`` values. An unknown network cannot be recovered
when neither the API nor remaining ports identify it. Workload links open
project detail pages; operators must select the owning project to use them.
Cloud resource names and IDs are displayed unchanged and HTML-escaped.

The Servers tab uses the admin's credentials for one Nova list filtered to the
resource project, one Glance list filtered to the image IDs, and one flavor
list. It matches Nova instances by ``compute_id`` and keeps Coast records
visible when an instance no longer exists. It does not retrieve each instance
or image separately. Keystone resolves project names in a list call. These
results stay within the request and require no sticky sessions. For Horizon API
signatures, see `Horizon API source`_.

.. _Horizon API source:
   https://docs.openstack.org/horizon/2024.2/contributor/api.html

To smoke-test in a configured Horizon deployment:

* Sign in as an admin. Open Admin -> App Hosting -> Stacks and filter by
  project and status, then host and search. Expand a stack row. Open a stack
  and check all six tabs.
* In Servers, follow a Nova instance and a Cinder volume link. Compare the
  host, image, flavor and IPs with their cloud resources. A deleted Nova
  instance must show ``not found`` while the Coast server remains visible.
* Sign in as a member or reader. The Admin Stacks panel and its direct URLs
  must not give access. Apply a Coast admin policy denial and check again.

Development
-----------

Use Python 3.10-3.12 with Horizon 25 and Django 4.2. Run tox itself with a
supported interpreter; Django 4.2 is not compatible with Python 3.14::

    tox -e pep8,py3

Tests use the Horizon TestCase and a mocked Coast client. They cover API
routes and bodies, pagination, secret masking, forms, parent validation,
actions, detail tabs, errors and AJAX row updates. These tests do not prove
completion of real Coast provisioning or deployment operations.

For a manual smoke test in a configured Horizon deployment:

* Open Project -> App Hosting -> Stacks. Create a stack with configured app
  engine server and worker flavors, two workers and the build-server checkbox.
  Open its detail and check that status refreshes and server roles appear.
* Create an app group, then create an app from a public Git repository in its
  ``production`` environment. Select its worker, then deploy from the Apps row
  action. Check the status and Deployments tab until the operation ends.
* Open Domains, Env vars and Logs. Check that secrets show only ``********`` and
  that Logs opens within Horizon. Open Console as a project member, connect,
  and check that the session can end with an exit code. A reader does not see
  Console. Delete the service and stack through their confirmation dialogs.
  Coast can reject deletion while resources are busy.

API contract sources
--------------------

The implementation follows Coast's ``api-ref/source/``,
``coast/api/v1/*_controllers.py``, ``schemas.py`` and ``common/states.py``.
The Horizon table and modal interfaces are documented at:

* https://docs.openstack.org/horizon/2024.2/contributor/ref/tables.html
* https://docs.openstack.org/horizon/2024.2/contributor/ref/forms.html
* https://docs.openstack.org/horizon/2024.2/contributor/ref/tabs.html

Release notes
-------------

See ``RELEASENOTES.rst`` and ``releasenotes/notes/*.yaml`` for 0.1.0 notes.

License
-------

Apache License 2.0. See ``LICENSE``.

Development checks
------------------

``tools/fast-check.sh`` runs flake8 on changed files and the dashboard unit
tests sequentially before pushing.

Merge-request pipelines skip ``py3`` when only release notes or docs change
and skip ``releasenotes`` when no notes change; ``main`` runs everything.
The Gitleaks job scans the current tree with its default secret rules on every
merge request and on ``main``, with no path filter or history scan.
