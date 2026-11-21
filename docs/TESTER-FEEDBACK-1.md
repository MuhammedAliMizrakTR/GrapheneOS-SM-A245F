# Tester feedback #1 — analysis and fix

Logs supplied: `last_kmsg.log`, `recovery.log`, `logcat.log`.

## Verdict on each log

`recovery.log` — OrangeFox Recovery R12.0 for `a24`, 2026-08-04. Healthy. The
device has a working custom recovery, which is the single most useful safety
net for this project. Nothing here indicates a problem.

`logcat.log` — 12633 lines, zero `FATAL`, zero `beginning of crash`. It opens
with `--------- beginning of kernel` and shows the SM5714 MUIC/charger stack
probing normally. **This is a stock-kernel session, not a boot of our image.**

`last_kmsg.log` — the one that matters.

## Root cause: the boot image held an uncompressed kernel

The MediaTek preloader/LK gzips-in-place. Its boot path calls
`decompress_kernel()` unconditionally, so the payload on the `boot` partition
**must** be gzip. From the log:

```
[   12.851429] boot_linux_fdt:1028: decompress kernel image...
[   12.851435] gzip header is not correct. Error!
[   12.851438] [PROFILE] ::: decompress_kernel takes 0 ms
[   12.851444] panic (caller 0xffff000050f0d670): decompress kernel image fail!!!
[   12.851452] HALT: action = 0, reason = 9
```

Note what this is and is not:

- It is **not** a kernel crash. The kernel never started — no `Linux version`,
  no `Booting Linux`, no driver init from our image.
- It is **not** AVB rejecting the image. The preloader got as far as reading
  the boot partition and trying to decompress it.
- The `wdt_status (0x6), exp_type (0x6)` and `reset_reason = 3` lines at
  1.4 s are the *next* boot reporting the previous one's watchdog reset.

So all the vbmeta work was solving a problem that had not been reached yet.

### Why it happened

`arch/arm64/Makefile` states it plainly:

```
158: KBUILD_IMAGE := $(boot)/Image.gz
162: all: Image.gz
```

The build ran `make Image`, which produces only the uncompressed `Image` and
does **not** produce `Image.gz`. The packaging step then did this:

```sh
IMAGEGZ=".../Image.gz"
[[ -f "${IMAGEGZ}" ]] || IMAGEGZ=".../Image"   # silent fallback
```

so it packaged the raw `Image` under the name `kernel`. `mkbootimg` does not
inspect or compress the payload, so the image looked well-formed and the
corruption only surfaced on the device.

### Fix

1. Build `Image.gz` instead of `Image`.
2. Remove the silent fallback — no `Image.gz` is now a hard error.
3. Verify the payload is really gzip before packaging: `gzip -t` plus a check
   for the `1f 8b` magic bytes. A mislabelled kernel can no longer ship.

## What the tester should expect next

The next image should get much further: the preloader will decompress it and
hand control to the kernel. From there the remaining unknowns are the ones
already documented — whether the device reaches userspace with RKP/KDP/DEFEX/
FIVE/PROCA/GAF stripped, and whether the stock `vendor_dlkm` modules load.

If the next attempt also dies before `Linux version`, capture `last_kmsg` the
same way; the reasoning above shows exactly which line identifies the stage.
