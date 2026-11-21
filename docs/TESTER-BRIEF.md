# Tester brief — v1.0.5-kernel

**Release:** https://github.com/MuhammedAliMizrakTR/GrapheneOS-SM-A245F/releases/tag/v1.0.5-kernel

## Where we are

Two rounds so far. Round 1 failed because the kernel was packaged
uncompressed; the bootloader needs gzip. That is fixed and confirmed — round 2
showed the bootloader decompressing the kernel in 247 ms and jumping to it.

Round 2 stopped one step later: **there is no record of what the kernel does.**
That is not the same as the kernel being dead, and this brief is mostly about
fixing the blind spot.

## The log you sent is the bootloader's, not the kernel's

`last_kmsg-2.log` contains `mblock_pl_boottag_hook` (preloader) and
`boot_linux_fdt` (LK). Both are bootloader functions. The file ends at
`devapc_protection_enable success!` — `devapc` is the bootloader's own
protection unit, configured immediately before it jumps.

So the file covers the bootloader and stops exactly where the kernel starts.
It cannot tell us anything about the kernel, including whether it ran.

`dmesg.log` ends with `scontext=u:r:recovery` — that is OrangeFox's kernel, not
ours. `logcat-2.log` is a 30-second stock session for the same reason.

**Three logs, none of them from our kernel.** That is the thing to fix.

## Your log also contains five different boots

Splitting on the preloader's start marker gives five records:

| Boot | What ended it |
|---|---|
| 1 | secure-boot check, no kernel attempt |
| 2 | **Download Mode — a button was held** |
| 3 | secure-boot check, no kernel attempt |
| 4 | same |
| 5 | **jumped to the kernel** |

Boot 2 is worth knowing about but is not a defect:

```
mtk_detect_keypad:240: key 1 is pressed
AST_DLOAD FROM KEY..
Entering usb mode for do_download (1)..
read 'warning_svb.jpg'(511198) completed.
```

`AST_DLOAD FROM KEY` means the bootloader saw a key held at power-on and went
straight to Download Mode. `warning_svb.jpg` is the warning screen it draws.
Nothing was tested in that boot.

**Power on with a short press and release, and do not touch any button until
the logo appears.**

## What this release changes

The MediaTek UART was being built as a **module**:

```
CONFIG_SERIAL_8250_MT6577=m
```

A module cannot load before userspace exists. Until it loads there is no
console, so every early `printk` is thrown away. If the kernel dies in those
first milliseconds, it dies silently — which matches exactly what we see.

It is now built in (`=y`), and the build fails if it ever goes back to `=m`.

The same mistake was in the thing that records crashes. `/proc/last_kmsg` on
this phone comes from Samsung's `sec_debug_log.c`, and it too was a module:

```
CONFIG_SEC_DEBUG=m
```

A module only loads once Android is up. During bring-up it does not exist, so
nothing the kernel does gets written down — including a crash. **That is why
every `last_kmsg` you have sent has contained only bootloader output: there was
never a kernel side to it.**

It is built in now, along with MediaTek's panic recorder. This is the first
build that can tell us what actually happens after the bootloader jumps.

## What I need from you, in order

### 1. Time the failure

Power on and watch. Which happens?

- **A** — returns to Download Mode after a few seconds
- **B** — reboots itself, repeatedly, on its own
- **C** — stays on the Samsung logo forever
- **D** — shows the orange unlocked warning, then black, then nothing

These are four different faults. Right now I cannot tell which one is
happening, which is why the last two rounds have been slow.

Also: did you flash `vbmeta.img` this time? `unlock_count = 4` in the log means
Odin has been used repeatedly, so I want to confirm what is actually on the
`boot` partition.

### 2. Get a kernel log

Do these while **in OrangeFox recovery**, not in Android:

```bash
adb devices
adb shell 'cat /proc/last_kmsg' > last_kmsg-after-boot.txt
adb shell 'ls -l /sys/fs/pstore/' > pstore-list.txt
adb shell 'cat /sys/fs/pstore/console-ramoops*' > console-ramoops.txt
adb shell 'cat /proc/last_kmsg' | head -50
```

The last one is just to see immediately whether there is anything there.

If `/sys/fs/pstore/` is empty, that is itself the answer: the kernel died
before pstore could write anything.

Then in the recovery menu: **Advanced → Export logs**. That gets the full
recovery session.

Run this on whatever you get and paste the summary:

```bash
python3 analyze_bootlog.py last_kmsg-after-boot.txt
```

### 3. If you can open the phone

A UART cable on the test points is the only way to see the kernel's first
lines. Without it, every round is a guess and we have already spent two.

## What to flash

| File | Purpose |
|---|---|
| `boot-kernelsu.img` | kernel + KernelSU-Next — **this is the only thing to flash** |
| `vbmeta-kernelsu.img` | **not needed** — you already flashed it |

**Flash `boot` only. Do not reflash vbmeta.**

Your last log proves the custom vbmeta is already on the device and already
accepted:

```
SECURE : Signature verification failed (vbmeta)
CUSTOM vbmeta
[AVB] avb_ret = 0
avb_boot_state = 2        (orange)
avb_device_locked = 0
```

`CUSTOM vbmeta` means the bootloader is reading *our* vbmeta, not Samsung's.
`avb_ret = 0` means it accepted it. `Signature verification failed` is the
expected consequence of an unsigned vbmeta and is not a failure. Verified boot
is already off — there is nothing left for a second vbmeta flash to disable.

`boot.img` goes to the AP slot in Odin.
`a24_kernelsu_A245FXXS9DYG1_*.tar.gz` is the same kernel wrapped for AP;
`boot-kernelsu.img` is the raw partition image if you prefer to `dd` it.

> Only flash `vbmeta` if the device falls back to Download Mode **and** the log
> shows `avb_device_locked = 1` or no `CUSTOM vbmeta` line at all. Otherwise it
> changes nothing.

## Before you flash

```bash
python3 check_device.py
```

Attached to the release. It prints **compatible** or **DO NOT FLASH** with a
reason.

> **Fuse warning.** This firmware is binary 9 (`A245FXXS9DYG1`). Samsung's
> rollback fuse is one-way. If your device is already fused higher than 9, this
> will not boot no matter what we change, and there is no way to undo a flash
> that trips the fuse. `check_device.py` checks this. Do not skip it.

> **This is not GrapheneOS.** It is a custom kernel; the ROM is a separate,
> later build.

## Sending a report

Useful:
- which of A/B/C/D you saw, and roughly how long it took
- model and build string (`A245FXXU9EYK1`, etc.)
- the output of `analyze_bootlog.py`
- any log from **after** our kernel was flashed

Not useful:
- `logcat` from a session that booted stock
- `dmesg` from recovery
- screenshots of the logo

**Do not include your IMEI, serial number, or account details.** Model, build
string and boot logs are what I need.
