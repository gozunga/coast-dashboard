===============
coast-dashboard
===============

0.1.0
=====

.. Source: releasenotes/notes/first-release-0-1-0-5c2a9d7e831b460f.yaml

Version 0.1.0 is the first release of coast-dashboard, a Horizon plugin for Coast application hosting on OpenStack. It adds App Hosting panels to manage stacks, app groups, environments, applications and template services through the public Coast API, with resource details, deployment status, domains, environment settings and logs.

These notes describe the features in 0.1.0. Source fragments are in
``releasenotes/notes/``.

Features
--------

.. Source: releasenotes/notes/admin-coast-panel-3f0ec74be32eae7a.yaml

* Add a read-only Coast panel to Horizon's Admin dashboard. Operators can
  inspect stacks across projects, map servers to Nova instances and Glance
  images, inspect attached volumes and workload placement, and read server
  history. Access requires Horizon admin permissions and Coast admin policy
  checks. The panel uses admin stack inventory API microversion 1.18,
  including explicit cross-project stack detail reads and Nova IDs in
  server create/delete and failover history. Missing fields remain optional.

.. Source: releasenotes/notes/admin-stacks-topology-7c6bb8ca93b942f0.yaml

* The read-only admin panel is App Hosting > Stacks at
  ``/admin/stacks/``. It shows linked projects, worker/build counts,
  App engine server versions, health summaries, expandable server rows,
  host filters and stack/instance/IP search. Details include Volumes and
  a cloud topology with missing-resource markers. Cloud resource names
  and IDs are preserved.

.. Source: releasenotes/notes/app-sources-139.yaml

* Apps can now use a private Git repository with a generated or uploaded
  deploy key, a pasted or uploaded Dockerfile, or Docker Compose. Public
  deploy keys can be copied and replaced from the app details. Dockerfiles
  and Compose configuration can be saved without deploying.
  Private key upload fields appear only when uploading a deploy key.
  Generated keys are ed25519 key pairs. Only the public key is returned;
  private keys stay in Barbican and never appear in API responses, the CLI
  or dashboard. Creation with a generated key does not deploy: add the public
  key to the Git host, then deploy. After rotation, authorize the replacement
  public key at the Git host before deploying.
  On redeploy, an unchanged Dockerfile is skipped and its image reused.
  A changed Dockerfile is refused: "This app can't use a changed Dockerfile.
  Create a new app from the new Dockerfile, or deploy from a Git repository."

.. Source: releasenotes/notes/databases-panel-8b365d1eb542a009.yaml

* Added a Databases panel with an engine catalog, database creation,
  connection details, and deletion with name confirmation. Standalone database
  engines use Databases; bundled application templates remain in Services.
  Members can reveal credentials on demand; passwords are never included
  in the initial page or cached.
  Supported engines and versions are shown in the create form and come
  from Coast's ``coast/common/engine_versions.py``.

.. Source: releasenotes/notes/database-operations-9c138ae70b213cbb.yaml

