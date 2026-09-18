import pygame
import threading
import time
from mutagen.mp3 import MP3
from mutagen.wave import WAVE
from mutagen.flac import FLAC
from mutagen.oggvorbis import OggVorbis
from mutagen.mp4 import MP4
import os
import logging
from pathlib import Path
import subprocess

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AudioService:
    """
    Service untuk mengelola audio playback menggunakan pygame mixer
    Playlist otomatis dibuat dari semua file di folder upload
    Shared untuk semua pengguna
    """
    
    SUPPORTED_FORMATS = ['.mp3', '.wav', '.flac', '.ogg', '.oga', '.m4a', '.mp4', '.aac']
    
    def __init__(self, upload_folder: str = "static/uploads"):
        """
        Inisialisasi audio service
        
        Args:
            upload_folder: Path ke folder yang berisi file musik
        """
        try:
            # Init pygame mixer dengan pengaturan optimal untuk OrangePi
            pygame.mixer.init(
                frequency=44100,  # Sample rate
                size=-16,         # 16-bit audio
                channels=2,       # Stereo
                buffer=2048       # Buffer size
            )
            logger.info("✓ Audio service initialized successfully")
        except Exception as e:
            logger.error(f"✗ Failed to initialize audio service: {e}")
            raise
        
        # Upload folder path
        self.upload_folder = upload_folder
        os.makedirs(upload_folder, exist_ok=True)
        
        # State variables
        self.current_music = None
        self.is_playing = False
        self.is_paused = False
        self.volume = 70
        self.position = 0.0
        self.duration = 0.0
        
        # Playlist variables
        self.playlist = []  # List of {title, filepath}
        self.current_index = 0
        self.auto_play = True  # Auto play next song (hanya untuk lanjut ke lagu berikutnya)
        self.repeat_mode = "all"  # "all", "one", "off"
        
        # Thread untuk tracking posisi
        self.position_thread = None
        self.stop_position_thread = False
        self._lock = threading.Lock()
        
        # Set volume awal
        pygame.mixer.music.set_volume(self.volume / 100.0)
        logger.info(f"✓ Initial volume set to {self.volume}%")
        
        # Load playlist dari folder tanpa auto-play
        self.refresh_playlist()
    
    def refresh_playlist(self):
        """
        Scan folder upload dan refresh playlist.
        Lagu baru akan masuk ke playlist tanpa auto-play.
        Dipanggil otomatis saat init dan bisa dipanggil manual (misal: setelah upload).
        """
        try:
            with self._lock:
                self.playlist = []
                
                # Scan semua file di folder upload
                if os.path.exists(self.upload_folder):
                    for filename in sorted(os.listdir(self.upload_folder)):
                        filepath = os.path.join(self.upload_folder, filename)
                        
                        # Hanya ambil file (bukan folder)
                        if not os.path.isfile(filepath):
                            continue
                        
                        # Check ekstensi file
                        ext = os.path.splitext(filename)[1].lower()
                        if ext not in self.SUPPORTED_FORMATS:
                            continue
                        
                        # Tambahkan ke playlist
                        title = os.path.splitext(filename)[0]  # Nama file tanpa ekstensi
                        self.playlist.append({
                            "title": title,
                            "filepath": filepath,
                            "filename": filename
                        })
                
                logger.info(f"✓ Playlist refreshed: {len(self.playlist)} songs found")
                
                # Jika musik yang sedang diputar masih ada di playlist, update index-nya
                if self.current_music and self.is_playing:
                    current_found = False
                    for i, music in enumerate(self.playlist):
                        if music['filepath'] == self.current_music['filepath']:
                            self.current_index = i
                            current_found = True
                            break
                    
                    # Jika musik yang sedang diputar sudah dihapus dari folder, stop
                    if not current_found:
                        logger.warning("⚠ Currently playing music no longer in folder")
                        pygame.mixer.music.stop()
                        self.is_playing = False
                        self.is_paused = False
                        self.position = 0.0
                        self.current_music = None
                        self.current_index = 0

                # Tidak ada auto-play saat refresh playlist
                # Music hanya diputar jika user eksplisit menekan play dari frontend

        except Exception as e:
            logger.error(f"✗ Error refreshing playlist: {e}")
    
    def get_audio_duration(self, filepath: str) -> float:
        """
        Dapatkan durasi audio dalam detik
        Support: MP3, WAV, FLAC, OGG, M4A, AAC
        """
        try:
            if not os.path.exists(filepath):
                logger.error(f"✗ File not found: {filepath}")
                return 0.0
            
            ext = os.path.splitext(filepath)[1].lower()
            audio = None
            
            if ext == '.mp3':
                audio = MP3(filepath)
            elif ext == '.wav':
                audio = WAVE(filepath)
            elif ext == '.flac':
                audio = FLAC(filepath)
            elif ext in ['.ogg', '.oga']:
                audio = OggVorbis(filepath)
            elif ext in ['.m4a', '.mp4', '.aac']:
                audio = MP4(filepath)
            else:
                logger.warning(f"⚠ Unsupported audio format: {ext}")
                return 0.0
            
            if audio and hasattr(audio.info, 'length'):
                duration = float(audio.info.length)
                return duration
            
            return 0.0
            
        except Exception as e:
            logger.error(f"✗ Error getting duration: {e}")
            return 0.0
    
    def _update_position(self):
        """
        Background thread untuk update posisi playback
        Berjalan selama musik diputar
        """
        logger.info("► Position tracking thread started")
        
        while not self.stop_position_thread:
            try:
                should_play_next = False
                
                with self._lock:
                    if self.is_playing and not self.is_paused:
                        # Update posisi (increment setiap 0.1 detik)
                        self.position += 0.1
                        
                        # Cek apakah musik sudah selesai
                        if self.position >= self.duration and self.duration > 0:
                            logger.info("♪ Music playback completed")
                            
                            # Auto play next song jika enabled
                            if self.auto_play:
                                should_play_next = True
                            else:
                                self.is_playing = False
                                self.is_paused = False
                                self.position = 0.0
                                self.current_music = None
                
                # Play next outside the lock
                if should_play_next:
                    self._play_next_in_playlist()
                
                time.sleep(0.1)
                
            except Exception as e:
                logger.error(f"✗ Error in position thread: {e}")
                time.sleep(0.5)
        
        logger.info("■ Position tracking thread stopped")
    
    def _play_next_in_playlist(self):
        """
        Internal method untuk memutar lagu berikutnya dalam playlist
        Dipanggil otomatis saat lagu selesai
        """
        try:
            # Refresh playlist untuk update terbaru
            self.refresh_playlist()
            
            if len(self.playlist) == 0:
                logger.info("⚠ Playlist is empty, stopping playback")
                with self._lock:
                    self.is_playing = False
                    self.is_paused = False
                    self.position = 0.0
                    self.current_music = None
                return
            
            with self._lock:
                if self.repeat_mode == "one":
                    # Repeat lagu yang sama
                    next_index = self.current_index
                else:
                    # Lanjut ke lagu berikutnya
                    next_index = self.current_index + 1
                    
                    if next_index >= len(self.playlist):
                        if self.repeat_mode == "all":
                            next_index = 0  # Kembali ke awal playlist
                            logger.info("🔁 Restarting playlist from beginning")
                        else:
                            logger.info("✓ Playlist completed")
                            self.is_playing = False
                            self.is_paused = False
                            self.position = 0.0
                            self.current_music = None
                            return
                
                self.current_index = next_index
            
            # Play lagu berikutnya
            self.play_by_index(next_index)
            
        except Exception as e:
            logger.error(f"✗ Error playing next song: {e}")
            with self._lock:
                self.is_playing = False
    
    def play_by_index(self, index: int):
        """
        Putar musik berdasarkan index di playlist
        
        Args:
            index: Index lagu di playlist (0-based)
        """
        with self._lock:
            if index < 0 or index >= len(self.playlist):
                logger.error(f"✗ Invalid playlist index: {index}")
                return
            
            music = self.playlist[index]
            filepath = music['filepath']
            title = music['title']
        
        self.play(filepath, title)
    
    def play_by_filename(self, filename: str):
        """
        Putar musik berdasarkan nama file
        
        Args:
            filename: Nama file musik di folder upload
        """
        filepath = os.path.join(self.upload_folder, filename)
        
        logger.info(f"[play_by_filename] Filename: {filename}")
        logger.info(f"[play_by_filename] Upload folder: {self.upload_folder}")
        logger.info(f"[play_by_filename] Full path: {filepath}")
        logger.info(f"[play_by_filename] File exists: {os.path.exists(filepath)}")
        
        if not os.path.exists(filepath):
            logger.error(f"✗ File not found: {filename}")
            logger.error(f"✗ Searched in: {self.upload_folder}")
            if os.path.exists(self.upload_folder):
                files = os.listdir(self.upload_folder)
                logger.error(f"✗ Available files: {files}")
            raise FileNotFoundError(f"File not found: {filename}")
        
        # Update playlist dulu
        self.refresh_playlist()
        
        # Cari index di playlist
        with self._lock:
            for i, music in enumerate(self.playlist):
                if music['filename'] == filename:
                    self.current_index = i
                    logger.info(f"✓ Found in playlist at index {i}")
                    break
            else:
                logger.warning(f"⚠ File not in playlist, adding it")
        
        title = os.path.splitext(filename)[0]
        logger.info(f"► Playing: {title}")
        self.play(filepath, title)
    
    def play(self, filepath: str, title: str):
        """
        Putar musik dari filepath
        
        Args:
            filepath: Path ke file audio
            title: Judul musik
        """
        try:
            if not os.path.exists(filepath):
                raise FileNotFoundError(f"Audio file not found: {filepath}")
            
            logger.info(f"► Loading music: {title}")
            
            # Stop musik sebelumnya jika ada
            if self.is_playing:
                pygame.mixer.music.stop()
            
            with self._lock:
                # Load dan play musik
                pygame.mixer.music.load(filepath)
                pygame.mixer.music.play()
                
                # Update state
                self.current_music = {
                    "title": title,
                    "filepath": filepath,
                    "filename": os.path.basename(filepath)
                }
                
                self.is_playing = True
                self.is_paused = False
                self.position = 0.0
                self.duration = self.get_audio_duration(filepath)
            
            logger.info(f"♪ Now playing: '{title}' ({self.current_index + 1}/{len(self.playlist)}) Duration: {self.duration:.1f}s")
            
            # Start position tracking thread jika belum ada
            if self.position_thread is None or not self.position_thread.is_alive():
                self.stop_position_thread = False
                self.position_thread = threading.Thread(
                    target=self._update_position,
                    daemon=True,
                    name="AudioPositionTracker"
                )
                self.position_thread.start()
            
        except Exception as e:
            logger.error(f"✗ Error playing audio: {e}")
            raise Exception(f"Error playing audio: {str(e)}")
    
    def pause(self):
        """Pause musik yang sedang diputar"""
        with self._lock:
            if self.is_playing and not self.is_paused:
                pygame.mixer.music.pause()
                self.is_paused = True
                self.is_playing = False
                logger.info("❚❚ Music paused")

    def resume(self):
        """Resume musik yang di-pause"""
        with self._lock:
            if not self.is_playing and self.is_paused:
                pygame.mixer.music.unpause()
                self.is_paused = False
                self.is_playing = True
                logger.info("► Music resumed")

    def stop(self):
        """Stop musik dan reset state"""
        with self._lock:
            pygame.mixer.music.stop()
            self.is_playing = False
            self.is_paused = False
            self.position = 0.0
            logger.info("■ Music stopped")
    
    def skip_next(self):
        """Skip ke lagu berikutnya dalam playlist"""
        self.refresh_playlist()
        
        if len(self.playlist) == 0:
            logger.warning("⚠ Cannot skip: Playlist is empty")
            return
        
        with self._lock:
            next_index = self.current_index + 1
            if next_index >= len(self.playlist):
                next_index = 0
            
            self.current_index = next_index
        
        logger.info(f"⏭ Skipping to next song")
        self.play_by_index(next_index)
    
    def skip_previous(self):
        """Skip ke lagu sebelumnya dalam playlist"""
        self.refresh_playlist()
        
        if len(self.playlist) == 0:
            logger.warning("⚠ Cannot skip: Playlist is empty")
            return
        
        with self._lock:
            # Jika posisi > 3 detik, restart lagu current
            if self.position > 3.0:
                self.position = 0.0
                pygame.mixer.music.play()
                logger.info("⏮ Restarting current song")
                return
            
            prev_index = self.current_index - 1
            if prev_index < 0:
                prev_index = len(self.playlist) - 1
            
            self.current_index = prev_index
        
        logger.info(f"⏮ Skipping to previous song")
        self.play_by_index(prev_index)
    
    def set_volume(self, volume: int):
        """
        Set volume player
        
        Args:
            volume: Volume level (0-100)
        """
        with self._lock:
            self.volume = max(0, min(100, volume))
            pygame.mixer.music.set_volume(self.volume / 100.0)
            logger.info(f"🔊 Volume set to {self.volume}%")
    
    def set_repeat_mode(self, mode: str):
        """
        Set repeat mode
        
        Args:
            mode: "all", "one", atau "off"
        """
        if mode in ["all", "one", "off"]:
            with self._lock:
                self.repeat_mode = mode
            logger.info(f"🔁 Repeat mode: {mode}")
        else:
            logger.warning(f"⚠ Invalid repeat mode: {mode}")
    
    def seek(self, position: float):
        """
        Pindah ke posisi tertentu dalam musik
        
        Args:
            position: Posisi dalam detik
        
        Note:
            - set_pos() hanya bekerja untuk MP3 dan OGG
            - Untuk format lain, musik akan di-reload dan play dari position
        """
        if not self.is_playing or not self.current_music:
            logger.warning("⚠ Cannot seek: No music playing")
            return
        
        try:
            with self._lock:
                position = max(0.0, min(position, self.duration))
                
                try:
                    pygame.mixer.music.set_pos(position)
                    self.position = position
                    logger.info(f"⏩ Seeked to {position:.1f}s")
                except NotImplementedError:
                    logger.info(f"⏩ Reloading music to seek to {position:.1f}s")
                    was_paused = self.is_paused
                    
                    pygame.mixer.music.load(self.current_music["filepath"])
                    pygame.mixer.music.play(start=position)
                    self.position = position
                    
                    if was_paused:
                        pygame.mixer.music.pause()
                        self.is_paused = True
                        
        except Exception as e:
            logger.error(f"✗ Error seeking: {e}")
    
    def delete_music(self, filename: str):
        """
        Hapus file musik dari folder dan refresh playlist
        
        Args:
            filename: Nama file yang akan dihapus
        """
        try:
            filepath = os.path.join(self.upload_folder, filename)
            
            is_current = False
            if self.current_music and self.current_music['filename'] == filename:
                is_current = True
            
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"🗑️ Deleted file: {filename}")
            
            self.refresh_playlist()
            
            if is_current and self.is_playing:
                logger.info("⏭ Deleted song was playing, skipping to next")
                if len(self.playlist) > 0:
                    self.skip_next()
                else:
                    self.stop()
                    
        except Exception as e:
            logger.error(f"✗ Error deleting music: {e}")
            raise
    
    def get_status(self) -> dict:
        """
        Dapatkan status player saat ini
        
        Returns:
            dict: Status player dengan informasi lengkap
        """
        with self._lock:
            return {
                "is_playing": self.is_playing,
                "is_paused": self.is_paused,
                "volume": self.volume,
                "position": round(self.position, 1),
                "duration": round(self.duration, 1),
                "current_music": self.current_music,
                "playlist_count": len(self.playlist),
                "current_index": self.current_index,
                "repeat_mode": self.repeat_mode,
                "auto_play": self.auto_play
            }
    
    def get_playlist(self) -> list:
        """Dapatkan playlist saat ini"""
        with self._lock:
            return self.playlist.copy()
    
    def get_formatted_position(self) -> str:
        """Format posisi ke MM:SS"""
        minutes = int(self.position // 60)
        seconds = int(self.position % 60)
        return f"{minutes:02d}:{seconds:02d}"
    
    def get_formatted_duration(self) -> str:
        """Format durasi ke MM:SS"""
        minutes = int(self.duration // 60)
        seconds = int(self.duration % 60)
        return f"{minutes:02d}:{seconds:02d}"
    
    def __del__(self):
        """Cleanup saat service dihapus"""
        try:
            self.stop_position_thread = True
            if self.position_thread and self.position_thread.is_alive():
                self.position_thread.join(timeout=1.0)
            pygame.mixer.quit()
            logger.info("✓ Audio service cleaned up")
        except Exception as e:
            logger.error(f"✗ Error during cleanup: {e}")


# Singleton instance
_audio_service_instance = None

def get_audio_service(upload_folder: str = "static/uploads") -> AudioService:
    """
    Get singleton instance of AudioService
    
    Args:
        upload_folder: Path ke folder yang berisi file musik (default: static/uploads)
    """
    global _audio_service_instance
    if _audio_service_instance is None:
        _audio_service_instance = AudioService(upload_folder)
    return _audio_service_instance