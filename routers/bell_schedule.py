# backend/routers/bell_schedule.py - COMPLETE REFACTOR
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Literal
from datetime import datetime
from database import get_db
from models import BellScheduleModel, BellScheduleStatusModel
from schemas import (
    BellSchedule,
    BellTestRequest,
    BellScheduleCreate,
    BellScheduleUpdate,
    BellScheduleStatus,
    BellScheduleStatusResponse,
    BellScheduleToggleRequest,
)
from services.bell_serial_service import get_bell_service
import logging
from fastapi.encoders import jsonable_encoder

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bell-schedule", tags=["Bell Schedule"])

# Valid day names
VALID_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


# =====================================================
# Helper Functions
# =====================================================
def get_or_create_status(db: Session) -> BellScheduleStatusModel:
    """Pastikan status bell selalu ada di DB"""
    status = db.query(BellScheduleStatusModel).first()
    if not status:
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
        db.refresh(status)
    return status


def validate_day(day: str) -> str:
    """Validate and normalize day name"""
    day_lower = day.lower()
    if day_lower not in VALID_DAYS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid day. Must be one of: {', '.join(VALID_DAYS)}"
        )
    return day_lower


# =====================================================
# CRUD Bell Schedule
# =====================================================
@router.post("/{day}", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_bell_schedule(
    day: str,
    schedule: BellScheduleCreate,
    db: Session = Depends(get_db),
):
    """Membuat jadwal bell baru untuk hari tertentu"""
    day = validate_day(day)
    
    db_schedule = BellScheduleModel(
        schedule_type=day,
        time=schedule.time,
        count=schedule.count,
        duration=schedule.duration,
    )
    db.add(db_schedule)
    db.commit()
    db.refresh(db_schedule)

    logger.info(f"✅ Created bell schedule for {day} at {schedule.time}")

    return {
        "message": f"Schedule created successfully for {day}",
        "schedule": jsonable_encoder(db_schedule),
    }


@router.get("/{day}", response_model=List[BellSchedule])
def get_bell_schedules(
    day: str,
    db: Session = Depends(get_db),
):
    """Ambil semua jadwal untuk hari tertentu"""
    day = validate_day(day)
    
    schedules = (
        db.query(BellScheduleModel)
        .filter(BellScheduleModel.schedule_type == day)
        .order_by(BellScheduleModel.time)
        .all()
    )
    return schedules


@router.get("/", response_model=dict)
def get_all_bell_schedules(db: Session = Depends(get_db)):
    """Mendapatkan semua jadwal bell, dikelompokkan berdasarkan hari"""
    result = {}
    
    for day in VALID_DAYS:
        schedules = db.query(BellScheduleModel).filter(
            BellScheduleModel.schedule_type == day
        ).order_by(BellScheduleModel.time).all()
        
        result[day] = jsonable_encoder(schedules)
    
    return result


@router.put("/{schedule_id}", response_model=dict)
def update_bell_schedule(
    schedule_id: int,
    schedule: BellScheduleUpdate,
    db: Session = Depends(get_db),
):
    """Update jadwal bell"""
    db_schedule = db.query(BellScheduleModel).filter_by(id=schedule_id).first()
    if not db_schedule:
        raise HTTPException(status_code=404, detail="Bell schedule not found")

    update_data = schedule.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_schedule, key, value)

    db.commit()
    db.refresh(db_schedule)

    logger.info(f"✅ Updated bell schedule ID {schedule_id}")

    return {
        "message": "Schedule updated successfully",
        "schedule": jsonable_encoder(db_schedule),
    }


@router.delete("/{schedule_id}", response_model=dict)
def delete_bell_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
):
    """Hapus jadwal bell"""
    db_schedule = db.query(BellScheduleModel).filter_by(id=schedule_id).first()
    if not db_schedule:
        raise HTTPException(status_code=404, detail="Bell schedule not found")

    day = db_schedule.schedule_type
    db.delete(db_schedule)
    db.commit()

    logger.info(f"✅ Deleted bell schedule ID {schedule_id} for {day}")

    return {"message": "Schedule deleted successfully"}


# =====================================================
# STATUS ENDPOINTS - FIX ORDER (ALL BEFORE {day})
# =====================================================
@router.get("/status/current", response_model=BellScheduleStatus)
def get_bell_status(db: Session = Depends(get_db)):
    """Dapatkan status aktif/inaktif untuk semua hari"""
    status = get_or_create_status(db)
    return status


