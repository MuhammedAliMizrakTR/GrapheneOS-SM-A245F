# Tester brief — v1.1.1-kernel

**Release:** https://github.com/MuhammedAliMizrakTR/GrapheneOS-SM-A245F/releases/tag/v1.1.1-kernel

## Bu turda kaynak ağacı tamamen değişti

Dört turdur `A245FXXS9DYG1` (binary 9, kernel 5.10.226) ağacını derliyordum. İmajlar açılıyordu, kernel'e atlanıyordu, sonra hiçbir iz kalmıyordu. Her hipotezim loglarla çürütüldü.

**Artık farklı bir ağaç kullanılıyor:**

| | Eski | Yeni |
|---|---|---|
| Kaynak | `oliplusmzr/a245f` @ `A245FXXS9DYG1` | **`VH-Devices/android_kernel_samsung_a24`** @ `OSRC` |
| Kernel | 5.10.226 | **5.10.177** |
| Kaynak firmware | A245FXXS9DYG1 (binary 9) | A245FXXU3BWK3 (binary 3) |

**Neden bu ağaç:** Bu cihazda çalıştığı **kanıtlanmış tek kernel sürümü** OrangeFox'un kendi kernel'i:

```
5.10.177-android12-9-27760517
```

VH-Devices ağacı tam olarak **5.10.177**. Yani cihazda çalışan sürümle aynı.

## Binary 9 meselesi — önemli

Binary 9'da derleme **gerekmiyor**. Sebep:

- Rollback sayacı **kernel imajında taşınmıyor**, bootloader zincirinde taşınıyor.
- LK sadece imajın **kendi versiyon alanına** bakıyor.
- Bootloader'ın kendisi binary 9'da ve dokunulmuyor.

Kernel 5.10.177 olması, bootloader'ın binary 9 olmasıyla çelişmiyor. OrangeFox tam olarak bu kombinasyonla çalışıyor.

## Config profili de değişti

Önceki build'lerde Samsung'un güvenlik sürücülerini **kapatıyordum**:

```
RKP=n  KDP=n  DEFEX=n  FIVE=n  PROCA=n
```

Bu ağaçta bunlar **açık bırakıldı** (`KEEP-SECURITY` profili). Gerekçe: bu ayarlar Samsung'un kendi config'inde açık ve bu ağaç cihazda çalışan sürüme en yakın olanı. Kapatmanın işe yaradığı hiç gösterilmedi.

## Build kimliği artık release notlarında

Dosya indirmeye gerek yok — release sayfasında yazıyor:

| | |
|---|---|
| kernel | `5.10.177` |
| kaynak | `VH-Devices/android_kernel_samsung_a24` @ `OSRC` |
| config profili | `KEEP-SECURITY` |
| LOCALVERSION | `-a24-vanill-11221457` |

## Ne yapmanız gerekiyor

### 1. Önce sürümü okuyun

Flash ettikten sonra OrangeFox'ta:

```bash
adb shell 'uname -r'
```

**Beklenen:** `5.10.177-a24-vanill-...` gibi bir şey.

Eğer `5.10.177-android12-9-27760517` görürseniz, o OrangeFox'un kendi kernel'i — bizim imaj hiç çalışmamış demektir.

Bu tek satır, son dört turun neden ilerlemediğini çözecek.

### 2. Vanilla ile başlayın

`boot-vanilla.img` — **hiç denenmedi.**

| Sıra | Dosya |
|---|---|
| 1 | `boot-vanilla.img` |
| 2 | `boot-kernelsu.img` |

Ayrı ayrı deneyin, hangisinin ne yaptığını ayrı söyleyin.

### 3. Ekranı izleyin

`panic=-1` var, yani panik olursa telefon reset atmamalı.

- **Yazı çıkıyorsa** → fotoğraf (son 15-20 satır)
- **Logo + reset** → söyleyin
- **Hiç logo yok** → söyleyin

### 4. `last_kmsg` alın

```bash
adb shell 'cat /proc/last_kmsg' > last_kmsg-5.txt
python3 analyze_bootlog.py last_kmsg-5.txt
```

## Flash

| Dosya | Odin slotu |
|---|---|
| `boot-vanilla.img` | **AP** |
| `boot-kernelsu.img` | **AP** |

**`vbmeta` flashlamayın.** Zaten kurulu (`CUSTOM vbmeta`, `avb_ret = 0`).

> **Fuse uyarısı.** Bootloader binary 9'da. Samsung rollback fuse'ı tek yönlü. Bu kernel binary 3 ağacından geliyor ama **kernel binary taşımaz** — bootloader'a dokunulmuyor. Yine de cihaz 9'dan yüksekse hiçbir şey açılmaz ve geri dönüşü yoktur.

## Elenen ihtimaller

Bunlar kontrol edildi ve **çürütüldü**:

| Hipotez | Sonuç |
|---|---|
| AVB reddi | Hayır — `avb_boot_state = 2`, `avb_device_locked = 0` |
| gzip / sıkıştırma | Düzeltildi, 247 ms'de açılıyor |
| DTB / overlay | LK kendi FDT'sini kuruyor |
| Boot header adresleri | LK'nın bildirdiği ile aynı |
| MMU / sayfa boyutu | VA_BITS=39, 4K, PA=48 |
| Rollback fuse | `(1, 9, 9, 9)...ok` |
| RKP el sıkışması | Logda yok, o satırlar `rkpdapp` (Android) |
| `secdbg-kernel-log` DT node | **Yanlış** — `mt6789.dts:7357` include ediyor |
| Kernel partition'a sığmıyor | **Yanlış** — 46.59 MiB / 80 MiB |
| Konsol eksikliği | `VT`/`DRM_FBDEV` eklendi, fark etmedi |

## Göndermeyin

IMEI, seri numarası, hesap bilgisi. `logcat` ve OrangeFox `dmesg`'i işe yaramaz — üç turdur bizim kernelimize ait değiller.
