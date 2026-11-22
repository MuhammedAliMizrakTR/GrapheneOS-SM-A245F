#!/usr/bin/env bash
# ============================================================================
#  build-kernel.sh — reproducible kernel build for SM-A245F (Galaxy A24)
# ============================================================================
#  Produces, for each variant:
#     boot.img        (Android boot image, header v2, with DTB appended)
#     dtbo.img        (device tree overlay)
#     <variant>.tar   (Odin-flashable AP-payload)
#     *.ko            (vendor modules, kept out of boot.img on purpose)
#
#  Usage:
#     ./scripts/build-kernel.sh --variant vanilla
#     ./scripts/build-kernel.sh --variant kernelsu
#     ./scripts/build-kernel.sh --variant bakasu
#
#  All parameters come from config.env; nothing is hard-coded here.
# ============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/config.env"

VARIANT="vanilla"
HARDENED="0"
KEEP_SECURITY="0"
DEBUG_UART="0"
STOCK_BOOT_IMG=""
STOCK_RAMDISK=""
JOBS="$(nproc)"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --variant)  VARIANT="$2"; shift 2 ;;
        --harden)     HARDENED="1"; shift ;;
        --keep-security) KEEP_SECURITY="1"; shift ;;
        --debug-uart) DEBUG_UART="1"; shift ;;
        --stock-boot) STOCK_BOOT_IMG="$2"; shift 2 ;;
        --stock-ramdisk) STOCK_RAMDISK="$2"; shift 2 ;;
        --jobs)     JOBS="$2"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

case "${VARIANT}" in
    vanilla|kernelsu|kernelsu-up) ;;
    *) echo "variant must be vanilla|kernelsu|kernelsu-up" >&2; exit 2 ;;
esac

log() { printf '\033[1;36m[build]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[fail]\033[0m %s\n' "$*" >&2; exit 1; }

WORK="${ROOT}/work"
KSRC="${WORK}/kernel"
TC="${WORK}/toolchain"
OUT="${WORK}/out-${VARIANT}"
mkdir -p "${WORK}" "${ROOT}/${DIST_DIR}"

# ---------------------------------------------------------------------------
# 1. Source
# ---------------------------------------------------------------------------
if [[ ! -d "${KSRC}/.git" ]]; then
    log "cloning kernel source (${KERNEL_BRANCH})"
    git clone --depth=1 --single-branch --branch "${KERNEL_BRANCH}" \
        "${KERNEL_REPO}" "${KSRC}"
fi
# KERNEL_DIR may be empty: the VH-Devices tree keeps the kernel at the repo
# root instead of under kernel-5.10/ like the Samsung a245f drop does.
if [[ -n "${KERNEL_DIR}" ]]; then
    KERNEL_SRC="${KSRC}/${KERNEL_DIR}"
else
    KERNEL_SRC="${KSRC}"
fi
[[ -f "${KERNEL_SRC}/Makefile" ]] || die "kernel Makefile not found in ${KERNEL_SRC}"

ACTUAL_VER="$(make -s -C "${KERNEL_SRC}" kernelversion 2>/dev/null || true)"
log "kernel source version: ${ACTUAL_VER:-unknown} (expected ${KERNEL_VERSION})"

# ---------------------------------------------------------------------------
# 2. Toolchain
# ---------------------------------------------------------------------------
if [[ ! -x "${TC}/${CLANG_BIN_SUBDIR}/clang" ]]; then
    log "cloning toolchain (${TOOLCHAIN_TAG})"
    git clone --depth=1 --single-branch "${TOOLCHAIN_REPO}" "${TC}"
fi
export PATH="${TC}/${CLANG_BIN_SUBDIR}:${PATH}"
clang --version | head -1 || die "clang not runnable"

