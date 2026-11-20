# Flashing and rollback

> **Read all of this before you touch a device.** These builds have not been
> tested on hardware. The failure mode of a bad kernel is a device that does
> not boot and must be recovered through Download Mode.

---

## Step 0 — let the script check your device

With the device booted normally and USB debugging on:

```bash
python3 scripts/check_device.py
```

It reads the model, build string and verified-boot state, and prints either
**compatible** or **DO NOT FLASH** with the reason. It writes nothing to the
device. Do not skip this because "it is probably fine" — the check exists
precisely for the case where it is not.

---

## Before anything: check the binary

Your device must be on, or be able to return to, **bootloader binary 9** —
i.e. a firmware `A245FXXS9D…` build.

Check in **Settings → About phone → Software information → Build number**.
The 5th character from the end is the binary. `A245FXXS9DYG1` → `9`.

If your build is `A245FXX**SBE**ZB5` or anything with binary `A`–`E`, you are on
Android 16 firmware and **cannot** go back to a binary-9 base. Stop here.

**Do not** flash a binary-9 firmware onto a device that has already booted a
higher binary. Samsung's rollback-prevention fuses will refuse it, and that
state cannot be undone.

---

## What you need

1. **The matching stock firmware** for your exact model and CSC, downloaded
   **before** you start. This is your only guaranteed recovery path.
   Verify the archive is complete and extract it.
2. **Odin** (Windows) — the standard Samsung flashing tool. Use a version new
   enough for Android 13+ firmware.
3. A **known-good USB cable** and a **USB 2.0 port** if possible. Front-panel
   USB 3 hubs cause `FAIL` on Samsung flashing.
4. **Battery above 50%**.

## What this repository produces

A `boot.img` packaged as `a24_<variant>_...tar.gz`. Inside is a single
`boot.img`. This replaces the kernel. It does **not** touch `super`, your data,
or the vendor partition.

---

## Flashing (Odin, Windows)

1. Extract the `.tar.gz` so you have a plain `.tar` (or use it directly if Odin
   accepts it).
2. Put the device in **Download Mode**. On recent Samsung devices: power off,
   then hold **Volume Up + Volume Down** while plugging in USB, and confirm.
3. Open Odin. Wait for the device to appear in the ID:COM box.
4. Put the `.tar` in the **AP** slot.
5. **Leave `Re-Partition` unticked.** Leave everything else at default.
6. **Start.**

### ⚠️ Bootloader lock

Flashing a custom `boot.img` requires an **unlocked bootloader**
(OEM unlocking enabled in Developer options, then unlocked in Download Mode).

Unlocking:
- **Wipes all data**, irreversibly.
- **Trips the Knox warranty bit permanently.** Samsung Pay, Secure Folder,
  Samsung Pass and Knox-dependent enterprise apps stop working forever.
- May take effect only after a 7-day OEM-unlock waiting period.

Do not proceed if any of that is unacceptable.

### ⚠️ Verified boot — you will almost certainly need the vbmeta image

The kernels in this release are **unsigned**. On a device with verified boot
enforcing, Android Verified Boot rejects them and the bootloader drops back to
Download Mode. That looks identical to a broken kernel, so do not conclude the
build is bad when this happens.

Every release therefore also ships a `vbmeta.img` with both
`disable-verity` and `disable-verification` set (this is `avbtool --flags 2`,
verified at build time). Flash it **to the `vbmeta` partition** together with
`boot.img`.

In Odin:
- `boot.img` → **AP**
- `vbmeta.img` → **AP** as well, in a second run, or in the same run if your
  Odin build accepts multiple AP slots

Do not put `vbmeta.img` inside the boot tar — it must land on its own
partition.

**This weakens device security permanently for as long as it is flashed.**
With verification disabled, nothing checks that your boot or system partitions
are the ones Samsung signed. Flash the stock `vbmeta.img` again — it is inside
the stock `AP` tar — to undo it.

If the device still refuses to boot with vbmeta flashed, the bootloader is
rejecting the kernel itself, not the signature, and the build needs
investigation rather than more flashing.

---

## Rollback

The reliable rollback is a **full stock flash**:

1. Download the stock firmware for your exact model and CSC.
2. Odin → **BL**, **AP**, **CP**, and **CSC** (use `CSC` for a clean wipe,
   `HOME_CSC` only if you are sure the data layout is unchanged).
3. Start. First boot takes several minutes.

Because your `boot.img` is the only partition this project writes, you can
also roll back by flashing just the stock `AP` file — but a full four-file
flash is safer and is what you should plan for.

**Keep the stock firmware archive. Do not delete it to save disk space.**

---

## What to capture if it fails

Write this down before you flash, so you can report accurately:

| Field | Your value |
|---|---|
| Model | `SM-A245F` / `SM-A245F/DS` / `SM-A245F/DSN` |
| CSC / region | |
| Build number (before flashing) | |
| Binary (5th char from end) | |
| Variant flashed | `vanilla` / `kernelsu` / `bakasu` |
| Release tag | |
| SHA256 of the `.tar.gz` | |
| Result | booted / bootloop / black screen / Download Mode only |

**Do not share**: IMEI, serial number, phone number, ICCID, account
credentials, or unlock tokens. Crop those out of screenshots.

---

## What is verified and what is not

| Step | Status |
|---|---|
| Kernel compiles | Not yet — first CI run pending |
| Boot image packs correctly | Not yet |
| Device boots | Not yet |
| Vendor modules load | Not yet |
| Root works | Not yet |
| Rollback procedure rehearsed | Not yet |

Treat every artifact as untested until the release notes say otherwise.
