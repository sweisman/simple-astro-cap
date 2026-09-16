#!/usr/bin/env bash
#
# install-udev-rules.sh — generate and install udev rules for the supported cameras.
#
# Cameras are USB devices: without rules they are root-only, and QHY cameras additionally
# need firmware uploaded over USB every time they are plugged in. This script writes rules
# carrying this checkout's real absolute paths, so there is no "/path/to/..." to edit.
#
# The QHY rules are generated from QHYCCD's own 85-qhyccd.rules (shipped in their SDK and
# unpacked by fetch-deps.sh), which covers every QHY model rather than a hand-kept subset.
# Only the fxload path, the firmware path, and — if needed — the fxload argument syntax
# are rewritten.
#
# Usage:
#   sudo ./scripts/install-udev-rules.sh
#   ./scripts/install-udev-rules.sh --dry-run    # print the rules, install nothing
#   ./scripts/install-udev-rules.sh --build-fxload

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CACHE_DIR="$REPO_ROOT/vendor-cache"
FIRMWARE_DIR="$REPO_ROOT/firmware/qhy"
BIN_DIR="$REPO_ROOT/bin"
RULES_DIR="/etc/udev/rules.d"

DRY_RUN=0
BUILD_FXLOAD=0

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33m warn:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)      DRY_RUN=1 ;;
        --build-fxload) BUILD_FXLOAD=1 ;;
        -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^#\s\?//'; exit 0 ;;
        *) die "Unknown option: $1 (try --help)" ;;
    esac
    shift
done

# ---------------------------------------------------------------------------
# Locate the QHY SDK unpacked by fetch-deps.sh
# ---------------------------------------------------------------------------
SDK_DIR="$(find "$CACHE_DIR" -maxdepth 1 -type d -name 'sdk_linux64_*' 2>/dev/null \
           | sort -V | tail -1)"

QHY_RULES_TEMPLATE=""
if [[ -n "$SDK_DIR" && -f "$SDK_DIR/etc/udev/rules.d/85-qhyccd.rules" ]]; then
    QHY_RULES_TEMPLATE="$SDK_DIR/etc/udev/rules.d/85-qhyccd.rules"
fi

# ---------------------------------------------------------------------------
# fxload discovery
#
# Two incompatible programs are both called "fxload":
#
#   ezusb  — David Brownell's original (GPLv2). Talks to usbfs directly.
#            Syntax: -t fx3 -I <firmware> -D $env{DEVNAME}
#            This is what QHY's own rules are written against, and what QHY ships
#            (with full source) in usr/local/fx3load/ of their SDK.
#
#   libusb — the modern libusb fork, packaged by most distros as "fxload" 1.x.
#            Syntax: -t fx3 -i <firmware> -p <bus>,<addr>   (there is no -D)
#
# Both support FX3. We detect which one we have and emit matching arguments.
# ---------------------------------------------------------------------------

# Echoes "ezusb" or "libusb" on stdout, or nothing if unusable.
classify_fxload() {
    local prog="$1" out
    out="$(LC_ALL=C "$prog" -h 2>&1 || true)"

    grep -q 'fx3' <<<"$out" || return 0          # no FX3 support — unusable for QHY5III

    if grep -qE '\-D[ ]+devpath|\[-D devpath\]' <<<"$out"; then
        echo ezusb
    elif grep -qE '\-p[ ]+<?bus' <<<"$out"; then
        echo libusb
    fi
}