# ---------------------------------------------------------------------------
# 3. Root solution
#    Injected as a Kbuild module directory, exactly like upstream KernelSU
#    docs describe. The version is read back afterwards so the release can
#    ship the matching manager APK.
# ---------------------------------------------------------------------------
#  A clone alone does nothing: Kbuild only descends into a directory that is
#  referenced from a parent Makefile, and the CONFIG_KSU symbol only exists if
#  some parent Kconfig sources the module's Kconfig. Without both, the
#  defconfig's `CONFIG_KSU=y` is an unknown symbol, kconfiglib silently drops
#  it, and the resulting kernel has no root at all while still reporting a
#  successful build. This mirrors kernel/setup.sh from upstream.
KSU_DIR=""
KSU_REPO_DIR=""
case "${VARIANT}" in
    kernelsu)
        log "fetching KernelSU-Next (${KSU_NEXT_REF})"
        rm -rf "${KERNEL_SRC}/KernelSU-Next"
        git clone --depth=1 --single-branch --branch "${KSU_NEXT_REF}" \
            "${KSU_NEXT_REPO}" "${KERNEL_SRC}/KernelSU-Next"
        KSU_REPO_DIR="${KERNEL_SRC}/KernelSU-Next"
        ;;
    kernelsu-up)
        log "fetching upstream KernelSU (${KSU_UPSTREAM_REF})"
        rm -rf "${KERNEL_SRC}/KernelSU"
        git clone --depth=1 --single-branch --branch "${KSU_UPSTREAM_REF}" \
            "${KSU_UPSTREAM_REPO}" "${KERNEL_SRC}/KernelSU"
        KSU_REPO_DIR="${KERNEL_SRC}/KernelSU"
        ;;
esac

if [[ -n "${KSU_REPO_DIR}" ]]; then
    KSU_SUBMODULE="${KSU_REPO_DIR}/kernel"
    [[ -f "${KSU_SUBMODULE}/Kconfig" ]] || die "KernelSU kernel/Kconfig missing in ${KSU_REPO_DIR}"
    [[ -f "${KSU_SUBMODULE}/Kbuild"  ]] || die "KernelSU kernel/Kbuild missing in ${KSU_REPO_DIR}"

    DRIVERS_DIR="${KERNEL_SRC}/drivers"

    # 1. Expose the module tree as drivers/kernelsu
    rm -rf "${DRIVERS_DIR}/kernelsu"
    ln -sfn "${KSU_SUBMODULE}" "${DRIVERS_DIR}/kernelsu"

    # 2. Make Kbuild descend into it.
    #
    #    obj-y, not obj-$(CONFIG_KSU). drivers/ is itself built as part of a
    #    module-enabled build and the conditional form was observed to expand
    #    empty in that context, so Kbuild never entered drivers/kernelsu/ even
    #    though CONFIG_KSU=y was in .config and verified there. obj-y is
    #    unconditional, and the directory still compiles to nothing unless
    #    its own Kbuild selects kernelsu.o (it does: obj-$(CONFIG_KSU) +=
    #    kernelsu.o sits inside the module's Kbuild, which is evaluated in the
    #    module directory where the symbol is visible).
    if ! grep -q "kernelsu" "${DRIVERS_DIR}/Makefile"; then
        printf '\nobj-y += kernelsu/\n' >> "${DRIVERS_DIR}/Makefile"
    fi

    # 3. Make the CONFIG_KSU symbol exist by sourcing its Kconfig
    if ! grep -q 'drivers/kernelsu/Kconfig' "${DRIVERS_DIR}/Kconfig"; then
        # Insert the source line immediately BEFORE the final endmenu, keeping
        # that endmenu. (Dropping it would unbalance the top-level menu and
        # every subsequent Kconfig parse would fail.)
        python3 - "${DRIVERS_DIR}/Kconfig" <<'KCONFIG_PATCH'
import sys
path = sys.argv[1]
with open(path) as f:
    lines = f.read().splitlines()
idx = None
for i, line in enumerate(lines):
    if line.strip() == "endmenu":
        idx = i
if idx is None:
    sys.exit("no endmenu found in %s" % path)
lines.insert(idx, 'source "drivers/kernelsu/Kconfig"')
with open(path, "w") as f:
    f.write("\n".join(lines) + "\n")
KCONFIG_PATCH
        grep -q 'drivers/kernelsu/Kconfig' "${DRIVERS_DIR}/Kconfig" || \
            die "failed to wire KernelSU into drivers/Kconfig"
    fi

    KSU_DIR="${KSU_REPO_DIR}"
    log "KernelSU wired into drivers/ (symlink + Makefile + Kconfig)"
fi

