#!/usr/bin/env python3
# ============================================================================
#  apply_defconfig_overrides.py — tune a24_defconfig for a custom kernel
# ============================================================================
#  Samsung ships a defconfig that is correct for SIGNED, PRODUCTION firmware.
#  Several of its settings are actively hostile to a locally built kernel:
#
#   LTO_CLANG_FULL     full LTO of the whole kernel. Needs a very large
#                      linker memory budget and a fast disk; usually the
#                      first thing to fail in CI containers.
#   DEBUG_INFO         emits vmlinux with DWARF. Several GB of disk and RAM.
#
#  And several Samsung security features will refuse to boot an unsigned,
#  locally built kernel at all. All four teams that ship MediaTek Samsung
#  kernels report the same set must be turned off:
#
#   RKP    (Rollback/Realtime Kernel Protection)
#   KDP    (Kernel Data Protection)
#   DEFEX  (seccomp-based execution restrictions)
#   FIVE   (file integrity verification)
#   PROCA  (process authentication)
#
#  Everything else in the Samsung defconfig is LEFT UNTOUCHED: the vendor
#  module ABI, the DTB selection, and the hardware drivers all stay as
#  shipped, which is what keeps the kernel loadable by the stock vendor
#  partition.
#
#  Use --harden to produce a build that keeps the security features on.
#  That variant will only boot on a device whose boot chain accepts it.
# ============================================================================

import re
import sys
import argparse

