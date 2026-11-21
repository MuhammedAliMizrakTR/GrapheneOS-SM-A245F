# Tester feedback #2 — analysis

Logs supplied: `last_kmsg-2.log`, `dmesg.log`, `logcat-2.log`.

## Headline

**The Image.gz fix worked.** The preloader no longer aborts:

```
boot_linux_fdt:1028: decompress kernel image...
[PROFILE] ::: decompress_kernel takes 247 ms
boot_linux_fdt:1132: booting linux @ 0x401e8000, ramdisk @ 0x66f00000 (39796280)
boot_linux_fdt:1135: lk finished --> jump to linux kernel 64Bit
devapc_protection_enable success!
```

`gzip header is not correct` appears **zero** times. The kernel is decompressed
and the bootloader hands over. That is real progress and it rules out the
previous failure mode.

## The log covers four separate boots

Splitting `last_kmsg-2.log` on the `mblock_pl_boottag_hook init done` marker
gives four boot records with different endings. They are not the same event and
must not be read as one:

| Boot | Ends because |
|---|---|
| 1 | Secure boot / rollback check, no kernel attempt |
| 2 | **Download Mode — a key was held** |
| 3 | Same as boot 1 |
| 4 | **Jumped to the kernel**, then silence |

### Boot 2 is a user action, not a bug

```
[ 1.915518] mtk_detect_keypad:240: key 1 is pressed
[ 1.966981] AST_DLOAD FROM KEY..
[ 1.974182] : Entering usb mode for do_download (1)..
[ 1.978373] read 'warning_svb.jpg'(511198) completed.
```

`AST_DLOAD FROM KEY` means the bootloader entered Download Mode because a key
combination was held during power-on. `warning_svb.jpg` is the Download Mode
warning screen. Nothing was tested in that boot.

**Action:** power on with a short press and release, and keep hands off the
buttons until the boot logo appears.

### Boot 4: the kernel is entered but says nothing

```
[BLDP] avb_boot_state = 2      (orange — unlocked)
[BLDP] avb_device_locked = 0
[BLDP] unlock_count = 4
[BLDP] kg_state = 0x1
```

Verified boot did **not** reject anything. The device is unlocked, the state is
orange, and `lk finished --> jump to linux kernel 64Bit` happens.

What is missing is every kernel-side line: no `Booting Linux`, no
`Linux version`, no `Kernel command line`, no `Memory:`. And there is **no
panic and no OOPS** anywhere in the file — a crashing kernel would still print
something on the way down. Zero output plus no panic means the kernel is
either executing with nowhere to write, or dying before the first `printk`
reaches a console.

`bootargs` in the device tree explain the amplifier:

```
chosen {
    bootargs = "console=tty0 root=/dev/ram
                loglevel=8 ...
```

`console=tty0` means the only console is the framebuffer, which the kernel
brings up *later*. Until then its output goes nowhere. The stock kernel is
also seeded by the bootloader through the `boot_args` structure
(`mboot_params`, `log_store`), which this build does not consume — so its
early output is captured where ours is not.

**This means the boot may genuinely be failing, or it may be running blind. The
logs cannot distinguish those.** Before changing kernel code, get a console.

## What to send next

### 1. Which image, and how

State the variant and whether `vbmeta.img` was flashed. `unlock_count = 4`
suggests Odin has been used several times, so it is worth confirming what is
actually on the `boot` partition.

### 2. How long does it stay on screen?

Power on, then time it:
- returns to Download Mode after a few seconds
- reboots itself in a loop
- sits on the Samsung logo indefinitely
- shows the orange/unlocked warning and then nothing

These are four different failures.

### 3. OrangeFox logs, not `logcat`

`logcat-2.log` opens with `--------- beginning of kernel` and runs to 30 s with
the stock kernel's driver stack. `dmesg.log` ends with
`scontext=u:r:recovery` — that is OrangeFox, not our kernel. Neither log
contains anything about this boot.

Once OrangeFox is available, use it:
- **Recovery → Advanced → Export logs** — gets the full recovery session
- `adb shell dmesg` **while in recovery** gives the live kernel log

### 4. Enable UART if possible

A UART cable on the exposed test points is the only way to see early kernel
output on this platform. Without it every iteration is a guess.

## What was checked in the build

To rule out packaging as a cause:

```
boot.img header      v2, 1660 bytes, page 4096
base                 0x3fff8000
kernel load addr     0x40000000
ramdisk load addr    0x66f00000
tags addr            0x47c80000
dtb load addr        0x41ef8000
cmdline              bootopt=64S3,32N2,64N2 loop.max_part=7
kernel payload       gzip, verified 1f 8b
dtb                  mt6789.dtb, 293098 bytes after overlay
```

The bootloader's own numbers agree: it reports `booting linux @ 0x401e8000`
(0x40000000 + 0x1e8000 image offset) and `ramdisk @ 0x66f00000`, which is
exactly what the image header asks for. **The image is being read correctly.**

## Next build change, if the console does not explain it

The most likely remaining cause is that the kernel dies before a console
exists. The next iteration should add, in this order:

1. `earlycon` on the MTK UART, so `start_kernel()` prints from its first line.
2. Keep `CONFIG_DEBUG_LL` / `DEBUG_UART` available for a panic-on-early path.
3. If a console is still silent, the failure is before `start_kernel()` and the
   problem is the entry path, not the kernel configuration.
