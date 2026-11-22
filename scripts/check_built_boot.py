#!/usr/bin/env python3
# ============================================================================
#  check_built_boot.py — is the boot.img we just built actually bootable?
# ============================================================================
#  Usage:
#      python3 scripts/check_built_boot.py dist/a24_*/boot.img ...
#
#  The failure this exists to catch: a boot image whose ramdisk is an empty
#  gzip. The kernel finds no /init, has no root= on the cmdline, waits about
#  twenty seconds for a root device that never appears and then panics with
#  panic=-1 set, so the watchdog cuts power. On the device that looks like a
#  boot that ends in a power-off, which is exactly what was reported.
#
#  So: parse the header, pull the ramdisk, decompress it, count the entries,
#  and require a real init to be in there. Exit non-zero if not.
# ============================================================================

import gzip
import struct
import sys

MTK_MAGIC = b"\x88\x16\x88\x58"
LZ4_LEGACY = b"\x02\x21\x4c\x18"
LZ4_MODERN = b"\x04\x22\x4d\x18"
MIN_RAMDISK = 1024 * 1024


def unlz4(blob):
    if blob[:4] == LZ4_MODERN:
        import lz4.frame
        return lz4.frame.decompress(blob)
    import lz4.block
    out = bytearray()
    pos = 4
    while pos + 4 <= len(blob):
        n, = struct.unpack_from("<I", blob, pos)
        pos += 4
        if n == 0:
            break
        if n & 0x80000000:
            ln = n & 0x7FFFFFFF
            out += blob[pos:pos + ln]
            pos += ln
        else:
            out += lz4.block.decompress(blob[pos:pos + n],
                                        uncompressed_size=8 << 20)
            pos += n
    return bytes(out)


def cpio_entries(data, limit=20000):
    """Walk every cpio 'newc' archive in the buffer and yield (name, size).

    An Android ramdisk is often a concatenation of many archives rather than
    one: recovery.img on this device has 127 of them. Stopping at the first
    TRAILER!!! would see only a handful of symlinks and wrongly conclude there
    is no init.
    """
    pos = 0
    n = 0
    while pos + 110 <= len(data) and n < limit:
        if data[pos:pos + 6] != b"070701":
            nxt = data.find(b"070701", pos)
            if nxt < 0:
                break
            pos = nxt
            continue
        try:
            filesize = int(data[pos + 54:pos + 62], 16)
            namesize = int(data[pos + 94:pos + 102], 16)
        except ValueError:
            break
        name = data[pos + 110:pos + 110 + namesize - 1].decode("ascii", "replace")
        if name == "TRAILER!!!":
            pos += (110 + namesize + 3) & ~3
            continue
        yield name, filesize
        pos += (110 + namesize + filesize + 3) & ~3
        n += 1


def check(path):
    raw = open(path, "rb").read()
    problems = []

    if raw[:8] != b"ANDROID!":
        return ["not an Android boot image (first 8 bytes %s)" % raw[:8].hex()]

    header_version, = struct.unpack_from("<I", raw, 40)

    if header_version >= 3:
        kernel_size, = struct.unpack_from("<I", raw, 8)
        ramdisk_size, = struct.unpack_from("<I", raw, 12)
        page = 4096
    else:
        kernel_size, = struct.unpack_from("<I", raw, 8)
        ramdisk_size, = struct.unpack_from("<I", raw, 16)
        page, = struct.unpack_from("<I", raw, 36)

    if page not in (2048, 4096, 8192, 16384):
        return ["implausible page size %d" % page]

    pages = lambda v: (v + page - 1) // page
    off = page + pages(kernel_size) * page
    rd = raw[off:off + ramdisk_size]

    print("  %-42s v%d page %d" % (path.split("/")[-2] + "/" + path.split("/")[-1],
                                   header_version, page))
    print("    kernel  %8d bytes (%.2f MiB)" % (kernel_size, kernel_size / 1048576))
    print("    ramdisk %8d bytes (%.2f MiB)" % (ramdisk_size, ramdisk_size / 1048576))

    if ramdisk_size < MIN_RAMDISK:
        problems.append("ramdisk is only %d bytes (< 1 MiB): this is the empty "
                        "placeholder, the image cannot boot" % ramdisk_size)
        return problems

    if rd[:4] == MTK_MAGIC:
        rd = rd[512:]
        print("    (stripped a 512-byte MTK header from the ramdisk)")

    try:
        if rd[:2] == b"\x1f\x8b":
            data = gzip.decompress(rd)
            kind = "gzip"
        elif rd[:4] in (LZ4_LEGACY, LZ4_MODERN):
            data = unlz4(rd)
            kind = "lz4"
        else:
            problems.append("ramdisk magic is %s: neither gzip nor lz4"
                            % rd[:4].hex())
            return problems
    except Exception as e:                       # noqa: BLE001
        problems.append("ramdisk will not decompress: %s" % e)
        return problems

    print("    %s -> %d bytes (%.2f MiB)" % (kind, len(data), len(data) / 1048576))

    if data[:6] != b"070701":
        problems.append("ramdisk payload is not a cpio archive")
        return problems

    names = [n for n, _ in cpio_entries(data, 4000)]
    has_init = any(n.lstrip("./") == "init" or n.endswith("/init") for n in names)
    print("    cpio: %d entries, init %s" % (len(names), "present" if has_init else "MISSING"))

    if not has_init:
        problems.append("cpio archive has no /init, the kernel would find "
                        "nothing to execute")

    if not names:
        problems.append("cpio archive is empty")

    return problems


def main():
    paths = sys.argv[1:]
    if not paths:
        raise SystemExit("usage: check_built_boot.py <boot.img> [...]")

    failed = 0
    for p in paths:
        try:
            problems = check(p)
        except FileNotFoundError:
            print("  %s: missing" % p)
            problems = ["missing"]
        if problems:
            failed += 1
            for pr in problems:
                print("    FAIL: %s" % pr)
        else:
            print("    OK: carries a real initramfs with /init")
        print()

    if failed:
        print("%d image(s) would not boot" % failed)
        return 1
    print("all images carry a real initramfs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
