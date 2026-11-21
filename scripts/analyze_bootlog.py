#!/usr/bin/env python3
# ============================================================================
#  analyze_bootlog.py - tell apart the ways this device can fail to boot
# ============================================================================
#  Usage:
#      python3 scripts/analyze_bootlog.py last_kmsg.txt
#
#  The a24 boot chain fails in several visually identical ways, and the log
#  that the tester pastes is often a concatenation of several boots. This
#  splits it into boots and reports what ended each one, so a report can be
#  acted on instead of guessed at.
# ============================================================================

import re
import sys

# Every boot of the preloader begins with this line.
BOOT_MARKER = "mblock_pl_boottag_hook init done"

TS_RE = re.compile(r"^\[\s*(\d+\.\d+)\]\s?(.*)$")

SIGNATURES = [
    ("gzip header is not correct",
     "bootloader could not decompress the kernel",
     "The boot partition holds something other than a gzipped Image. This is a "
     "packaging bug, not a kernel bug."),
    ("decompress kernel image fail",
     "bootloader could not decompress the kernel",
     "Same as above."),
    ("AST_DLOAD FROM KEY",
     "Download Mode entered by key combination",
     "A button was held during power-on. Nothing was tested. Power on with a "
     "short press and do not touch the buttons."),
    ("Entering usb mode for do_download",
     "Download Mode",
     "See above."),
    ("HALT: action = 0, reason = 9",
     "preloader halted",
     "Usually accompanies a decompress failure."),
    ("Restore lock state successfully",
     None, None),   # noise, present on healthy boots too
    ("jump to linux kernel",
     "handed over to the kernel",
     "The bootloader did its job. Whatever follows is the kernel's problem."),
    ("Kernel panic",
     "kernel panicked",
     "The kernel started and then died. Real information is in the panic text."),
    ("Unable to handle kernel",
     "kernel oops",
     "The kernel started and faulted."),
]

# Lines that only exist once the kernel has a working console.
KERNEL_ALIVE = [
    "Booting Linux",
    "Linux version",
    "Kernel command line",
    "Memory:",
    "smpboot",
    "Freeing unused kernel",
    "Run /init",
]


def split_boots(text):
    if BOOT_MARKER not in text:
        return ["(whole file)"]
    parts = text.split(BOOT_MARKER)
    if parts[0].strip():
        # content before the first marker still belongs to a boot
        parts = [parts[0]] + [BOOT_MARKER + p for p in parts[1:]]
    else:
        parts = [BOOT_MARKER + p for p in parts[1:]]
    return parts


def analyze(boot_text):
    lines = []
    for raw in boot_text.splitlines():
        m = TS_RE.match(raw.strip())
        if m:
            lines.append((float(m.group(1)), m.group(2)))

    max_ts = max((t for t, _ in lines), default=0.0)

    hits = []
    for pat, label, advice in SIGNATURES:
        if label and pat in boot_text:
            hits.append((pat, label, advice))

    alive = [k for k in KERNEL_ALIVE if k in boot_text]
    panics = boot_text.count("Kernel panic")
    oops = boot_text.count("Unable to handle kernel")

    return {
        "lines": len(lines),
        "max_ts": max_ts,
        "hits": hits,
        "alive": alive,
        "panics": panics,
        "oops": oops,
    }


def verdict(info):
    if any(lbl == "bootloader could not decompress the kernel"
           for _, lbl, _ in info["hits"]):
        return ("PACKAGING", "The kernel never ran. Fix the build.")
    if any(lbl == "Download Mode" or lbl == "Download Mode entered by key combination"
           for _, lbl, _ in info["hits"]):
        return ("NOT TESTED", "The device went to Download Mode. Retry without "
                              "touching the buttons.")
    if info["panics"] or info["oops"]:
        return ("KERNEL CRASH", "The kernel started and died. Read the panic.")
    if "handed over to the kernel" in [l for _, l, _ in info["hits"]]:
        if info["alive"]:
            return ("KERNEL RAN", "The kernel produced output. Look at where "
                                  "the output stops.")
        return ("BLIND", "The kernel was entered but printed nothing. Either it "
                         "died before any console existed, or it is running with "
                         "no console. A UART log is the only way to tell these "
                         "apart.")
    if info["max_ts"] > 0:
        return ("UNKNOWN", "No known signature. Compare against a stock boot.")
    return ("EMPTY", "No timestamped lines - the file may not be a kernel log.")


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: analyze_bootlog.py <logfile>")

    text = open(sys.argv[1], "rb").read().decode("utf-8", "replace")
    boots = split_boots(text)
    print("found %d boot record(s)\n" % len(boots))

    overall = []
    for i, boot in enumerate(boots, 1):
        info = analyze(boot)
        kind, why = verdict(info)
        overall.append(kind)
        print("=" * 70)
        print("boot %d   %s" % (i, kind))
        print("  lines with timestamps : %d" % info["lines"])
        print("  reached             : %.3fs" % info["max_ts"])
        if info["hits"]:
            print("  signatures:")
            for pat, label, advice in info["hits"]:
                print("    - %s" % label)
                if advice:
                    print("      %s" % advice)
        if info["alive"]:
            print("  kernel-side lines present: %s" % ", ".join(info["alive"]))
        else:
            print("  kernel-side lines present: NONE "
                  "(no Booting Linux / Linux version / Memory:)")
        print("  verdict : %s" % why)
        print()

    print("=" * 70)
    print("summary: %s" % ", ".join("boot%d=%s" % (i, k)
                                    for i, k in enumerate(overall, 1)))


if __name__ == "__main__":
    main()
