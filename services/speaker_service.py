# backend/services/speaker_service.py - FIXED VERSION WITH HARDWARE INIT
import serial
import json
import time
from typing import Optional, Dict
from sqlalchemy.orm import Session
from models import SpeakerConfig
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class SpeakerESP32Service:
    """Service untuk komunikasi dengan ESP32 via USB Serial untuk kontrol speaker relay"""
    
    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 115200):
        self.port = port
        self.baudrate = baudrate
        self.serial_conn: Optional[serial.Serial] = None
        self.max_retries = 3
        self.connect()
    
    def connect(self) -> bool:
        """Establish serial connection to ESP32"""
        try:
            if self.serial_conn and self.serial_conn.is_open:
                logger.info("Serial connection already open")
                return True
                
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=2,
                write_timeout=2
            )
            time.sleep(2)  # Wait for ESP32 to reset
            
            # Clear buffer
            self.serial_conn.reset_input_buffer()
            self.serial_conn.reset_output_buffer()
            
            logger.info(f"✅ Connected to ESP32 Speaker Control on {self.port}")
            return True
        except serial.SerialException as e:
            logger.error(f"❌ Failed to connect to ESP32: {e}")
            self.serial_conn = None
            return False
        except Exception as e:
            logger.error(f"❌ Unexpected error connecting to ESP32: {e}")
            self.serial_conn = None
            return False
    
    def disconnect(self):
        """Close serial connection"""
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
            logger.info("🔌 Disconnected from ESP32 Speaker Control")
    
    def _clear_buffers(self):
        """Clear serial input/output buffers"""
        if self.serial_conn and self.serial_conn.is_open:
            try:
                self.serial_conn.reset_input_buffer()
                self.serial_conn.reset_output_buffer()
            except Exception as e:
                logger.warning(f"Failed to clear buffers: {e}")
    
    def _read_response(self, timeout: float = 1.0) -> Optional[str]:
        """Read response from ESP32 with error handling"""
        if not self.serial_conn or not self.serial_conn.is_open:
            return None
        
        start_time = time.time()
        response_buffer = b''
        
        while (time.time() - start_time) < timeout:
            if self.serial_conn.in_waiting > 0:
                try:
                    chunk = self.serial_conn.read(self.serial_conn.in_waiting)
                    response_buffer += chunk
                    
                    # Check if we have a complete line
                    if b'\n' in response_buffer:
                        # Get first complete line
                        lines = response_buffer.split(b'\n')
                        for line in lines:
                            if line.strip():
                                try:
                                    # Try to decode
                                    decoded = line.decode('utf-8', errors='ignore').strip()
                                    if decoded:
                                        return decoded
                                except Exception:
                                    continue
                        
                        # If no valid line found, continue reading
                        response_buffer = lines[-1]
                
                except Exception as e:
                    logger.warning(f"Error reading chunk: {e}")
                    continue
            
            time.sleep(0.05)
        
        # Try to return whatever we have
        if response_buffer:
            try:
                return response_buffer.decode('utf-8', errors='ignore').strip()
            except:
                return None
        
        return None
    
    def send_command(self, command: Dict) -> Dict:
        """
        Send command to ESP32 and get response with retry logic
        Command format: {"speaker": 1, "action": "ON"}
        """
        for attempt in range(self.max_retries):
            try:
                if not self.serial_conn or not self.serial_conn.is_open:
                    if not self.connect():
                        return {
                            "status": "error",
                            "message": "Failed to connect to ESP32"
                        }
                
                # Clear buffers before sending
                self._clear_buffers()
                
                # Send command as JSON
                cmd_json = json.dumps(command) + "\n"
                self.serial_conn.write(cmd_json.encode())
                self.serial_conn.flush()
                
                # Wait and read response
                time.sleep(0.3)
                response_str = self._read_response(timeout=2.0)
                
                if not response_str:
                    if attempt < self.max_retries - 1:
                        logger.warning(f"No response from ESP32 (attempt {attempt + 1}/{self.max_retries})")
                        time.sleep(0.5)
                        continue
                    return {
                        "status": "timeout",
                        "message": "No response from ESP32 after retries"
                    }
                
                logger.debug(f"ESP32 Response: {response_str}")
                
                # Try to parse as JSON
                try:
                    response_data = json.loads(response_str)
                    return response_data
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON response (attempt {attempt + 1}): {response_str[:100]}")
                    
                    # If we got some response but invalid JSON, retry
                    if attempt < self.max_retries - 1:
                        time.sleep(0.5)
                        continue
                    
                    return {
                        "status": "error",
                        "message": "Invalid JSON response from ESP32",
                        "raw_response": response_str[:200]
                    }
            
            except serial.SerialException as e:
                logger.error(f"❌ Serial error (attempt {attempt + 1}): {e}")
                self.serial_conn = None
                
                if attempt < self.max_retries - 1:
                    time.sleep(0.5)
                    continue
                
                return {
                    "status": "error",
                    "message": f"Serial communication error: {str(e)}"
                }
            
            except Exception as e:
                logger.error(f"❌ Error sending command (attempt {attempt + 1}): {e}")
                
                if attempt < self.max_retries - 1:
                    time.sleep(0.5)
                    continue
                
                return {
                    "status": "error",
                    "message": str(e)
                }
        
        return {
            "status": "error",
            "message": f"Failed after {self.max_retries} attempts"
        }
    
    def control_speaker(self, speaker_number: int, action: str) -> Dict:
        """
        Control specific speaker
        Args:
            speaker_number: 1-5
            action: "ON" or "OFF"
        """
        command = {
            "speaker": speaker_number,
            "action": action.upper()
        }
        logger.info(f"Sending command to ESP32: {command}")
        return self.send_command(command)
    
    def get_all_status(self) -> Dict:
        """Get status of all speakers from ESP32"""
        command = {"action": "STATUS"}
        logger.info("Requesting status from ESP32...")
        return self.send_command(command)
    
    def turn_on_all_speakers(self) -> Dict:
        """Turn on all speakers (1-5)"""
        logger.info("🔊 Turning ON all speakers...")
        results = {}
        
        for speaker_num in range(1, 6):
            result = self.control_speaker(speaker_num, "ON")
            results[f"speaker_{speaker_num}"] = result
            time.sleep(0.2)  # Small delay between commands
        
        logger.info("✅ All speakers turned ON")
        return {
            "status": "success",
            "message": "All speakers turned ON",
            "results": results
        }
    
    def sync_status(self, db: Session) -> bool:
        """Sync speaker status from ESP32 to database"""
        status_response = self.get_all_status()
        
        if status_response.get("status") == "success":
            speakers_status = status_response.get("speakers", {})
            
            for speaker_num, is_active in speakers_status.items():
                speaker = db.query(SpeakerConfig).filter(
                    SpeakerConfig.speaker_number == int(speaker_num)
                ).first()
                
                if speaker:
                    speaker.is_active = is_active
                    speaker.last_updated = datetime.utcnow()
            
            db.commit()
            logger.info("✅ Speaker status synced from ESP32 to database")
            return True
        
        logger.error("❌ Failed to sync speaker status")
        return False