# Read the integrated version code back out of the source, so the release can
# pair the kernel with the exactly matching manager APK.
#
# KernelSU-Next does NOT ship the version as a header macro. kernel/Kbuild
# computes it at build time as `30000 + git rev-list --count HEAD`, so the same
# arithmetic is reproduced here from the cloned tree. Upstream KernelSU keeps
# a header, so that path is still honoured.
KSU_VERSION_CODE="none"
KSU_VERSION_TAG="none"
if [[ -n "${KSU_REPO_DIR}" ]]; then
    # The version is derived from commit count, so it only equals a published
    # manager APK if we build a *tagged* ref. A branch such as KernelSU-Next
    # `dev` sits 199 commits past v3.4.2 (33554 vs the APK's 33355) and could
    # never be paired. Warn loudly rather than shipping a kernel whose manager
    # cannot be found.
    if ! git -C "${KSU_REPO_DIR}" describe --tags --exact-match >/dev/null 2>&1; then
        log "WARNING: ${KSU_REPO_DIR##*/} is not at a tagged ref; its version code will not match any published APK"
    fi
    if [[ -f "${KSU_REPO_DIR}/${KSU_VERSION_HEADER}" ]]; then
        KSU_VERSION_CODE="$(grep -oE '#define[[:space:]]+KERNELSU_VERSION_CODE(_BASE)?[[:space:]]+[0-9]+' \
            "${KSU_REPO_DIR}/${KSU_VERSION_HEADER}" | grep -oE '[0-9]+$' | head -1 || true)"
    fi
    if [[ -z "${KSU_VERSION_CODE}" || "${KSU_VERSION_CODE}" == "none" ]]; then
        # Version is derived from history, so a --depth=1 clone would give the
        # wrong answer. Widen the clone first.
        ( cd "${KSU_REPO_DIR}" && git fetch --unshallow --quiet 2>/dev/null || true )
        _count="$(cd "${KSU_REPO_DIR}" && git rev-list --count HEAD 2>/dev/null || true)"
        if [[ -n "${_count}" ]]; then
            KSU_VERSION_CODE="$((30000 + _count))"
        fi
    fi
    KSU_VERSION_TAG="$(cd "${KSU_REPO_DIR}" && git describe --tags --abbrev=0 2>/dev/null || echo none)"
    [[ -n "${KSU_VERSION_CODE}" ]] || KSU_VERSION_CODE="unparsed"
fi
log "integrated KSU version code: ${KSU_VERSION_CODE} (tag ${KSU_VERSION_TAG})"

# ---------------------------------------------------------------------------
# 4. Defconfig
# ---------------------------------------------------------------------------
DEFCONFIG_SRC="${KERNEL_SRC}/arch/arm64/configs/${KERNEL_DEFCONFIG}"
[[ -f "${DEFCONFIG_SRC}" ]] || die "defconfig ${KERNEL_DEFCONFIG} not found"

DEFCONFIG_TMP="${WORK}/defconfig.${VARIANT}"
HARDEN_ARG=""
[[ "${HARDENED}" == "1" ]] && HARDEN_ARG="--harden"
# KEEP_SECURITY is the default for the VH-Devices tree, whose own defconfig
# already has RKP/KDP/DEFEX/FIVE/PROCA enabled and which is the configuration
# closest to the one OrangeFox actually boots on this hardware.
[[ "${KEEP_SECURITY}" == "1" ]] && HARDEN_ARG="${HARDEN_ARG} --keep-security"

python3 "${ROOT}/scripts/apply_defconfig_overrides.py" \
    --in "${DEFCONFIG_SRC}" \
    --out "${DEFCONFIG_TMP}" \
    --report "${WORK}/defconfig-report.${VARIANT}.md" \
    ${HARDEN_ARG}

# Root integration markers
if [[ -n "${KSU_DIR}" ]]; then
    if grep -q '^CONFIG_KSU=' "${DEFCONFIG_TMP}"; then
        sed -i 's/^CONFIG_KSU=.*/CONFIG_KSU=y/' "${DEFCONFIG_TMP}"
    else
        echo 'CONFIG_KSU=y' >> "${DEFCONFIG_TMP}"
    fi
    # SUSFS is only enabled when the kernel source actually provides the hooks.
    # This tree does not (verified: zero susfs references under kernel-5.10),
    # so this is normally a no-op. It stays here so a future tree that does
    # ship SUSFS picks it up automatically instead of silently losing it.
    if grep -rqs "CONFIG_KSU_SUSFS" "${KERNEL_SRC}/fs" "${KERNEL_SRC}/kernel" 2>/dev/null; then
        log "SUSFS hooks found in tree - enabling CONFIG_KSU_SUSFS"
        if grep -q '^CONFIG_KSU_SUSFS=' "${DEFCONFIG_TMP}"; then
            sed -i 's/^CONFIG_KSU_SUSFS=.*/CONFIG_KSU_SUSFS=y/' "${DEFCONFIG_TMP}"
        else
            echo 'CONFIG_KSU_SUSFS=y' >> "${DEFCONFIG_TMP}"
        fi
    else
        log "no SUSFS hooks in this kernel tree - leaving SUSFS disabled"
    fi