build_fxload_from_sdk() {
    [[ -n "$SDK_DIR" && -f "$SDK_DIR/usr/local/fx3load/main.c" ]] \
        || die "No fx3load source in vendor-cache. Run ./scripts/fetch-deps.sh --qhy first."
    command -v cc >/dev/null || command -v gcc >/dev/null \
        || die "No C compiler found; install base-devel / build-essential."

    log "Building fxload from the QHY SDK's GPLv2 source (vendor-cache/.../fx3load)"
    local build="$CACHE_DIR/fx3load-build"
    rm -rf "$build"
    cp -a "$SDK_DIR/usr/local/fx3load" "$build"
    make -C "$build" clean >/dev/null 2>&1 || true
    make -C "$build" all >/dev/null || die "fxload build failed; run 'make -C $build' to see why."

    mkdir -p "$BIN_DIR"
    cp -a "$build/fxload" "$BIN_DIR/fxload"
    cp -a "$build/COPYING" "$BIN_DIR/fxload.COPYING"
    cp -a "$build/main.c" "$build/ezusb.c" "$build/ezusb.h" "$build/Makefile" "$BIN_DIR/" 2>/dev/null || true
    log "Built $BIN_DIR/fxload (source kept alongside it to satisfy GPLv2 §3)"
}

FXLOAD=""
FXLOAD_KIND=""

pick_fxload() {
    local candidates=("$BIN_DIR/fxload" /usr/sbin/fxload /sbin/fxload /usr/bin/fxload)
    local resolved
    resolved="$(command -v fxload 2>/dev/null || true)"
    [[ -n "$resolved" ]] && candidates+=("$resolved")

    # Prefer the ezusb variant: it is what QHY's rules target, and it needs no libusb
    # rescan inside a udev add event.
    local kind prog
    for want in ezusb libusb; do
        for prog in "${candidates[@]}"; do
            [[ -x "$prog" ]] || continue
            kind="$(classify_fxload "$prog")"
            if [[ "$kind" == "$want" ]]; then
                FXLOAD="$prog"; FXLOAD_KIND="$kind"; return 0
            fi
        done
    done
    return 1
}

if [[ $BUILD_FXLOAD -eq 1 ]]; then
    build_fxload_from_sdk
fi

if ! pick_fxload; then
    warn "No usable fxload found (need one that lists 'fx3' as a target type)."
    warn "Options:"
    warn "  1. Install your distro's package:  sudo pacman -S fxload   |   sudo apt install fxload"
    warn "  2. Build QHY's own copy:           ./scripts/install-udev-rules.sh --build-fxload"
    die "fxload is required for QHY cameras."
fi

log "Using fxload: $FXLOAD  (${FXLOAD_KIND} variant)"
if [[ "$FXLOAD_KIND" == "libusb" ]]; then
    warn "This is the libusb fxload, not the ezusb one QHY's rules assume."
    warn "Arguments will be rewritten (-I -> -i, -D \$env{DEVNAME} -> -p \$env{BUSNUM},\$env{DEVNUM})."
    warn "If firmware upload proves unreliable, re-run with --build-fxload."
fi

# ---------------------------------------------------------------------------
# Rule generation
# ---------------------------------------------------------------------------
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

HEADER="# Generated by simple-astro-cap scripts/install-udev-rules.sh
# Source checkout: $REPO_ROOT
# Do not edit by hand — re-run the script instead.
"

