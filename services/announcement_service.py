# backend/services/announcement_service.py - 16kHz OPTIMIZED VERSION WITH SPEAKER STATE MANAGEMENT
import pygame
import io
import logging
import asyncio
import time
import os
import numpy as np
from collections import deque
from math import gcd
from datetime import datetime
from typing import List, Optional, Dict
from fastapi import WebSocket
from scipy import signal

from services.audio_service import get_audio_service
from services.speaker_service import get_speaker_service, SpeakerDatabaseService
from services.websocket_manager import get_ws_manager
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ========================================
# CHANGED: 16kHz configuration (was 44.1kHz)
# ========================================
SAMPLE_RATE = 16000  # 16kHz - much lower bandwidth
CHANNELS = 1  # Mono from Flutter

# Channel pygame khusus announcement.
#
# Siaran HARUS berjalan di satu channel tetap. sound.play() mengambil channel
# bebas mana pun dari kolam 8 channel, sehingga potongan berikutnya mulai
# berbunyi sebelum potongan sebelumnya habis — suaranya bertindihan dan
# terdengar kresek. Dengan satu channel tetap + Channel.queue(), potongan
# tersambung berurutan tanpa jeda dan tanpa tumpang tindih.
ANNOUNCEMENT_CHANNEL = 0

# Penguatan maksimum untuk suara pembicara yang pelan.
VOLUME_BOOST = 2.0

# Sisakan 5% ruang di bawah batas int16 supaya limiter sempat menurunkan gain
# sebelum sinyal menyentuh langit-langit. Memotong dengan np.clip meratakan
# puncak gelombang, dan puncak yang rata itulah distorsi yang paling kasar
# terdengar — bukan "keras", tapi "kresek".
HEADROOM = 32767.0 * 0.95

# Sangga playback dihitung dalam CHUNK, jadi nilainya bergantung pada durasi
# chunk yang dikirim client (saat ini 100 ms per chunk).
#
# PREROLL adalah cadangan yang dikumpulkan sebelum bunyi pertama. Cadangan ini
# yang menyerap jitter jaringan. Tanpa itu, produksi dan konsumsi berjalan tepat
# 1:1 dan keterlambatan sekecil apa pun langsung mengeringkan playback —
# terdengar sebagai suara patah-patah yang tidak pernah pulih.
#
# BATCH adalah panjang tiap Sound yang diputar. Semakin kecil, semakin sering
# _pump_playback() berkesempatan menyusulkan potongan berikutnya sebelum channel
# habis; semakin besar, semakin sedikit overhead make_sound().
PREROLL_CHUNKS = 5   # ~500 ms cadangan
BATCH_CHUNKS = 2     # ~200 ms per Sound