fi

# ---------------------------------------------------------------------------
# 5. Configure
#    gen_config.py replaces `make defconfig` so that flex/bison are not
#    required. It writes .config plus the generated headers.
# ---------------------------------------------------------------------------
log "generating configuration (kconfiglib; no flex/bison needed)"
rm -rf "${OUT}"
mkdir -p "${OUT}"
python3 "${ROOT}/scripts/gen_config.py" \
    --srctree "${KERNEL_SRC}" \
    --defconfig "${DEFCONFIG_TMP}" \
    --out "${OUT}" \
    --toolchain-bin "${TC}/${CLANG_BIN_SUBDIR}"

# ---------------------------------------------------------------------------
# 6. Build
# ---------------------------------------------------------------------------
export ARCH=arm64
export CC=clang LD=ld.lld AR=llvm-ar NM=llvm-nm
export OBJCOPY=llvm-objcopy OBJDUMP=llvm-objdump
export READELF=llvm-readelf STRIP=llvm-strip

# LLVM=1 alone does NOT make clang emit AArch64 code. The kernel derives the
# clang target triple from CROSS_COMPILE (arch/arm64/Makefile ->
# CLANG_FLAGS += --target=$(notdir $(CROSS_COMPILE:%-=%)), wired in via
# scripts/Makefile.clang). With CROSS_COMPILE unset, clang falls back to the
# host triple and the build dies almost immediately with
#   arch/arm64/include/asm/atomic_lse.h: error: unknown register name 'x1' in asm
# Only the triple is taken from CROSS_COMPILE here: LD/AR/NM/OBJCOPY are all
# overridden to the llvm-* equivalents above, so no GNU aarch64 binutils
# package is required.
export CROSS_COMPILE="aarch64-linux-gnu-"
export CLANG_TRIPLE="aarch64-linux-gnu-"

# Embed the commit and build time in the kernel's own version string. Without
# this the only record of which image is on a device is a filename on someone
# else's computer: round 4 arrived showing a 19.79 MiB kernel against a
# 46.29 MiB release and there was no way to tell from the log which build had
# actually been flashed. With it, `uname -r` answers the question, and so does
# any log line that prints the version.
# utsrelease.h caps the whole version string at 64 characters, and KernelSU
# appends its own "-g<sha>" and can add "-dirty".  A stamp of yymmddHHMM is
# enough to separate two builds of the same day and leaves room for both.
GIT_REV="${GIT_REV:-$(git -C "${ROOT}" rev-parse --short=8 HEAD 2>/dev/null || echo unknown)}"
BUILD_STAMP="${BUILD_STAMP:-$(date -u +%y%m%d%H%M)}"
log "build id: ${GIT_REV} built ${BUILD_STAMP}"

if [[ "${HARDENED}" == "1" ]]; then
    PROFILE_NAME="HARDENED"
elif [[ "${KEEP_SECURITY}" == "1" ]]; then
    PROFILE_NAME="KEEP-SECURITY"
else
    PROFILE_NAME="STANDARD"
fi
LOCALVERSION_USED="-a24-${VARIANT:0:6}-${BUILD_STAMP:2:10}"

MAKE=(make -C "${KERNEL_SRC}" O="${OUT}" ARCH=arm64
      LLVM=1 LLVM_IAS=1
      CROSS_COMPILE="${CROSS_COMPILE}"
      KCFLAGS="-Wno-error"
      LOCALVERSION="${LOCALVERSION_USED}")

log "building (jobs=${JOBS})"
# Image.gz, not Image. arch/arm64/Makefile sets KBUILD_IMAGE := $(boot)/Image.gz
# and its all: target is Image.gz, and the MediaTek bootloader gzips-in-place:
# it calls decompress_kernel() and panics with
#   gzip header is not correct. Error!
#   panic (caller ...): decompress kernel image fail!!!
# if the boot partition holds an uncompressed Image. `make Image` produces no
# .gz at all, so the packaging step used to fall back to the raw Image and
# every flash died at ~12 s with HALT reason 9. Reported by the tester.
"${MAKE[@]}" -j"${JOBS}" Image.gz dtbs 2>&1 | tee "${WORK}/build-${VARIANT}.log"

ln -sfn "${KERNEL_SRC}" "${WORK}/kernel-5.10" 2>/dev/null || true

