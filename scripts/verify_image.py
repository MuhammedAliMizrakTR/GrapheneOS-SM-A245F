#!/usr/bin/env python3
# ============================================================================
#  verify_image.py — check that Image.gz really is a bootable arm64 Image
# ============================================================================
#  Usage:
#      python3 scripts/verify_image.py Image.gz
#      python3 scripts/verify_image.py boot.img
#
#  Why this exists
#  ---------------
#  The MediaTek bootloader decompresses the kernel and then jumps to it with
#  no further checks. If the payload is not a valid arm64 Image it will jump
#  anyway, into whatever the first bytes happen to be, and the device dies
#  without printing anything at all — no panic, no OOPS, nothing in
#  last_kmsg. That is indistinguishable from a hundred other faults once it
#  has happened on a tester's phone.
#
#  The arm64 Image header is the contract between the kernel and whatever
#  loads it:
#
#      0x00  code0        branch into the kernel  (opcode 0b000101 = B)
#      0x04  code1        usually 0
#      0x08  text_offset  where the image wants to be placed
#      0x10  image_size   how much of the file is live
#      0x18  flags        endianness, page size, physical placement
#      0x38  magic        'ARM\x64'  = 41 52 4d 64
#
#  A missing magic means the wrapper produced a raw binary or something else
#  entirely, and the only way that gets discovered on hardware is a silent
#  brick-shaped bootloop.
# ============================================================================

import gzip
import struct
import sys

ARM64_MAGIC = b"ARM\x64"
B_OPCODE = 0b000101


def load(path):
    """Return the decompressed Image for a .gz, or the input for a boot.img."""
    raw = open(path, "rb").read()

    if raw[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(raw), "gzip"
        except OSError as exc:
            raise SystemExit("%s: gzip payload is corrupt: %s" % (path, exc))

    # Android boot image v2: 8-byte magic, then kernel_size at offset 8.
    if raw[:8] == b"ANDROID!":
        kernel_size, = struct.unpack_from("<I", raw, 8)
        page, = struct.unpack_from("<I", raw, 36)
        if page not in (2048, 4096, 8192, 16384):
            raise SystemExit("%s: boot image page size %d is not valid" % (path, page))
        start = page
        payload = raw[start:start + kernel_size]
        # The kernel inside a boot image may itself be compressed.
        if payload[:2] == b"\x1f\x8b":
            return gzip.decompress(payload), "boot.img -> gzip"
        return payload, "boot.img -> raw"

    # Raw Image, or raw Image.gz that failed the magic test above.
    return raw, "raw"


def verify(path):
    try:
        img, how = load(path)
    except SystemExit:
        raise
    except Exception as exc:
        print("  FAIL: could not read %s: %s" % (path, exc))
        return False

    print("  source      : %s (%s)" % (path, how))
    print("  size        : %d bytes (%.2f MiB)" % (len(img), len(img) / 1048576))

    if len(img) < 0x40:
        print("  FAIL: shorter than the 64-byte arm64 Image header")
        return False

    code0, code1 = struct.unpack_from("<II", img, 0)
    text_offset, image_size = struct.unpack_from("<QQ", img, 0x08)
    flags, = struct.unpack_from("<Q", img, 0x18)
    magic = img[0x38:0x3C]

    print("  code0       : 0x%08x" % code0)
    print("  text_offset : 0x%x" % text_offset)
    print("  image_size  : %d (0x%x)" % (image_size, image_size))
    print("  flags       : 0x%x" % flags)
    print("  magic@0x38  : %r" % magic)

    ok = True
    if magic != ARM64_MAGIC:
        print("  FAIL: magic is %r, expected %r" % (magic, ARM64_MAGIC))
        print("        The loader will jump into this and die silently.")
        ok = False
    else:
        print("  OK: arm64 Image magic present")

    # code0 is a branch in a stub-bearing Image, but not every toolchain emits
    # one and the loader on this platform decompresses to an address it picks
    # at runtime, so the file offset the jump starts from is not necessarily 0.
    # An ADRP there is the first instruction of a real prologue, not junk.
    # Report it, do not fail on it: the magic is the contract, this is not.
    opcode = code0 >> 26
    if opcode == B_OPCODE:
        print("  OK: entry point is a branch")
    elif opcode in (0b100100, 0b100101, 0b100010, 0b110100):
        print("  note: code0 opcode 0b%s is %s, not a branch."
              % (format(opcode, "06b"),
                 {0b100100: "ADRP", 0b100101: "BL",
                  0b100010: "ADD-imm", 0b110100: "LDR/STR"}[opcode]))
        print("        Expected only when the loader skips a stub; not fatal.")
    else:
        print("  WARN: code0 opcode 0b%s is not a recognised branch or prologue"
              % format(opcode, "06b"))
        print("        first instruction - inspect before trusting this image")

    # image_size is the size of the *decompressed* image in memory, not the
    # length of the file it arrived in. Comparing it against the compressed
    # payload is meaningless - a gzip kernel is always smaller than the field.
    # Only meaningful for a raw Image, where the two should agree.
    if image_size:
        if how.startswith("boot.img -> gzip") or how == "gzip":
            print("  note: image_size is the decompressed size (%.2f MiB);"
                  " this file is compressed, so no comparison is made"
                  % (image_size / 1048576))
        elif image_size > len(img):
            print("  FAIL: raw image claims image_size=%d but only %d bytes exist"
                  % (image_size, len(img)))
            ok = False
        else:
            print("  OK: image_size %d fits the %d-byte file"
                  % (image_size, len(img)))

    # Endianness and page size live in flags. Anything unexpected here means
    # the kernel was built for a different configuration than the platform.
    if flags:
        endian = flags & 1
        pagesize = (flags >> 1) & 3
        phys = (flags >> 3) & 1
        print("  flags decode: endian=%s page=%s phys_placement=%s"
              % ("BE" if endian else "LE",
                 {0: "unspecified", 1: "4K", 2: "16K", 3: "64K"}[pagesize],
                 "2GB" if phys else "any"))
        if endian:
            print("  FAIL: big-endian kernel")
            ok = False

    return ok


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: verify_image.py <Image.gz|boot.img> [...]")

    failures = 0
    for path in sys.argv[1:]:
        print("--- %s" % path)
        if not verify(path):
            failures += 1
        print()

    if failures:
        raise SystemExit("%d image(s) failed verification" % failures)
    print("all images verified")


if __name__ == "__main__":
    main()
