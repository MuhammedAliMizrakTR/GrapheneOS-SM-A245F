#!/usr/bin/env python3
# ============================================================================
#  check_device.py - read the A245F version strings and decide if this
#                    kernel release can be flashed on the attached device
# ============================================================================
#  Run with the device booted normally and USB debugging enabled:
#
#      python3 scripts/check_device.py
#
#  Nothing is written to the device. This only reads properties and prints a
#  verdict. It exists because the single most common way to brick a Samsung
#  device with this kind of project is flashing a base the bootloader has
#  already fused past, and the build string is the only place that shows up
#  before you commit to a flash.
# ============================================================================

import argparse
import re
import subprocess
import sys

EXPECTED_MODEL = "SM-A245F"
EXPECTED_BASE = "A245FXXS9DYG1"
EXPECTED_BINARY = 9

# A Samsung build number looks like  A245FXXS9DYG1
#                                        ^^^^  model + region + update type
#                                            ^ binary (fifth character from end)
#                                             ^^^ One UI index / year / month
BUILD_RE = re.compile(r"^(?P<model>[A-Z0-9]{4,6})(?P<mid>[A-Z]{2})(?P<upd>[A-Z])"
                      r"(?P<binary>[0-9A-Z])(?P<ui>[A-Z])(?P<year>[A-Z])(?P<month>[A-Z])"
                      r"(?P<iter>[0-9A-Z]+)$")

# Binary is a base-36-ish counter: 1..9 then A..Z.
B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def to_int(ch):
    try:
        return B36.index(ch.upper())
    except ValueError:
        return -1


def adb(*args, timeout=30):
    return subprocess.run(["adb", *args], capture_output=True, text=True,
                          timeout=timeout)


def getprop(name):
    r = adb("shell", "getprop", name)
    return r.stdout.strip() if r.returncode == 0 else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expect-base", default=EXPECTED_BASE)
    ap.add_argument("--expect-binary", default=None,
                    help="override the binary this release targets "
                         "(default: parsed from --expect-base)")
    args = ap.parse_args()

    if subprocess.run(["which", "adb"], capture_output=True).returncode != 0:
        sys.exit("adb not found in PATH")

    devices = adb("devices").stdout.strip().splitlines()[1:]
    live = [d.split("\t")[0] for d in devices if "\tdevice" in d]
    if not live:
        sys.exit("no device in 'device' state - enable USB debugging and "
                 "authorise this computer")
    if len(live) > 1:
        sys.exit("more than one device attached: %s" % ", ".join(live))

    model = getprop("ro.product.model")
    device = getprop("ro.product.device")
    build = getprop("ro.build.display.id") or getprop("ro.build.id")
    bootloader = getprop("ro.boot.bootloader")
    fingerprint = getprop("ro.build.fingerprint")

    print("detected")
    print("  model       : %s" % (model or "<unknown>"))
    print("  device      : %s" % (device or "<unknown>"))
    print("  build       : %s" % (build or "<unknown>"))
    print("  bootloader  : %s" % (bootloader or "<unknown>"))
    print("  fingerprint : %s" % (fingerprint or "<unknown>"))
    print()

    problems = []
    warnings = []

    if model != EXPECTED_MODEL:
        problems.append(
            "model is %r, this release is for %s only. A245M (Latin America) "
            "and A245N (Korea) are different firmware lines - do not cross-flash."
            % (model, EXPECTED_MODEL))

    m = BUILD_RE.match(build or "")
    if not m:
        warnings.append(
            "could not parse the build string %r, so the rollback fuse could "
            "not be checked. Read the binary yourself: it is the fifth "
            "character from the end." % build)
        device_binary = None
    else:
        device_binary = to_int(m.group("binary"))
        print("build string decoded")
        print("  bootloader binary : %s" % m.group("binary"))
        print("  one UI letter     : %s  (a generation marker, NOT a binary)"
              % m.group("ui"))
        print()

    expected_binary = (to_int(args.expect_binary)
                       if args.expect_binary else to_int(EXPECTED_BASE[4]))

    if device_binary is not None:
        if device_binary > expected_binary:
            problems.append(
                "device is on binary %s, this release is built for binary %s. "
                "Samsung rollback protection is one-way: a device that has "
                "booted a higher binary will refuse this firmware. There is no "
                "software workaround."
                % (m.group("binary"), expected_binary))
        elif device_binary == expected_binary:
            print("binary matches the release base")
        else:
            warnings.append(
                "device is on an OLDER binary (%s) than the release base (%s). "
                "This can work, but the kernel was built against the %s source "
                "drop; mismatched vendor blobs are a real risk."
                % (m.group("binary"), expected_binary, args.expect_base))

    locked = getprop("ro.boot.verifiedbootstate")
    if locked:
        print("verified boot state: %s" % locked)
        if locked == "green":
            warnings.append(
                "verified boot is green (fully locked). Flashing an unsigned "
                "boot.img will fail until the bootloader is unlocked.")
    unlockable = getprop("ro.oem_unlock_supported")
    if unlockable:
        print("oem unlock supported: %s" % unlockable)

    print()
    if problems:
        print("VERDICT: DO NOT FLASH")
        for p in problems:
            print("  [stop] %s" % p)
        for w in warnings:
            print("  [warn] %s" % w)
        return 1

    print("VERDICT: compatible")
    for w in warnings:
        print("  [warn] %s" % w)
    print()
    print("Next: docs/FLASHING.md. Keep the stock firmware for your exact "
          "model and CSC on hand before you start.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
