# backend/services/bell_scheduler_service.py
from datetime import datetime, time as dt_time, date
from sqlalchemy.orm import Session
from models import BellScheduleModel, BellScheduleStatusModel
from database import get_db
from services.bell_serial_service import get_bell_service
import asyncio
import logging

logger = logging.getLogger(__name__)


class BellSchedulerService:
    """
    Background scheduler untuk trigger bell berdasarkan jadwal di database
    Berjalan terus di background, cek setiap 30 detik
    """
    
    def __init__(self):
        self.is_running = False
        self.checked_schedules = set()  # Track jadwal yang sudah dijalankan hari ini
        self._last_reset_date = None
    
    def get_today_day_name(self) -> str:
        """
        Mendapatkan nama hari ini (lowercase)
        Returns: "monday", "tuesday", ..., "sunday"
        """
        day_names = [
            "monday", "tuesday", "wednesday", "thursday", 
            "friday", "saturday", "sunday"
        ]
        today = datetime.now().weekday()  # 0 = Monday, 6 = Sunday
        return day_names[today]
    
    def should_run_bell(self, db: Session, day_name: str) -> bool:
        """
        Cek apakah bell schedule harus dijalankan untuk hari tertentu
        
        Args:
            db: Database session
            day_name: "monday", "tuesday", ..., "sunday"
        
        Returns:
            bool: True jika schedule harus dijalankan, False jika inactive
        """
        status = db.query(BellScheduleStatusModel).first()
        if not status:
            # Jika belum ada status, buat default (semua active)
            status = BellScheduleStatusModel(
                monday_active=True,
                tuesday_active=True,
                wednesday_active=True,
                thursday_active=True,
                friday_active=True,
                saturday_active=True,
                sunday_active=True
            )
            db.add(status)
            db.commit()
            return True
        
        # Cek status berdasarkan day_name
        is_active = getattr(status, f"{day_name}_active", True)
        
        if not is_active:
            logger.debug(f"{day_name} schedule is inactive")
        
        return is_active
    
    def get_schedule_key(self, schedule: BellScheduleModel) -> str:
        """Generate unique key untuk schedule"""
        return f"{schedule.schedule_type}_{schedule.time.hour}:{schedule.time.minute}"
    
    def reset_daily_check(self):
        """Reset checked schedules setiap hari berganti"""
        current_date = date.today()
        if self._last_reset_date != current_date:
            self.checked_schedules.clear()
            self._last_reset_date = current_date
            logger.info(f"📅 Reset checked schedules untuk tanggal baru: {current_date}")
    
    async def check_schedules(self, db: Session):
        """Cek dan jalankan jadwal yang sesuai"""
        # Reset checked schedules jika hari berganti
        self.reset_daily_check()
        
        # Tentukan hari ini
        day_name = self.get_today_day_name()
        
        # Cek apakah hari ini aktif
        if not self.should_run_bell(db, day_name):
            return
        
        now = datetime.now().time()
        
        # Ambil jadwal hari ini
        schedules = db.query(BellScheduleModel).filter(
            BellScheduleModel.schedule_type == day_name
        ).all()
        
        for schedule in schedules:
            schedule_key = self.get_schedule_key(schedule)
            
            # Skip jika jadwal ini sudah dijalankan hari ini
            if schedule_key in self.checked_schedules:
                continue
            
            # Cek apakah waktu sekarang cocok dengan jadwal (toleransi dalam 1 menit)
            schedule_time = schedule.time
            if (schedule_time.hour == now.hour and 
                schedule_time.minute == now.minute):
                
                logger.info(f"🔔 Menjalankan bell schedule: {day_name} at {schedule_time}, count={schedule.count}, duration={schedule.duration}ms")
                
                try:
                    # Trigger bell via serial
                    bell_service = get_bell_service()
                    result = bell_service.trigger_bell(schedule.count, schedule.duration)
                    
                    if result.get("status") == "success":
                        # Tandai jadwal ini sudah dijalankan
                        self.checked_schedules.add(schedule_key)
                        logger.info(f"✅ Bell schedule berhasil dijalankan: {schedule_key}")
                    else:
                        logger.error(f"❌ Bell trigger failed: {result.get('message')}")
                    
                except Exception as e:
                    logger.error(f"❌ Error saat menjalankan bell: {e}")
    
    async def start(self):
        """Mulai background scheduler"""
        self.is_running = True
        self._last_reset_date = date.today()
        logger.info("🚀 Bell Scheduler Service started")
        
        while self.is_running:
            db = next(get_db())
            try:
                await self.check_schedules(db)
            except Exception as e:
                logger.error(f"❌ Error in bell scheduler: {e}")
            finally:
                db.close()
            
            # Check setiap 30 detik
            await asyncio.sleep(30)
        
        logger.info("🛑 Bell Scheduler Service stopped")
    
    def stop(self):
        """Stop scheduler"""
        self.is_running = False
        logger.info("⏸️ Bell Scheduler Service stopping...")


# Global instance
bell_scheduler_service = BellSchedulerService()