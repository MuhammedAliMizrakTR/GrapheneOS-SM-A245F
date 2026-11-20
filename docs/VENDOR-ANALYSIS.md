# Vendor analysis — A245FXXS9DYG1

What was inspected, what was proven, and what is still unverified.

**Method note:** the firmware archive is 7.48 GB and the Drive connector used
here caps uploads/downloads at 100 MB, so `AP_*.tar.md5` → `super.img` could
not be extracted and inspected directly. Everything below comes from the
matching Samsung OSRC kernel drop (`A245FXXS9DYG1`), which is the same source
Samsung used to build the shipped modules. Cells marked **unverified** need a
local extraction of the firmware.

---

## 1. Vendor module inventory

The kernel build pulls in external modules via `CONFIG_EXT_MODULES`:

```
connectivity/common          connectivity/conninfra     connectivity/connfem
connectivity/gps/gps_stp     connectivity/gps/data_link/plat/v010
connectivity/gps/data_link/plat/v030
connectivity/gps/data_link/plat/v050
connectivity/gps/gps_pwr     connectivity/gps/gps_scp
gpu                          connectivity/fmradio
```

Three trees:

| Tree | Contents |
|---|---|
| `vendor/mediatek/kernel_modules/connectivity/` | 8 subdirs — BT, WLAN, conninfra, connfem, GPS, FM radio |
| `vendor/mediatek/kernel_modules/gpu/` | Mali Valhall `mali-r25p0` |
| `vendor/mediatek/kernel_modules/met_drv_v3/` | MTK metering/debug driver |

These compile to the `.ko` files that live on `vendor_dlkm` in the stock
firmware. **They are not rebuilt by this project**, and they are not shipped in
`boot.img` — the stock ones on `vendor_dlkm` are used.

## 2. Symbol-surface check (the important one)

The concern with disabling `RKP`/`KDP`/`DEFEX`/`FIVE`/`PROCA`/`GAF` is that a
vendor module might import a symbol provided by one of those features, which
would make the module fail to load.

**Result: no vendor module references any of them.**

```
rkp_      referenced in 0 files
kdp_      referenced in 0 files
defex     referenced in 0 files
five_     referenced in 0 files
proca_    referenced in 0 files
gaf_      referenced in 0 files
```

Confirmed twice: a text search for the symbols, and a search for
`CONFIG_RKP` / `CONFIG_KDP` under `vendor/` (no hits).

Additionally, the MediaTek KMI symbol list (`android/abi_gki_aarch64_mtk`,
3357 symbols) contains no RKP/KDP/DEFEX/FIVE/PROCA/GAF symbols. The only
security-adjacent entries are two UFS perf tracepoints, which are unrelated.

**Conclusion:** disabling these six features does not remove anything the
vendor modules need. This is the strongest evidence available that the
standard (non-hardened) build is the right default.

## 3. Kconfig gating

`RKP` and `KDP` are declared in `arch/arm64/Kconfig` with `default n` and a
`depends on UH`. They are normal tristate/bool options, not forced-on
infrastructure — so turning them off produces a coherent configuration rather
than a build break.

`SECURITY_DEFEX`, `FIVE` and `PROCA` live under `security/samsung/` and compile
out cleanly.

## 4. What stays enabled, deliberately

| Config | Why it must stay |
|---|---|
| `MODVERSIONS` | vendor modules carry version magic; removing this breaks loading |
| `EXT_MODULES` | the vendor module build list |
| all `MTK_*` / `COMMON_CLK_MT6789_*` | hardware drivers |
| DTB set under `arch/arm64/boot/dts/mediatek/a24/` | device tree |

## 5. A build-breaking path baked into the defconfig

The shipped `a24_defconfig` contains one line that cannot work anywhere except
Samsung's own build server:

```
CONFIG_UNUSED_KSYMS_WHITELIST="/home/dpi/qb5_8814/workspace/P4_1716/android/out/target/product/a24/obj/KERNEL_OBJ/kernel-5.10/abi_symbollist.raw"
```

It is an absolute path to a throw-away file inside a specific engineer's
workspace. Because the option is active, the kernel build runs
`scripts/gen_autoksyms.sh`, which refuses to continue without that file:

```
  GEN     include/generated/autoksyms.h
ERROR: '/home/dpi/qb5_8814/.../abi_symbollist.raw' whitelist file not found
make[1]: *** [Makefile:1298: include/generated/autoksyms.h] Error 1
```

The fix is to drop `CONFIG_TRIM_UNUSED_KSYMS` entirely and delete the stale
path. This is safe for the vendor modules: `TRIM_UNUSED_KSYMS` only *removes*
exports that nothing in the build appears to use, so turning it off leaves a
superset of the whitelist in place — every symbol a vendor module could ask for
is still exported. The runtime module-ABI contract is `CONFIG_MODVERSIONS`,
which stays on.

## 6. SUSFS

**Not present.** A search for `susfs` across `kernel-5.10` returns zero files,
and there is no `CONFIG_KSU_SUSFS` in the tree.

This is why the BakaSU variant was dropped. BakaSU's distinguishing feature
over plain KernelSU is SUSFS integration; without SUSFS hooks in the kernel it
would be a plain KernelSU plus an extra dependency. The build therefore offers:

- `kernelsu` — KernelSU-Next (poqdavid fork, ref `dev`)
- `kernelsu-up` — upstream KernelSU (tiann, ref `main`)

The build script still enables `CONFIG_KSU_SUSFS` **automatically** if a future
kernel tree ships the hooks, so nothing is lost when the tree changes.

## 7. Still unverified — needs local firmware extraction

These cannot be answered without unpacking `super.img`:

| Item | Why it matters |
|---|---|
| `ro.board.api_level` / `ro.vendor.api_level` | decides which GSI/system-image version is realistic |
| actual `.ko` list on `vendor_dlkm` | confirms the module set matches the source tree |
| `vendor` partition contents / VNDK refs | GSI compatibility |
| `vbmeta` flags and AVB chain | whether a patched `vbmeta` is required to boot an unsigned image |
| `super` logical partition sizes | how much room a replacement system image has |
| bootloader-visible `KG` / `KnoxGuard` state | whether unlocking is even possible on retail units |

**To extract locally** (needs ~40 GB free and the full 7.48 GB archive):

```bash
unzip SAMFW.COM_SM-A245F_TUR_A245FXXS9DYG1_fac.zip
# AP is a tar.md5 holding super.img.lz4
tar -xf AP_A245FXXS9DYG1_*.tar.md5
lz4 -d super.img.lz4 super.img
# logical partitions live inside super
lpunpack --slot=0 super.img super_out/
# then inspect super_out/vendor and super_out/vendor_dlkm
```

That extraction is the next concrete task, and it is the one that would turn
the last column of the table above from **unverified** into fact.

## 8. Risk summary

| Risk | Severity | Status |
|---|---|---|
| Vendor modules reject the kernel | high | **reduced** — no symbol dependency on disabled features |
| Bootloader rejects unsigned `boot.img` | high | **unverified** — likely needs patched `vbmeta` |
| DTB mismatch | medium | low — DTB source is in-tree for `a24` |
| Rollback impossible if base is wrong | high | **known** — binary 9 required |
| VoLTE/IMS breaks | high if a GSI is attempted | not in scope for a kernel-only build |
