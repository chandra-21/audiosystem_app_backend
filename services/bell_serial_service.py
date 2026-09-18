# backend/services/bell_serial_service.py
import serial
import json
import time
from typing import Optional, Dict
import logging

logger = logging.getLogger(__name__)


class BellSerialService:
    """Service untuk komunikasi dengan ESP32 via USB Serial untuk kontrol bell relay"""
    
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
            
            logger.info(f"✅ Connected to ESP32 Bell Control on {self.port}")
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
            logger.info("🔌 Disconnected from ESP32 Bell Control")
    
    def _clear_buffers(self):
        """Clear serial input/output buffers"""
        if self.serial_conn and self.serial_conn.is_open:
            try:
                self.serial_conn.reset_input_buffer()
                self.serial_conn.reset_output_buffer()
            except Exception as e:
                logger.warning(f"Failed to clear buffers: {e}")
    
    def _read_response(self, timeout: float = 3.0) -> Optional[str]:
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
                        lines = response_buffer.split(b'\n')
                        for line in lines:
                            if line.strip():
                                try:
                                    decoded = line.decode('utf-8', errors='ignore').strip()
                                    if decoded:
                                        return decoded
                                except Exception:
                                    continue
                        
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
                response_str = self._read_response(timeout=3.0)
                
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
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON response (attempt {attempt + 1}): {response_str[:100]}")
                    
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
    
    def trigger_bell(self, count: int, duration: int) -> Dict:
        """
        Trigger bell relay
        Args:
            count: Jumlah bunyi (1-10)
            duration: Durasi tiap bunyi dalam milliseconds (100-5000)
        """
        command = {
            "bell": "ON",
            "count": count,
            "duration": duration
        }
        logger.info(f"🔔 Triggering bell: count={count}, duration={duration}ms")
        return self.send_command(command)


# Global instance
bell_serial_service: Optional[BellSerialService] = None

def get_bell_service() -> BellSerialService:
    """Get global bell service instance"""
    global bell_serial_service
    if bell_serial_service is None:
        raise RuntimeError("Bell service not initialized")
    return bell_serial_service

def init_bell_service(port: str = "/dev/ttyUSB0", baudrate: int = 115200):
    """Initialize global bell service"""
    global bell_serial_service
    bell_serial_service = BellSerialService(port=port, baudrate=baudrate)
    return bell_serial_service