# (config, value, reason)
OVERRIDES = {
    # ---- build feasibility -------------------------------------------------
    "LTO_CLANG_FULL": ("n", "full LTO exhausts CI memory/disk budgets"),
    "LTO_CLANG_THIN": ("n", "thin LTO still requires a large link step"),
    "LTO_CLANG": ("n", "disable all LTO variants"),
    "DEBUG_INFO": ("n", "DWARF debug info costs GB of disk; not needed to boot"),

    # Samsung's defconfig treats every compiler warning as an error. The
    # MediaTek vendor code does not build warning-clean with a newer clang
    # (cameraisp/dpe emits -Wsometimes-uninitialized diagnostics that were
    # never seen by whatever clang Samsung used), so WERROR alone stops the
    # build long before the device tree is reached. Warnings are still printed
    # and still worth reading; they just should not end the build.
    "WERROR": ("n", "vendor MTK code is not warning-clean with this clang"),

    # ---- make the serial console usable -----------------------------------
    # The shipped defconfig builds the MediaTek UART driver as a module
    # (SERIAL_8250_MT6577=m). A module cannot be loaded before userspace, so
    # the console the cmdline asks for does not exist during early boot:
    # every printk before the module loads goes nowhere, which is exactly the
    # "kernel entered but printed nothing" case the tester hit. Built in, the
    # driver registers its OF earlycon (8250_mtk.c, OF_EARLYCON_DECLARE(
    # mtk8250, "mediatek,mt6577-uart", ...)) and start_kernel() output becomes
    # visible.
    "SERIAL_8250_MT6577": ("y", "UART must be built in or early boot output is lost"),
    "SERIAL_8250_CONSOLE": ("y", "console support"),
    "SERIAL_EARLYCON": ("y", "early console plumbing"),

    # ---- make the kernel log survive a crash -----------------------------
    # CONFIG_SEC_DEBUG is the driver behind /proc/last_kmsg: sec_debug_log.c
    # keeps a copy of the kernel log in the region Samsung reserves for it, so
    # that the next boot (or recovery) can read what happened. It ships as
    # =m. A module only loads once userspace is up, which is far too late to
    # catch a kernel that dies during bring-up: the last_kmsg the tester sent
    # held nothing but preloader and LK output, because nothing on the kernel
    # side was ever writing.
    #
    # Built in, a crash during early boot leaves the log behind where recovery
    # can read it. This does not change what the kernel does; it only makes it
    # possible to find out why it stopped.
    "SEC_DEBUG": ("y", "provides /proc/last_kmsg; =m cannot capture an early crash"),
    "SEC_DEBUG_AUTO_COMMENT": ("y", "crash annotations for the last_kmsg record"),
    "SEC_DEBUG_HISTORY_LOG": ("y", "boot history alongside the crash log"),

    # The MediaTek equivalent. mrdump/ipanic (mboot_params.o) is the other
    # half of the same story and is also shipped as a module.
    #
    # MTK_AEE_FEATURE is deliberately left at =m. Pulling the whole AEE
    # subsystem in-tree makes aee_rs.o built-in, and that object needs
    # aee_get_mode/DAL_Printf/DAL_SetColor from aed-main.c and the DAL it
    # depends on, which are not built in this configuration:
    #
    #   ld.lld: error: undefined symbol: aee_get_mode
    #   ld.lld: error: undefined symbol: DAL_Printf
    #
    # Only the panic recorder is needed here.
    "MTK_AEE_IPANIC": ("y", "kernel panic recorder, must exist before the crash"),

    # ---- give the kernel a console the tester can actually see ------------
    # The shipped config has no console at all:
    #
    #   CONFIG_VT                 unset
    #   CONFIG_FRAMEBUFFER_CONSOLE unset
    #   CONFIG_DRM_FBDEV_EMULATION unset
    #
    # so bootargs' console=tty0 has nothing to bind to, and with no UART cable
    # attached there is no way to see a panic. That is why four rounds of
    # tester logs contained nothing from the kernel: not because it printed
    # nothing, but because there was nowhere for it to print.
    #
    # mtk_drm_drv.c already calls drm_fbdev_generic_setup(drm, 32), so turning
    # fbdev emulation on gives a real console on the panel once DRM is up.
    # VT must come with it - fbdev emulation provides the console but VT is
    # what the kernel console actually hangs off.
    #
    # This only helps once the display driver has probed, so it will not catch
    # a failure in the first few instructions of head.S. It does catch
    # everything after that, which is where a watchdog reset implies the
    # kernel is going.
    "VT": ("y", "console plumbing; without it there is no tty to print to"),
    "VT_CONSOLE": ("y", "attach the kernel console to the VT"),
    "DRM_FBDEV_EMULATION": ("y", "MTK DRM already calls drm_fbdev_generic_setup"),
    "DRM_KMS_FB_HELPER": ("y", "required by fbdev emulation"),

    # The shipped defconfig hardcodes Samsung's build-server path as the KMI
    # whitelist:
    #   CONFIG_UNUSED_KSYMS_WHITELIST="/home/dpi/qb5_8814/.../abi_symbollist.raw"
    # That file exists nowhere else, so the build dies at
    #   GEN include/generated/autoksyms.h
    #   ERROR: '<path>' whitelist file not found
    # TRIM_UNUSED_KSYMS only drops *unused* exports from ksymtab at build time;
    # it does not affect the runtime ABI that vendor modules bind against
    # (that is CONFIG_MODVERSIONS). Disabling it leaves every export in place,
    # which is a strict superset of any whitelist, so no vendor module can lose
    # a symbol it needs.
    "TRIM_UNUSED_KSYMS": ("n", "whitelist path is hardcoded to Samsung's build server"),

    # ---- Samsung security features that block unsigned kernels -------------
    "RKP": ("n", "Real-time Kernel Protection rejects unsigned images"),
    "KDP": ("n", "Kernel Data Protection"),
    "KDP_CRED": ("n", "KDP credential enforcement"),
    "KDP_NS": ("n", "KDP namespace enforcement"),
    "SECURITY_DEFEX": ("n", "DEFEX blocks execution outside signed allowlists"),
    "SECURITY_DEFEX_USER": ("n", "DEFEX userspace component"),
    "FIVE": ("n", "FIVE file-integrity verification"),
    "FIVE_GKI_10": ("n", "FIVE GKI 5.10 shim"),
    "PROCA": ("n", "PROCA process authentication"),
    "PROCA_S_OS": ("n", "PROCA S-OS policy"),
    "GAF": ("n", "GAF integrity driver"),
}

# Kept enabled on purpose. Removing these breaks vendor module loading.
KEEP = ("MODVERSIONS",)

