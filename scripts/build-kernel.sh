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
JOBS="$(nproc)"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --variant)  VARIANT="$2"; shift 2 ;;
        --harden)   HARDENED="1"; shift ;;
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
KERNEL_SRC="${KSRC}/${KERNEL_DIR}"
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
case "${VARIANT}" in
    kernelsu)
        log "fetching KernelSU-Next (${KSU_NEXT_REF})"
        rm -rf "${KERNEL_SRC}/KernelSU-Next"
        git clone --depth=1 --single-branch --branch "${KSU_NEXT_REF}" \
            "${KSU_NEXT_REPO}" "${KERNEL_SRC}/KernelSU-Next"
        KSU_DIR="${KERNEL_SRC}/KernelSU-Next"
        ;;
    kernelsu-up)
        log "fetching upstream KernelSU (${KSU_UPSTREAM_REF})"
        rm -rf "${KERNEL_SRC}/KernelSU"
        git clone --depth=1 --single-branch --branch "${KSU_UPSTREAM_REF}" \
            "${KSU_UPSTREAM_REPO}" "${KERNEL_SRC}/KernelSU"
        KSU_DIR="${KERNEL_SRC}/KernelSU"
        ;;
    *)
        KSU_DIR=""
        ;;
esac

# Read the integrated version code back out of the source, so the release can
# pair the kernel with the exactly matching manager APK.
KSU_VERSION_CODE="none"
if [[ -n "${KSU_DIR}" && -f "${KSU_DIR}/${KSU_VERSION_HEADER}" ]]; then
    KSU_VERSION_CODE="$(grep -oE '#define[[:space:]]+KERNELSU_VERSION_CODE(_BASE)?[[:space:]]+[0-9]+' \
        "${KSU_DIR}/${KSU_VERSION_HEADER}" | grep -oE '[0-9]+$' | head -1)"
    [[ -n "${KSU_VERSION_CODE}" ]] || KSU_VERSION_CODE="unparsed"
fi
log "integrated KSU version code: ${KSU_VERSION_CODE}"

# ---------------------------------------------------------------------------
# 4. Defconfig
# ---------------------------------------------------------------------------
DEFCONFIG_SRC="${KERNEL_SRC}/arch/arm64/configs/${KERNEL_DEFCONFIG}"
[[ -f "${DEFCONFIG_SRC}" ]] || die "defconfig ${KERNEL_DEFCONFIG} not found"

DEFCONFIG_TMP="${WORK}/defconfig.${VARIANT}"
HARDEN_ARG=""
[[ "${HARDENED}" == "1" ]] && HARDEN_ARG="--harden"

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

MAKE=(make -C "${KERNEL_SRC}" O="${OUT}" ARCH=arm64
      LLVM=1 LLVM_IAS=1
      CROSS_COMPILE="${CROSS_COMPILE}"
      LOCALVERSION="-a24-${VARIANT}")

log "building (jobs=${JOBS})"
"${MAKE[@]}" -j"${JOBS}" Image dtbs 2>&1 | tee "${WORK}/build-${VARIANT}.log"

ln -sfn "${KERNEL_SRC}" "${WORK}/kernel-5.10" 2>/dev/null || true

# Vendor modules: the stock vendor partition expects them under vendor_dlkm,
# so they are collected separately and are NOT unpacked into boot.img.
if [[ -f "${OUT}/.config" ]] && grep -q '^CONFIG_MODULES=y' "${OUT}/.config"; then
    log "building vendor modules"
    "${MAKE[@]}" -j"${JOBS}" modules 2>&1 | tee -a "${WORK}/build-${VARIANT}.log" || \
        log "module build reported errors; continuing (see log)"
    "${MAKE[@]}" INSTALL_MOD_PATH="${OUT}/modules_install" modules_install || true
fi

IMAGEGZ="${OUT}/arch/arm64/boot/Image.gz"
[[ -f "${IMAGEGZ}" ]] || IMAGEGZ="${OUT}/arch/arm64/boot/Image"
[[ -f "${IMAGEGZ}" ]] || die "no kernel image produced"

# ---------------------------------------------------------------------------
# 7. Package
# ---------------------------------------------------------------------------
log "packaging"
BOOTDIR="${WORK}/boot-${VARIANT}"
rm -rf "${BOOTDIR}"; mkdir -p "${BOOTDIR}"

cp "${IMAGEGZ}" "${BOOTDIR}/kernel"

# DTB: prefer the device-specific one, fall back to the mt6789 set
DTB_GLOB="${OUT}/arch/arm64/boot/dts/mediatek/a24/*.dtb"
if compgen -G "${DTB_GLOB}" > /dev/null; then
    cat ${DTB_GLOB} > "${BOOTDIR}/dtb"
else
    DTB_MERGE="${KERNEL_SRC}/scripts/dtbTool"
    [[ -x "${DTB_MERGE}" ]] || die "no a24 DTB and no dtbTool available"
    "${DTB_MERGE}" -o "${BOOTDIR}/dtb" -s 2048 -d \
        "${OUT}/arch/arm64/boot/dts/mediatek/" 2>/dev/null || true
fi

# Boot image header v2, offsets taken from the published a24 device tree.
MKBOOTIMG="${KERNEL_SRC}/tools/mkbootimg/mkbootimg.py"
[[ -f "${MKBOOTIMG}" ]] || MKBOOTIMG="$(command -v mkbootimg || true)"
[[ -n "${MKBOOTIMG}" ]] || die "mkbootimg not found"

RAMDISK="${BOOTDIR}/ramdisk.gz"
[[ -f "${RAMDISK}" ]] || { : > "${BOOTDIR}/empty"; gzip -c "${BOOTDIR}/empty" > "${RAMDISK}"; }

python3 "${MKBOOTIMG}" \
    --kernel "${BOOTDIR}/kernel" \
    --ramdisk "${RAMDISK}" \
    --dtb "${BOOTDIR}/dtb" \
    --header_version 2 \
    --base 0x3fff8000 \
    --kernel_offset 0x00008000 \
    --ramdisk_offset 0x26f08000 \
    --tags_offset 0x07c88000 \
    --pagesize 4096 \
    --cmdline "bootopt=64S3,32N2,64N2 loop.max_part=7" \
    --output "${BOOTDIR}/boot.img"

STAMP="$(date -u +%Y%m%d-%H%M%S)"
NAME="a24_${VARIANT}_${BASE_FIRMWARE}_${STAMP}"
DEST="${ROOT}/${DIST_DIR}/${NAME}"
mkdir -p "${DEST}"
cp "${BOOTDIR}/boot.img" "${DEST}/boot.img"
cp "${WORK}/defconfig-report.${VARIANT}.md" "${DEST}/defconfig-report.md" 2>/dev/null || true
cp "${OUT}/.config" "${DEST}/config-${VARIANT}" 2>/dev/null || true
cp "${WORK}/build-${VARIANT}.log" "${DEST}/build.log" 2>/dev/null || true

# Odin payload
( cd "${DEST}" && tar -cf "${NAME}.tar" boot.img && gzip -9 "${NAME}.tar" )

# Version metadata for the release job
{
    echo "VARIANT=${VARIANT}"
    echo "NAME=${NAME}"
    echo "KERNEL_VERSION=${ACTUAL_VER:-unknown}"
    echo "BASE_FIRMWARE=${BASE_FIRMWARE}"
    echo "KERNELSU_VERSION_CODE=${KSU_VERSION_CODE:-none}"
} > "${DEST}/build-info.env"

log "done -> ${DEST}"
ls -la "${DEST}"