# Vendor modules: the stock vendor partition expects them under vendor_dlkm,
# so they are collected separately and are NOT unpacked into boot.img.
# --- console gate ---------------------------------------------------------
# The shipped defconfig builds the MediaTek UART as a module. A module cannot
# be loaded before userspace, so if this silently stays =m every early printk
# is discarded and a failed boot produces an empty log with no clue in it.
# That is a 20-minute round trip to discover, so check it here instead.
if [[ -f "${OUT}/.config" ]]; then
    uart="$(grep -E '^CONFIG_SERIAL_8250_MT6577=' "${OUT}/.config" || true)"
    log "console: ${uart:-CONFIG_SERIAL_8250_MT6577 not present}"
    if [[ "${uart}" != "CONFIG_SERIAL_8250_MT6577=y" ]]; then
        die "CONFIG_SERIAL_8250_MT6577 is not =y (got: ${uart:-unset}); the UART would be a module and early boot output would be lost"
    fi

    # Same class of bug: SEC_DEBUG is /proc/last_kmsg. Shipped as =m it only
    # starts once userspace is up, so a kernel that dies earlier leaves no
    # record at all and the next log is pure bootloader output - which is
    # exactly what two rounds of tester feedback consisted of.
    crashlog="$(grep -E '^CONFIG_SEC_DEBUG=' "${OUT}/.config" || true)"
    log "crash log: ${crashlog:-CONFIG_SEC_DEBUG not present}"
    if [[ "${crashlog}" != "CONFIG_SEC_DEBUG=y" ]]; then
        die "CONFIG_SEC_DEBUG is not =y (got: ${crashlog:-unset}); /proc/last_kmsg would not exist and an early crash would leave no trace"
    fi

    # And the console itself. console=tty0 on the cmdline is inert without a
    # VT and something to hang it off; this device has no UART cable, so the
    # panel is the only place a panic can be read. Shipped without these, four
    # rounds of testing produced no kernel output at all.
    for want in VT DRM_FBDEV_EMULATION; do
        got="$(grep -E "^CONFIG_${want}=" "${OUT}/.config" || true)"
        log "console/${want}: ${got:-unset}"
        if [[ "${got}" != "CONFIG_${want}=y" ]]; then
            die "CONFIG_${want} is not =y (got: ${got:-unset}); console=tty0 would be inert and a panic would be invisible"
        fi
    done
fi

if [[ -f "${OUT}/.config" ]] && grep -q '^CONFIG_MODULES=y' "${OUT}/.config"; then
    log "building vendor modules"
    "${MAKE[@]}" -j"${JOBS}" modules 2>&1 | tee -a "${WORK}/build-${VARIANT}.log" || \
        log "module build reported errors; continuing (see log)"
    if ! "${MAKE[@]}" INSTALL_MOD_PATH="${OUT}/modules_install" modules_install 2>&1 \
            | tee -a "${WORK}/build-${VARIANT}.log"; then
        log "modules_install failed; in-tree modules are not packaged into boot.img anyway"
    fi
fi

