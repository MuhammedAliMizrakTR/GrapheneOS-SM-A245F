# Kernel build — {{TAG}}

> **Untested on hardware unless stated otherwise below.** Read
> [FLASHING.md](FLASHING.md) before you flash anything.

## Which file is for you

| File | For |
|---|---|
| `a24_vanilla_A245FXXS9DYG1_*.tar.gz` | Stock kernel, no root. **Start here.** |
| `a24_kernelsu_A245FXXS9DYG1_*.tar.gz` | KernelSU-Next kernel |
| `a24_kernelsu-up_A245FXXS9DYG1_*.tar.gz` | Upstream KernelSU kernel |
| `KernelSU_Next_v*_*-release.apk` | Manager for the `kernelsu` image — versionCode must match |
| `KernelSU_v*_*-release.apk` | Manager for the `kernelsu-up` image — versionCode must match |
| `boot-<variant>.img` | Bare boot image, same content as the tar |
| `build-info-<variant>.env` | Exact version codes this build produced |
| `kernelsu-version.txt` / `kernelsu-up-version.txt` | Source ref + version code pairing |
| `SHA256SUMS.txt` | Verify every download against this |

Each `*.tar.gz` is an **Odin AP payload** containing a single `boot.img`, which
flashes to the `boot` partition. Nothing else is touched.

## Compatibility

| | |
|---|---|
| Model | `SM-A245F` / `/DS` / `/DSN` only |
| Firmware base | `A245FXXS9DYG1` (Android 15, One UI 7.0) |
| Required bootloader binary | **9** |
| Not for | `SM-A245M`, `SM-A245N`, or any binary ≥ `A` |

Flashing onto the wrong base will not boot.

## Exact version matching

The manager APK must have the **same version code** as the kernel:

```
kernel version code : {{KSU_VERSION_CODE}}
manager APK         : {{KSU_APK_NAME}}
```

If these differ, the app will show the kernel as unsupported. Do not flash a
manager APK from a different release.

## Kernel details

| | |
|---|---|
| Kernel | {{KERNEL_VERSION}} |
| GKI | `android12-5.10`, KMI 9 |
| Toolchain | `clang-r416183b` |
| Source commit | `{{KERNEL_COMMIT}}` |

## Defconfig changes

See `defconfig-report.md` in this release. In short:

- Disabled for build feasibility: `LTO_CLANG*`, `DEBUG_INFO`
- Disabled for boot feasibility: `RKP`, `KDP`, `DEFEX`, `FIVE`, `PROCA`, `GAF`
- Kept: `MODVERSIONS`, `TRIM_UNUSED_KSYMS`, all vendor drivers and DTBs

## Known limitations

- **Not boot-tested.** No claim of working status is made.
- **No SUSFS.** This kernel tree has no SUSFS hooks, so the root variants are
  plain KernelSU / KernelSU-Next without hiding patches.
- Unlocking the bootloader trips the Knox warranty bit permanently.
- Verified boot may reject this image; a patched `vbmeta` is not included.
- No OTA. Every update is a full re-flash.
- `vendor_dlkm` modules are the stock ones; if they refuse to load, the kernel
  and the firmware base do not match.

## Rollback

Flash your stock firmware (BL + AP + CP + CSC) with Odin. Keep the archive.

## Credits

- Kernel source: Samsung OSRC via `oliplusmzr/android_kernel_samsung_a245f`
- Toolchain: AOSP `clang-r416183b`, mirrored by LineageOS
- Root: KernelSU-Next and BakaSU (both GPL-2.0), maintained by `poqdavid`

Not affiliated with Samsung, Google, GrapheneOS or RestlessOS.
