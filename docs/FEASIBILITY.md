# Feasibility notes — SM-A245F

Facts here are sourced. Anything marked **unknown** has not been measured on
hardware and must not be assumed.

---

## 1. The device is MediaTek, not Qualcomm

The Galaxy A24 4G is `MT6789` / Helio G99 with a Mali-G57 MC2 GPU. This is the
single most important fact in the project, because almost all public
MediaTek-Samsung bring-up knowledge comes from a handful of specific devices.

## 2. "Android 15, binary 9, DYG1" decoded

`A245FXXS9DYG1` means:

| Field | Value |
|---|---|
| Model | `A245F` |
| Region | `XX` — open/global |
| Update type | `S` — security-focused update |
| **Bootloader binary** | **`9`** |
| One UI index | `D` — One UI 7 |
| Year | `Y` — 2025 |
| Month | `G` — July |
| Iteration | `1` |

So "binary 9" is the **bootloader revision**, not Android 9. The build is
Android 15 / One UI 7.0, security patch 2025-08-01.

### The three numbers, and why they get confused

| Number | In `A245FXXS9DYG1` | What it is |
|---|---|---|
| Android OS version | — (not encoded) | Android **15**, One UI **7.0** |
| Bootloader binary | `9` | rollback fuse counter, `1`–`E` |
| One UI index letter | `D` | generation marker, **not** a binary |

Three traps, all of which are easy to fall into:

1. **`9` is not "Android 9".** It is the fifth character from the end. The
   device is on Android 15. Android 9 would be a different, far older kernel.
2. **`D` is not a binary and not a downgrade marker.** `D` = One UI 7. `E` =
   One UI 8. They are independent of the binary digit. A firmware `…EZE1…`
   can be binary `C`; a firmware `…DYG1…` can be binary `9`.
3. **`S` in `XXS9`** is the update type (security), not a serial.

A build string alone is therefore not enough. Read the fifth character from
the end for the binary, and the letters after it for the One UI generation.

> The same field is called "binary", "bit" or "SW REV" depending on who is
> writing. It drives the rollback-prevention fuses, which is why it matters
> more than any other part of the string.

## 3. Rollback prevention is irreversible and constrains everything

Samsung documents rollback-prevention fuses that encode the minimum acceptable
bootloader version. Once a higher binary has booted, lower binaries are
refused and the state cannot be reverted.

Practical consequences:

- A tester already on Android 16 firmware (binary `C`/`E`) **cannot** go back
  to a binary-9 base. Their device will refuse it.
- Therefore this project must either target the tester's *own* base, or the
  tester must already be on binary 9.
- This is a hardware fuse, not a software lock. No tool changes it.

## 4. Partition layout

From the public TWRP device tree for `a24`:

| Property | Value |
|---|---|
| A/B | **No** — A-only, no slots |
| Dynamic partitions | **Yes** — inside `super` |
| `super` size | `11744051200` bytes |
| Logical partitions | `system`, `vendor`, `product`, `odm`, `vendor_dlkm`, `system_ext` |
| `system` / `vendor` filesystem | **EROFS** |
| `userdata` | F2FS |

Consequences:

- No seamless A/B OTA. Updates are full re-flashes.
- Any custom system image must be installed by rebuilding `super`, not by
  writing a single partition.
- `vendor_dlkm` holds the vendor modules — this is why the kernel and the
  firmware base are tightly coupled.

## 5. Kernel / vendor coupling

| Item | Value |
|---|---|
| Kernel | 5.10.226 |
| GKI branch | `android12-5.10` |
| KMI generation | 9 |
| Vendor base (reported for this firmware) | Android 12 generation |

The kernel is built as a GKI-style kernel with an extensive set of external
MediaTek modules (`CONFIG_EXT_MODULES`): connectivity, conninfra, connfem, GPS,
GPU (Mali), and fmradio. These modules live on `vendor_dlkm` in the stock
firmware and are compiled from `vendor/mediatek/kernel_modules`.

**This means the kernel ABI must match the shipped modules.** A kernel built
from a different firmware base will not load the vendor modules correctly.

## 6. Samsung security features that block unsigned kernels

`a24_defconfig` enables, and this project must disable to boot a local build:

`RKP`, `KDP`, `KDP_CRED`, `KDP_NS`, `SECURITY_DEFEX`, `SECURITY_DEFEX_USER`,
`FIVE`, `FIVE_GKI_10`, `PROCA`, `PROCA_S_OS`, `GAF`.

This is not a preference. These features verify Samsung signatures on the
kernel and on executed binaries. An unsigned kernel is rejected.

**Unknown / not measured:**

- Whether disabling all of these is sufficient on *this specific* device, or
  whether the bootloader additionally enforces an AVB/knox verdict that needs
  a patched `vbmeta`.
- Whether the Knox warranty bit trips on first boot of an unsigned kernel.
  Assume **yes**.
- Whether KG (KnoxGuard) is active on retail units.

## 7. Why an official GrapheneOS port is not possible

GrapheneOS states that it does not support being used as a Generic System
Image, and that its userspace requires kernel functionality that a generic
vendor kernel does not provide. Its hardware requirements include Linux
6.12/6.18 GKI, ARM MTE, PAC/BTI, StrongBox with attestation, A/B firmware
updates with rollback, and re-lockable verified boot.

The A24 provides none of the following:

- 6.12/6.18 GKI (it is 5.10)
- ARM MTE (Cortex-A76/A55, ARMv8.2)
- A/B slots
- Re-lockable verified boot with a user key

So the realistic target is **RestlessOS** — an unofficial, unaffiliated
GrapheneOS *fork packaged as a GSI* — and even that is a system image running
on this vendor stack, not GrapheneOS.

## 8. System image target (when this project gets there)

| Target | Verdict |
|---|---|
| Android 15/16 GSI on Android 15 vendor | Plausible |
| Android 17 GSI on an Android 12-generation vendor | **Unproven**; there is a documented bootloop on sibling Helio G99/G85 hardware |
| Upstream GrapheneOS | Not possible |

The realistic order is: get the **kernel** booting and stable first (this
repository), then attempt a GSI on top of it.

## 9. Open questions

1. Does a locally built kernel boot at all with RKP/KDP/DEFEX/FIVE/PROCA off?
2. Do the stock `vendor_dlkm` modules load against this kernel, unchanged?
3. Does the bootloader require a patched `vbmeta` for an unsigned `boot.img`?
4. Does the device ship with KG active in the target market (Turkey)?
5. Is a binary-9 base still reachable for the testers, or are they all on
   Android 16 firmware already?

Question 5 must be answered **before** anyone downloads a release.
