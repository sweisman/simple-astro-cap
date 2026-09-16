#!/usr/bin/env bash
#
# fetch-deps.sh — populate lib/ and firmware/ from the camera vendors' own SDKs.
#
# simple-astro-cap loads vendor SDK shared libraries at runtime via ctypes, and QHY
# cameras need firmware uploaded over USB at plug-in time. Neither the libraries nor the
# firmware are ours to redistribute, so they are gitignored and fetched here instead.
#
# Nothing this script downloads is covered by the project's GPL-3 LICENSE. Each vendor
# archive carries its own terms.
#
# Usage:
#   ./scripts/fetch-deps.sh                 # all vendors
#   ./scripts/fetch-deps.sh --qhy           # just QHY (the only one most users need)
#   ./scripts/fetch-deps.sh --qhy --force   # re-fetch even if files already exist
#   ./scripts/fetch-deps.sh --clean-cache   # remove vendor-cache/ and exit

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CACHE_DIR="$REPO_ROOT/vendor-cache"
LIB_DIR="$REPO_ROOT/lib"
FIRMWARE_DIR="$REPO_ROOT/firmware/qhy"

# shellcheck source=deps.conf
source "$REPO_ROOT/scripts/deps.conf"

FORCE=0
WANT_QHY=0
WANT_ASI=0
WANT_PLAYERONE=0
WANT_TOUPTEK=0
ANY_SELECTED=0

SUMMARY=()

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m warn:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }
note() { SUMMARY+=("$*"); }

usage() {
    sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^#\s\?//'
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --qhy)        WANT_QHY=1;       ANY_SELECTED=1 ;;
        --asi)        WANT_ASI=1;       ANY_SELECTED=1 ;;
        --playerone)  WANT_PLAYERONE=1; ANY_SELECTED=1 ;;
        --touptek)    WANT_TOUPTEK=1;   ANY_SELECTED=1 ;;
        --force)      FORCE=1 ;;
        --clean-cache)
            log "Removing $CACHE_DIR"
            rm -rf "$CACHE_DIR"
            exit 0
            ;;
        -h|--help) usage ;;
        *) die "Unknown option: $1 (try --help)" ;;
    esac
    shift
done

if [[ $ANY_SELECTED -eq 0 ]]; then
    WANT_QHY=1; WANT_ASI=1; WANT_PLAYERONE=1; WANT_TOUPTEK=1
fi

for tool in curl tar; do
    command -v "$tool" >/dev/null || die "$tool is required but not installed"
done

mkdir -p "$CACHE_DIR" "$LIB_DIR"

# download <url> <dest-file> <expected-sha256-or-empty>
download() {
    local url="$1" dest="$2" sha="$3"

    if [[ -f "$dest" && $FORCE -eq 0 ]]; then
        log "Using cached $(basename "$dest")"
    else
        log "Downloading $(basename "$dest")"
        curl -fSL --progress-bar --retry 3 -o "$dest.part" "$url" \
            || die "Download failed: $url"
        mv "$dest.part" "$dest"
    fi

    if [[ -n "$sha" ]]; then
        local actual
        actual="$(sha256sum "$dest" | cut -d' ' -f1)"
        [[ "$actual" == "$sha" ]] \
            || die "Checksum mismatch for $(basename "$dest")
  expected $sha
  actual   $actual
If the vendor published a new build, update the *_SHA256 in scripts/deps.conf."
    else
        warn "No checksum pinned for $(basename "$dest") — integrity not verified"
    fi
}

# ---------------------------------------------------------------------------
# QHY
#
# One archive supplies everything QHY-related: the library, the full firmware set,
# the official udev rules (used by install-udev-rules.sh), and the GPLv2 source for
# fxload (used as the fallback when no distro fxload with FX3 support is present).
# ---------------------------------------------------------------------------
fetch_qhy() {
    log "QHY SDK $QHY_VERSION"

    if [[ -f "$LIB_DIR/libqhyccd.so" && -f "$FIRMWARE_DIR/QHY5III585.img" && $FORCE -eq 0 ]]; then
        note "QHY:       already present (use --force to re-fetch)"
        return
    fi

    local tarball="$CACHE_DIR/sdk_linux64_${QHY_VERSION}.tgz"
    local sdk_dir="$CACHE_DIR/sdk_linux64_${QHY_VERSION}"

    download "$QHY_URL" "$tarball" "$QHY_SHA256"

    rm -rf "$sdk_dir"
    tar xzf "$tarball" -C "$CACHE_DIR"
    [[ -d "$sdk_dir" ]] || die "Unexpected archive layout: $sdk_dir not found after extract"

    log "Installing libqhyccd into lib/"
    cp -a "$sdk_dir"/usr/local/lib/libqhyccd.so* "$LIB_DIR/"

    log "Installing QHY firmware into firmware/qhy/"
    mkdir -p "$FIRMWARE_DIR"
    cp -a "$sdk_dir"/lib/firmware/qhy/. "$FIRMWARE_DIR/"

    local n
    n="$(find "$FIRMWARE_DIR" -maxdepth 1 -type f \( -name '*.img' -o -name '*.HEX' \) | wc -l)"
    note "QHY:       libqhyccd.so + $n firmware files (SDK $QHY_VERSION)"

    # The official rules file and the fxload source stay in the cache; they are inputs
    # to install-udev-rules.sh, not runtime artifacts.
    [[ -f "$sdk_dir/etc/udev/rules.d/85-qhyccd.rules" ]] \
        || warn "SDK is missing 85-qhyccd.rules — install-udev-rules.sh will fall back"
    [[ -f "$sdk_dir/usr/local/fx3load/main.c" ]] \
        || warn "SDK is missing the fx3load source — fxload cannot be built locally"
}

