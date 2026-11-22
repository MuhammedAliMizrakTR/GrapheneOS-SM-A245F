#!/usr/bin/env python3
# ============================================================================
#  repair_boot_img.py — normalise a vendor boot image into a clean v2 boot.img
# ============================================================================
#  Usage:
#      python3 scripts/repair_boot_img.py <in> <out>
#
#  Why
#  ---
#  A boot image out of a Samsung/MediaTek firmware package is not necessarily
#  a bare Android boot image, and assuming it is has already cost a wasted
#  round trip. Three things get in the way, and they nest:
#
#    1. MTK header. MediaTek prepends a fixed 512-byte header:
#           0x00  4   magic 88 16 88 58   (LE 0x58881688)
#           0x04  4   payload length, little-endian
#           0x08  32  type tag: KERNEL / ROOTFS / RECOVERY
#           0x28  472 fill out to 512 (0xFF in practice, NUL in some tools)
#       so the ANDROID! magic sits at 0x200 rather than 0x000.
#
#    2. LZ4. Samsung ships boot.img.lz4. Two frame formats exist and both are
#       seen: the legacy frame (02 21 4c 18; blocks of at most 8 MiB, each
#       prefixed with a u32 length whose top bit means "stored") and the
#       modern frame (04 22 4d 18).
#
#    3. Neither, or both stacked — MTK(lz4(img)) is real.
#
#  The important lesson from the failed first attempt: searching for ANDROID!
#  inside a *compressed* buffer can hit a false positive in the noise, and a
#  false positive here silently produces a rubbish image. So this peels one
#  wrapper at a time, and every ANDROID! candidate is validated by parsing the
#  header that follows it and checking the numbers are plausible. A candidate
#  that does not validate is rejected and the next one is tried.
# ============================================================================

import struct
import sys

MTK_MAGIC = b"\x88\x16\x88\x58"      # LE 0x58881688
MTK_HDR = 512
LZ4_LEGACY = b"\x02\x21\x4c\x18"
LZ4_MODERN = b"\x04\x22\x4d\x18"
ANDROID_MAGIC = b"ANDROID!"

# Guards against false positives in compressed data.
VALID_PAGES = (2048, 4096, 8192, 16384)
VALID_HEADER_VERSIONS = (0, 1, 2, 3, 4)
MAX_PREFIX = 1 << 20                  # a real wrapper is never bigger


def _mtk_tag(hdr):
    """Read the 32-byte type tag, tolerating NUL or 0xFF padding."""
    raw = hdr[8:40]
    return raw.rstrip(b"\x00\xff").decode("ascii", "replace")


def _decompress_lz4_legacy(blob):
    """Decode a legacy lz4 frame by hand.

    python-lz4 refuses legacy frames and lz4.block needs to be told the
    output size, so the block loop is done explicitly. Legacy frame blocks
    decompress to at most 8 MiB.
    """
    import lz4.block

    out = bytearray()
    pos = 4
    while pos + 4 <= len(blob):
        n, = struct.unpack_from("<I", blob, pos)
        pos += 4
        if n == 0:
            break
        if n & 0x80000000:                       # stored, not compressed
            ln = n & 0x7FFFFFFF
            out += blob[pos:pos + ln]
            pos += ln
        else:
            out += lz4.block.decompress(blob[pos:pos + n],
                                        uncompressed_size=8 << 20)
            pos += n
    return bytes(out)


def _decompress_lz4(raw):
    """Undo an lz4 frame if the magic says there is one."""
    if len(raw) < 4:
        return raw, None
    if raw[:4] == LZ4_LEGACY:
        try:
            return _decompress_lz4_legacy(raw), "legacy lz4 frame (02214c18)"
        except Exception as e:                   # noqa: BLE001
            raise SystemExit("legacy lz4 decode failed: %s" % e)
    if raw[:4] == LZ4_MODERN:
        try:
            import lz4.frame
        except ImportError:
            raise SystemExit(
                "modern lz4 frame found but python-lz4 is missing; "
                "run: pip install lz4")
        return lz4.frame.decompress(raw), "modern lz4 frame (04224d18)"
    return raw, None


def _strip_mtk(buf):
    """Strip a leading MTK header if present. Returns (payload, note)."""
    if len(buf) >= MTK_HDR and buf[:4] == MTK_MAGIC:
        plen, = struct.unpack_from("<I", buf, 4)
        return buf[MTK_HDR:], "MTK header: type=%r payload_length=%d" % (
            _mtk_tag(buf), plen)
    return buf, None


def _validate_android(buf, idx):
    """Is the ANDROID! at idx the start of a plausible boot header?"""
    if idx + 44 > len(buf):
        return None
    kernel_size, = struct.unpack_from("<I", buf, idx + 8)
    ramdisk_size, = struct.unpack_from("<I", buf, idx + 16)
    page, = struct.unpack_from("<I", buf, idx + 36)
    header_version, = struct.unpack_from("<I", buf, idx + 40)

    if page not in VALID_PAGES:
        return None
    if header_version not in VALID_HEADER_VERSIONS:
        return None
    # Kernel and ramdisk have to fit in what is left of the file.
    if kernel_size == 0 or kernel_size > len(buf) - idx:
        return None
    if ramdisk_size == 0 or ramdisk_size > len(buf) - idx:
        return None
    return dict(kernel_size=kernel_size, ramdisk_size=ramdisk_size,
                page=page, header_version=header_version)


