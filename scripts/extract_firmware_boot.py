#!/usr/bin/env python3
# ============================================================================
#  extract_firmware_boot.py — pull boot.img out of a SamFW firmware zip
# ============================================================================
#  Usage:
#      python3 scripts/extract_firmware_boot.py \
#          "SAMFW.COM_SM-A245F_TUR_A245FXXS9DYG1_fac.zip" \
#          boot.img
#
#  Why this exists
#  ---------------
#  A full samfw package is ~7.5 GB and most of it is `super.img`. All that is
#  actually wanted here is `boot.img`, which is ~80 MB and holds the ramdisk
#  the kernel needs in order to have an /init at all.
#
#  Naively unzipping first costs 7.5 GB of disk and then another 8+ GB when the
#  AP tar is unpacked. This streams instead: it reads the zip's central
#  directory, walks to the AP member, and reads the tar sequentially until it
#  finds boot.img, never materialising anything else. Peak disk use is the
#  size of boot.img alone.
#
#  The structure being navigated:
#
#      SAMFW...fac.zip
#        └── AP_....tar.md5          (a tar, with an md5 appended at the end)
#              ├── boot.img          <- wanted
#              ├── dtbo.img
#              ├── vbmeta.img
#              └── super.img         (7+ GB, never touched)
#
#  The md5 suffix means the tar has trailing bytes after the end-of-archive
#  marker. tarfile's streaming reader stops at the marker and ignores them,
#  which is exactly the behaviour needed.
# ============================================================================

import hashlib
import os
import sys
import tarfile
import zipfile


def find_ap_member(zf):
    """Return the AP tar member, which holds boot.img."""
    names = zf.namelist()

    # SamFW names them AP_<model>_<build>_....tar.md5. Match on that first.
    ap = [n for n in names
          if os.path.basename(n).upper().startswith("AP")
          and (n.lower().endswith(".tar.md5") or n.lower().endswith(".tar")
               or n.lower().endswith(".tar.md5.1"))]
    if ap:
        return ap[0]

    # Fall back to any tar-shaped member that is not obviously another slot.
    for n in names:
        low = n.lower()
        if not (low.endswith(".tar") or low.endswith(".tar.md5")):
            continue
        base = os.path.basename(n).upper()
        if base.startswith(("BL", "CP", "CSC", "HOME_CSC", "USERDATA")):
            continue
        return n

    raise SystemExit(
        "no AP tar found in the zip. Contents were:\n  "
        + "\n  ".join(names[:40]))


def stream_member(zf, member_name, out_path):
    """Read boot.img out of the AP tar inside the zip, without unpacking."""
    with zf.open(member_name) as raw:
        # r| is the streaming reader: sequential, no seeking, stops at the
        # end-of-archive marker so the .md5 tail is ignored.
        with tarfile.open(fileobj=raw, mode="r|") as tar:
            for entry in tar:
                if not entry.isfile():
                    continue
                base = os.path.basename(entry.name)
                if base != "boot.img":
                    continue

                size = entry.size
                written = 0
                digest = hashlib.sha256()
                with tar.extractfile(entry) as src, open(out_path, "wb") as dst:
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        dst.write(chunk)
                        digest.update(chunk)
                        written += len(chunk)
                return written, digest.hexdigest()

    raise SystemExit(
        "walked the whole AP tar and found no member named boot.img")


def main():
    if len(sys.argv) != 3:
        raise SystemExit(
            "usage: extract_firmware_boot.py <firmware.zip> <out_boot.img>")

    zip_path, out_path = sys.argv[1], sys.argv[2]

    if not os.path.isfile(zip_path):
        raise SystemExit("%s does not exist" % zip_path)

    print("zip   : %s (%.2f GiB)"
          % (zip_path, os.path.getsize(zip_path) / 1024 ** 3))

    with zipfile.ZipFile(zip_path) as zf:
        members = zf.namelist()
        print("members: %d" % len(members))

        ap = find_ap_member(zf)
        ap_size = zf.getinfo(ap).file_size
        print("AP tar : %s (%.2f GiB)" % (ap, ap_size / 1024 ** 3))
        print("reading streamingly; nothing else is written to disk")

        size, sha = stream_member(zf, ap, out_path)

    print()
    print("boot.img written : %s" % out_path)
    print("size             : %d bytes (%.2f MiB)" % (size, size / 1048576))
    print("sha256           : %s" % sha)

    # A boot.img for this device is 83,886,080 bytes. Anything far from that
    # means the wrong file was taken.
    if size < 10 * 1024 * 1024:
        print("WARNING: that is far smaller than a64 boot image; check it")
    elif abs(size - 83886080) < 1024 * 1024:
        print("size matches the a24 boot partition exactly")
    else:
        print("note: not the 83,886,080-byte a24 partition size, but plausible")


if __name__ == "__main__":
    main()
