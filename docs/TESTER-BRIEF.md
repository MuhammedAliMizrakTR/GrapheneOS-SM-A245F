# Tester brief — v1.0.1-kernel

**Release:** https://github.com/MuhammedAliMizrakTR/GrapheneOS-SM-A245F/releases/tag/v1.0.1-kernel

## Read this first

This kernel has **never been run on a device**. It compiles and the images are
well-formed, but nothing more is proven. Expect it not to boot on the first
attempt, and plan for that.

Two things can go wrong and they look identical:

1. The bootloader rejects the unsigned kernel (fixable — flash the vbmeta).
2. The kernel itself is broken (not fixable by flashing).

Your first job is to tell those two apart.

## Before you download anything

```bash
python3 check_device.py
```

(It is attached to the release.) Requires `adb` and USB debugging.

It prints either **compatible** or **DO NOT FLASH** with the reason. If it says
do not flash, stop — do not try anyway. The common failure is a device already
on a newer bootloader binary than this release targets; Samsung's rollback fuse
is one-way and there is no workaround.

**Do not paste your IMEI, serial number or account details in any report.**
Model, build string and `dmesg` output are what is useful.

## What to download

| File | Purpose |
|---|---|
| `a24_vanilla_A245FXXS9DYG1_*.tar.gz` | Kernel, no root |
| `a24_kernelsu_A245FXXS9DYG1_*.tar.gz` | Kernel + KernelSU-Next |
| `a24_*_vbmeta.tar.gz` | Required in almost every case, see below |
| `KernelSU_Next_v3.4.2_33355-release.apk` | Manager for the `kernelsu` image |
| `KernelSU_v3.3.1_32680-release.apk` | Manager for the `kernelsu-up` image |
| `SHA256SUMS.txt` | Verify your downloads |

Start with **vanilla**. If root is the only thing that failed, you will at
least know the kernel boots.

The APK version code must match the kernel. `33355` for the KernelSU-Next
image and `32680` for the upstream one. Installing the other APK will report
the kernel as unsupported — that is expected, not a bug in the build.

## Flashing

Full procedure: `FLASHING.md`, attached to the release.

Short version:
1. Unlocked bootloader. **This wipes data and permanently trips the Knox
   warranty bit** — Samsung Pay, Secure Folder, Samsung Pass stop working for
   good. If that is not acceptable, do not continue.
2. Odin → **AP** → the variant tar. Flash.
3. If it fails to boot, Odin → **AP** → the matching `*_vbmeta.tar`. Flash.
4. Retry.

Keep the stock firmware for your exact model and CSC downloaded and extracted
**before** you start. It is your only guaranteed recovery.

## What to report back

Please include:

- output of `check_device.py`
- which variant, and whether you also flashed the vbmeta
- what the screen showed: boot logo then black? Download Mode? bootloop?
- if it reached Android at all: `adb shell uname -a` and
  `adb shell getprop ro.build.display.id`
- if root is expected: does the KernelSU app open, and does it show a
  version number?

Do not report "it doesn't work" without the above — that cannot be acted on.
