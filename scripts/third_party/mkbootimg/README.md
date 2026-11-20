# Vendored: AOSP mkbootimg

Source: https://github.com/LineageOS/android_system_tools_mkbootimg
Branch: `lineage-22.2`

`mkbootimg.py` and `unpack_bootimg.py` are copied verbatim from upstream;
`include/bootimg/bootimg.h` is kept alongside them as the format reference.
`gki/generate_gki_certificate.py` is present only because `mkbootimg.py`
imports it at module scope; the GKI signing path it belongs to is not used by
this project.

Licensed under the Apache License, Version 2.0 — see `LICENSE` in the
repository root. These files are not modified, so upstream and this copy should
stay byte-identical apart from this README.
