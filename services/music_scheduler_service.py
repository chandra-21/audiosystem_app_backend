# backend/services/music_scheduler_service.py
import asyncio
import logging
from datetime import datetime, time as datetime_time
from typing import Optional

from database import SessionLocal
import models

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MusicSchedulerService:
    """
    Service untuk menjalankan music schedule di background
    
    Logic:
    - Hanya aktif Senin-Jumat
    - Jam START: Auto-play jika music OFF
    - Jam END: Force stop apapun kondisinya
    - Di luar jam schedule: User bebas control manual
    """
    
    def __init__(self):
        self.is_running = False
        self._task = None
        self._check_interval = 30  # Check setiap 30 detik
        
    async def start(self):
        """Start scheduler service"""
        self.is_running = True
        logger.info("🎵 Music Scheduler Service started")
        
        try:
            while self.is_running:
                await self._check_and_execute_schedule()
                await asyncio.sleep(self._check_interval)
        except asyncio.CancelledError:
            logger.info("🛑 Music Scheduler Service cancelled")
        except Exception as e:
            logger.error(f"❌ Error in Music Scheduler: {e}")
            import traceback
            traceback.print_exc()
    
    def stop(self):
        """Stop scheduler service"""
        self.is_running = False
        logger.info("🛑 Music Scheduler Service stopped")
    
    async def _check_and_execute_schedule(self):
        """
        Check schedule dan execute action jika perlu
        """
        try:
            # Get schedule from database
            db = SessionLocal()
            try:
                schedule = db.query(models.MusicSchedule).first()
                
                if not schedule:
                    # Tidak ada schedule, skip
                    return
                
                if not schedule.is_active:
                    # Schedule inactive, skip
                    return
                
                # Check apakah hari ini weekday (Senin-Jumat)
                now = datetime.now()
                weekday_num = now.weekday()  # 0=Monday, 6=Sunday
                
                if weekday_num >= 5:  # Saturday or Sunday
                    # Weekend, skip
                    return
                
                current_time = now.time()
                
                # Import audio service
                from services.audio_service import get_audio_service
                audio_service = get_audio_service()
                
                # ============================================
                # LOGIC 1: AUTO START di jam start_time
                # ============================================
                if self._is_time_to_start(current_time, schedule.start_time):
                    # Cek apakah music sedang OFF
                    if not audio_service.is_playing and not audio_service.is_paused:
                        logger.info("⏰ Schedule START time reached - Auto starting music")
                        
                        # Refresh playlist
                        audio_service.refresh_playlist()
                        
                        if len(audio_service.playlist) > 0:
                            audio_service.play_by_index(0)
                            logger.info(f"✅ Music auto-started at {current_time.strftime('%H:%M:%S')}")
                        else:
                            logger.warning("⚠️ Cannot start music: Playlist is empty")
                    else:
                        logger.debug(f"⏩ Schedule START time but music already playing/paused - no action")
                
                # ============================================
                # LOGIC 2: FORCE STOP di jam end_time
                # ============================================
                elif self._is_time_to_stop(current_time, schedule.end_time):
                    # Paksa stop apapun kondisinya
                    if audio_service.is_playing or audio_service.is_paused:
                        logger.info("⏰ Schedule END time reached - Force stopping music")
                        audio_service.stop()
                        logger.info(f"✅ Music force-stopped at {current_time.strftime('%H:%M:%S')}")
                    else:
                        logger.debug(f"⏩ Schedule END time but music already stopped - no action")
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"❌ Error checking schedule: {e}")
            import traceback
            traceback.print_exc()
    
    def _is_time_to_start(self, current_time: datetime_time, start_time: datetime_time) -> bool:
        """
        Check apakah sekarang adalah waktu untuk START
        
        Toleransi: ±check_interval detik dari start_time
        Misal start_time = 08:00:00, check_interval = 30
        Maka akan trigger jika current_time antara 08:00:00 - 08:00:30
        """
        # Convert to seconds since midnight
        current_seconds = current_time.hour * 3600 + current_time.minute * 60 + current_time.second
        start_seconds = start_time.hour * 3600 + start_time.minute * 60 + start_time.second
        
        # Check if within tolerance window
        diff = current_seconds - start_seconds
        return 0 <= diff < self._check_interval
    
    def _is_time_to_stop(self, current_time: datetime_time, end_time: datetime_time) -> bool:
        """
        Check apakah sekarang adalah waktu untuk STOP
        
        Toleransi: ±check_interval detik dari end_time
        """
        # Convert to seconds since midnight
        current_seconds = current_time.hour * 3600 + current_time.minute * 60 + current_time.second
        end_seconds = end_time.hour * 3600 + end_time.minute * 60 + end_time.second
        
        # Check if within tolerance window
        diff = current_seconds - end_seconds
        return 0 <= diff < self._check_interval
    
    async def trigger_start_now(self):
        """Manual trigger untuk testing"""
        from services.audio_service import get_audio_service
        audio_service = get_audio_service()
        
        audio_service.refresh_playlist()
        if len(audio_service.playlist) > 0:
            audio_service.play_by_index(0)
            logger.info("✅ Music manually triggered to start")
        else:
            logger.warning("⚠️ Cannot start: Playlist is empty")
    
    async def trigger_stop_now(self):
        """Manual trigger untuk testing"""
        from services.audio_service import get_audio_service
        audio_service = get_audio_service()
        
        audio_service.stop()
        logger.info("✅ Music manually triggered to stop")


# Singleton instance
music_scheduler_service = MusicSchedulerService()


def get_music_scheduler_service() -> MusicSchedulerService:
    """Get singleton instance of MusicSchedulerService"""
    return music_scheduler_service