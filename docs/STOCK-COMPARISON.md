# Stock kernel comparison — the plan

Four rounds of testing have gone into a kernel that has never been shown to
execute a single instruction. The strategy now is to stop guessing and take the
kernel that is *known to boot on this exact device* as the reference.

## Reference points already in hand

The device boots two kernels that are not ours:

| Kernel | Where it comes from | Version |
|---|---|---|
| Stock | Samsung `boot.img` from `A245FXXS9DYG1` | 5.10.226 |
| OrangeFox | its own recovery image | 5.10.177-android12-9-27760517 |

Both run on this hardware with no arguments. Whatever our image does wrong,
they do right.

## What to extract

From the stock `AP` tar for `A245FXXS9DYG1`:

1. **`boot.img`** — unpack the header, the kernel, the ramdisk and the dtb.
2. **The kernel's `IKCONFIG`**, if `CONFIG_IKCONFIG_PROC=y`, from `/proc/config.gz`
   on a running stock device. That is the only authoritative source for what
   Samsung actually built; anything else is inference.
3. **The uncompressed `Image`** — compare its header against ours field by
   field: `text_offset`, `image_size`, `flags`, `magic`, and what `code0`
   actually is.

## The comparisons that matter

Run these and record the answer rather than reasoning about it:

| Check | Why |
|---|---|
| `Image` header bytes 0x00-0x40 | If Samsung's `code0` is a branch and ours is `ADRP`, the entry convention differs and that is the bug |
| `flags` field | Page size and physical placement must match the platform |
| `text_offset` | Must agree with what LK expects at the load address it picks |
| Kernel size | 19.79 MiB was flashed but 46.29 MiB was built — confirm which is real |
| `CONFIG_SEC_DEBUG` in stock | OrangeFox has the driver registered, so stock almost certainly does too |
| `CONFIG_VT` / `DRM_FBDEV_EMULATION` in stock | If stock has them off too, then stock has no console either and the argument that a console would have shown us a panic does not hold |

That last row is the most valuable one. It tests the assumption behind
`v1.0.7` rather than assuming it.

## What we already know about the flashed image

From the round-4 log:

```
boot_linux_fdt:1132: booting linux @ 0x401e8000, ramdisk @ 0x66f00000 (26) dtb @ 0x47c80000
```

and `kernel_sz=0x013c9a54` = **19.79 MiB**, repeated identically on every boot
that reached the kernel.

`v1.0.7`'s `Image.gz` is **46.29 MiB**. A 26-byte ramdisk also confirms the
image is one of ours — the stock ramdisk is 37.9 MiB. So the device is running
**one of our images, but not the newest one.**

That has to be settled before the next build means anything: if the tester is
flashing an older file, every conclusion drawn from these logs is about that
older file.

## Why this is the right next step

Each round so far has cost a full flash cycle and produced one hypothesis,
which was then either confirmed by luck or, more often, died on contact with
the evidence:

- RKP handshake — wrong, the log had nothing about it
- Missing `secdbg-kernel-log` DT node — wrong, `mt6789.dts:7357` includes it
- Kernel too large for the partition — wrong, 46.59 MiB into 80 MiB

The stock kernel cannot be wrong in the same way, because it is the thing that
works. Diffing against it replaces hypothesis with observation.

---

# The ramdisk finding (round 5)

Round 5 changed the picture completely: the tester reports a **25-30 second
boot followed by a power-off, not a reboot.**

That is the kernel running.

## What the timeline says

| Event | Time |
|---|---|
| bootloader decompresses and jumps | 4.14 s |
| kernel stops printing / system powers off | 25-30 s |

So there are **21-26 seconds of kernel execution** that produced no log
anywhere. A kernel running that long has a working printk ring buffer; it just
has no console to drain it to.

## Why it dies, and why `panic=-1` turned the panic into a power-off

`last_kmsg-5.log` shows the ramdisk the bootloader handed over:

```
boot_linux_fdt:1132: booting linux @ 0x401f0000, ramdisk @ 0x66f00000 (26) dtb @ ...
```

**26 bytes.** That is our own placeholder gzip — an empty initramfs. The stock
image carries **39,796,280 bytes** (round 2's log, when an older, larger image
of ours was flashed).

With an empty initramfs there is no `/init`, and our cmdline has no `root=`:

```
bootopt=64S3,32N2,64N2 loop.max_part=7 console=tty0 loglevel=7 panic=-1
```

So the kernel falls out of `prepare_namespace()`, calls
`mount_block_root()`, waits for a root device that was never named, and prints
`VFS: Cannot open root device` — to nowhere, because there is no console. Then
it would normally panic and reboot. `panic=-1` tells it not to. So it hangs
instead, and the hardware watchdog eventually cuts power.

**A power-off rather than a reboot is the signature of a panic that was told
not to restart.** The tester's observation and the code agree.

## The fix

`scripts/extract_ramdisk.py` pulls the ramdisk out of the stock `boot.img`
verbatim, and `build-kernel.sh --stock-boot <file>` places it in ours.

```
./scripts/build-kernel.sh --variant vanilla --stock-boot /path/to/stock_boot.img
```

Without a stock image the build still runs, but now says loudly that it is
packaging an empty initramfs and cannot boot.

## What is needed to try this

The stock `boot.img` for `A245FXXS9DYG1`, which comes from Samsung's AP tar
for that firmware. Roughly 80 MiB. It is not in this repository and CI cannot
fetch it — it has to be supplied.

Place it in the repo as `stock/boot.img` (the path is ignored by git) or pass
it to `--stock-boot` directly.