class SpeakerDatabaseService:
    """Service untuk operasi database speaker"""
    
    @staticmethod
    def initialize_speakers(db: Session):
        """Initialize 5 speakers in database - DEFAULT ALL ON"""
        gpio_pins = [25, 26, 27, 32, 33]
        
        for i in range(1, 6):
            existing = db.query(SpeakerConfig).filter(
                SpeakerConfig.speaker_number == i
            ).first()
            
            if not existing:
                speaker = SpeakerConfig(
                    speaker_number=i,
                    name=f"Speaker {i}",
                    gpio_pin=gpio_pins[i-1],
                    is_active=True  # ✅ Default semua speaker MENYALA
                )
                db.add(speaker)
                logger.info(f"Created speaker {i} config (default: ON)")
        
        db.commit()
        logger.info("✅ All speakers initialized (ALL ON by default)")
    
    @staticmethod
    def get_speaker(db: Session, speaker_number: int) -> Optional[SpeakerConfig]:
        """Get speaker by number"""
        return db.query(SpeakerConfig).filter(
            SpeakerConfig.speaker_number == speaker_number
        ).first()
    
    @staticmethod
    def get_all_speakers(db: Session) -> list:
        """Get all speakers"""
        return db.query(SpeakerConfig).order_by(SpeakerConfig.speaker_number).all()
    
    @staticmethod
    def update_speaker_status(
        db: Session, 
        speaker_number: int, 
        is_active: bool
    ) -> Optional[SpeakerConfig]:
        """Update speaker status"""
        speaker = db.query(SpeakerConfig).filter(
            SpeakerConfig.speaker_number == speaker_number
        ).first()
        
        if speaker:
            speaker.is_active = is_active
            speaker.last_updated = datetime.utcnow()
            db.commit()
            
            logger.info(f"Speaker {speaker_number} status updated: {'ON' if is_active else 'OFF'}")
            return speaker
        
        return None
    
    @staticmethod
    def initialize_hardware_speakers(db: Session):
        """Initialize hardware: turn on all speakers physically via ESP32"""
        try:
            speaker_service = get_speaker_service()
            
            logger.info("🔧 Initializing hardware speakers...")
            
            # Turn on all speakers via ESP32
            result = speaker_service.turn_on_all_speakers()
            
            if result.get("status") == "success":
                # Update database to match hardware state
                for i in range(1, 6):
                    SpeakerDatabaseService.update_speaker_status(db, i, True)
                
                logger.info("✅ Hardware speakers initialized successfully")
                return True
            else:
                logger.error("❌ Failed to initialize hardware speakers")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error initializing hardware speakers: {e}")
            return False


# Global instance
speaker_esp32_service: Optional[SpeakerESP32Service] = None

def get_speaker_service() -> SpeakerESP32Service:
    """Get global speaker service instance"""
    global speaker_esp32_service
    if speaker_esp32_service is None:
        raise RuntimeError("Speaker service not initialized")
    return speaker_esp32_service

def init_speaker_service(port: str = "/dev/ttyUSB0", baudrate: int = 115200):
    """Initialize global speaker service"""
    global speaker_esp32_service
    speaker_esp32_service = SpeakerESP32Service(port=port, baudrate=baudrate)
    return speaker_esp32_service