# ---------------------------------------------------------------------------
# 6b. Prove the root solution actually landed
#     A green build that silently dropped CONFIG_KSU would look identical to a
#     working one, and would brick the whole point of these images. Fail here
#     instead of shipping a rootless "kernelsu" kernel.
# ---------------------------------------------------------------------------
if [[ -n "${KSU_REPO_DIR}" ]]; then
    if ! grep -qE '^CONFIG_KSU=[ym]' "${OUT}/.config"; then
        grep -nE 'KSU' "${OUT}/.config" | head -20 || true
        die "CONFIG_KSU was requested but is absent from the generated .config"
    fi
    if ! grep -q '^CONFIG_KSU=y' "${OUT}/.config"; then
        die "CONFIG_KSU is not =y in the generated .config (got: $(grep -E '^CONFIG_KSU=' "${OUT}/.config"))"
    fi

    # Built-in code is archived into built-in.a and never produces a
    # standalone kernelsu.o -- that only happens for an =m module. Look for
    # both, plus any compiled object from the module's own subdirectories.
    OBJ="$(find "${OUT}/drivers/kernelsu" -name '*.o' 2>/dev/null | head -1)"
    [[ -n "${OBJ}" ]] || OBJ="$(find "${OUT}" -name 'kernelsu.o' -o -name 'ksu.o' 2>/dev/null | head -1)"
    [[ -n "${OBJ}" ]] || OBJ="$(find "${OUT}/drivers/kernelsu" -name 'built-in.a' 2>/dev/null | head -1)"
    if [[ -z "${OBJ}" ]]; then
        {
            echo "=== DIAG: KSU wiring ==="
            echo "-- drivers/Makefile tail --"; tail -5 "${KERNEL_SRC}/drivers/Makefile"
            echo "-- symlink --"; ls -la "${KERNEL_SRC}/drivers/kernelsu" 2>&1
            echo "-- symlink target Kbuild exists --"; ls -la "${KERNEL_SRC}/drivers/kernelsu/Kbuild" 2>&1
            echo "-- Kbuild obj line --"; grep -n 'obj-.*kernelsu' "${KERNEL_SRC}/drivers/kernelsu/Kbuild" 2>&1
            echo "-- drivers/Kconfig tail --"; tail -5 "${KERNEL_SRC}/drivers/Kconfig"
            echo "-- .config KSU lines --"; grep -E 'KSU' "${OUT}/.config" || echo none
            echo "-- any kernelsu output dir at all --"; find "${OUT}/drivers" -maxdepth 1 -name 'kernelsu*' 2>&1
            echo "-- log lines mentioning kernelsu --"
            grep -iE 'kernelsu' "${WORK}/build-${VARIANT}.log" | tail -20 || echo "(none)"
        } 2>&1 | tee "${WORK}/ksu-diag.txt"
        MSG=$(sed ':a;N;$!ba;s/\n/%0A/g' "${WORK}/ksu-diag.txt")
        echo "::error title=KSU diagnostics::${MSG}"
        die "CONFIG_KSU=y but no kernelsu object was produced"
    fi
    log "KernelSU object present: ${OBJ}"

    # The built kernel must carry the KSU symbol table entries, otherwise the
    # manager app cannot talk to it even though the config looked right.
    if command -v nm >/dev/null 2>&1; then
        KU_IMG="${OUT}/vmlinux"
        if [[ -f "${KU_IMG}" ]]; then
            if nm "${KU_IMG}" 2>/dev/null | grep -qiE ' ksu_| kernelsu'; then
                log "KernelSU symbols found in vmlinux"
            else
                die "CONFIG_KSU=y and object built, but no KSU symbols in vmlinux"
            fi
        fi
    fi
fi

IMAGEGZ="${OUT}/arch/arm64/boot/Image.gz"
[[ -f "${IMAGEGZ}" ]] || die "no Image.gz produced - the a24 bootloader only accepts a gzip-compressed kernel"

# This is the exact failure the tester hit, so prove the payload really is
# gzip rather than trusting the filename.
if ! gzip -t "${IMAGEGZ}" 2>/dev/null; then
    die "${IMAGEGZ} is not valid gzip - refusing to package an unbootable image"
fi
if [[ "$(head -c2 "${IMAGEGZ}" | od -An -tx1 | tr -d ' \n')" != "1f8b" ]]; then
    die "${IMAGEGZ} has no gzip magic (1f 8b)"
fi
log "kernel payload is gzip-compressed (verified)"

# Gzip alone is not enough. The bootloader decompresses and then jumps to
# whatever came out; if that is not a valid arm64 Image it jumps into garbage
# and the device dies without printing anything - no panic, nothing in
# last_kmsg. That is the hardest possible failure to diagnose from a tester's
# phone, and it costs one flash round trip per discovery.
python3 "${ROOT}/scripts/verify_image.py" "${IMAGEGZ}" \
    || die "Image.gz is not a valid arm64 Image - do not ship this"

# ---------------------------------------------------------------------------
# 7. Package
# ---------------------------------------------------------------------------
log "packaging"

# The console must not depend on a cable being attached. console=ttyS0 would
# still be registered even with nothing plugged into the UART pads, and a
# dormant console on this platform has been known to stall boot. So the UART
# console is opt-in:
#
#     ./scripts/build-kernel.sh --variant vanilla --debug-uart
#
# earlycon alone is harmless with no cable: it writes into the UART FIFO and
# discards, and boots the same either way.
EXTRA_CMDLINE=""
if [[ "${DEBUG_UART}" == "1" ]]; then
    EXTRA_CMDLINE=" earlycon=mtk8250,mmio32,0x11002000 console=ttyS0,921600n8 loglevel=8 ignore_loglevel"
    log "debug UART console enabled"
fi

BOOTDIR="${WORK}/boot-${VARIANT}"
rm -rf "${BOOTDIR}"; mkdir -p "${BOOTDIR}"

cp "${IMAGEGZ}" "${BOOTDIR}/kernel"