def normalise(raw):
    """Peel wrappers until a valid boot header sits at the front.

    Returns (clean_image, notes). Each wrapper is removed only when it is
    positively identified by its magic; nothing is guessed from offsets.
    """
    notes = []
    buf = raw

    # At most a couple of layers are ever seen; the loop is a safety net so a
    # novel combination still terminates.
    for _ in range(6):
        buf, note = _strip_mtk(buf)
        if note:
            notes.append(note)

        if buf[:8] == ANDROID_MAGIC and _validate_android(buf, 0):
            notes.append("ANDROID! at offset 0, header validates")
            return buf, notes

        buf, note = _decompress_lz4(buf)
        if note:
            notes.append(note)
            continue

        # Nothing identified at the front. Look for ANDROID!, but only accept
        # a candidate whose header parses — this is what stops the false
        # positive seen when the search ran over compressed data.
        best = None
        start = 0
        while True:
            idx = buf.find(ANDROID_MAGIC, start, min(len(buf), start + MAX_PREFIX))
            if idx < 0:
                break
            info = _validate_android(buf, idx)
            if info:
                best = (idx, info)
                break
            start = idx + 1

        if best is None:
            raise SystemExit(
                "could not find a valid Android boot header.\n"
                "  input starts with : %s\n"
                "  no MTK header, no lz4 frame, and no ANDROID! that parses\n"
                "  send this file as-is and we will look at it"
                % buf[:16].hex())

        idx, info = best
        notes.append("ANDROID! at offset 0x%x (%d bytes skipped, header "
                     "validates)" % (idx, idx))
        if idx == MTK_HDR and raw[:4] == MTK_MAGIC:
            notes.append("the skipped prefix is exactly one MTK header")
        buf = buf[idx:]
        return buf, notes

    raise SystemExit("wrappers did not resolve after 6 attempts")


def inspect(img):
    """Parse the v2 header and locate the ramdisk."""
    if img[:8] != ANDROID_MAGIC:
        raise SystemExit("normalised image still lacks ANDROID!")

    info = _validate_android(img, 0)
    if info is None:
        raise SystemExit("normalised image header does not validate")

    page = info["page"]
    kernel_size = info["kernel_size"]
    ramdisk_size = info["ramdisk_size"]

    def pages(n):
        return (n + page - 1) // page

    ramdisk_off = page + pages(kernel_size) * page
    ramdisk = img[ramdisk_off:ramdisk_off + ramdisk_size]

    if len(ramdisk) != ramdisk_size:
        raise SystemExit("truncated: ramdisk claims %d bytes, file has %d"
                         % (ramdisk_size, len(ramdisk)))

    info["ramdisk_off"] = ramdisk_off
    info["ramdisk"] = ramdisk
    info["total"] = len(img)

    # The ramdisk can itself carry an MTK header, in which case the leading
    # 512 bytes are a wrapper rather than part of the compressed stream. That
    # header is removed from the output: leaving it in place produces a
    # ramdisk whose first bytes are 88 16 88 58 instead of a gzip magic, and
    # the kernel has no hope of unpacking it.
    if ramdisk[:4] == MTK_MAGIC and len(ramdisk) > MTK_HDR:
        inner = ramdisk[MTK_HDR:]
        plen, = struct.unpack_from("<I", ramdisk, 4)
        if plen != len(inner):
            raise SystemExit(
                "ramdisk MTK header claims %d payload bytes but %d follow"
                % (plen, len(inner)))
        info["ramdisk_mtk"] = _mtk_tag(ramdisk)
        info["ramdisk"] = inner
        info["ramdisk_size"] = len(inner)
        info["ramdisk_magic"] = inner[:4].hex()
        info["ramdisk_stripped"] = MTK_HDR
    else:
        info["ramdisk_mtk"] = None
        info["ramdisk_magic"] = ramdisk[:4].hex()
        info["ramdisk_stripped"] = 0

    # Rebuild the image with the corrected ramdisk so the output is not just
    # the input with a note attached.
    if info["ramdisk_stripped"]:
        head = img[:ramdisk_off]
        rounded = pages(info["ramdisk_size"]) * page
        img = head + info["ramdisk"] + b"\x00" * (rounded - info["ramdisk_size"])
        info["total"] = len(img)

    return info, img


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: repair_boot_img.py <in> <out>")

    src, dst = sys.argv[1], sys.argv[2]
    with open(src, "rb") as f:
        raw = f.read()

    print("input          : %s (%d bytes, %.2f MiB)"
          % (src, len(raw), len(raw) / 1048576))
    print("first 16 bytes : %s" % raw[:16].hex())

    img, notes = normalise(raw)
    for n in notes:
        print("  note: %s" % n)

    info, img = inspect(img)

    print()
    print("  header version : %d" % info["header_version"])
    print("  page size      : %d" % info["page"])
    print("  kernel         : %d bytes (%.2f MiB)"
          % (info["kernel_size"], info["kernel_size"] / 1048576))
    print("  ramdisk        : %d bytes (%.2f MiB)"
          % (info["ramdisk_size"], info["ramdisk_size"] / 1048576))
    print("  ramdisk offset : 0x%x" % info["ramdisk_off"])
    if info["ramdisk_mtk"]:
        print("  ramdisk MTK hdr: %r (will be stripped on extraction)"
              % info["ramdisk_mtk"])
    print("  ramdisk magic  : %s" % info["ramdisk_magic"])

    if info["ramdisk_size"] < 1048576:
        print()
        print("!!! ramdisk is under 1 MiB — this is not a stock initramfs")
        print("!!! nothing written")
        return 1

    with open(dst, "wb") as f:
        f.write(img)

    print()
    print("  written to     : %s (%d bytes, %.2f MiB)"
          % (dst, len(img), len(img) / 1048576))
    print()
    print("OK: real boot image, real ramdisk (%d bytes)" % info["ramdisk_size"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
