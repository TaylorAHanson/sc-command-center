#!/bin/bash
# Regenerate uv.lock. Usage: ./lock.sh [uv lock args, e.g. --upgrade-package pandas]
#
# The deployed App downloads every package from the URLs recorded in uv.lock,
# so they must be public PyPI. Some networks (the Databricks corporate one among
# them) refuse pypi.org and allow only a mirror, which makes a plain `uv lock`
# fail. This resolves through the mirror and writes public URLs back: the mirror
# serves PyPI's own /packages/ paths, and uv checks every file against the
# sha256 in the lock, so a mapping that ever stopped matching would fail the
# install rather than fetch something else.
#
# With direct access to pypi.org, `uv lock` alone is equivalent.
set -euo pipefail
cd "$(dirname "$0")"

MIRROR="${UV_LOCK_MIRROR:-https://pypi-proxy.dev.databricks.com}"
PUBLIC_INDEX="https://pypi.org/simple"
PUBLIC_FILES="https://files.pythonhosted.org/packages/"

rewrite() {
    sed -i.bak -e "s#$1#$2#g" -e "s#$3#$4#g" uv.lock && rm -f uv.lock.bak
}

# Point the existing lock at the mirror first so uv keeps its pinned versions
# instead of treating a changed index as a reason to resolve from scratch.
if [ -f uv.lock ]; then
    rewrite "$PUBLIC_INDEX" "$MIRROR/simple" "$PUBLIC_FILES" "$MIRROR/packages/"
fi

trap 'rewrite "$MIRROR/simple" "$PUBLIC_INDEX" "$MIRROR/packages/" "$PUBLIC_FILES"' EXIT
uv lock --default-index "$MIRROR/simple" "$@"
