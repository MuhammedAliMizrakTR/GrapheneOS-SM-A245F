# Tester brief — v1.0.7-kernel

**Release:** https://github.com/MuhammedAliMizrakTR/GrapheneOS-SM-A245F/releases/tag/v1.0.7-kernel

## Bu turda ne değişti

Şimdiye kadar dört tur log geldi ve **hiçbirinde kernel'den tek satır yoktu**. Sebebi artık belli: bu kernelin **hiç konsolu yoktu**.

```
CONFIG_VT                   ayarlı değil
CONFIG_FRAMEBUFFER_CONSOLE  ayarlı değil
CONFIG_DRM_FBDEV_EMULATION  ayarlı değil
```

`console=tty0` cmdline'da yazıyor ama bağlanacak bir tty yok. UART kablosu da yok. Yani kernel dört turdur **hiçbir yere yazamıyordu** — yazmadığı için değil, yazacak yeri olmadığı için.

Bu turda:

- `VT`, `VT_CONSOLE`, `DRM_FBDEV_EMULATION`, `DRM_KMS_FB_HELPER` açıldı. MTK DRM sürücüsü zaten `drm_fbdev_generic_setup()` çağırıyor, yani panel üzerinden gerçek bir konsol gelecek.
- cmdline'a `console=tty0 loglevel=7` eklendi.
- cmdline'a **`panic=-1`** eklendi: panik olursa kernel **yeniden başlamayacak**, ekranda duracak.

**Beklenen sonuç:** eğer kernel panikliyorsa, artık bootloop yerine **ekranda yazı göreceksiniz** ve telefon kendini resetlemeyecek. O yazıyı fotoğraflamanız yeterli.

Bu, ilk birkaç yüz komutta ölürse işe yaramaz (display henüz kurulmamış olur). Ama watchdog reseti gördüğümüze göre kernel bir süre çalışıyor, yani display'e ulaşma şansı var.

## VANILLA'yı da deneyin — hiç denenmedi

Dört turdur sadece KernelSU'lu imajlar test edildi. **`boot-vanilla.img` bir kez bile denenmedi.**

Bu önemli, çünkü KernelSU kernel kaynağına patch uyguluyor. Eğer vanilla açılırsa sorun KernelSU'da demektir; eğer o da bootloop yaparsa sorun temel kernelde.

**Lütfen ikisini de deneyin ve hangisinin ne yaptığını ayrı ayrı söyleyin:**

| Dosya | Ne yapıyor |
|---|---|
| `boot-vanilla.img` | KernelSU yok — **önce bunu deneyin** |
| `boot-kernelsu.img` | KernelSU-Next v3.4.2 |

## Ne göndereceksiniz

### 1. Ekran fotoğrafı (en önemlisi)

`v1.0.7` ile açılışta:
- **Yazı çıkıyor mu?** Çıkıyorsa **fotoğrafını çekin**. Panik mesajının son 15-20 satırı yeterli.
- Yoksa yine sadece logo mu? Bunu söyleyin.

`panic=-1` yüzünden telefon artık reset atmayacak. Yazı ekranda kalacak.

### 2. Boot süresi

- Logo kaç saniye sonra geliyor?
- Ne kadar sonra reset atıyor / duruyor?

### 3. Kernel logu

Telefonu **OrangeFox'a** alıp:

```bash
adb shell 'cat /proc/last_kmsg' > last_kmsg-4.txt
adb shell 'ls -l /sys/fs/pstore/'
```

`last_kmsg-4.txt` bu kez **kernel satırları içermeli**. İçeriyorsa:

```bash
python3 analyze_bootlog.py last_kmsg-4.txt
```

çıktısını gönderin.

## Flash

| Dosya | Odin slotu |
|---|---|
| `boot-vanilla.img` | **AP** — önce bu |
| `boot-kernelsu.img` | **AP** — sonra bu |

**`vbmeta` flashlamayın.** Zaten kurulu ve kabul edilmiş durumda. Logunuzda `CUSTOM vbmeta` ve `avb_ret = 0` var, yani doğrulama zaten kapalı.

> **Fuse uyarısı.** Bu firmware binary 9 (`A245FXXS9DYG1`). Samsung'un rollback fuse'ı tek yönlüdür. Cihazınız 9'dan yüksek bir binary'deyse bu kernel hiç açılmaz ve bunu geri almanın yolu yoktur.

## Bilinen ve elenen şeyler

Bunlar kontrol edildi, tekrar bakmanıza gerek yok:

- **Doğrulama reddi (AVB):** hayır. `avb_boot_state = 2`, `avb_device_locked = 0`, cihaz Download Mode'a düşmüyor.
- **gzip / sıkıştırma:** düzeltildi, kernel 247 ms'de açılıyor.
- **DTB / overlay:** bootloader kendi FDT'sini kuruyor, sorun değil.
- **Boot header:** LK'nın bildirdiği adresler header ile birebir uyuşuyor.
- **MMU / sayfa boyutu:** VA_BITS=39, 4K, PA=48 — platform varsayılanı.
- **Rollback fuse:** `(1, 9, 9, 9)...ok`.
- **UART modülü:** düzeltildi (`SERIAL_8250_MT6577=m` → `=y`).
- **`/proc/last_kmsg`:** düzeltildi (`SEC_DEBUG=m` → `=y`).

## Açık kalan tek soru

**Kernel çalışıyor mu, çalışıyorsa nerede ölüyor?**

Watchdog reseti kernel'in bir süre çalıştığını gösteriyor. Bu turda onu **görebileceğiz**.

Eğer `v1.0.7` de yazı göstermezse, kalan tek yol UART kablosudur ve o zaman bu yaklaşımı bırakıp başka bir yol önereceğim.

## Göndermeyin

IMEI, seri numarası, hesap bilgisi. Model ve build string yeterli.

Stok kernel ile açılmış `logcat` ve OrangeFox'un kendi `dmesg`'si işe yaramaz — ikisi de bizim kernelimize ait değil.
