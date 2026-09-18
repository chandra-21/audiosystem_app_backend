# backend/main.py - NO AUTH VERSION
from fastapi import FastAPI, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
import asyncio
import models
import config

from database import engine, Base, get_db

# Import routers
from routers import playlist, bell_schedule, speaker, announcement, music_schedule, app_version

# Import services
from services.bell_serial_service import init_bell_service
from services.bell_scheduler_service import bell_scheduler_service
from services.speaker_service import init_speaker_service, SpeakerDatabaseService
from services.music_scheduler_service import music_scheduler_service

# =====================================================
# LOGGING SETUP
# =====================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# =====================================================
# CREATE DATABASE TABLES
# =====================================================
Base.metadata.create_all(bind=engine)
logger.info("Database tables created successfully")


# =====================================================
# APP LIFESPAN
# =====================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown events"""
    # Startup
    logger.info("🚀 Application starting up...")
    
    # Initialize speaker service
    try:
        init_speaker_service(port="/dev/ttyUSB0", baudrate=115200)
        logger.info("✅ Speaker service initialized")
        
        db = next(get_db())
        try:
            SpeakerDatabaseService.initialize_speakers(db)
            logger.info("🔊 Initializing hardware speakers...")
            SpeakerDatabaseService.initialize_hardware_speakers(db)
        except Exception as e:
            logger.error(f"❌ Error initializing speakers: {e}")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"⚠️ Failed to initialize speaker service: {e}")
        logger.info("Application will continue without speaker control")
    
    # Initialize bell service
    try:
        init_bell_service(port="/dev/ttyUSB0", baudrate=115200)
        logger.info("✅ Bell serial service initialized")
    except Exception as e:
        logger.error(f"⚠️ Failed to initialize bell service: {e}")
        logger.info("Application will continue without bell control")
    
    # Start bell scheduler
    bell_scheduler_task = None
    try:
        bell_scheduler_task = asyncio.create_task(bell_scheduler_service.start())
        logger.info("✅ Bell scheduler started")
    except Exception as e:
        logger.error(f"⚠️ Failed to start bell scheduler: {e}")
    
    # Start music scheduler
    music_scheduler_task = None
    try:
        music_scheduler_task = asyncio.create_task(music_scheduler_service.start())
        logger.info("✅ Music scheduler started")
    except Exception as e:
        logger.error(f"⚠️ Failed to start music scheduler: {e}")
    
    yield
    
    # Shutdown
    logger.info("🛑 Application shutting down...")
    
    if bell_scheduler_task:
        bell_scheduler_service.stop()
        try:
            await bell_scheduler_task
        except asyncio.CancelledError:
            logger.info("✅ Bell scheduler cancelled successfully")
    
    if music_scheduler_task:
        music_scheduler_service.stop()
        try:
            await music_scheduler_task
        except asyncio.CancelledError:
            logger.info("✅ Music scheduler cancelled successfully")


# =====================================================
# APP INITIALIZATION
# =====================================================
app = FastAPI(
    title="IoT Audio System Backend",
    description="Backend API untuk sistem audio IoT (No Auth - Protected by HRIS)",
    version="4.0.0",
    lifespan=lifespan
)

# =====================================================
# CORS SETUP
# =====================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Ubah di production ke HRIS domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================================================
# INCLUDE ROUTERS
# =====================================================
app.include_router(playlist.router)
app.include_router(bell_schedule.router)
app.include_router(speaker.router)
app.include_router(announcement.router)
app.include_router(music_schedule.router)
app.include_router(app_version.router)


# =====================================================
# ROOT ENDPOINT
# =====================================================
@app.get("/")
def root():
    return {
        "message": "IoT Audio System Backend API",
        "version": "4.0.0",
        "auth": "Protected by HRIS (No JWT validation here)",
        "systems": {
            "audio": {
                "bell_system": "Serial-based (OrangePi Scheduler)",
                "music_scheduler": "Auto play/stop (Weekdays only)",
                "speaker_control": "Multi-speaker via Serial",
                "announcement": "Real-time audio streaming"
            },
        },
        "endpoints": {
            "docs": "/docs",
            "bell_schedule": "/bell-schedule",
            "playlist": "/music",
            "speaker": "/speaker",
            "announcement": "/announcement",
            "music_schedule": "/music-schedule"
        }
    }


@app.get("/health")
def health_check():
    """Health check endpoint"""
    from services.bell_serial_service import bell_serial_service
    from services.speaker_service import speaker_esp32_service
    
    return {
        "status": "healthy",
        "database": "connected",
        "services": {
            "bell_scheduler": bell_scheduler_service.is_running,
            "bell_serial": bell_serial_service is not None and bell_serial_service.serial_conn is not None,
            "speaker_serial": speaker_esp32_service is not None and speaker_esp32_service.serial_conn is not None,
            "music_scheduler": music_scheduler_service.is_running,
        }
    }