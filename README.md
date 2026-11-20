# Kernel builds for the Samsung Galaxy A24 (SM-A245F)

Reproducible Linux kernel builds for `SM-A245F`, pinned to the
`A245FXXS9DYG1` firmware base.

> **This repository is not a ROM.** It ships a kernel only. It is not
> affiliated with, endorsed by or supported by Samsung, Google, GrapheneOS
> or RestlessOS. See [docs/FEASIBILITY.md](docs/FEASIBILITY.md) for what is
> actually achievable on this hardware and why an official GrapheneOS port
> is not one of those things.

---

## What this is

| | |
|---|---|
| Device | Samsung Galaxy A24 4G — `SM-A245F` / `SM-A245F/DS` / `SM-A245F/DSN` |
| SoC | MediaTek Helio G99 (`MT6789`), Mali-G57 MC2 |
| Kernel | Linux **5.10.226**, GKI `android12-5.10`, KMI generation **9** |
| Source | Samsung OSRC drop for `A245FXXS9DYG1` |
| Toolchain | AOSP `clang-r416183b` (the compiler named in the stock defconfig) |
| Firmware base | `A245FXXS9DYG1` — Android 15 / One UI 7.0, bootloader binary **9** |

### Variants

| Variant | Root | Manager app | Notes |
|---|---|---|---|
| `vanilla` | none | — | Closest to stock. Start here when debugging. |
| `kernelsu` | KernelSU-Next | `KernelSU_Next_*.apk` | poqdavid fork, ref `dev`. |
| `kernelsu-up` | KernelSU (upstream) | `KernelSU_v*.apk` | tiann, ref `main`. |

**BakaSU is not built.** This kernel tree has no SUSFS support — a search for
`susfs` across `kernel-5.10` returns zero files. BakaSU's advantage over plain
KernelSU is SUSFS, so without the hooks it is just KernelSU with an extra
dependency. See [docs/VENDOR-ANALYSIS.md](docs/VENDOR-ANALYSIS.md#5-susfs).

**Never mix a manager APK from a different version code than the kernel you
flashed.** The app talks to the kernel over a versioned ioctl; a mismatch
shows up as "kernel version unsupported" and root silently does not work.

---

## Not supported

Do not flash these builds on:

- `SM-A245M` (Latin America), `SM-A245N` (South Korea) — different firmware branches.
- Any `SM-A245F` on **bootloader binary higher than 9 without re-basing** the build.
  The kernel is built against the vendor modules of `A245FXXS9DYG1`. A newer
  firmware has a different vendor partition and a different module ABI.
- Any device you cannot afford to lose. Read [docs/FLASHING.md](docs/FLASHING.md) first.

---

## Repository layout

```
config.env                        single source of truth (device, base, toolchain)
scripts/gen_config.py             kernel .config without flex/bison
scripts/apply_defconfig_overrides.py   strips LTO/debug info, disables RKP/KDP/DEFEX/FIVE/PROCA
scripts/build-kernel.sh           one-shot build: source -> boot.img -> Odin tar.gz
scripts/third_party/mkbootimg/    vendored AOSP mkbootimg (Apache-2.0)
.github/workflows/build-kernel.yml    CI: three variants -> artifacts (release is opt-in)
docs/FEASIBILITY.md               what is and is not possible on this device
docs/VENDOR-ANALYSIS.md           vendor module/symbol analysis for this base
docs/BUILD.md                     build instructions and troubleshooting
docs/FLASHING.md                  flash + rollback procedure
docs/RELEASE_NOTES.md             release template
```

---

## Quick start (local)

```bash
git clone https://github.com/<you>/GrapheneOS-SM-A245F.git
cd GrapheneOS-SM-A245F
sudo apt install bc bison flex libssl-dev libelf-dev lz4 zstd cpio kmod
pip install kconfiglib
./scripts/build-kernel.sh --variant vanilla --jobs "$(nproc)"
```

Output lands in `dist/a24_vanilla_A245FXXS9DYG1_<timestamp>/`.

If `flex` or `bison` are unavailable, the build still reaches the
configuration stage because `gen_config.py` replaces `make defconfig`, but
the final `make` will stop at `syncconfig`. See
[docs/BUILD.md](docs/BUILD.md#no-flexbison).

## Quick start (CI)

Actions → **Build kernel** → *Run workflow*:

- `variant`: `all` builds vanilla, kernelsu and kernelsu-up.
- `publish`: create a GitHub Release with the artifacts.
- `hardened`: keeps Samsung's security features on. Builds, but will almost
  certainly not boot — it exists for A/B comparison, not for flashing.

---

## Why the defconfig is modified

Samsung's `a24_defconfig` is written for **signed production firmware**. Two
groups of settings are changed:

1. **Build feasibility** — `LTO_CLANG*` and `DEBUG_INFO` are off. Full LTO of
   this tree needs more memory and disk than most build hosts have.
2. **Boot feasibility** — `RKP`, `KDP`, `DEFEX`, `FIVE`, `PROCA`, `GAF` are off.
   These verify that the kernel is Samsung-signed and will reject an unsigned
   image.

Everything else — vendor module ABI, DTB selection, driver set — is left
exactly as shipped, which is what keeps the kernel loadable by the stock
vendor partition. `MODVERSIONS` and `TRIM_UNUSED_KSYMS` are deliberately kept.

Every build writes a `defconfig-report.md` recording exactly what was changed
and why. It is included in the release.

---

## Repository vs. kernel licensing

- Everything **in this repository** (scripts, workflow, documentation) is
  licensed under the **Apache License 2.0** — see [LICENSE](LICENSE).
- The **kernel source** is `GPL-2.0 WITH Linux-syscall-note`. The full texts
  are vendored in [licenses/](licenses/). Kernel source is not mirrored here;
  it is fetched at build time from the link in `config.env`, as the GPL
  requires for the binaries we distribute.

---

## Status

- [x] Kernel source identified and verified (`a24_defconfig`, `MT6789`, 5.10.226)
- [x] Toolchain pinned (`clang-r416183b`)
- [x] Build scripts + CI written
- [x] Vendor symbol-surface analysis (no module depends on the disabled features)
- [ ] **First successful CI build — not yet run**
- [ ] Boot tested on hardware — **not done**
- [ ] Vendor module compatibility verified on device — **not done**

Nothing in this repository has been validated on a physical device yet.
Treat every artifact as untested.
