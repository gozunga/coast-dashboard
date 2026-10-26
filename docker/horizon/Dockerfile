# Horizon image for Coast: the stock Kolla Horizon image with
# coast-dashboard and python-coastclient installed into the Kolla venv.
#
# Build with tools/build-horizon-image.sh. It passes this repository as the
# main context and a python-coastclient checkout as the "coastclient" build
# context. Both need their .git directory so pbr can compute the version and
# include templates and static files.
#
# Kolla's start script runs collectstatic and compress on every fresh
# container, so nothing is compressed at build time.
#
# BASE_IMAGE is required: the Kolla Horizon image to extend, for example
# <registry>/kolla/horizon:2026.1-ubuntu-noble.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

ARG COAST_DASHBOARD_REVISION=unknown
ARG COASTCLIENT_REVISION=unknown
LABEL org.opencontainers.image.title="horizon-coast" \
      org.opencontainers.image.description="Kolla Horizon with coast-dashboard" \
      org.opencontainers.image.source="https://github.com/gozunga/coast-dashboard" \
      org.opencontainers.image.revision="${COAST_DASHBOARD_REVISION}" \
      coast_dashboard_revision="${COAST_DASHBOARD_REVISION}" \
      coastclient_revision="${COASTCLIENT_REVISION}"

# The sources are bind-mounted, so .git never lands in an image layer.
# safe.directory: the mounted trees are not owned by the build user.
# No network: everything needed (pbr, setuptools) is already in the venv,
# and Kolla hosts often run docker without a default bridge.
RUN --network=none \
    --mount=type=bind,source=.,target=/src/coast-dashboard,rw \
    --mount=type=bind,from=coastclient,source=.,target=/src/python-coastclient,rw \
    set -eux; \
    VENV=/var/lib/kolla/venv; \
    git config --system --add safe.directory '*'; \
    "$VENV/bin/pip" install --no-deps --no-cache-dir --no-build-isolation \
        /src/python-coastclient /src/coast-dashboard; \
    git config --system --unset-all safe.directory; \
    SP="$("$VENV/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"; \
    # Fail the build if pbr left out templates or static files.
    test -d "$SP/coast_dashboard/templates/project"; \
    test -d "$SP/coast_dashboard/templates/admin"; \
    test -d "$SP/coast_dashboard/static"; \
    "$VENV/bin/python" -c 'from coastclient.v1 import client; import coast_dashboard; import designatedashboard'; \
    cp "$SP"/coast_dashboard/enabled/_19*.py "$SP/openstack_dashboard/local/enabled/"; \
    ls "$SP"/openstack_dashboard/local/enabled/_19*.py