# Removed outright rather than set to "n": this is a string option, and its
# shipped value is the dead Samsung build-server path. It depends on
# TRIM_UNUSED_KSYMS, which we disable, so leaving the line behind is merely
# cosmetically confusing -- but a stale absolute path in a published defconfig
# is exactly the kind of thing that misleads the next reader.
DROP = ("UNUSED_KSYMS_WHITELIST",)


def patch(text, overrides):
    lines = text.splitlines()
    seen = set()
    out = []

    for line in lines:
        m = re.match(r"^(CONFIG_([A-Z0-9_]+))=", line)
        if m and m.group(2) in DROP:
            seen.add(m.group(2))
            continue
        if m and m.group(2) in overrides:
            name = m.group(2)
            value, _ = overrides[name]
            seen.add(name)
            if value == "n":
                out.append("# CONFIG_%s is not set" % name)
            else:
                out.append("CONFIG_%s=%s" % (name, value))
            continue
        out.append(line)

    # Append anything the defconfig did not mention at all.
    missing = [n for n in overrides if n not in seen]
    if missing:
        out.append("")
        out.append("# --- added by apply_defconfig_overrides.py ---")
        for name in missing:
            value, _ = overrides[name]
            if value == "n":
                out.append("# CONFIG_%s is not set" % name)
            else:
                out.append("CONFIG_%s=%s" % (name, value))

    return "\n".join(out) + "\n", sorted(seen), missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="dst", required=True)
    ap.add_argument("--harden", action="store_true",
                    help="stop after build-feasibility changes; keep Samsung security features")
    ap.add_argument("--keep-security", action="store_true",
                    help="leave Samsung's RKP/KDP/DEFEX/FIVE/PROCA enabled "
                         "(correct for a tree whose own defconfig ships them on)")
    ap.add_argument("--report", help="write a summary of applied changes here")
    args = ap.parse_args()

    with open(args.src) as f:
        text = f.read()

    SECURITY = ("RKP", "KDP", "KDP_CRED", "KDP_NS", "SECURITY_DEFEX",
                "SECURITY_DEFEX_USER", "FIVE", "FIVE_GKI_10", "PROCA",
                "PROCA_S_OS", "GAF")
    BUILD_ONLY = ("LTO_CLANG_FULL", "LTO_CLANG_THIN", "LTO_CLANG", "DEBUG_INFO")

    if args.harden:
        applied = {k: v for k, v in OVERRIDES.items() if k in BUILD_ONLY}
    elif getattr(args, "keep_security", False):
        # Used with a tree whose own defconfig already ships the Samsung
        # security drivers enabled (VH-Devices OSRC does). Turning them off
        # there is a change to a configuration that is known to boot, and the
        # change has never been shown to help.
        applied = {k: v for k, v in OVERRIDES.items() if k not in SECURITY}
    else:
        applied = OVERRIDES

    new_text, seen, missing = patch(text, applied)

    with open(args.dst, "w") as f:
        f.write(new_text)

    report = ["# defconfig override report", ""]
    report.append("source : %s" % args.src)
    report.append("output : %s" % args.dst)
    if args.harden:
        mode = "HARDENED"
    elif getattr(args, "keep_security", False):
        mode = "KEEP-SECURITY"
    else:
        mode = "STANDARD"
    report.append("mode   : %s" % mode)
    report.append("")
    report.append("| config | value | reason |")
    report.append("|---|---|---|")
    for name in sorted(applied):
        value, reason = applied[name]
        mark = "" if name in seen else " *(appended)*"
        report.append("| `CONFIG_%s` | `%s` | %s%s |" % (name, value, reason, mark))
    report.append("")
    report.append("## Removed outright")
    for name in DROP:
        report.append("- `CONFIG_%s` — shipped value was a dead absolute path "
                      "on Samsung's build server" % name)
    report.append("")
    report.append("## Deliberately kept enabled")
    for k in KEEP:
        report.append("- `CONFIG_%s` — required for vendor modules to load" % k)
    report.append("")

    if args.report:
        with open(args.report, "w") as f:
            f.write("\n".join(report) + "\n")
    print("\n".join(report))


if __name__ == "__main__":
    main()
