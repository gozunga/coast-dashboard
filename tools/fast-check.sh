#!/usr/bin/env bash
# Fast local check for dashboard hot-patch lanes: flake8 on changed Python
# files, then the complete dashboard unit suite. Runtime depends on the
# local environment. CI still runs on the MR.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
base=${1:-origin/main}
mapfile -t py < <( { git diff --name-only --diff-filter=d "$(git merge-base "$base" HEAD)";
                     git diff --name-only --diff-filter=d HEAD;
                     git ls-files --others --exclude-standard; } | grep '\.py$' | sort -u)
[ -x .tox/py3/bin/python ] || tox -e py3 --notest
if [ ${#py[@]} -gt 0 ]; then .tox/py3/bin/python -m flake8 "${py[@]}"; fi
tox -e py3 -q
echo "fast-check: OK (CI still runs the MR pipeline)"