* Databases now offer start, stop and restart actions, runtime logs,
  resource limits and IPv4 public access controls. Supported engines
  include scheduled backups, downloads and restores into a new database.
  Backups require a Swift-compatible object-storage endpoint on the cloud.
  They are not verified end to end in 0.1.0; full verification is tracked
  for 0.1.1 (gozunga/coast#124).

.. Source: releasenotes/notes/appgroup-inline-status-6c38a41e0b7f429d.yaml

* App Groups omit the Status column and show badges next to non-active names:
  Creating for pending groups, Deleting during deletion, Error on failure,
  and title-cased labels for other states. Active names have no badge.
  App group references in Environments, Apps, Services, and detail tables use
  the same display. Badge labels, colors, and AJAX polling are shared with
  environments.

.. Source: releasenotes/notes/appgroup-relations-f62b8c193e1a406d.yaml

* App Groups show linked counts for Environments, Apps, and Services.
  Groups with up to three environments show their names as detail links.
  Related list panels support an appgroup query parameter and a clear-filter
  link. App group details include related resource tables and empty states.

.. Source: releasenotes/notes/appgroup-rename-c4e2a9f1b7d35068.yaml

* App Groups (slug ``coast.appgroups``) contain environments, apps and
  services. Apps (``coast.apps``) lists ``kind=app``; Services
  (``coast.services``) lists ``kind=service`` template workloads.

.. Source: releasenotes/notes/build-flavor-any-workers-9a1c3e5b7d2f4068.yaml

* Create Stack offers Nova flavors with a configured Coast VM plan for
  each role: App engine server, worker and optional build server. It
  preselects the first allowed flavor, sorted by RAM and name. Worker
  count is at least one; choosing a build server flavor does not restrict
  that count. Plan lookup uses Coast API 1.1. Stack creation uses 1.1
  when a build server flavor is selected and 1.0 otherwise.

.. Source: releasenotes/notes/change-image-in-place-d36065de8b1a664c.yaml

* Image-based services have a Change image action and an image link on
  Overview. The form keeps the current image and tag, displays API validation
  faults, and offers Save or Save and redeploy. Redeploy opens live Logs.
  Requires Coast API microversion 1.14. Settings, variables, storage and
  domains are kept.

.. Source: releasenotes/notes/compose-editor-4910ba16ae8270e5.yaml

* Compose services have a Compose tab for project members and admins.
  Users can save the full YAML document or save and redeploy, then follow
  live runtime logs. API validation errors keep the submitted edits in the
  editor. This feature requires Coast API microversion 1.12. Runtime logs
  refresh every three seconds by default.

.. Source: releasenotes/notes/console-tab-7c4e1a9b2d6f4083.yaml

* Project members and admins can open a console from the Console tab on
  an app or a service. Connect asks Coast for a session address with
  ``POST /v1/apps/{id}/console`` or ``POST /v1/services/{id}/console``
  at microversion 1.9. The browser opens that session. Coast records
  when the session opens and when it closes, and does not record
  keystrokes or screen text. By default sessions close after 15 minutes
  without terminal data
  in either direction or four hours total; operators can change the
  limits. Readers do not see the tab.

.. Source: releasenotes/notes/container-config-files-e26c5a9ed20bdc1f.yaml

* Apps and services have a Files tab beside Storage. Users can add,
  edit, and delete container config files through Coast microversion 1.15.
  File changes apply on the next deploy. Content is write-only; editing
  preserves it unless replacement is selected. The dashboard shows Coast
  validation messages and uses the standard delete confirmation.
  File sizes are not returned by the API, and permission modes cannot be
  set. Template services can select a container by name.

.. Source: releasenotes/notes/customer-add-server-ecbe8120a31d079f.yaml

* Customers can add a worker or build server from a stack's Servers tab,
  choosing a role-compatible flavor independently of the stack's plan.
  The action checks project compute and volume quotas before submitting.
  Coast API microversion 1.27 is required for the flavor allowlist and
  customer-visible server flavor information.

.. Source: releasenotes/notes/dashboard-app-env-58b6e9247ac01d33.yaml

* App Groups and Environments have create actions with ACTIVE parent
  choices and delete actions with confirmation. Transitional rows refresh.
  Create App supports public HTTPS Git repositories with an optional base
  directory and container images with a tag. Source fields follow the
  source type. Creation requests the first deployment.

.. Source: releasenotes/notes/dashboard-panels-6df2b7308c914eaa.yaml

* Stack details show server roles and status. Apps and services have
  deployment history, domains, Env vars and inline Logs tabs. Horizon
  tables refresh transitional rows. Secret environment values are masked
  as ``********`` before rendering. Public service responses omit
  task_state; deployment history supplies build/deploy progress where
  fetched. Runtime logs use repeated HTTP reads rather than streaming.

.. Source: releasenotes/notes/dashboard-skeleton-1a2b3c4d5e6f7a8b.yaml

* The Project dashboard has an App Hosting panel group with Stacks,
  App Groups, Environments, Apps and Services. Panels require an
  ``app-hosting`` catalog entry and use python-coastclient.

.. Source: releasenotes/notes/database-backups-tab-7c93e4b2d6a1408f.yaml

* Database services have a Backups tab when the Coast API supports backup
  control (microversion 1.20). The tab includes daily schedules, daily and
  weekly retention, explicit database engine and container selection, manual
  backups, history, downloads, deletion, and restore into a new copy or over
  the existing database. Overwrite requires the service name and explains
  the database stop and safety backup. Older APIs hide the tab.
  Backups need a Swift-compatible object-storage endpoint in the cloud;
  backups are not verified end to end in 0.1.0; full verification is tracked
  for 0.1.1 (gozunga/coast#124).

.. Source: releasenotes/notes/deployment-reason-9a1c5e3b7d2f6084.yaml

* The Deployments table shows the failure reason Coast reports.

.. Source: releasenotes/notes/designate-dns-6b81ea23c94d071f.yaml

* Stacks can use a project DNS zone as the default domain for new apps.
  App and service domains can use a host and a project zone with automatic
  DNS management. The Domains tab shows Coast-managed records and keeps
  manual record instructions for external zones. These controls require
  the DNS API microversion and are hidden on older Coast deployments.

.. Source: releasenotes/notes/detail-resource-ids-09e7d62c1b8a435f.yaml

* List tables for Stacks, App Groups, Environments, Apps, and Services omit
  UUID columns. Parent names replace stack and app group IDs, including on
  AJAX row updates and in the template catalog. Missing parent names display
  as unavailable. Resource detail pages show the ID with a copy button.

.. Source: releasenotes/notes/env-developer-view-6a1c3e5b7d9f2e04.yaml

* The Env vars tab has a Developer View button that swaps the table for
  one .env text box (KEY=value per line, comments and quoted values).
  Saving applies the whole set; invalid lines are reported and nothing is
  saved. Normal View switches back.

.. Source: releasenotes/notes/env-no-autofill-3d9b7f1e2a4c6b08.yaml

* Environment variable forms disable autofill. Values are plain text while
  Secret is clear and masked while Secret is checked. Saved secret values
  are write-only; leaving an existing secret blank preserves its value.

.. Source: releasenotes/notes/env-paste-markers-7b2e9c41d6a35f08.yaml

* The environment variable Developer view (.env paste) accepts a
  ``# secret`` trailing marker that stores the value as a secret, next to
  the existing ``# runtime-only`` and ``# build-time`` markers. Markers
  combine with commas in any order, for example
  ``KEY=value # secret, runtime-only``. Secret rows render with
  ``# secret`` so the text round-trips. Unmarked lines never make a secret
  plain again.

.. Source: releasenotes/notes/environment-inline-status-4ab19e5d7c804362.yaml

* Environment lists omit the Status column. Non-active environments show a
  badge next to their name using the shared status colors: Creating for
  pending environments, Deleting during deletion, Error on failure, and
  title-cased labels for other states. Active environments have no badge.
  This also applies to app group environment links and related tables and
  to environment names in Apps and Services. AJAX row updates are preserved.

.. Source: releasenotes/notes/environment-resources-status-colors-c70a915e8b2d463f.yaml

* Environment details list apps and services from a fresh API request on
  each load, with detail links, kind, and status badges.

.. Source: releasenotes/notes/friendly-create-forms-5ed2c7d4e34f108b.yaml

* Create forms explain stacks, app groups, environments, apps, services,
  domains and environment variables, with field guidance. Stack creation
  loads App engine server, worker and optional build server flavors from
  Nova,
  sorted by RAM and name. Choices show CPU, RAM and disk capacity and send
  flavor names to Coast. The optional build server flavor is shown only
  when a build server is selected. If flavors cannot be loaded, the form
  shows a message and leaves the flavor choices empty.

.. Source: releasenotes/notes/health-check-4a1c7e9f2053b860.yaml

* App creation, service templates with ports, and Edit Settings offer
  an optional HTTP health check. New apps default to None, so background
  workers can run without ports. HTTP checks support a port and path and
  use Coast API microversion 1.4. Existing apps keep their HTTP setting.
  The overview shows the check type and identifies apps with no public URL.

.. Source: releasenotes/notes/kolla-horizon-image-41c0a5e2d7b9f316.yaml

* Added ``docker/horizon/Dockerfile`` and ``tools/build-horizon-image.sh``
  to build a Kolla Horizon image with python-coastclient and
  coast-dashboard installed and the Coast panels enabled. Kolla
  reconfigures and deploys of Horizon keep the Coast dashboard.

.. Source: releasenotes/notes/names-logs-actions-5c2e8a1f7d3b9064.yaml

* Worker choices show ``<stack name> / <worker>``. Apps and Services
  tables show app group and environment names. Logs shows the last 200
  runtime lines with Refresh and auto-refresh every three seconds.
  Deployments offer View Build Log and Cancel Deployment. Redeploy is
  available before the first deployment and while idle; in-flight
  deployment tasks block it. Batch failures show Coast API reasons.
  The Ports field explains which port to enter.

.. Source: releasenotes/notes/native-resource-details-3af68e21d094475c.yaml

* Resource details use native Horizon tabs, resource names as page titles,
  and header actions. App and service Overview tabs show resource fields.
  Separate Deployments, Logs, Domains, and Env vars
  tabs preserve deployment cancellation, runtime logs, and settings features.
  Environment, App Group, and Stack details have scoped related-resource
  tabs.
  App and service actions include Start, Stop, and Restart with state checks.

.. Source: releasenotes/notes/nested-panel-urls-9e4b2c7a1f5d3068.yaml

* Project panels use ``/project/coast/stacks/``,
  ``/project/coast/appgroups/``, ``/project/coast/environments/``,
  ``/project/coast/apps/`` and ``/project/coast/services/``. Their slugs
  are ``coast.stacks``, ``coast.appgroups``, ``coast.environments``,
  ``coast.apps`` and ``coast.services``.

.. Source: releasenotes/notes/oneclick-appgroup-field-3b9e1c4d7a2f5e60.yaml

* Create Service sends the selected app group as ``appgroup_id``, along
  with its environment and worker IDs.

.. Source: releasenotes/notes/oneclick-create-76ef938abd012345.yaml

* The Services panel includes the Coast template catalog, a Create
  Service form, and a Deploy action for each template. Creation requires
  an active worker in the app group stack and requests deployment.

.. Source: releasenotes/notes/oneclick-defaults-7dbf294c61e843a0.yaml

* The one-click Create Service form defaults to a name based on the selected
  template. Existing names in the selected app group use the next available
  numeric suffix. Template and app group changes update the suggested name
  in the browser while preserving custom names. Compatible app group,
  environment, and worker choices default only when there is one
  compatible choice. All fields remain
  editable, and initial defaults also work without JavaScript.

.. Source: releasenotes/notes/qa-services-urls-wording-2c7a9e4f1b3d6a58.yaml

* Service pages live under ``/project/coast/services/<id>/`` for detail,
  logs, console, deployments, env vars, domains and settings. Webhooks is
  an app-only tab. Deployment times use the user timezone. Deployment
  failure messages point to stack Activity where applicable; build logs
  scrub engine helper image names. Env var Secret shows Yes or No.

.. Source: releasenotes/notes/redeploy-detail-domains-4c8e1a7b9d0f42ab.yaml

* Create App and Redeploy open the deployment page when Coast returns a
  deployment ID. Template service creation and redeployment open Logs.
  Overview shows a worker name linked to its stack and links to workload
  addresses and domain management. The resource ID is the first field.
  Create Service selects an app group, environment or worker only when
  there is one compatible choice; users can change these fields.
  Domains show DNS records and a Verify action where allowed. Add
  Domain and Edit Domain offer Let's Encrypt or plain HTTP.
  The settings banner requests redeploy only for pending changes. Name
  and description changes show a saved message.

.. Source: releasenotes/notes/resource-concept-help-a74c159e8d2b436f.yaml

* Create App Group, Create Environment, Create App, and Create Service forms
  have brief Description text explaining the resource and its placement.
  Stacks, App Groups, Environments, Apps, and Services list pages start
  with a short introduction to the resource and how it relates to the others.

.. Source: releasenotes/notes/resource-links-edit-settings-a51f7c8d29e046b3.yaml

* Apps and Services have an Edit Settings row action and a detail-page
  button. The existing form supports name, ports, CPU and memory limits,
  healthcheck path, description, and Git source branch updates. After save,
  Overview shows a redeploy banner when Coast reports pending changes.
  Replica edits are omitted because the API does not support replica PATCH.

.. Source: releasenotes/notes/server-resize-7d1a3f8c90b42e65.yaml

* Project stack Servers tabs offer Resize for idle, ACTIVE VM workers,
  build servers and the App engine server. The modal shows the current flavor
  and only larger operator flavors allowed for the server role. Accepted
  requests return to the Servers tab and use existing asynchronous row
  polling.
  Requires Coast API 1.27 for the customer flavor catalog and server sizes.

.. Source: releasenotes/notes/service-container-views-43ba11f6713cef20.yaml

* Compose service details include a Containers tab. Each container has
  Overview, Logs and Environment tabs, with resource limits, health and
  restart counts. Logs refresh every three seconds. Container reads use
  Coast API microversion 1.13 and preserve its secret masking and fault
  messages. Detail and log responses prevent browser caching.

.. Source: releasenotes/notes/service-metrics-6a90d8ca4b7e491f.yaml

* Service and app detail pages include a Metrics tab when Coast
  advertises API microversion 1.21 or later. Stacked CPU and memory charts,
  per-container memory limit lines, and current values refresh every
  30 seconds while the tab is visible. Six time ranges cover 15 minutes
  through 30 days.

.. Source: releasenotes/notes/service-settings-58d41c06a68a732e.yaml

* Apps and services have separate Env vars and Domains tabs. Variables
  can be added, edited and deleted without replacing unrelated keys.
  Saved secret values stay hidden; Coast reports when redeploy is needed.

.. Source: releasenotes/notes/service-worker-required-3c1d2e4f5a6b7c8d.yaml

* App and template service creation require an active worker in the
  selected app group stack; Coast does not choose placement automatically.

.. Source: releasenotes/notes/settings-banner-2e9c4a7b1f5d6083.yaml

* Edit Settings is available from app and service rows and detail headers.
  When Coast reports ``pending_changes``, Overview shows a redeploy banner.
  Redeploy availability follows the resource and deployment state.

.. Source: releasenotes/notes/stack-column-apps-services-4e1d2a7b9c3f5e60.yaml

* The Apps and Services tables show a Stack column linked to the stack,
  and app and service detail pages show a linked Stack row, so items with
  the same name on different stacks can be told apart.

.. Source: releasenotes/notes/stack-firewall-9f5b1e7c42a068d3.yaml

* Project stack pages include a Firewall tab for listing worker ingress
  rules and adding or deleting custom rules. Required rules are marked
  "Managed by Coast" and cannot be deleted. The Overview shows open ports
  and links to edit the rules. Firewall management requires Coast API
  microversion 1.25 or later; the tab and overview link are hidden on older
  APIs.

.. Source: releasenotes/notes/stack-firewall-9f5b1e7c42a068d3.yaml

* Admin stack overviews display Worker security group and Management
  security group names with copyable IDs.
  The worker security group rules list identifies customer-added rules.

.. Source: releasenotes/notes/storage-tab-e5435b2a378d9ed1.yaml

* App and service Storage tabs list typed service mounts at API 1.19.
  Members and admins can create and edit user mounts; managers and admins
  can delete them. Template-origin mounts are read-only in the dashboard.
  Deleting a mount keeps its data; deploy to apply mount changes.

.. Source: releasenotes/notes/typed-storage-99bb6b92515f4a21.yaml

* The app and service Storage tab has an explicit choice between a
  bind mount (host folder) and a named volume. User mounts can be edited
  and deleted; mounts from templates show their type and source and are
  read-only in the dashboard. The tab is hidden until the API advertises
  the typed storage microversion.
  The dashboard uses the API 1.19 contract. Only managers and
  administrators can delete mounts. Delete keeps the data, and storage
  changes take effect on deployment.

.. Source: releasenotes/notes/worker-name-log-refresh-8e2a4c6b1d3f5a07.yaml

* Overview links the worker name to its stack. Runtime Logs auto-refresh
  every three seconds.

Behavior and validation
-----------------------

.. Source: releasenotes/notes/api-error-messages-6d3b9f1a2c8e4075.yaml

* Create and update forms show Coast API 4xx fault messages. Server errors
  use a generic message.

.. Source: releasenotes/notes/api-error-messages-6d3b9f1a2c8e4075.yaml

* Create Stack lists only Nova flavors that have a Coast plan for each
  role (App engine server, worker, build server).

.. Source: releasenotes/notes/console-status-connected-5b2e8d1f4a6c9e03.yaml

* The Console tab shows "Connected." as soon as the shell is live. When
  the session ends, the status
  says so in red, the terminal is dimmed and stops taking input, and only
  the Reconnect button is shown.

.. Source: releasenotes/notes/create-app-single-preselect-5b1d2e7c9a3f4e10.yaml

* Create App leaves the app group, environment and worker unselected when
  there is more than one to choose from.

.. Source: releasenotes/notes/detail-redeploy-worker-search-d17034c951b842af.yaml

* Apps and services can redeploy before their first deployment and while
  idle, including STOPPED resources with pending changes. The pending-change
  banner and header actions use the same rule and block in-flight operations.
  Details keep one header Edit Settings action and show the worker name
  linked
  to its stack. Template search submits a q query, resets pagination, and
  filters the full catalog before applying the 50-row page limit.

.. Source: releasenotes/notes/engine-neutral-wording-c75f186a9b2043de.yaml

* Stack introductions, creation descriptions, flavor labels, and server role
  labels use engine-neutral wording. The control server is labeled
  App engine server. Internal API role keys and driver names are unchanged.

.. Source: releasenotes/notes/env-value-plain-text-7d2e4a9c1b6f3e05.yaml

* The environment variable form for apps and services shows the value as
  plain text and masks it only while Secret is checked. Saved secret
  values stay hidden and write-only.

.. Source: releasenotes/notes/environment-resources-status-colors-c70a915e8b2d463f.yaml

* Tables and detail pages use shared status badge colors. Stopped and
  cancelled resources are gray, active and running resources are green,
  pending operations are yellow, and failures are red. Cancelled resources
  with a fault or error are red. Unknown states are gray.

.. Source: releasenotes/notes/native-resource-details-3af68e21d094475c.yaml

* Edit Settings has the AJAX template and stable modal/form IDs required
  by Horizon. Both modal links and normal page navigation open the existing
  settings form. Settings saves return to Overview; pending changes show
  a redeploy banner.

.. Source: releasenotes/notes/resource-links-edit-settings-a51f7c8d29e046b3.yaml

* Resource name links in Apps, Services, Environments, and App Groups
  resolve detail URLs with explicit resource IDs.

.. Source: releasenotes/notes/service-catalog-pagination-b93e82a10f6d407c.yaml

* The Services template catalog fetches one catalog per engine version
  and shows each template once. Name and category search and 50-row pages
  reduce the size of the page. Deploy actions identify the template.
  Service rows use status and deployment IDs from the list API, without
  per-service deployment calls or row polling. No Horizon process cache is
  used.

.. Source: releasenotes/notes/template-deploy-logs-3b7c9e1a5d2f4e68.yaml

* Deploying or redeploying a template service opens the service Logs
  tab, which polls runtime logs. A template service deployment page shows
  its status and times without a build log box. Built services keep
  the build log.

.. Source: releasenotes/notes/topology-app-service-counts-2c8f61a9e0b74d35.yaml

* The stack Topology Servers panel counts apps and services separately
  (for example "1 app, 1 service"), omits zero parts, and shows "No apps"
  when a server runs nothing.
