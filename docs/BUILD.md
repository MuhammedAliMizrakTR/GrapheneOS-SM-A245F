# Building the kernel

## Host requirements

| Requirement | Why |
|---|---|
| Linux x86_64 | the prebuilt toolchain is `linux-x86` |
| ~20 GB free disk | source tree ~1.6 GB, toolchain ~1.7 GB, build output several GB |
| ~8 GB RAM (16 GB comfortable) | no LTO, so this is manageable |
| `bc bison flex libssl-dev libelf-dev lz4 zstd cpio kmod git python3` | standard kernel build dependencies |
| `pip install kconfiglib` | lets us configure without flex/bison |

```bash
sudo apt install -y bc bison flex libssl-dev libelf-dev lz4 zstd cpio kmod git python3-pip
pip install kconfiglib
```

## Build

```bash
./scripts/build-kernel.sh --variant vanilla --jobs "$(nproc)"
```

Variants: `vanilla`, `kernelsu`, `bakasu`.

Add `--harden` to keep Samsung's security features enabled. It builds, but it
will almost certainly not boot; it exists to compare against the standard build.

Output:

```
dist/a24_<variant>_<base>_<timestamp>/
├── boot.img
├── a24_<variant>_<base>_<timestamp>.tar.gz   # Odin AP payload
├── config-<variant>                          # exact .config used
├── defconfig-report.md                       # every override, with reasons
├── build.log
└── build-info.env
```

## What the build does

1. Clones the Samsung OSRC kernel drop for `A245FXXS9DYG1` (branch name is the
   firmware build number).
2. Clones the AOSP `clang-r416183b` toolchain — the exact compiler named in
   the stock defconfig.
3. For root variants, clones KernelSU-Next or BakaSU into the tree.
4. Rewrites `a24_defconfig`:
   - **build feasibility**: `LTO_CLANG*`, `DEBUG_INFO` off
   - **boot feasibility**: `RKP`, `KDP`, `DEFEX`, `FIVE`, `PROCA`, `GAF` off
   - everything else untouched, including `MODVERSIONS`/`TRIM_UNUSED_KSYMS`
5. Configures via `gen_config.py` (kconfiglib) instead of `make defconfig`.
6. Builds `Image` and `dtbs`.
7. Packs a header-v2 boot image with the a24 offsets and appends the DTB.

## Troubleshooting

### <a name="no-flexbison"></a>`flex: not found` / `bison: not found`

Two different failure sites:

- **Configure stage** — avoided. `gen_config.py` writes `.config`,
  `auto.conf`, `tristate.conf` and `autoconf.h` directly, so `make defconfig`
  is never called.
- **`make` stage** — `syncconfig` still wants the generated lexer/parser when
  `auto.conf.cmd` is missing. `gen_config.py` does not create that stamp file,
  so on a host without flex/bison `make` will stop there.

**Fix:** install flex and bison. They are two small packages and there is no
clean workaround for the `make` stage.

### `Sorry, this assembler is not supported.`

`scripts/Kconfig.include` calls `scripts/as-version.sh` using `$(srctree)`.
Under kconfiglib, `srctree` comes from the environment. `gen_config.py` sets it
to `.` and sets `CLANG_FLAGS=-fintegrated-as`. If you call kconfiglib yourself,
you must do the same.

### `LTO` / linker OOM

Already handled — LTO is disabled. If you re-enable it, expect the link step to
need 16 GB+ of RAM.

### `MODVERSIONS` errors after changing the defconfig

Do not disable `MODVERSIONS` or `TRIM_UNUSED_KSYMS`. The vendor modules are
built with version magic; removing these breaks loading.

### Kernel builds but the device does not boot

That is the expected first outcome. Capture `dmesg` via UART if available, or
compare against a stock `boot.img` and check:

- DTB actually matches `mt6789`/`a24`
- `bootopt=64S3,32N2,64N2` is present in the cmdline
- the boot image header is v2 with the a24 offsets
- `vbmeta` has not rejected the image (see `docs/FLASHING.md`)

## Reproducibility notes

- Toolchain is pinned by repository, not by commit. For a fully reproducible
  build, pin the commit hash in `config.env`.
- Kernel source is pinned by branch name, which Samsung reuses per firmware
  build. Record the resulting commit hash in the release notes.
- `CONFIG_LOCALVERSION_AUTO=y` in the stock defconfig appends the git hash,
  so two builds from different commits produce different `uname -r`. That is
  intentional and useful for support.
