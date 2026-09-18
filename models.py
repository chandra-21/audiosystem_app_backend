# backend/models.py
from sqlalchemy import Column, Integer, String, Boolean, Date, Time, DateTime, Float, Text, ForeignKey, func
from sqlalchemy.orm import relationship
from database import Base

# =====================================================
# MUSIC MODEL
# =====================================================
class Music(Base):
    """Model untuk menyimpan informasi musik"""
    __tablename__ = "music"
    __table_args__ = {'extend_existing': True}
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True, nullable=False)
    filename = Column(String, nullable=False)
    filepath = Column(String, nullable=False)
    duration = Column(Float, default=0.0)
    uploaded_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=func.now())
    uploaded_at = Column(DateTime, default=func.now())

# =====================================================
# BELL SCHEDULE MODELS
# =====================================================
class BellScheduleModel(Base):
    """Model untuk menyimpan jadwal bell per hari"""
    __tablename__ = "bell_schedules"
    
    id = Column(Integer, primary_key=True, index=True)
    schedule_type = Column(String(20), nullable=False, index=True)
    time = Column(Time, nullable=False)
    count = Column(Integer, nullable=False)
    duration = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class BellScheduleStatusModel(Base):
    """Model untuk menyimpan status bell schedule per hari"""
    __tablename__ = "bell_schedule_status"
    
    id = Column(Integer, primary_key=True, index=True)
    
    monday_active = Column(Boolean, default=True, nullable=False)
    tuesday_active = Column(Boolean, default=True, nullable=False)
    wednesday_active = Column(Boolean, default=True, nullable=False)
    thursday_active = Column(Boolean, default=True, nullable=False)
    friday_active = Column(Boolean, default=True, nullable=False)
    saturday_active = Column(Boolean, default=True, nullable=False)
    sunday_active = Column(Boolean, default=True, nullable=False)
    
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

# =====================================================
# SPEAKER CONTROL MODEL
# =====================================================
class SpeakerConfig(Base):
    """Model untuk konfigurasi dan status speaker"""
    __tablename__ = "speaker_config"
    
    id = Column(Integer, primary_key=True, index=True)
    speaker_number = Column(Integer, unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    gpio_pin = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=False, nullable=False)
    last_updated = Column(DateTime, default=func.now(), onupdate=func.now())

# =====================================================
# MUSIC SCHEDULE MODEL
# =====================================================
class MusicSchedule(Base):
    """Model untuk music schedule (auto start/stop)"""
    __tablename__ = "music_schedule"
    
    id = Column(Integer, primary_key=True, index=True)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())