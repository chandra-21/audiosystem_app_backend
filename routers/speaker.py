# backend/routers/speaker.py - SIMPLIFIED (NO LOGGING)
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
from schemas import (
    SpeakerConfigResponse,
    SpeakerControlRequest,
    SpeakerStatusResponse,
    SpeakerNameUpdateRequest
)
from services.speaker_service import (
    get_speaker_service,
    SpeakerDatabaseService
)
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/speaker", tags=["Speaker Control"])


@router.get("/status", response_model=List[SpeakerStatusResponse])
def get_all_speakers_status(db: Session = Depends(get_db)):
    """Get status of all speakers"""
    speakers = SpeakerDatabaseService.get_all_speakers(db)
    
    return [
        SpeakerStatusResponse(
            speaker_number=s.speaker_number,
            name=s.name,
            is_active=s.is_active,
            last_updated=s.last_updated
        )
        for s in speakers
    ]


@router.get("/status/{speaker_number}", response_model=SpeakerStatusResponse)
def get_speaker_status(speaker_number: int, db: Session = Depends(get_db)):
    """Get status of specific speaker"""
    if not 1 <= speaker_number <= 5:
        raise HTTPException(status_code=400, detail="Speaker number must be 1-5")
    
    speaker = SpeakerDatabaseService.get_speaker(db, speaker_number)
    
    if not speaker:
        raise HTTPException(status_code=404, detail="Speaker not found")
    
    return SpeakerStatusResponse(
        speaker_number=speaker.speaker_number,
        name=speaker.name,
        is_active=speaker.is_active,
        last_updated=speaker.last_updated
    )


@router.post("/control", response_model=dict)
def control_speaker(
    request: SpeakerControlRequest,
    db: Session = Depends(get_db)
):
    """Control speaker ON/OFF"""
    if not 1 <= request.speaker_number <= 5:
        raise HTTPException(status_code=400, detail="Speaker number must be 1-5")
    
    # Get speaker service
    try:
        esp32_service = get_speaker_service()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    
    # Send command to ESP32
    esp_response = esp32_service.control_speaker(
        request.speaker_number,
        request.action
    )
    
    if esp_response.get("status") != "success":
        raise HTTPException(
            status_code=500,
            detail=f"ESP32 error: {esp_response.get('message', 'Unknown error')}"
        )
    
    # Update database (NO LOGGING)
    is_active = request.action.upper() == "ON"
    speaker = SpeakerDatabaseService.update_speaker_status(
        db,
        request.speaker_number,
        is_active
    )
    
    if not speaker:
        raise HTTPException(status_code=404, detail="Speaker not found")
    
    return {
        "status": "success",
        "message": f"Speaker {request.speaker_number} turned {request.action}",
        "speaker": SpeakerStatusResponse(
            speaker_number=speaker.speaker_number,
            name=speaker.name,
            is_active=speaker.is_active,
            last_updated=speaker.last_updated
        )
    }


@router.post("/sync", response_model=dict)
def sync_speakers_status(db: Session = Depends(get_db)):
    """Sync speaker status from ESP32 to database"""
    try:
        esp32_service = get_speaker_service()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    
    success = esp32_service.sync_status(db)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to sync with ESP32")
    
    speakers = SpeakerDatabaseService.get_all_speakers(db)
    
    return {
        "status": "success",
        "message": "Speakers status synced",
        "speakers": [
            SpeakerStatusResponse(
                speaker_number=s.speaker_number,
                name=s.name,
                is_active=s.is_active,
                last_updated=s.last_updated
            )
            for s in speakers
        ]
    }


@router.get("/config", response_model=List[SpeakerConfigResponse])
def get_speakers_config(db: Session = Depends(get_db)):
    """Get all speakers configuration"""
    speakers = SpeakerDatabaseService.get_all_speakers(db)
    
    return [
        SpeakerConfigResponse(
            id=s.id,
            speaker_number=s.speaker_number,
            name=s.name,
            gpio_pin=s.gpio_pin,
            is_active=s.is_active,
            last_updated=s.last_updated
        )
        for s in speakers
    ]


@router.put("/config/{speaker_number}", response_model=dict)
def update_speaker_name(
    speaker_number: int,
    request: SpeakerNameUpdateRequest,
    db: Session = Depends(get_db)
):
    """Update speaker name"""
    if not 1 <= speaker_number <= 5:
        raise HTTPException(status_code=400, detail="Speaker number must be 1-5")
    
    speaker = SpeakerDatabaseService.get_speaker(db, speaker_number)
    
    if not speaker:
        raise HTTPException(status_code=404, detail="Speaker not found")
    
    speaker.name = request.name
    db.commit()
    
    return {
        "status": "success",
        "message": "Speaker name updated",
        "speaker": SpeakerConfigResponse(
            id=speaker.id,
            speaker_number=speaker.speaker_number,
            name=speaker.name,
            gpio_pin=speaker.gpio_pin,
            is_active=speaker.is_active,
            last_updated=speaker.last_updated
        )
    }


@router.get("/test/connection", response_model=dict)
def test_esp32_connection():
    """Test ESP32 serial connection"""
    try:
        esp32_service = get_speaker_service()
        
        # Try to get status
        result = esp32_service.get_all_status()
        
        if result.get("status") == "success":
            return {
                "status": "success",
                "message": "ESP32 connection OK",
                "data": result
            }
        else:
            return {
                "status": "error",
                "message": "ESP32 not responding properly",
                "data": result
            }
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Connection test failed: {str(e)}"
        )