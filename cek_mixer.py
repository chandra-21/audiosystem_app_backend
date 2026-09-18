#!/usr/bin/env python3
"""Cek laju mixer & biaya resample di Orange Pi — TANPA mengubah apa pun.

Jalankan DARI folder backend (yang berisi services/), di proses terpisah.
Service yang sedang berjalan tidak disentuh dan tidak perlu di-restart.

    cd /home/orangepi/iotaudio_system_backend
    python3 cek_mixer.py

Menjawab dua hal:
  1. Mixer pygame sebenarnya berjalan di berapa Hz pada urutan init produksi?
  2. Sanggupkah CPU Orange Pi melakukan resample 16k->laju mixer secara realtime?
"""
import sys
import time

SAMPLE_RATE = 16000       # laju yang dikirim aplikasi Flutter
BATCH_MS = 200            # panjang tiap Sound (BATCH_CHUNKS=2 x chunk 100 ms)


def bagian(judul):
    print(f"\n{'=' * 58}\n{judul}\n{'=' * 58}")


bagian("1. Laju mixer menurut urutan inisialisasi produksi")

# Persis seperti AnnouncementService.__init__: get_audio_service() dipanggil
# lebih dulu, baru mixer diperiksa.
try:
    import pygame
    from services.audio_service import get_audio_service

    get_audio_service()          # ini yang memanggil pygame.mixer.init(44100)
    init = pygame.mixer.get_init()

    if init is None:
        print("Mixer TIDAK aktif — tidak bisa disimpulkan dari sini.")
        mixer_rate = None
    else:
        mixer_rate, fmt, channels = init
        print(f"  Mixer aktif   : {mixer_rate} Hz, {channels} channel, format {fmt}")
        print(f"  Announcement  : {SAMPLE_RATE} Hz mono")
        if mixer_rate == SAMPLE_RATE:
            print("\n  -> COCOK. Resample tidak diperlukan.")
        else:
            r = mixer_rate / SAMPLE_RATE
            print(f"\n  -> TIDAK COCOK. Audio 16 kHz diputar {r:.2f}x terlalu cepat.")
            print(f"     Sound {BATCH_MS} ms akan habis dalam {BATCH_MS / r:.0f} ms,")
            print(f"     menyisakan senyap {BATCH_MS - BATCH_MS / r:.0f} ms tiap potongan.")
except ImportError as e:
    print(f"  Gagal import ({e}). Jalankan dari folder backend, di venv yang benar.")
    mixer_rate = None
except Exception as e:
    # Device audio bisa saja sedang dipakai service. Itu tidak apa-apa —
    # jawabannya tetap bisa dibaca dari sumber audio_service.py.
    print(f"  Mixer tidak bisa dibuka di proses ini: {e}")
    print("  (kemungkinan device dipakai service yang sedang berjalan)")
    mixer_rate = None

if mixer_rate is None:
    try:
        import re
        src = open("services/audio_service.py", encoding="utf-8").read()
        m = re.search(r"frequency\s*=\s*(\d+)", src)
        if m:
            mixer_rate = int(m.group(1))
            print(f"  Dibaca dari audio_service.py: frequency={mixer_rate}")
    except Exception:
        pass

bagian("2. Biaya resample di CPU ini")

try:
    import numpy as np
    from math import gcd
    from scipy import signal
except ImportError as e:
    print(f"  numpy/scipy tidak tersedia: {e}")
    sys.exit(1)

target = mixer_rate or 44100
if target == SAMPLE_RATE:
    print("  Laju sama — tidak ada resample untuk diukur.")
    sys.exit(0)

n = int(SAMPLE_RATE * BATCH_MS / 1000)
mono = (np.random.randn(n) * 5000).astype(np.int16)
d = gcd(target, SAMPLE_RATE)
up, down = target // d, SAMPLE_RATE // d
print(f"  {SAMPLE_RATE} Hz -> {target} Hz  (up={up}, down={down})")
print(f"  Potongan uji: {n} sampel = {BATCH_MS} ms")

signal.resample_poly(mono.astype(np.float32), up, down)   # pemanasan

ULANG = 50
t0 = time.perf_counter()
for _ in range(ULANG):
    out = signal.resample_poly(mono.astype(np.float32), up, down)
elapsed_ms = (time.perf_counter() - t0) / ULANG * 1000

beban = elapsed_ms / BATCH_MS * 100
print(f"\n  Waktu per potongan : {elapsed_ms:.2f} ms")
print(f"  Anggaran realtime  : {BATCH_MS} ms")
print(f"  Beban CPU          : {beban:.1f}% dari satu inti")

if beban < 20:
    print("\n  -> AMAN. Resample jauh di bawah anggaran realtime.")
elif beban < 50:
    print("\n  -> MASIH CUKUP, tapi tidak lega. Pantau underrun ALSA.")
else:
    print("\n  -> TERLALU BERAT. Lebih baik set mixer ke 16000 Hz di")
    print("     audio_service.py (konsekuensi: kualitas musik latar turun).")

print(f"\n  Sanity check: output {len(out)} sampel = "
      f"{len(out) / target * 1000:.0f} ms (harus ~{BATCH_MS} ms)")
