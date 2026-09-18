<div align="center">

# Audio System Backend

**Backend FastAPI untuk sistem audio gedung: bel, musik terjadwal, dan pengumuman**

Berjalan di Orange Pi, mengendalikan relay bel lewat ESP32 dan menyiarkan audio ke
speaker per zona. Dikendalikan dari aplikasi mobile Kapitmas Platform.

`FastAPI` · `SQLAlchemy` · `SQLite` · `WebSocket` · `PySerial` · `APScheduler`

</div>

---

## Apa yang dikerjakan

Gedung memerlukan bel otomatis untuk penanda jam kerja, musik latar pada jam
tertentu, dan kemampuan menyiarkan pengumuman suara secara langsung. Backend ini
menyatukan ketiganya di satu layanan kecil yang berjalan di sebuah Orange Pi.

| Modul | Isi |
|---|---|
| **Bell** | jadwal bel per hari, jumlah dan durasi dering, diaktifkan per hari dalam seminggu |
| **Music** | pustaka musik, playlist, dan jendela jam pemutaran otomatis |
| **Announcement** | siaran suara langsung dari aplikasi mobile, dengan jingle pembuka dan penutup |
| **Speaker** | konfigurasi zona speaker beserta pin GPIO-nya |
| **App version** | pemeriksaan versi untuk aplikasi mobile |

## Dua jalur ke perangkat keras

Yang membuat backend ini tidak sekadar CRUD adalah dua jalur komunikasi yang
berbeda karakternya:

### Serial ke ESP32 — relay bel

`BellSerialService` berbicara ke ESP32 lewat **USB serial** (`/dev/ttyUSB0`,
115200 baud) untuk menggerakkan relay bel. Koneksi serial gampang putus — kabel
tersenggol, perangkat restart — sehingga service ini menyimpan koneksi sebagai state,
memeriksa ulang sebelum dipakai, dan mencoba kembali sampai tiga kali sebelum
menyerah.

Jalur serial dipilih ketimbang jaringan karena relay bel harus bekerja meskipun WiFi
gedung sedang bermasalah. Bel yang tidak berbunyi karena jaringan putus adalah
kegagalan yang langsung terasa oleh seluruh penghuni gedung.

### WebSocket — pengumuman langsung

`WebSocketManager` menangani siaran suara dari aplikasi mobile. Satu aturan penting:
**hanya satu koneksi pengumuman yang boleh aktif** pada satu waktu
(`announcement_connection`). Dua orang yang menyiarkan bersamaan akan menghasilkan
suara bertumpuk di speaker, jadi pembatasan ini dijaga di level manager, bukan
diserahkan ke antarmuka.

## Penjadwal

Dua scheduler berjalan berdampingan:

- `bell_scheduler_service` — memicu bel sesuai `bell_schedules`, dengan
  `bell_schedule_status` sebagai penanda hari mana saja yang aktif
- `music_scheduler_service` — menyalakan dan mematikan musik latar sesuai jendela jam
  di `music_schedule`

Memisahkan jadwal (kapan berbunyi) dari status aktif (hari apa saja berlaku) membuat
libur nasional atau akhir pekan cukup ditangani dengan mematikan satu hari, tanpa
menghapus jadwalnya.

---

## Struktur

```
.
├── main.py                 aplikasi FastAPI, health check, WebSocket
├── config.py               database, ESP32, direktori unggahan
├── database.py             engine & sesi SQLAlchemy
├── models.py               Music, BellSchedule, BellScheduleStatus,
│                           SpeakerConfig, MusicSchedule
├── schemas.py              skema Pydantic
├── auth.py  utils.py
├── routers/
│   ├── bell_schedule.py    music_schedule.py    playlist.py
│   ├── announcement.py     speaker.py           app_version.py
├── services/
│   ├── bell_serial_service.py      serial ke ESP32
│   ├── bell_scheduler_service.py   pemicu bel terjadwal
│   ├── music_scheduler_service.py  jendela jam musik
│   ├── announcement_service.py     audio_service.py
│   ├── speaker_service.py
│   └── websocket_manager.py        siaran langsung
├── migrations/
└── static/jingle/          jingle pembuka & penutup pengumuman
```

---

## Menjalankan

Prasyarat: Python 3.11+, dan ESP32 yang terhubung lewat USB bila relay bel dipakai.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Dokumentasi API otomatis tersedia di `http://localhost:8000/docs`, dan
`GET /health` untuk pemeriksaan kesehatan layanan.

### Konfigurasi

| Variabel | Default | Guna |
|---|---|---|
| `ESP32_HOST` | `192.0.2.10` | alamat ESP32 di jaringan lokal — **wajib diganti** |

Pengaturan lain ada di `config.py`: `DATABASE_URL` (SQLite di berkas lokal),
`ESP32_SCHEDULE_ENDPOINT`, `ESP32_TIMEOUT`, `UPLOAD_DIR`, dan `JINGLE_DIR`.

Port serial ESP32 di-set saat `BellSerialService` dibuat; default `/dev/ttyUSB0`
sesuai penempatan di Orange Pi.

### Basis data

SQLite dibuat otomatis saat pertama dijalankan. Berkas `.db` **tidak** ikut dalam
repositori — datanya bersifat spesifik per pemasangan.

---

## Klien

Backend ini dikendalikan oleh modul HR/HC pada aplikasi mobile
**Kapitmas Platform** (Flutter): penjadwalan bel, pustaka musik, perekaman dan
penyiaran pengumuman, serta konfigurasi speaker.

---

## Catatan

Repositori ini memakai riwayat yang dimulai bersih. Riwayat sebelumnya memuat berkas
basis data, lingkungan virtual lengkap, dan nilai kredensial contoh yang sudah tidak
dipakai lagi di kode — semuanya tidak terbawa. Tidak ada berkas `.env`, basis data,
atau unggahan pengguna yang disertakan.

Alamat IP yang muncul sebagai nilai default adalah alamat dokumentasi
(`192.0.2.0/24`, RFC 5737), bukan alamat jaringan nyata.

Dibangun untuk kebutuhan PT. Kapitmas. Merek dan nama perusahaan adalah milik mereka.

## Author

**Candra Gd**