generate_qhy() {
    local out="$STAGE/85-qhyccd.rules"

    if [[ -z "$QHY_RULES_TEMPLATE" ]]; then
        warn "QHY SDK rules not found in vendor-cache — run ./scripts/fetch-deps.sh --qhy"
        warn "Skipping QHY rules."
        return 1
    fi
    [[ -d "$FIRMWARE_DIR" ]] \
        || die "No firmware at $FIRMWARE_DIR. Run ./scripts/fetch-deps.sh --qhy first."

    printf '%s\n' "$HEADER" > "$out"
    printf '%s\n\n' "# Derived from QHYCCD's own 85-qhyccd.rules (SDK $(basename "$SDK_DIR"))." >> "$out"

    # Rewrite the vendor's absolute paths to this checkout's.
    sed -e "s|/sbin/fxload|$FXLOAD|g" \
        -e "s|/lib/firmware/qhy|$FIRMWARE_DIR|g" \
        "$QHY_RULES_TEMPLATE" >> "$out"

    if [[ "$FXLOAD_KIND" == "libusb" ]]; then
        # -I/-s take the same meaning but lowercase -i; -D has no equivalent, so address
        # the device by libusb bus/address, which udev provides as BUSNUM/DEVNUM.
        sed -i -e 's| -I | -i |g' \
               -e 's|-D \$env{DEVNAME}|-p $env{BUSNUM},$env{DEVNUM}|g' "$out"
    fi

    # Give QHY the same usbfs buffer bump the ASI rules get; QHY5III cameras at full
    # frame rate hit the 16 MB default just as hard.
    cat >> "$out" <<'EOF'

# ---- usbfs buffer (large frames at high frame rates) ----
ACTION=="add", ATTR{idVendor}=="1618", RUN+="/bin/sh -c '/bin/echo 200 >/sys/module/usbcore/parameters/usbfs_memory_mb'"
EOF

    # Sanity: every firmware the rules reference must actually exist.
    local missing=0 fw
    while read -r fw; do
        [[ -f "$fw" ]] || { warn "rule references missing firmware: $(basename "$fw")"; missing=$((missing + 1)); }
    done < <(grep -oE "$FIRMWARE_DIR/[A-Za-z0-9_.-]+" "$out" | sort -u)
    [[ $missing -eq 0 ]] || warn "$missing firmware file(s) referenced but not present (harmless if you don't own those models)"

    local n
    n="$(grep -c 'fxload' "$out")"
    log "QHY: $n firmware rules covering QHYCCD's full supported model list"
}

generate_others() {
    printf '%s\n' "$HEADER" > "$STAGE/99-asi.rules"
    cat >> "$STAGE/99-asi.rules" <<'EOF'
ACTION=="add", ATTR{idVendor}=="03c3", RUN+="/bin/sh -c '/bin/echo 200 >/sys/module/usbcore/parameters/usbfs_memory_mb'"
SUBSYSTEMS=="usb", ATTR{idVendor}=="03c3", MODE="0666"
EOF

    printf '%s\n' "$HEADER" > "$STAGE/99-playerone.rules"
    cat >> "$STAGE/99-playerone.rules" <<'EOF'
ACTION=="add", ATTR{idVendor}=="a0a0", RUN+="/bin/sh -c '/bin/echo 200 >/sys/module/usbcore/parameters/usbfs_memory_mb'"
SUBSYSTEMS=="usb", ATTR{idVendor}=="a0a0", MODE="0666"
EOF

    # Touptek OEMs under many brands (Altair, Omegon, Bresser, Celestron, ...);
    # they all present the same vendor IDs.
    printf '%s\n' "$HEADER" > "$STAGE/99-touptek.rules"
    cat >> "$STAGE/99-touptek.rules" <<'EOF'
SUBSYSTEMS=="usb", ATTR{idVendor}=="0547", MODE="0666"
SUBSYSTEMS=="usb", ATTR{idVendor}=="04b4", MODE="0666"
EOF

    log "ASI / Player One / Touptek: permission rules generated"
}

generate_qhy || true
generate_others

# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------
if [[ $DRY_RUN -eq 1 ]]; then
    for f in "$STAGE"/*.rules; do
        printf '\n\033[1;32m----- %s -----\033[0m\n' "$(basename "$f")"
        cat "$f"
    done
    echo
    log "Dry run — nothing installed. Re-run with sudo to install into $RULES_DIR"
    exit 0
fi

[[ $EUID -eq 0 ]] || die "Installing into $RULES_DIR needs root. Re-run with sudo (or use --dry-run)."

for f in "$STAGE"/*.rules; do
    install -m 0644 "$f" "$RULES_DIR/$(basename "$f")"
    log "Installed $RULES_DIR/$(basename "$f")"
done

udevadm control --reload-rules
udevadm trigger

log "Done. Unplug and replug the camera, then: python run.py"
