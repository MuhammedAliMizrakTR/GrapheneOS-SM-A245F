# Tester brief — v1.0.8-kernel

**Release:** https://github.com/MuhammedAliMizrakTR/GrapheneOS-SM-A245F/releases/tag/v1.0.8-kernel

## Önce: hangi sürümün flashlandığını artık bilebileceğiz

Round 4 logunda bootloader şunu söylüyordu:

```
kernel_sz=0x013c9a54   = 19.79 MiB
```

Ama `v1.0.7`'nin `Image.gz`'si **46.29 MiB**. İkisi de bizim imajımız (ramdisk 26 bayt, stok 37.9 MiB) — ama **cihaz en son sürümü çalıştırmıyor.** Ve logda hangi sürümün çalıştığını söyleyen hiçbir şey yoktu. Bu yüzden bütün tur okunamaz hale geldi.

**Artık kernel kendini tanıtıyor.** Sürüm stringi şöyle:

```
5.10.226-a24-vanill-2611221025
                └─┬───┘ └───┬───┘
                  │         └─ build zamanı (yy ayddHHMM)
                  └─ variant
```

Yani `uname -r` ya da logdaki herhangi bir sürüm satırı, cihazdaki build'i kesin söyler.

## Bu turda ne yapmanız gerekiyor

### 1. Flash ettikten sonra sürümü okuyun

OrangeFox'ta:

```bash
adb shell 'uname -r'
```

Çıktıyı bana gönderin. **Bu tek satır, son dört turun neden ilerlemediğini çözecek.**

Beklenen biçim: `5.10.226-a24-...-...`

Eğer `5.10.177-android12-9-27760517` görürseniz, o OrangeFox'un kendi kernel'i — yani cihaz hâlâ recovery'de, bizim imajımız hiç çalışmamış.

### 2. VANILLA ile başlayın

`boot-vanilla.img` **dört turdur hiç denenmedi.** KernelSU'lu imajlar hep denendi. Bu boşluk kapatılmalı.

| Sıra | Dosya | Neden |
|---|---|---|
| 1 | `boot-vanilla.img` | KernelSU yok — temel kernel çalışıyor mu? |
| 2 | `boot-kernelsu.img` | KernelSU-Next v3.4.2 |

**İkisini ayrı ayrı deneyin ve hangisinin ne yaptığını ayrı söyleyin.**

### 3. Ekranı izleyin

`panic=-1` sayesinde telefon artık panik olunca reset atmamalı. Yani:

- **Yazı çıkıyorsa** → fotoğraf (son 15-20 satır yeterli)
- **Sadece logo + tekrar reset** → bunu söyleyin
- **Logo hiç gelmiyor** → bunu söyleyin

### 4. `last_kmsg` yine de alın

Telefonu OrangeFox'a alıp:

```bash
adb shell 'cat /proc/last_kmsg' > last_kmsg-5.txt
```

Ve üstünde:

```bash
python3 analyze_bootlog.py last_kmsg-5.txt
```

## Flash

| Dosya | Odin slotu |
|---|---|
| `boot-vanilla.img` | **AP** — önce bu |
| `boot-kernelsu.img` | **AP** — sonra bu |

**`vbmeta` flashlamayın.** Zaten kurulu ve kabul edilmiş (`CUSTOM vbmeta`, `avb_ret = 0`).

> **Fuse uyarısı.** Binary 9 (`A245FXXS9DYG1`). Samsung rollback fuse'ı tek yönlü. Cihaz 9'dan yüksekse bu kernel açılmaz ve geri dönüşü yoktur.

## Download Mode notu

Geçen turda söylediğiniz gibi, loglardaki Download Mode boot'ları sizin recovery geçişinizmiş. Anlaşıldı — artık o boot'ları "arıza" saymıyorum, sadece atlanacak veri. Bunun için ayrı bir şey yapmanıza gerek yok.

## Elenen ihtimaller

Bunlar kontrol edildi ve **çürütüldü**, tekrar bakmayın:

| Hipotez | Sonuç |
|---|---|
| AVB reddi | Hayır — `avb_boot_state = 2`, `avb_device_locked = 0` |
| gzip / sıkıştırma | Düzeltildi, 247 ms'de açılıyor |
| DTB / overlay | LK kendi FDT'sini kuruyor |
| Boot header adresleri | LK'nın bildirdiği ile birebir aynı |
| MMU / sayfa boyutu | VA_BITS=39, 4K, PA=48 — stok değerler |
| Rollback fuse | `(1, 9, 9, 9)...ok` |
| RKP el sıkışması | Logda RKP el sıkışması yok, o satırlar `rkpdapp` (Android) |
| `secdbg-kernel-log` DT node yok | **Yanlış** — `mt6789.dts:7357` include ediyor |
| Kernel partition'a sığmıyor | **Yanlış** — 46.59 MiB / 80 MiB |

## Açık kalan soru

**Kernel çalışıyor mu, çalışıyorsa nerede ölüyor?**

Dört turdur cevap yok. Sıradaki adım, çalıştığı **kanıtlanmış** stok kernel'i çıkarıp bizimkiyle karşılaştırmak — tahmin etmek yerine ölçmek. Detay: `docs/STOCK-COMPARISON.md`.

## Göndermeyin

IMEI, seri numarası, hesap bilgisi.

`logcat` ve OrangeFox `dmesg`'i işe yaramaz — ikisi de bizim kernelimize ait değil. Bunu üç turdur görüyoruz.