# IMPORTANT: /all HARUS SEBELUM /{day} untuk menghindari conflict
@router.post("/status/toggle/all", response_model=BellScheduleStatusResponse)
def toggle_all_schedules(
    request: BellScheduleToggleRequest,
    db: Session = Depends(get_db)
):
    """
    Toggle semua schedule sekaligus (semua hari)
    Berguna untuk master switch
    """
    bell_status = get_or_create_status(db)
    
    # Update semua hari
    for day in VALID_DAYS:
        setattr(bell_status, f"{day}_active", request.is_active)
    
    db.commit()
    db.refresh(bell_status)
    
    action = "activated" if request.is_active else "deactivated"
    message = f"All schedules {action}"
    logger.info(f"✅ {message}")
    
    return {
        "status": "success",
        "message": message,
        "data": jsonable_encoder(bell_status)
    }


# Sekarang baru {day} parameter
@router.post("/status/toggle/{day}", response_model=BellScheduleStatusResponse)
def toggle_day_status(
    day: str,
    request: BellScheduleToggleRequest,
    db: Session = Depends(get_db)
):
    """
    Toggle status schedule untuk hari tertentu
    - is_active: true → Aktifkan schedule untuk hari ini
    - is_active: false → Nonaktifkan schedule untuk hari ini
    """
    day = validate_day(day)
    bell_status = get_or_create_status(db)
    
    # Update status untuk hari tersebut
    setattr(bell_status, f"{day}_active", request.is_active)
    db.commit()
    db.refresh(bell_status)
    
    action = "activated" if request.is_active else "deactivated"
    message = f"{day.capitalize()} schedule {action}"
    logger.info(f"✅ {message}")
    
    return {
        "status": "success",
        "message": message,
        "data": jsonable_encoder(bell_status)
    }


# =====================================================
# GET ACTIVE SCHEDULES
# =====================================================
@router.get("/active-today", response_model=List[BellSchedule])
def get_active_schedules_today(db: Session = Depends(get_db)):
    """
    Ambil jadwal aktif berdasarkan hari ini
    Mempertimbangkan status individual per hari
    """
    status = get_or_create_status(db)
    
    # Tentukan hari ini
    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    today_index = datetime.now().weekday()  # 0 = Monday
    day_name = day_names[today_index]
    
    # Cek apakah hari ini aktif
    is_active = getattr(status, f"{day_name}_active", True)
    
    # Jika inactive, return empty array
    if not is_active:
        logger.info(f"{day_name} schedule is inactive today")
        return []
    
    # Ambil jadwal
    schedules = (
        db.query(BellScheduleModel)
        .filter(BellScheduleModel.schedule_type == day_name)
        .order_by(BellScheduleModel.time)
        .all()
    )
    
    logger.info(f"Found {len(schedules)} active schedules for {day_name}")
    return schedules


# =====================================================
# MANUAL BELL TEST
# =====================================================
@router.post("/test/bell", response_model=dict)
def test_bell_endpoint(
    request: BellTestRequest,
    db: Session = Depends(get_db)
):
    """
    Manual test bell via serial communication
    """
    count = request.count
    duration = request.duration

    logger.info(f"🔔 Testing bell via serial: count={count}, duration={duration}ms")

    try:
        bell_service = get_bell_service()
        result = bell_service.trigger_bell(count, duration)

        if result.get("status") != "success":
            raise HTTPException(
                status_code=503,
                detail={"message": "Failed to test bell", "error": result}
            )

        return {
            "status": "success",
            "message": f"Bell tested: {count}x rings, {duration}ms each",
            "data": result
        }
    except RuntimeError as e:
        raise HTTPException(
            status_code=503,
            detail={"message": "Bell service not initialized", "error": str(e)}
        )
    except Exception as e:
        logger.error(f"❌ Error testing bell: {e}")
        raise HTTPException(
            status_code=500,
            detail={"message": "Internal server error", "error": str(e)}
        )


# =====================================================
# SCHEDULER STATUS
# =====================================================
@router.get("/scheduler/status", response_model=dict)
def get_scheduler_status():
    """Get status bell scheduler service"""
    from services.bell_scheduler_service import bell_scheduler_service
    
    return {
        "status": "success",
        "scheduler": {
            "is_running": bell_scheduler_service.is_running,
            "checked_schedules_today": len(bell_scheduler_service.checked_schedules),
            "last_reset_date": bell_scheduler_service._last_reset_date.isoformat() if bell_scheduler_service._last_reset_date else None,
            "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        "message": "Scheduler is running" if bell_scheduler_service.is_running else "Scheduler is stopped"
    }