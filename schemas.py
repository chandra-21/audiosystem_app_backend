# backend/schemas.py
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, Literal, List
from datetime import time, datetime, date
from enum import Enum
from datetime import time as time_type, datetime

# =====================================================
# MUSIC/PLAYLIST SCHEMAS
# =====================================================
class MusicResponse(BaseModel):
    id: int
    title: str
    filename: str
    filepath: str
    duration: float
    created_at: datetime
    uploaded_by: Optional[str] = None
    
    class Config:
        from_attributes = True

class PlayerStatusResponse(BaseModel):
    is_playing: bool
    is_paused: bool
    volume: int
    position: float
    duration: float
    current_music: Optional[dict]

class PlaybackControlRequest(BaseModel):
    volume: Optional[int] = None
    position: Optional[float] = None

# =====================================================
# BELL SCHEDULE SCHEMAS
# =====================================================
class BellScheduleBase(BaseModel):
    """Base schema untuk bell schedule"""
    time: time
    count: int = Field(..., ge=1, le=10, description="Jumlah bell (1-10)")
    duration: int = Field(..., ge=100, le=5000, description="Durasi tiap bunyi dalam milliseconds (100-5000)")


class BellScheduleCreate(BellScheduleBase):
    """Schema untuk membuat bell schedule baru"""
    pass


class BellScheduleUpdate(BaseModel):
    time: Optional[time_type] = None  # ← tetap time object, bukan str
    count: Optional[int] = Field(None, ge=1, le=10)
    duration: Optional[int] = Field(None, ge=100, le=5000)

    @field_validator('time', mode='before')
    @classmethod
    def normalize_time(cls, v):
        if v is None:
            return v
        if isinstance(v, str):
            try:
                if len(v) == 5:  # "HH:MM"
                    return datetime.strptime(v, "%H:%M").time()
                return datetime.strptime(v, "%H:%M:%S").time()  # "HH:MM:SS"
            except ValueError:
                raise ValueError(f"Format waktu tidak valid: '{v}'. Gunakan HH:MM atau HH:MM:SS")
        return v


class BellSchedule(BellScheduleBase):
    """Schema response untuk bell schedule"""
    id: int
    schedule_type: Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    
    class Config:
        from_attributes = True
        orm_mode = True


# =====================================================
# BELL SCHEDULE STATUS SCHEMAS
# =====================================================
class BellScheduleStatus(BaseModel):
    """Schema untuk status bell schedule dengan status per hari"""
    monday_active: bool
    tuesday_active: bool
    wednesday_active: bool
    thursday_active: bool
    friday_active: bool
    saturday_active: bool
    sunday_active: bool
    
    class Config:
        from_attributes = True
        orm_mode = True


class BellScheduleToggleRequest(BaseModel):
    """Schema untuk request toggle status individual schedule"""
    is_active: bool = Field(..., description="true untuk aktifkan, false untuk nonaktifkan")


class BellScheduleStatusResponse(BaseModel):
    """Schema response untuk operasi status"""
    status: Literal["success", "error"]
    message: str
    data: Optional[BellScheduleStatus] = None


class BellTestRequest(BaseModel):
    """Schema untuk request test bell via serial"""
    count: int = Field(..., ge=1, le=10, description="Jumlah bell (1-10)")
    duration: int = Field(..., ge=100, le=5000, description="Durasi tiap bunyi dalam milliseconds (100-5000)")

# =====================================================
# SPEAKER CONTROL SCHEMAS
# =====================================================
class SpeakerConfigBase(BaseModel):
    """Base schema untuk speaker config"""
    speaker_number: int = Field(..., ge=1, le=5, description="Nomor speaker (1-5)")
    name: str = Field(..., max_length=100)
    gpio_pin: int

class SpeakerConfigResponse(SpeakerConfigBase):
    """Schema response untuk speaker config"""
    id: int
    is_active: bool
    last_updated: datetime
    
    class Config:
        from_attributes = True

class SpeakerControlRequest(BaseModel):
    """Schema untuk request control speaker"""
    speaker_number: int = Field(..., ge=1, le=5, description="Nomor speaker (1-5)")
    action: Literal["ON", "OFF"] = Field(..., description="Action: ON atau OFF")

class SpeakerStatusResponse(BaseModel):
    """Schema response untuk status speaker"""
    speaker_number: int
    name: str
    is_active: bool
    last_updated: datetime

class SpeakerNameUpdateRequest(BaseModel):
    """Schema untuk update nama speaker"""
    name: str = Field(..., max_length=100)

# =====================================================
# ANNOUNCEMENT SCHEMAS
# =====================================================

class AnnouncementSpeakerSelection(BaseModel):
    """Schema untuk pemilihan speaker"""
    speaker_numbers: List[int] = Field(..., description="List of speaker numbers (1-5)")
    
    @field_validator('speaker_numbers')
    @classmethod
    def validate_speaker_numbers(cls, v):
        if not v:
            raise ValueError("At least one speaker must be selected")
        for num in v:
            if num < 1 or num > 5:
                raise ValueError("Speaker number must be between 1 and 5")
        return list(set(v))

class AnnouncementStatus(BaseModel):
    """Schema untuk status announcement"""
    is_active: bool
    state: Literal["idle", "initializing", "ready", "streaming", "stopping"]
    user_id: Optional[int] = None
    username: Optional[str] = None
    selected_speakers: List[int] = []
    started_at: Optional[str] = None
    duration: Optional[float] = None

class AnnouncementStartResponse(BaseModel):
    """Schema response untuk start announcement"""
    status: Literal["success", "error"]
    message: str
    websocket_url: Optional[str] = None

# =====================================================
# MUSIC SCHEDULE SCHEMAS
# =====================================================

class MusicScheduleBase(BaseModel):
    """Base schema untuk music schedule"""
    start_time: time = Field(..., description="Jam mulai auto-play (e.g., 08:00)")
    end_time: time = Field(..., description="Jam auto-stop (e.g., 17:00)")


class MusicScheduleCreate(MusicScheduleBase):
    """Schema untuk membuat music schedule baru"""
    is_active: bool = True
    
    @model_validator(mode='after')
    def validate_times(self):
        """Validate that end_time is after start_time"""
        if self.end_time <= self.start_time:
            raise ValueError("end_time harus lebih besar dari start_time")
        return self


class MusicScheduleUpdate(BaseModel):
    """Schema untuk update music schedule"""
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    is_active: Optional[bool] = None


class MusicScheduleResponse(MusicScheduleBase):
    """Schema response untuk music schedule"""
    id: int
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class MusicScheduleToggleRequest(BaseModel):
    """Schema untuk toggle schedule active/inactive"""
    is_active: bool = Field(..., description="true untuk aktifkan, false untuk nonaktifkan")


class MusicScheduleStatusResponse(BaseModel):
    """Schema response untuk status schedule saat ini"""
    has_schedule: bool
    schedule: Optional[MusicScheduleResponse] = None
    current_time: str
    is_weekday: bool
    should_be_playing: bool
    actual_playing: bool
    next_action: Optional[str] = None
    next_action_time: Optional[str] = None