# ---------------------------------------------------------------------------
# ZWO ASI
#
# ZWO serves one ~112 MB zip covering every platform; there is no Linux-only endpoint.
# We pull the Linux tarball out of it and take only the x64 .so.
# ---------------------------------------------------------------------------
fetch_asi() {
    log "ZWO ASI SDK"

    if [[ -f "$LIB_DIR/libASICamera2.so" && $FORCE -eq 0 ]]; then
        note "ASI:       already present (use --force to re-fetch)"
        return
    fi

    if ! command -v unzip >/dev/null; then
        warn "unzip not installed — skipping ASI. Install unzip and re-run with --asi."
        note "ASI:       SKIPPED (unzip missing)"
        return
    fi

    local zipfile="$CACHE_DIR/ASI_Camera_SDK.zip"
    local work="$CACHE_DIR/asi"

    warn "The ZWO archive is ~112 MB (it bundles every platform)."
    download "$ASI_URL" "$zipfile" "$ASI_SHA256"

    rm -rf "$work"; mkdir -p "$work"
    unzip -q -o "$zipfile" -d "$work"

    local linux_tar
    linux_tar="$(find "$work" -name 'ASI_linux_mac_SDK*.tar.bz2' -print -quit)"
    [[ -n "$linux_tar" ]] || die "No ASI_linux_mac_SDK*.tar.bz2 inside the ZWO archive"

    tar xjf "$linux_tar" -C "$work"

    local so
    so="$(find "$work" -path '*/lib/x64/libASICamera2.so*' -type f -print -quit)"
    [[ -n "$so" ]] || die "libASICamera2.so not found under lib/x64/ in the ASI SDK"

    cp -a "$so" "$LIB_DIR/libASICamera2.so"
    note "ASI:       libASICamera2.so ($(basename "$linux_tar"))"
}

# ---------------------------------------------------------------------------
# Player One / Touptek
#
# No stable direct URL, and both backends resolve via ctypes.util.find_library(), so a
# system-wide vendor install is the supported path. We only handle a manual drop-in.
# ---------------------------------------------------------------------------
fetch_manual() {
    local name="$1" soname="$2" page="$3" pattern="$4"

    log "$name SDK"

    if [[ -f "$LIB_DIR/$soname" && $FORCE -eq 0 ]]; then
        note "$(printf '%-10s' "$name:")already present in lib/"
        return
    fi

    local archive
    archive="$(find "$CACHE_DIR" -maxdepth 1 -iname "$pattern" -print -quit 2>/dev/null || true)"

    if [[ -z "$archive" ]]; then
        warn "$name has no automatable download."
        warn "  Either install the vendor SDK system-wide (find_library will locate it),"
        warn "  or download the Linux SDK from $page"
        warn "  into vendor-cache/ and re-run this script."
        note "$(printf '%-10s' "$name:")MANUAL — see $page"
        return
    fi

    local work="$CACHE_DIR/${name,,}"
    rm -rf "$work"; mkdir -p "$work"

    case "$archive" in
        *.zip)     unzip -q -o "$archive" -d "$work" ;;
        *.tar.bz2) tar xjf "$archive" -C "$work" ;;
        *.tar.gz|*.tgz) tar xzf "$archive" -C "$work" ;;
        *) die "Don't know how to unpack $archive" ;;
    esac

    local so
    so="$(find "$work" -name "$soname*" -type f -path '*64*' -print -quit)"
    [[ -n "$so" ]] || so="$(find "$work" -name "$soname*" -type f -print -quit)"
    [[ -n "$so" ]] || die "$soname not found inside $(basename "$archive")"

    cp -a "$so" "$LIB_DIR/$soname"
    note "$(printf '%-10s' "$name:")$soname (from $(basename "$archive"))"
}

if [[ $WANT_QHY -eq 1 ]]; then
    fetch_qhy
fi
if [[ $WANT_ASI -eq 1 ]]; then
    fetch_asi
fi
if [[ $WANT_PLAYERONE -eq 1 ]]; then
    fetch_manual "PlayerOne" "libPlayerOneCamera.so" "$PLAYERONE_PAGE" '*PlayerOne*'
fi
if [[ $WANT_TOUPTEK -eq 1 ]]; then
    fetch_manual "Touptek" "libtoupcam.so" "$TOUPTEK_PAGE" '*toupcam*'
fi

echo
log "Summary"
for line in "${SUMMARY[@]}"; do printf '    %s\n' "$line"; done
echo
log "Next: sudo ./scripts/install-udev-rules.sh"
