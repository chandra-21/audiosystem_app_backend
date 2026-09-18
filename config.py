# backend/config.py
import os
# =====================================================
# Database
# =====================================================
DATABASE_URL = "sqlite:///./iot_audio.db"

# =====================================================
# ESP32 settings (Audio System)
# =====================================================
# Alamat ESP32 di jaringan lokal. Set lewat environment variable
# ESP32_HOST; nilai default hanya contoh dan hampir pasti perlu diganti.
ESP32_HOST = os.getenv("ESP32_HOST", "192.0.2.10")
ESP32_SCHEDULE_ENDPOINT = "/schedule"
ESP32_TIMEOUT = 10

# =====================================================
# Upload Directory
# =====================================================
UPLOAD_DIR = "static/uploads"
JINGLE_DIR = "static/jingle"