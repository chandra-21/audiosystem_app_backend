# backend/routers/music_schedule.py - NO AUTH VERSION
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, time as datetime_time
import logging

import models
import schemas
from database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/music-schedule", tags=["music-schedule"])

# =====================================================
# HELPER FUNCTIONS
# =====================================================

def get_schedule(db: Session) -> Optional[models.MusicSchedule]:
    """Get the single music schedule (hanya ada 1 row)"""
    return db.query(models.MusicSchedule).first()


def is_weekday() -> bool:
    """Check apakah hari ini weekday (Senin-Jumat)"""
    return datetime.now().weekday() < 5


def is_in_schedule_time(schedule: models.MusicSchedule) -> bool:
    """Check apakah waktu sekarang dalam rentang schedule"""
    now = datetime.now().time()
    return schedule.start_time <= now < schedule.end_time


# =====================================================
# GET SCHEDULE STATUS
# =====================================================

@router.get("/status", response_model=schemas.MusicScheduleStatusResponse)
async def get_schedule_status(db: Session = Depends(get_db)):
    """Get status schedule saat ini dengan informasi lengkap"""
    from services.audio_service import get_audio_service
    audio_service = get_audio_service()
    
    schedule = get_schedule(db)
    now = datetime.now()
    current_time_str = now.strftime("%H:%M:%S")
    weekday = is_weekday()
    
    response = {
        "has_schedule": schedule is not None,
        "schedule": schedule,
        "current_time": current_time_str,
        "is_weekday": weekday,
        "should_be_playing": False,
        "actual_playing": audio_service.is_playing,
        "next_action": None,
        "next_action_time": None
    }
    
    if schedule and schedule.is_active and weekday:
        in_range = is_in_schedule_time(schedule)
        response["should_be_playing"] = in_range
        
        current_time = now.time()
        if current_time < schedule.start_time:
            response["next_action"] = "start"
            response["next_action_time"] = schedule.start_time.strftime("%H:%M")
        elif current_time < schedule.end_time:
            response["next_action"] = "stop"
            response["next_action_time"] = schedule.end_time.strftime("%H:%M")
        else:
            response["next_action"] = "start (tomorrow)"
            response["next_action_time"] = schedule.start_time.strftime("%H:%M")
    
    return response


# =====================================================
# GET SCHEDULE
# =====================================================

@router.get("/", response_model=Optional[schemas.MusicScheduleResponse])
async def get_music_schedule(db: Session = Depends(get_db)):
    """Get music schedule (hanya ada 1 schedule)"""
    schedule = get_schedule(db)
    return schedule


# =====================================================
# CREATE OR UPDATE SCHEDULE
# =====================================================

@router.post("/set", response_model=schemas.MusicScheduleResponse)
async def set_music_schedule(
    schedule_data: schemas.MusicScheduleCreate,
    db: Session = Depends(get_db)
):
    """
    Create atau update music schedule
    Hanya ada 1 schedule dalam sistem (singleton pattern)
    """
    # Validasi waktu
    if schedule_data.end_time <= schedule_data.start_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end_time harus lebih besar dari start_time"
        )
    
    existing_schedule = get_schedule(db)
    
    if existing_schedule:
        # Update existing
        existing_schedule.start_time = schedule_data.start_time
        existing_schedule.end_time = schedule_data.end_time
        existing_schedule.is_active = schedule_data.is_active
        existing_schedule.updated_at = datetime.now()
        
        db.commit()
        db.refresh(existing_schedule)
        
        logger.info(f"Music schedule updated: {schedule_data.start_time} - {schedule_data.end_time}")
        return existing_schedule
    else:
        # Create new
        new_schedule = models.MusicSchedule(
            start_time=schedule_data.start_time,
            end_time=schedule_data.end_time,
            is_active=schedule_data.is_active
        )
        
        db.add(new_schedule)
        db.commit()
        db.refresh(new_schedule)
        
        logger.info(f"Music schedule created: {schedule_data.start_time} - {schedule_data.end_time}")
        return new_schedule


# =====================================================
# UPDATE SCHEDULE
# =====================================================

@router.patch("/update", response_model=schemas.MusicScheduleResponse)
async def update_music_schedule(
    schedule_data: schemas.MusicScheduleUpdate,
    db: Session = Depends(get_db)
):
    """Update music schedule (partial update)"""
    schedule = get_schedule(db)
    
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Music schedule not found. Use POST /set to create."
        )
    
    if schedule_data.start_time is not None:
        schedule.start_time = schedule_data.start_time
    
    if schedule_data.end_time is not None:
        schedule.end_time = schedule_data.end_time
    
    if schedule_data.is_active is not None:
        schedule.is_active = schedule_data.is_active
    
    # Validasi ulang waktu
    if schedule.end_time <= schedule.start_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end_time harus lebih besar dari start_time"
        )
    
    schedule.updated_at = datetime.now()
    db.commit()
    db.refresh(schedule)
    
    logger.info(f"Music schedule updated")
    return schedule


# =====================================================
# TOGGLE SCHEDULE ACTIVE
# =====================================================

@router.post("/toggle", response_model=schemas.MusicScheduleResponse)
async def toggle_schedule(
    toggle_data: schemas.MusicScheduleToggleRequest,
    db: Session = Depends(get_db)
):
    """Toggle schedule active/inactive"""
    schedule = get_schedule(db)
    
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Music schedule not found. Use POST /set to create."
        )
    
    schedule.is_active = toggle_data.is_active
    schedule.updated_at = datetime.now()
    
    db.commit()
    db.refresh(schedule)
    
    status_text = "activated" if toggle_data.is_active else "deactivated"
    logger.info(f"Music schedule {status_text}")
    
    return schedule


# =====================================================
# DELETE SCHEDULE
# =====================================================

@router.delete("/delete")
async def delete_schedule(db: Session = Depends(get_db)):
    """Delete music schedule"""
    schedule = get_schedule(db)
    
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Music schedule not found"
        )
    
    db.delete(schedule)
    db.commit()
    
    logger.info(f"Music schedule deleted")
    
    return {"message": "Music schedule deleted successfully"}


# =====================================================
# MANUAL TRIGGER (TESTING)
# =====================================================

@router.post("/trigger/start")
async def manual_trigger_start(db: Session = Depends(get_db)):
    """Manual trigger start music (untuk testing)"""
    from services.audio_service import get_audio_service
    audio_service = get_audio_service()
    
    audio_service.refresh_playlist()
    
    if len(audio_service.playlist) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Playlist kosong, upload musik terlebih dahulu"
        )
    
    if not audio_service.is_playing:
        audio_service.play_by_index(0)
        logger.info(f"Music manually started")
        return {"message": "Music started", "playing": True}
    else:
        return {"message": "Music already playing", "playing": True}


@router.post("/trigger/stop")
async def manual_trigger_stop():
    """Manual trigger stop music (untuk testing)"""
    from services.audio_service import get_audio_service
    audio_service = get_audio_service()
    
    if audio_service.is_playing or audio_service.is_paused:
        audio_service.stop()
        logger.info(f"Music manually stopped")
        return {"message": "Music stopped", "playing": False}
    else:
        return {"message": "Music already stopped", "playing": False}