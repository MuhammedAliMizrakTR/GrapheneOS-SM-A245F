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
KEEP = ("MODVERSIONS", "TRIM_UNUSED_KSYMS")


def patch(text, overrides):
    lines = text.splitlines()
    seen = set()
    out = []

    for line in lines:
        m = re.match(r"^(CONFIG_([A-Z0-9_]+))=", line)
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
    ap.add_argument("--report", help="write a summary of applied changes here")
    args = ap.parse_args()

    with open(args.src) as f:
        text = f.read()

    if args.harden:
        applied = {k: v for k, v in OVERRIDES.items() if k in
                   ("LTO_CLANG_FULL", "LTO_CLANG_THIN", "LTO_CLANG", "DEBUG_INFO")}
    else:
        applied = OVERRIDES

    new_text, seen, missing = patch(text, applied)

    with open(args.dst, "w") as f:
        f.write(new_text)

    report = ["# defconfig override report", ""]
    report.append("source : %s" % args.src)
    report.append("output : %s" % args.dst)
    report.append("mode   : %s" % ("HARDENED" if args.harden else "STANDARD"))
    report.append("")
    report.append("| config | value | reason |")
    report.append("|---|---|---|")
    for name in sorted(applied):
        value, reason = applied[name]
        mark = "" if name in seen else " *(appended)*"
        report.append("| `CONFIG_%s` | `%s` | %s%s |" % (name, value, reason, mark))
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
