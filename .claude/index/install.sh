#!/usr/bin/env bash
# Put the pinned codebase-memory-mcp on this box, or say why it could not.
#
# WHAT. Downloads the release asset pin.env names for this platform, checks the
# tarball and then the extracted binary against the two checksums there, and
# installs the binary into ~/.cache/harness/cbm/<version>/ (cbm_pin.py says
# where). Never ~/.local/bin: that path is shared with every other installer on
# the box. Idempotent: a box already holding the right binary is left alone and
# the script says so. The binary is moved into place in one rename, so a reader
# never sees half a file.
#
# WHY THE CHECKSUMS ARE NOT OPTIONAL. This binary reads every file in the
# repository and answers questions a session then acts on. An install that
# takes whatever the URL served cannot say what it is running.
#
# WHY NOT `codebase-memory-mcp install`. Upstream's installer writes client
# configuration for many editors, subagent definitions and harness hooks, and
# registers a long-running server. This script only gets a named binary onto
# the box; the harness asks it through its plain cli, one call at a time.
#
# FAILURE POLICY: fail loud. Every path either installs the pinned build or
# exits non-zero saying which check failed.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# CBM_VERSION, CBM_ASSET, both checksums, CBM_UPSTREAM and CBM_BIN for this
# platform; cbm_pin.py exits non-zero, naming the platform, when none is pinned.
eval "$(python3 "$HERE/cbm_pin.py" shell)"

_sha() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | cut -d' ' -f1
    else
        shasum -a 256 "$1" | cut -d' ' -f1
    fi
}

_refuse() {
    echo "$1 checksum mismatch for $CBM_VERSION" >&2
    echo "  pin.env says $2" >&2
    echo "  download is $3" >&2
    echo "  the pin is the authority; do not widen it to make this pass" >&2
    exit 1
}

if python3 "$HERE/cbm_pin.py" check 2>/dev/null; then
    echo "codebase-memory-mcp $CBM_VERSION already installed at $CBM_BIN"
else
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT

    echo "fetching $CBM_VERSION/$CBM_ASSET"
    if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
        gh release download "$CBM_VERSION" --repo "$CBM_UPSTREAM" \
            --pattern "$CBM_ASSET" --dir "$tmp"
    else
        curl -fsSL -o "$tmp/$CBM_ASSET" \
            "https://github.com/$CBM_UPSTREAM/releases/download/$CBM_VERSION/$CBM_ASSET"
    fi

    got="$(_sha "$tmp/$CBM_ASSET")"
    [ "$got" = "$CBM_TARBALL_SHA256" ] || _refuse tarball "$CBM_TARBALL_SHA256" "$got"

    tar -xzf "$tmp/$CBM_ASSET" -C "$tmp"
    found="$(find "$tmp" -type f -name 'codebase-memory-mcp' -print -quit)"
    [ -n "$found" ] || { echo "no binary inside $CBM_ASSET" >&2; exit 1; }

    got="$(_sha "$found")"
    [ "$got" = "$CBM_SHA256" ] || _refuse binary "$CBM_SHA256" "$got"

    dir="$(dirname "$CBM_BIN")"
    mkdir -p "$dir"
    chmod 0755 "$found"
    mv -f "$found" "$dir/.codebase-memory-mcp.partial"
    mv -f "$dir/.codebase-memory-mcp.partial" "$CBM_BIN"
    python3 "$HERE/cbm_pin.py" check
    echo "installed codebase-memory-mcp $CBM_VERSION at $CBM_BIN"
fi

"$CBM_BIN" --version
