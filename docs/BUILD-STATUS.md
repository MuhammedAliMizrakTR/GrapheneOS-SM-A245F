# Kernel build — status

_Last updated: 2026-11-20_

## Current state: build is green

All three variants compile successfully in CI and produce flashable Odin
tarballs. Verified on run `44754012971` (tag `v1.0.0-vt9`):

| Job | Result |
|---|---|
| `prepare` | success |
| `build (vanilla)` | success |
| `build (kernelsu)` (KernelSU-Next) | success |
| `build (kernelsu-up)` (upstream KernelSU) | success |
| `release` | skipped (opt-in, see below) |

**No GitHub Release has been published.** Publishing is gated behind an
explicit `publish=true` input; a tag push now only produces artifacts.

## What had to be fixed

Five separate defects stood between the first CI run and a green build. Each
one is documented in `docs/BUILD.md` under Troubleshooting.

### 1. A dead path baked into the defconfig

```
CONFIG_UNUSED_KSYMS_WHITELIST="/home/dpi/qb5_8814/.../abi_symbollist.raw"
```

An absolute path inside Samsung's build server. With `TRIM_UNUSED_KSYMS` on,
`gen_autoksyms.sh` demands that file and the build dies at
`GEN include/generated/autoksyms.h`.

Fixed by disabling `TRIM_UNUSED_KSYMS` and deleting the stale path. Safe for
the vendor modules: trimming only *removes* exports nothing appears to use, so
disabling it leaves a superset of the whitelist. `CONFIG_MODVERSIONS`, which is
the actual runtime module-ABI contract, stays on.

### 2. clang was targeting x86_64

`LLVM=1` does not imply an AArch64 triple. `arch/arm64/Makefile` derives
`--target` from `CROSS_COMPILE`; unset, the build dies almost immediately with

```
arch/arm64/include/asm/atomic_lse.h:367:1: error: unknown register name 'x1' in asm
```

### 3. `-Werror` is hardcoded in the Makefile

`# CONFIG_WERROR is not set` is not enough — this tree pins `-Werror` into
`KBUILD_CFLAGS` at the top level, ahead of the config-driven flag. MediaTek's
display and cameraisp code trips `-Wframe-larger-than=` (8 KB and 2.8 KB
frames) and that aborts all of `drivers/`. `KCFLAGS=-Wno-error` is appended
last and wins.

### 4. No mkbootimg anywhere

Not in the kernel tree, not in apt, not on PyPI. Hand-writing the v2 header
was attempted and was wrong: the 1024-byte `extra_cmdline` array pushes the
v1/v2 fields to the end of the 1632-byte v0 struct, and the wrong offsets
produce an image that flashes but reports a null `dtb_size`.

AOSP's `mkbootimg.py` and `unpack_bootimg.py` are now vendored under
`scripts/third_party/mkbootimg/` (Apache-2.0, from LineageOS, `lineage-22.2`).
Verified by round-trip: `unpack_bootimg.py` extracts a kernel, ramdisk and dtb
byte-identical to the inputs.

### 5. The DTB target never existed

`arch/arm64/boot/dts/Makefile` lists exactly one dts dir (`mediatek`), and
`mediatek/Makefile` has exactly one target: `mt6789.dtb`. Nothing is emitted
under `dts/mediatek/a24/`, so the original glob always missed and the fallback
died on a `dtbTool` this fork does not ship.

The `dts/samsung/a24/` trees are `/plugin/` overlays belonging to the separate
`dtbo` partition. They are deliberately **not** built or replaced: a mismatched
dtbo against an otherwise stock vendor image breaks panel and camera bring-up.

## Boot image parameters

| Field | Value | Source |
|---|---|---|
| Header | v2, 1660 bytes | published a24 device tree |
| page size | 4096 | |
| base | `0x3fff8000` | |
| kernel offset | `0x00008000` | |
| ramdisk offset | `0x26f08000` | |
| tags offset | `0x07c88000` | |
| dtb offset | `0x01f00000` | |
| cmdline | `bootopt=64S3,32N2,64N2 loop.max_part=7` | |
| partition size | 83,886,080 B | boot = recovery, not A/B |

## Not yet done — needs hardware

A green build is not a booting kernel. Untested on a device:

- whether the bootloader accepts an unsigned `boot.img` (likely needs
  `vbmeta` handling — see `docs/FLASHING.md`)
- whether the stripped Samsung security features (`RKP`, `KDP`, `DEFEX`,
  `FIVE`, `PROCA`, `GAF`) leave a coherent runtime
- whether the stock `vendor_dlkm` modules load against this kernel

The vendor-symbol analysis in `docs/VENDOR-ANALYSIS.md` is the evidence that
disabling those six features is safe: no vendor module references any of their
symbols, and none of those symbols appear in the 3357-entry MTK KMI list.

## Caveats that still apply

- Base `A245FXXS9DYG1` is **bootloader binary 9**. Current stock is newer
  (`A245FXXSEFZH6`, binary E). Flashing this base is a **downgrade**; a unit
  already fused to a higher binary cannot take it at all. Knox rollback
  protection is one-way.
- The base is `SM-A245F` only. `A245M` (Latin America) and `A245N` (Korea) are
  different firmware lines and must never be cross-flashed.
