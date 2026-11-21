# Boot diagnosis — rounds 1 and 2

Two rounds of tester logs have been analysed. This is what they do and do not
prove, kept current so the next round does not repeat old work.

## Round 1 — solved

**Symptom:** bootloader halts, device restarts.

```
boot_linux_fdt:1028: decompress kernel image...
gzip header is not correct. Error!
panic (caller 0xffff0000...): decompress kernel image fail!!!
HALT: action = 0, reason = 9
```

**Cause:** the bootloader decompresses the kernel unconditionally, and the
packaging step had produced an uncompressed `Image`. `make Image` does not
build `Image.gz` — `arch/arm64/Makefile` sets `KBUILD_IMAGE := $(boot)/Image.gz`
and `all: Image.gz` — but the script had a silent fallback to the raw `Image`.
`mkbootimg` does not inspect the payload, so every local check passed.

**Fixed in** `v1.0.2-kernel`. Confirmed in round 2: zero occurrences of
`gzip header is not correct`, and decompression now takes 247 ms.

## Round 2 — the bootloader succeeds, then the record stops

```
boot_linux_fdt:817:        kernel_sz=0x011e235b        (17.9 MiB)
boot_linux_fdt:1028:       decompress kernel image... (247 ms)
                           dtbo_size=101933
                           after overlay, fdt size(289870)
                           DT overlay ok, fdt size(4194304)
boot_linux_fdt:1132:       booting linux @ 0x401e8000, ramdisk @ 0x66f00000 (39796280)
boot_linux_fdt:1133:       lk boot mode = 2
boot_linux_fdt:1135:       lk finished --> jump to linux kernel 64Bit
boot_linux_fdt:1141:       Restore lock state successfully
[PROFILE] ::: gz_unmap2() takes 60 ms
                           devapc_protection_enable success!        <- last line
```

Nothing after that. No `Linux version`, no `Booting Linux`, and **no panic and
no OOPS anywhere in the file**. A kernel that crashes still prints something on
the way down, so "silent" and "dead" are not the same thing.

### The log is the bootloader's, not the kernel's

Every line in `last_kmsg-2.log` comes from the preloader (`mblock_pl_*`) or
from LK (`boot_linux_fdt`, `[BLDP]`, `[SEC]`, `[GZ_UNMAP2]`, `devapc`).
`devapc` is the bootloader's own protection unit, configured immediately before
the jump.

`/proc/last_kmsg` on this device is produced by
`drivers/samsung/debug/sec_debug_log.c`, and that driver was shipped as a
**module**:

```
CONFIG_SEC_DEBUG=m
```

A module only loads once userspace exists. During bring-up it is not there, so
nothing on the kernel side is ever written into the log region. The file
therefore contains the bootloader's log and stops where the kernel starts —
which is exactly what it does.

**This means round 2 cannot say whether the kernel ran.** It is not evidence of
a dead kernel, and it is not evidence of a live one.

Fixed in `v1.0.5-kernel`: `SEC_DEBUG`, `SEC_DEBUG_AUTO_COMMENT`,
`SEC_DEBUG_HISTORY_LOG`, `MTK_AEE_IPANIC` are now `=y`, and the build fails if
`SEC_DEBUG` returns to `=m`.

### The file contains five boots, not one

Splitting on `mblock_pl_boottag_hook init done`:

| Boot | Ending |
|---|---|
| 1 | secure-boot check, no kernel attempt |
| 2 | Download Mode |
| 3 | secure-boot check, no kernel attempt |
| 4 | secure-boot check, no kernel attempt |
| 5 | jumped to the kernel |

Boot 2 was not a test at all:

```
mtk_detect_keypad:240: key 1 is pressed
AST_DLOAD FROM KEY..
Entering usb mode for do_download (1)..
read 'warning_svb.jpg'(511198) completed.
```

A key was held at power-on and the bootloader went to Download Mode.

## What is ruled out

Checked against the logs, so these should not be investigated again:

| Candidate | Verdict |
|---|---|
| AVB rejecting the unsigned kernel | **No.** `avb_boot_state = 2` (orange), `avb_device_locked = 0`, `unlock_count = 4`, and LK jumps anyway. |
| Decompression | **No.** 247 ms, no error. |
| DT overlay | **No.** `DT overlay ok, fdt size(4194304)`. The bootloader builds the FDT itself from `lk_main_dtb` + the `dtbo` partition; the DTB inside `boot.img` is not what gets used. |
| Boot image header | **No.** LK reports `booting linux @ 0x401e8000` and `ramdisk @ 0x66f00000`, matching the header's base + offsets exactly. |
| MMU / page size | **No.** `ARM64_VA_BITS=39`, 4 KiB pages, `PA_BITS=48` — the platform defaults. |
| Rollback fuse | **No.** `img ver check, (group, key ver, cnt ver, otp)=(1, 9, 9, 9)...ok` |

## What is still unknown

**Whether the kernel executes at all.**

The two remaining explanations cannot be told apart from the logs:

1. The kernel runs but has no console — `bootargs` is `console=tty0`, and the
   framebuffer is not up yet when the first `printk`s happen.
2. The kernel dies before `start_kernel()` reaches any console.

The UART was also a module (`SERIAL_8250_MT6577=m`), now fixed in
`v1.0.4-kernel`, but without a cable attached a working console still shows
nothing to the tester.

`v1.0.5-kernel` is the first build that can answer the question on hardware,
because `/proc/last_kmsg` will now exist and contain whatever the kernel wrote
before it stopped.

## Observations not used as evidence

Recorded so they are not re-derived, but none of them diagnosed anything:

- `[BLDP] Error. No Signer Info data`, `kernel_build_id = 2147483647P`,
  `kernel_build_type = 0xff` — expected for an unsigned kernel, and BLDP
  continues past them.
- `secure_boot = 0x1`, `kernel_rp = 0x9` — the device is fused at binary 9 and
  secure boot is on. This is why `check_device.py` gates on the binary number.
- `avb_slot_verify.c:894: ERROR: recovery: Public key used to sign data
  rejected` — refers to the **recovery** partition (OrangeFox), not `boot`.
- `[SEC] Partition [seccfg] write fail ... ret:0x100008` — OrangeFox's
  protection, harmless.
- `[ufshcd_authensss_wcnt_read_rsp_check]: RPMB Fail in Mac Check!` — appears
  on stock boots too; `rpmb_state = 0x0` in BLDP is clean.
- `reboot_reason = 0x7` — the meaning of this code is not defined anywhere in
  the source tree, so nothing is concluded from it.

## Next round

1. Flash `v1.0.5-kernel`, boot, and go straight to OrangeFox.
2. `adb shell 'cat /proc/last_kmsg'` — this is the file that was always empty
   before and is now the whole answer.
3. `python3 analyze_bootlog.py that-file.txt`
4. If the kernel is in there, the last line it printed is where it died.
5. If the file is still pure bootloader output, the kernel died before
   `sec_debug_log` could initialise, and a UART cable is the only remaining
   route.