# DTB: what belongs in boot.img is the base board tree, mt6789.dtb. That is
# the only target the tree actually builds -- arch/arm64/boot/dts/Makefile
# lists exactly one dts dir (mediatek) and mediatek/Makefile has a single
# dtb-y. The Samsung board trees under arch/arm64/boot/dts/samsung/a24/ are
# /plugin/ overlays and are not built here at all; they belong to the separate
# dtbo partition and are deliberately left untouched, because a mismatched
# dtbo against an otherwise stock vendor image breaks panel and camera
# bring-up.
DTB_CANDIDATES=(
    "${OUT}/arch/arm64/boot/dts/mediatek/mt6789.dtb"
    "${OUT}/arch/arm64/boot/dts/mediatek/a24/"*.dtb
)
DTB_SRC=""
for cand in "${DTB_CANDIDATES[@]}"; do
    [[ -f "${cand}" ]] && { DTB_SRC="${cand}"; break; }
done
[[ -n "${DTB_SRC}" ]] || die "no dtb produced under arch/arm64/boot/dts/mediatek"
log "dtb source: ${DTB_SRC}"
cat "${DTB_SRC}" > "${BOOTDIR}/dtb"

# Boot image header v2. mkbootimg is vendored under scripts/third_party:
# the kernel tree in this repository ships no tools/mkbootimg, and neither
# apt nor PyPI provides one. Writing the header out of hand was tried first
# and got the v1/v2 block offsets wrong (the 1024-byte extra_cmdline array
# pushes them to the end of the v0 header), so the upstream implementation is
# used instead.
MKBOOTIMG="${ROOT}/scripts/third_party/mkbootimg/mkbootimg.py"
[[ -f "${MKBOOTIMG}" ]] || die "vendored mkbootimg missing at ${MKBOOTIMG}"

# The ramdisk is not optional decoration: it holds /init, which is what
# mounts the system and starts vendor bring-up. A boot.img built with a
# placeholder gzip hands the kernel an empty initramfs, and with no root= in
# the cmdline it then waits ~20 s for a root device that never appears and
# dies - the 25-30 s boot followed by a power-off the tester reported.
#
# Point STOCK_BOOT_IMG at the stock boot.img for this firmware and its
# ramdisk is carried over verbatim. Without it the build still produces an
# image, but that image can only ever reach the same dead end, so say so
# loudly.
RAMDISK="${BOOTDIR}/ramdisk.gz"
if [[ -n "${STOCK_RAMDISK}" ]]; then
    # A ramdisk on its own is the easier thing to carry around: the stock
    # recovery.img for this firmware is 80 MiB and has to be lz4-decoded
    # before the ramdisk can be read out of it.
    [[ -f "${STOCK_RAMDISK}" ]] || die "STOCK_RAMDISK=${STOCK_RAMDISK} does not exist"
    log "using the stock ramdisk file ${STOCK_RAMDISK}"
    cp "${STOCK_RAMDISK}" "${RAMDISK}"
    RAMDISK_SIZE="$(stat -c %s "${RAMDISK}")"
    [[ "${RAMDISK_SIZE}" -gt 1000000 ]] || \
        die "ramdisk is only ${RAMDISK_SIZE} bytes - that is not a real initramfs"
elif [[ -n "${STOCK_BOOT_IMG}" ]]; then
    [[ -f "${STOCK_BOOT_IMG}" ]] || die "STOCK_BOOT_IMG=${STOCK_BOOT_IMG} does not exist"
    log "using the stock ramdisk from ${STOCK_BOOT_IMG}"
    python3 "${ROOT}/scripts/extract_ramdisk.py" \
        "${STOCK_BOOT_IMG}" "${RAMDISK}" || die "could not extract the stock ramdisk"
    RAMDISK_SIZE="$(stat -c %s "${RAMDISK}")"
    [[ "${RAMDISK_SIZE}" -gt 1000000 ]] || \
        die "extracted ramdisk is only ${RAMDISK_SIZE} bytes - that is not a real initramfs"
else
    : > "${BOOTDIR}/empty"
    gzip -c "${BOOTDIR}/empty" > "${RAMDISK}"
    log "WARNING: no STOCK_BOOT_IMG given - packaging an EMPTY ramdisk."
    log "WARNING: the kernel will find no /init and no root=, and will die"
    log "WARNING: after ~20 s waiting for a root device."
    log "WARNING: set --stock-ramdisk (or --stock-boot) to fix this."
