#!/bin/bash
# Build the Coast Horizon image (stock Kolla Horizon + coast-dashboard) and
# push it to the local registry.
#
# Usage: COASTCLIENT_SRC=/path/to/python-coastclient \
#            tools/build-horizon-image.sh [--no-push]
# Run from a clean checkout of the commit to ship, on a host whose docker is
# logged in to the registry. REGISTRY is required: the registry that holds
# the Kolla images, for example registry.example.com:5000. COASTCLIENT_SRC
# is a clean git
# checkout of python-coastclient at the commit to ship (default:
# ../python-coastclient next to this repository).
#
# Tags pushed:
#   ${REGISTRY}/${NAMESPACE}/horizon:${BASE_TAG}-coast-<short sha>
#   ${REGISTRY}/${NAMESPACE}/horizon:${BASE_TAG}-coast   (moving tag)
# Kolla globals: horizon_tag: "<BASE_TAG>-coast"
set -euo pipefail

REGISTRY=${REGISTRY:?set REGISTRY to the registry that holds the Kolla images}
NAMESPACE=${NAMESPACE:-kolla}
BASE_TAG=${BASE_TAG:-2026.1-ubuntu-noble}
BASE_IMAGE=${BASE_IMAGE:-${REGISTRY}/${NAMESPACE}/horizon:${BASE_TAG}}
DOCKER=${DOCKER:-docker}
PUSH=yes
[ "${1:-}" = "--no-push" ] && PUSH=no

cd "$(git rev-parse --show-toplevel)"
COASTCLIENT_SRC=${COASTCLIENT_SRC:-../python-coastclient}
for repo in . "$COASTCLIENT_SRC"; do
    if [ -n "$(git -C "$repo" status --porcelain)" ]; then
        echo "$repo: working tree not clean; commit or stash first" >&2
        exit 1
    fi
done
SHA=$(git rev-parse --short=7 HEAD)
CLIENT_SHA=$(git -C "$COASTCLIENT_SRC" rev-parse --short=7 HEAD)
IMAGE=${REGISTRY}/${NAMESPACE}/horizon
SHA_TAG=${BASE_TAG}-coast-${SHA}
MOVING_TAG=${BASE_TAG}-coast

$DOCKER pull "$BASE_IMAGE"
DOCKER_BUILDKIT=1 $DOCKER build -f docker/horizon/Dockerfile \
    --build-context "coastclient=${COASTCLIENT_SRC}" \
    --build-arg "BASE_IMAGE=${BASE_IMAGE}" \
    --build-arg "COAST_DASHBOARD_REVISION=${SHA}" \
    --build-arg "COASTCLIENT_REVISION=${CLIENT_SHA}" \
    -t "${IMAGE}:${SHA_TAG}" -t "${IMAGE}:${MOVING_TAG}" .

# Smoke check: the dashboard imports and the panels are enabled.
$DOCKER run --rm --network none --entrypoint /var/lib/kolla/venv/bin/python "${IMAGE}:${SHA_TAG}" -c '
import importlib.metadata as m, glob, sysconfig
sp = sysconfig.get_paths()["purelib"]
import coast_dashboard
from coastclient.v1 import client
print("coast-dashboard", m.version("coast-dashboard"))
print("python-coastclient", m.version("python-coastclient"))
enabled = sorted(glob.glob(sp + "/openstack_dashboard/local/enabled/_19*.py"))
assert enabled, "no Coast panels enabled"
print(len(enabled), "Coast panel files enabled")
'

if [ "$PUSH" = yes ]; then
    $DOCKER push "${IMAGE}:${SHA_TAG}"
    $DOCKER push "${IMAGE}:${MOVING_TAG}"
fi
echo "IMAGE ${IMAGE}:${SHA_TAG}"
echo "IMAGE ${IMAGE}:${MOVING_TAG}"