class AnnouncementService:
    """Service untuk mengelola announcement - 16kHz VERSION"""
    
    def __init__(self):
        self.is_active = False
        self.state = "idle"
        self.selected_speakers: List[int] = []
        self.current_user_id: Optional[int] = None
        self.current_username: Optional[str] = None
        self.started_at: Optional[datetime] = None
        
        # ✅ NEW: Store speaker state before announcement
        self.speaker_state_before: Dict[int, bool] = {}
        
        # Buffer configuration - optimized for 16kHz
        self.chunk_count = 0
        self.audio_buffer = []
        # Ambang sangga sekarang berupa konstanta modul PREROLL_CHUNKS dan
        # BATCH_CHUNKS, karena nilainya terikat pada durasi chunk yang dikirim
        # client dan harus dibaca berdampingan dengan penjelasan di sana.
        self.channel = None
        self.playback_started = False

        # Potongan yang menunggu giliran diputar. pygame hanya menyimpan SATU
        # sound di antrean channel, jadi sisanya ditahan di sini dan disusulkan
        # oleh _pump_playback() setiap ada chunk masuk.
        self.pending_sounds = deque()
        
        # Simple noise gate
        self.noise_threshold = 100

        # Gain yang dipakai di akhir chunk sebelumnya. Dipakai sebagai titik
        # awal ramp supaya gain tidak melompat di batas antar-chunk.
        self._last_gain: Optional[float] = None
        
        # Services
        self.audio_service = get_audio_service()
        self.ws_manager = get_ws_manager()
        
        # ========================================
        # CHANGED: Initialize pygame with 16kHz
        # ========================================
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(
                    frequency=SAMPLE_RATE,
                    size=-16,
                    channels=2,  # Stereo output
                    buffer=4096
                )
            pygame.mixer.set_num_channels(8)

            # Mixer pygame itu GLOBAL dan hanya ada satu. audio_service sudah
            # menyalakannya lebih dulu di 44100 Hz untuk pemutaran musik, jadi
            # blok init di atas hampir selalu DILEWATI.
            #
            # Laporkan laju yang benar-benar berjalan, bukan yang kita minta.
            # Versi lama mencetak "16kHz" tanpa syarat meski mixer sebenarnya
            # 44100 Hz — log yang menyesatkan itu menyembunyikan penyebab suara
            # melengking dan patah-patah selama berhari-hari.
            init = pygame.mixer.get_init()
            self.mixer_rate = init[0] if init else SAMPLE_RATE
            logger.info(
                f"✅ Pygame mixer aktif: {self.mixer_rate} Hz, "
                f"{init[2] if init else '?'} channel, buffer=4096"
            )
            if self.mixer_rate != SAMPLE_RATE:
                logger.warning(
                    f"⚠️ Mixer berjalan di {self.mixer_rate} Hz sedangkan "
                    f"announcement masuk di {SAMPLE_RATE} Hz — audio akan "
                    f"di-resample sebelum diputar."
                )
        except Exception as e:
            logger.error(f"❌ Failed to init pygame mixer: {e}")
    
    def get_status(self) -> dict:
        """Get current announcement status"""
        return {
            "is_active": self.is_active,
            "state": self.state,
            "user_id": self.current_user_id,
            "username": self.current_username,
            "selected_speakers": self.selected_speakers,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "duration": (datetime.now() - self.started_at).total_seconds() if self.started_at else 0
        }
    
    async def start_announcement(
        self, 
        user_id: int, 
        username: str, 
        speaker_numbers: List[int],
        db: Session
    ) -> dict:
        """Start announcement process"""
        try:
            if self.is_active:
                return {
                    "success": False,
                    "message": "Announcement already in progress"
                }
            
            # Set state
            self.is_active = True
            self.state = "initializing"
            self.selected_speakers = speaker_numbers
            self.current_user_id = user_id
            self.current_username = username
            self.started_at = datetime.now()
            self.chunk_count = 0
            self.audio_buffer.clear()
            self.pending_sounds.clear()
            self._last_gain = None
            self.channel = None
            self.playback_started = False
            
            logger.info(f"📢 Starting announcement (16kHz): user={username}, speakers={speaker_numbers}")
            
            # Step 1: Pause music
            logger.info("⏸️ Pausing music...")
            if self.audio_service.is_playing:
                self.audio_service.pause()
                await asyncio.sleep(0.5)
            
            # ✅ Step 2: Save current speaker state
            logger.info("💾 Saving current speaker state...")
            all_speakers = SpeakerDatabaseService.get_all_speakers(db)
            self.speaker_state_before = {
                speaker.speaker_number: speaker.is_active 
                for speaker in all_speakers
            }
            logger.info(f"📊 Saved state: {self.speaker_state_before}")
            
            # ✅ Step 3: Turn OFF all speakers first
            logger.info("🔇 Turning OFF all speakers...")
            speaker_service = get_speaker_service()
            for speaker_num in range(1, 6):
                result = speaker_service.control_speaker(speaker_num, "OFF")
                if result.get("status") == "success":
                    SpeakerDatabaseService.update_speaker_status(db, speaker_num, False)
            
            await asyncio.sleep(0.3)
            
            # ✅ Step 4: Activate ONLY selected speakers
            logger.info(f"🔊 Activating selected speakers: {speaker_numbers}")
            for speaker_num in speaker_numbers:
                result = speaker_service.control_speaker(speaker_num, "ON")
                if result.get("status") == "success":
                    SpeakerDatabaseService.update_speaker_status(db, speaker_num, True)
                    logger.info(f"✅ Speaker {speaker_num} activated")
                else:
                    logger.warning(f"⚠️ Failed to activate speaker {speaker_num}")
            
            await asyncio.sleep(0.5)
            
            # Step 5: Play intro jingle
            logger.info("🔔 Playing intro jingle...")
            jingle_path = "static/uploads/jingle/announcement_jingle.mp3"
            await self._play_jingle(jingle_path)
            
            # Step 6: Set state to ready
            self.state = "ready"
            logger.info("✅ Ready for streaming (16kHz)")
            
            return {
                "success": True,
                "message": "Announcement initialized successfully"
            }
            
        except Exception as e:
            logger.error(f"❌ Error starting announcement: {e}")
            await self.stop_announcement(db)
            return {
                "success": False,
                "message": f"Failed to start announcement: {str(e)}"
            }
    
    async def _play_jingle(self, jingle_path: str):
        """Play jingle before/after announcement"""
        try:
            if not os.path.exists(jingle_path):
                logger.warning(f"⚠️ Jingle not found at: {jingle_path}")
                
                # Try alternative paths
                alternative_paths = [
                    "static/jingle/announcement_jingle.mp3",
                    "uploads/jingle/announcement_jingle.mp3",
                ]
                
                found = False
                for alt_path in alternative_paths:
                    if os.path.exists(alt_path):
                        jingle_path = alt_path
                        logger.info(f"✅ Found jingle at: {alt_path}")
                        found = True
                        break
                
                if not found:
                    logger.info("⚠️ Using beep sound instead")
                    await self._generate_beep()
                    return
            
            logger.info(f"🔔 Loading jingle from: {jingle_path}")
            
            # Load and play jingle
            sound = pygame.mixer.Sound(jingle_path)
            sound.set_volume(1.0)
            channel = sound.play()
            
            # Wait for jingle to finish
            while channel.get_busy():
                await asyncio.sleep(0.1)
            
            logger.info("✅ Jingle playback completed")
            
        except Exception as e:
            logger.error(f"❌ Error playing jingle: {e}")
            await self._generate_beep()
    
    async def _generate_beep(self):
        """Generate simple beep sound"""
        try:
            frequency = 880
            duration_ms = 200
            sample_rate = 16000  # CHANGED: Use 16kHz
            
            for i in range(3):
                # Generate beep
                num_samples = int(sample_rate * duration_ms / 1000)
                t = np.linspace(0, duration_ms / 1000, num_samples, dtype=np.float32)
                wave = np.sin(2 * np.pi * frequency * t)
                wave = (wave * 32767).astype(np.int16)
                
                # Create stereo
                stereo_wave = np.column_stack((wave, wave))
                
                try:
                    sound = pygame.sndarray.make_sound(stereo_wave)
                    sound.set_volume(0.8)
                    channel = sound.play()
                    
                    while channel.get_busy():
                        await asyncio.sleep(0.01)
                except Exception as e:
                    logger.error(f"❌ Error playing beep: {e}")
                    await asyncio.sleep(duration_ms / 1000)
                
                if i < 2:
                    await asyncio.sleep(0.2)
            
            logger.info("✅ Beep sequence completed")
            
        except Exception as e:
            logger.error(f"❌ Error generating beep: {e}")
            await asyncio.sleep(1.0)
    
    def _apply_simple_processing(self, audio_array: np.ndarray) -> np.ndarray:
        """Noise gate + penguatan volume untuk audio 16kHz.

        Dua aturan yang menentukan suaranya bersih atau kresek:

        1. Gain tidak boleh MELOMPAT di batas antar-chunk. Menerapkan satu nilai
           gain rata ke seluruh chunk membuat diskontinuitas di setiap sambungan
           — pada chunk 100 ms itu sepuluh klik per detik. Karena itu gain
           di-ramp dari nilai akhir chunk sebelumnya.

        2. Sinyal tidak boleh dipotong di batas int16. Penguatan tetap 2x
           meratakan puncak gelombang setiap kali pembicara bersuara keras.
           Gain diturunkan lebih dulu oleh limiter supaya puncaknya tetap utuh.
        """
        try:
            audio_float = audio_array.astype(np.float32)

            # 1. Noise gate — hitung gain TUJUAN untuk chunk ini, jangan
            #    langsung dikalikan.
            rms = float(np.sqrt(np.mean(audio_float ** 2)))
            if rms < self.noise_threshold:
                gate = 0.1
            elif rms < self.noise_threshold * 1.5:
                ratio = (rms - self.noise_threshold) / (self.noise_threshold * 0.5)
                gate = 0.1 + 0.9 * ratio
            else:
                gate = 1.0

            target_gain = gate * VOLUME_BOOST

            # 2. Limiter: turunkan gain kalau puncak chunk ini akan melewati
            #    headroom. Menurunkan gain terdengar sebagai "sedikit lebih
            #    pelan"; memotong terdengar sebagai distorsi.
            peak = float(np.max(np.abs(audio_float)))
            if peak > 0.0:
                target_gain = min(target_gain, HEADROOM / peak)

            # 3. Ramp gain dari nilai chunk sebelumnya ke nilai chunk ini.
            if self._last_gain is None:
                self._last_gain = target_gain

            gain = np.linspace(
                self._last_gain, target_gain, num=audio_float.size, dtype=np.float32
            )
            self._last_gain = target_gain

            audio_float *= gain

            # Jaring pengaman; limiter di atas seharusnya sudah mencegahnya.
            np.clip(audio_float, -32768.0, 32767.0, out=audio_float)

            return audio_float.astype(np.int16)

        except Exception as e:
            logger.error(f"❌ Error in audio processing: {e}")
            return audio_array
    
    async def process_audio_chunk(self, audio_data: bytes):
        """
        Process incoming PCM audio chunk - 16kHz VERSION
        Audio from Flutter: 16kHz, mono, int16
        """
        try:
            if self.state != "streaming":
                return
            
            # Convert bytes to numpy array (PCM int16)
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            
            if len(audio_array) < 50:
                return
            
            self.chunk_count += 1
            
            # Simple processing
            audio_processed = self._apply_simple_processing(audio_array)
            
            # Add to buffer
            self.audio_buffer.append(audio_processed)

            # Kumpulkan cadangan dulu sebelum bunyi pertama.
            if not self.playback_started:
                if len(self.audio_buffer) < PREROLL_CHUNKS:
                    return
                self.playback_started = True
                logger.info(
                    f"🎵 Starting playback (cadangan {len(self.audio_buffer)} chunk)"
                )

            # Ubah menjadi Sound berukuran TETAP, dan JANGAN kosongkan seluruh
            # sangga. Menguras habis setiap kali memutar menghapus cadangan yang
            # susah payah dikumpulkan, sehingga sistem kembali berjalan 1:1
            # tanpa toleransi jitter. Sisanya sengaja ditinggal di
            # pending_sounds — di situlah cadangan itu hidup.
            while len(self.audio_buffer) >= BATCH_CHUNKS:
                combined = np.concatenate(self.audio_buffer[:BATCH_CHUNKS])
                del self.audio_buffer[:BATCH_CHUNKS]

                combined = self._to_mixer_rate(combined)

                # Convert MONO to STEREO
                stereo_array = np.column_stack((combined, combined))

                try:
                    sound = pygame.sndarray.make_sound(stereo_array)
                    sound.set_volume(1.0)
                    # Jangan sound.play(): itu menyebar potongan ke channel
                    # berbeda-beda sehingga saling bertindihan. Sambung
                    # berurutan di satu channel khusus.
                    self.pending_sounds.append(sound)
                except Exception as e:
                    logger.error(f"❌ Pygame error: {e}")
                    break

            self._pump_playback()

            if self.chunk_count % 50 == 0:
                logger.info(
                    f"🎵 Chunk {self.chunk_count} "
                    f"(antre {len(self.pending_sounds)} sound, "
                    f"sisa {len(self.audio_buffer)} chunk)"
                )
            
        except Exception as e:
            logger.error(f"❌ Error processing chunk: {e}")
    
    def _to_mixer_rate(self, mono: np.ndarray) -> np.ndarray:
        """Ubah PCM 16 kHz ke laju mixer yang sedang berjalan.

        pygame.sndarray.make_sound() menafsirkan isi array MENGIKUTI laju mixer,
        bukan laju asli datanya. Menyerahkan 16 kHz mentah ke mixer 44100 Hz
        membuat tiap potongan diputar 2,76x lebih cepat: suaranya melengking
        seperti anak kecil, dan Sound 200 ms habis dalam 72 ms lalu menyisakan
        senyap sampai potongan berikutnya tiba — itulah suara patah-patah.
        """
        if self.mixer_rate == SAMPLE_RATE:
            return mono

        divisor = gcd(self.mixer_rate, SAMPLE_RATE)
        resampled = signal.resample_poly(
            mono.astype(np.float32),
            self.mixer_rate // divisor,
            SAMPLE_RATE // divisor,
        )
        np.clip(resampled, -32768.0, 32767.0, out=resampled)
        return resampled.astype(np.int16)

    def _pump_playback(self):
        """Sambungkan potongan berikutnya ke channel khusus announcement.

        pygame hanya menampung satu sound di antrean sebuah channel, dan
        Channel.queue() akan MENIMPA antrean yang sudah terisi. Karena itu
        potongan ditahan di self.pending_sounds dan hanya disusulkan saat masih
        ada tempat: satu sedang berbunyi, satu mengantre. Hasilnya sambungan
        tanpa jeda, tanpa tumpang tindih, dan tanpa potongan yang hilang.
        """
        if self.channel is None:
            self.channel = pygame.mixer.Channel(ANNOUNCEMENT_CHANNEL)

        while self.pending_sounds:
            if not self.channel.get_busy():
                self.channel.play(self.pending_sounds.popleft())
            elif self.channel.get_queue() is None:
                self.channel.queue(self.pending_sounds.popleft())
            else:
                break

    async def stop_announcement(self, db: Session):
        """Stop announcement and cleanup"""
        try:
            logger.info("🛑 Stopping announcement...")
            logger.info(f"📊 Total chunks: {self.chunk_count}")
            
            self.state = "stopping"
            
            # Play remaining buffered audio
            if self.audio_buffer:
                try:
                    combined = self._to_mixer_rate(
                        np.concatenate(self.audio_buffer)
                    )
                    stereo_array = np.column_stack((combined, combined))
                    sound = pygame.sndarray.make_sound(stereo_array)
                    sound.set_volume(1.0)

                    # Sambung ke antrean yang sama supaya sisa terakhir tidak
                    # bertabrakan dengan potongan yang masih berbunyi.
                    self.pending_sounds.append(sound)

                    logger.info(f"✅ Played remaining buffer ({len(combined)} samples)")
                except Exception as e:
                    logger.error(f"❌ Error playing remaining buffer: {e}")
                
                self.audio_buffer.clear()

            # Tunggu seluruh antrean habis sebelum menutup, kalau tidak kata
            # terakhir pembicara ikut terpotong.
            try:
                while self.pending_sounds or (
                    self.channel is not None and self.channel.get_busy()
                ):
                    self._pump_playback()
                    await asyncio.sleep(0.01)
            except Exception as e:
                logger.error(f"❌ Error draining playback queue: {e}")
            
            # Stop all pygame sounds
            self.pending_sounds.clear()
            pygame.mixer.stop()
            self.channel = None
            
            # Small delay for audio cleanup
            await asyncio.sleep(0.3)
            
            # Play outro dan TUNGGU sampai selesai
            logger.info("🔔 Playing outro jingle...")
            await self._play_outro_async()
            
            # ✅ Restore speaker state to before announcement
            logger.info("🔄 Restoring speaker state...")
            speaker_service = get_speaker_service()
            
            if self.speaker_state_before:
                logger.info(f"📊 Restoring to: {self.speaker_state_before}")
                
                for speaker_num in range(1, 6):
                    # Get previous state (default to True if not in saved state)
                    previous_state = self.speaker_state_before.get(speaker_num, True)
                    action = "ON" if previous_state else "OFF"
                    
                    result = speaker_service.control_speaker(speaker_num, action)
                    if result.get("status") == "success":
                        SpeakerDatabaseService.update_speaker_status(db, speaker_num, previous_state)
                        logger.info(f"✅ Speaker {speaker_num} restored to {action}")
                    else:
                        logger.warning(f"⚠️ Failed to restore speaker {speaker_num}")
                
                # Clear saved state
                self.speaker_state_before = {}
            else:
                logger.warning("⚠️ No saved speaker state, turning all ON by default")
                # Fallback: turn all speakers ON
                for speaker_num in range(1, 6):
                    result = speaker_service.control_speaker(speaker_num, "ON")
                    if result.get("status") == "success":
                        SpeakerDatabaseService.update_speaker_status(db, speaker_num, True)
            
            await asyncio.sleep(0.3)
            
            # Resume music SETELAH speaker restored
            logger.info("▶️ Resuming music...")
            if self.audio_service.is_paused:
                self.audio_service.resume()
            
            # Reset state
            duration = (datetime.now() - self.started_at).total_seconds() if self.started_at else 0
            logger.info(f"✅ Announcement stopped. Duration: {duration:.1f}s")
            
            self.is_active = False
            self.state = "idle"
            self.selected_speakers = []
            self.current_user_id = None
            self.current_username = None
            self.started_at = None
            self.chunk_count = 0
            
        except Exception as e:
            logger.error(f"❌ Error stopping: {e}")
            self.is_active = False
            self.state = "idle"
            self.speaker_state_before = {}

    async def _play_outro_async(self):
        """Play outro jingle and WAIT until finished"""
        try:
            outro_path = "static/jingle/announcement_jingle_outro.mp3"
            
            if not os.path.exists(outro_path):
                logger.warning(f"⚠️ Outro not found at: {outro_path}, checking alternatives...")
                
                # Try alternative paths
                alternative_paths = [
                    "static/uploads/jingle/announcement_jingle_outro.mp3",
                    "uploads/jingle/announcement_jingle_outro.mp3",
                ]
                
                found = False
                for alt_path in alternative_paths:
                    if os.path.exists(alt_path):
                        outro_path = alt_path
                        logger.info(f"✅ Found outro at: {alt_path}")
                        found = True
                        break
                
                if not found:
                    logger.warning("⚠️ Outro file not found, skipping")
                    return
            
            logger.info(f"🔔 Loading outro from: {outro_path}")
            
            # Load and play outro
            outro_sound = pygame.mixer.Sound(outro_path)
            outro_sound.set_volume(1.0)
            outro_channel = outro_sound.play()
            
            # WAIT until outro finishes
            while outro_channel.get_busy():
                await asyncio.sleep(0.1)
            
            logger.info("✅ Outro playback completed")
            
            # Cleanup
            del outro_sound
            
        except Exception as e:
            logger.error(f"❌ Error playing outro: {e}")


# Global instance
_announcement_service_instance = None

def get_announcement_service() -> AnnouncementService:
    """Get singleton instance of AnnouncementService"""
    global _announcement_service_instance
    if _announcement_service_instance is None:
        _announcement_service_instance = AnnouncementService()
    return _announcement_service_instance