fi

# Offsets are the published a24 values: base 0x3fff8000, kernel +0x8000,
# ramdisk +0x26f08000, tags +0x07c88000, dtb +0x01f00000.
python3 "${MKBOOTIMG}" \
    --kernel "${BOOTDIR}/kernel" \
    --ramdisk "${RAMDISK}" \
    --dtb "${BOOTDIR}/dtb" \
    --header_version 2 \
    --base 0x3fff8000 \
    --kernel_offset 0x00008000 \
    --ramdisk_offset 0x26f08000 \
    --tags_offset 0x07c88000 \
    --dtb_offset 0x01f00000 \
    --pagesize 4096 \
    --cmdline "bootopt=64S3,32N2,64N2 loop.max_part=7 console=tty0 loglevel=7 panic=-1${EXTRA_CMDLINE}" \
    --output "${BOOTDIR}/boot.img"

STAMP="$(date -u +%Y%m%d-%H%M%S)"
NAME="a24_${VARIANT}_${BASE_FIRMWARE}_${STAMP}"
DEST="${ROOT}/${DIST_DIR}/${NAME}"
mkdir -p "${DEST}"
cp "${BOOTDIR}/boot.img" "${DEST}/boot.img"
cp "${WORK}/defconfig-report.${VARIANT}.md" "${DEST}/defconfig-report.md" 2>/dev/null || true
cp "${OUT}/.config" "${DEST}/config-${VARIANT}" 2>/dev/null || true
cp "${WORK}/build-${VARIANT}.log" "${DEST}/build.log" 2>/dev/null || true

# ---------------------------------------------------------------------------
# Disabled-verification vbmeta
#
# The kernels built here are unsigned. On a locked-verity device AVB rejects
# them and the bootloader falls back to Download Mode, which looks exactly
# like a bad kernel. A vbmeta image carrying both the disable-verity and
# disable-verification flags lets the device boot an unsigned boot partition.
#
# This is produced per variant so a tester can flash boot.img and vbmeta.img
# from the same folder and knows they belong together.
# ---------------------------------------------------------------------------
AVBTOOL="${ROOT}/scripts/third_party/avbtool/avbtool.py"
if [[ -f "${AVBTOOL}" ]]; then
    python3 "${AVBTOOL}" make_vbmeta_image \
        --flags 2 \
        --padding_size 4096 \
        --output "${DEST}/vbmeta.img" \
        || die "failed to produce vbmeta.img"
    log "vbmeta.img written (flags=2: disable-verity + disable-verification)"
    # Prove the flags landed instead of trusting the exit status.
    if python3 "${AVBTOOL}" info_image --image "${DEST}/vbmeta.img" 2>/dev/null \
            | grep -qE '^Flags:[[:space:]]+2$'; then
        log "vbmeta flags verified"
    else
        die "vbmeta.img does not carry flags=2"
    fi
else
    log "WARNING: avbtool not present, no vbmeta.img in this build"
fi

# Odin payload
( cd "${DEST}" && tar -cf "${NAME}.tar" boot.img && gzip -9 "${NAME}.tar" )

# Separate vbmeta payload: it goes to the vbmeta partition, so it must not be
# bundled into the AP tar (that would put it in the wrong partition).
if [[ -f "${DEST}/vbmeta.img" ]]; then
    ( cd "${DEST}" && tar -cf "${NAME}_vbmeta.tar" vbmeta.img && gzip -9 "${NAME}_vbmeta.tar" )
fi

# Version metadata for the release job
{
    echo "VARIANT=${VARIANT}"
    echo "NAME=${NAME}"
    echo "KERNEL_VERSION=${ACTUAL_VER:-unknown}"
    echo "KERNEL_REPO=${KERNEL_REPO}"
    echo "KERNEL_BRANCH=${KERNEL_BRANCH}"
    echo "CONFIG_PROFILE=${PROFILE_NAME}"
    echo "LOCALVERSION=${LOCALVERSION_USED}"
    echo "BASE_FIRMWARE=${BASE_FIRMWARE}"
    echo "KERNELSU_VERSION_CODE=${KSU_VERSION_CODE:-none}"
    echo "RAMDISK_BYTES=${RAMDISK_SIZE:-0}"
    echo "RAMDISK_SOURCE=${STOCK_RAMDISK:-${STOCK_BOOT_IMG:-EMPTY-PLACEHOLDER}}" 
} > "${DEST}/build-info.env"

log "done -> ${DEST}"
ls -la "${DEST}"
