#!/usr/bin/env python3
# ============================================================================
#  extract_ramdisk.py — pull the ramdisk out of a stock boot.img
# ============================================================================
#  Usage:
#      python3 scripts/extract_ramdisk.py stock_boot.img out/ramdisk.gz
#
#  Why
#  ---
#  The kernel on this device does not carry its own userspace. The stock
#  boot.img holds a ~38 MiB ramdisk whose /init is what mounts system and
#  starts the vendor bring-up. A boot.img built without one (mkbootimg with a
#  placeholder gzip) gives the kernel an empty initramfs and no root=, so it
#  spends its last 20 seconds waiting for a root device that will never
#  appear and then dies - which is exactly the 25-30 s boot followed by a
#  power-off the tester reported.
#
#  So the stock ramdisk has to be carried over. This extracts it verbatim,
#  including its compression, so nothing is re-encoded on the way through.
# ============================================================================

import struct
import sys


def extract(path, out):
    raw = open(path, "rb").read()

    if raw[:8] != b"ANDROID!":
        raise SystemExit("%s: not an Android boot image (no ANDROID! magic)" % path)

    kernel_size, = struct.unpack_from("<I", raw, 8)
    ramdisk_size, = struct.unpack_from("<I", raw, 16)
    page, = struct.unpack_from("<I", raw, 36)

    if page not in (2048, 4096, 8192, 16384):
        raise SystemExit("%s: implausible page size %d" % (path, page))

    def pages(n):
        return (n + page - 1) // page

    # Layout: header (1 page), kernel, ramdisk, second stage, recovery dtbo.
    ramdisk_off = page + pages(kernel_size) * page
    ramdisk = raw[ramdisk_off:ramdisk_off + ramdisk_size]

    if not ramdisk:
        raise SystemExit("%s: ramdisk is empty" % path)

    magic = ramdisk[:4].hex()
    if magic[:4] != "1f8b" and ramdisk[:4] != b"\x02\x21\x4c\x18":
        print("  note: ramdisk magic is %s (not gzip/lz4); copying verbatim" % magic)

    with open(out, "wb") as f:
        f.write(ramdisk)

    print("  page size      : %d" % page)
    print("  kernel size    : %d (%d pages)" % (kernel_size, pages(kernel_size)))
    print("  ramdisk offset : 0x%x" % ramdisk_off)
    print("  ramdisk size   : %d bytes (%.2f MiB)" % (len(ramdisk), len(ramdisk) / 1048576))
    print("  ramdisk magic  : %s" % magic)
    print("  written to     : %s" % out)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: extract_ramdisk.py <stock_boot.img> <out_ramdisk.gz>")
    extract(sys.argv[1], sys.argv[2])
