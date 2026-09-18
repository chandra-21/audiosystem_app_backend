# backend/routers/announcement.py - NO AUTH VERSION
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
import logging
import json

from database import get_db
from schemas import AnnouncementSpeakerSelection, AnnouncementStatus, AnnouncementStartResponse
from services.announcement_service import get_announcement_service
from services.websocket_manager import get_ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/announcement", tags=["Announcement"])

# =====================================================
# REST ENDPOINTS
# =====================================================

@router.get("/status", response_model=AnnouncementStatus)
def get_announcement_status():
    """Get current announcement status"""
    announcement_service = get_announcement_service()
    status_dict = announcement_service.get_status()
    
    return AnnouncementStatus(**status_dict)


@router.post("/start", response_model=AnnouncementStartResponse)
async def start_announcement(
    selection: AnnouncementSpeakerSelection,
    username: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Start announcement session"""
    announcement_service = get_announcement_service()
    
    if announcement_service.is_active:
        return AnnouncementStartResponse(
            status="error",
            message="Announcement already in progress",
            websocket_url=None
        )
    
    # Start announcement
    result = await announcement_service.start_announcement(
        user_id=0,  # Dummy user_id
        username=username or "HRIS User",
        speaker_numbers=selection.speaker_numbers,
        db=db
    )
    
    if result["success"]:
        websocket_url = f"/announcement/ws"
        
        return AnnouncementStartResponse(
            status="success",
            message=result["message"],
            websocket_url=websocket_url
        )
    else:
        return AnnouncementStartResponse(
            status="error",
            message=result["message"],
            websocket_url=None
        )


@router.post("/stop")
async def stop_announcement(db: Session = Depends(get_db)):
    """Stop current announcement"""
    announcement_service = get_announcement_service()
    
    await announcement_service.stop_announcement(db)
    
    return {
        "status": "success",
        "message": "Announcement stopped successfully"
    }


# =====================================================
# WEBSOCKET ENDPOINT
# =====================================================

@router.websocket("/ws")
async def websocket_announcement(
    websocket: WebSocket,
    db: Session = Depends(get_db)
):
    """WebSocket endpoint for announcement audio streaming"""
    
    announcement_service = get_announcement_service()
    ws_manager = get_ws_manager()
    
    try:
        # Accept connection
        await websocket.accept()
        logger.info("📞 WebSocket connection accepted")
        
        # Register connection langsung tanpa auth
        user_id = announcement_service.current_user_id or 0
        await ws_manager.connect(websocket, user_id)
        ws_manager.set_announcement_connection(websocket, user_id)
        
        logger.info(f"✅ WebSocket connected (no auth)")
        
        # Send ready signal
        logger.info(f"📤 Sending ready signal (current state: {announcement_service.state})")
        await websocket.send_json({
            "type": "status",
            "state": "ready",
            "message": "Ready to receive audio"
        })
        
        # Set streaming state
        announcement_service.state = "streaming"
        logger.info("📢 State changed to streaming")
        
        # Main loop: receive audio chunks
        while True:
            try:
                message = await websocket.receive()
                
                if "bytes" in message:
                    audio_data = message["bytes"]
                    await announcement_service.process_audio_chunk(audio_data)
                    
                elif "text" in message:
                    data = json.loads(message["text"])
                    msg_type = data.get("type")
                    
                    if msg_type == "control":
                        action = data.get("action")
                        
                        if action == "stop":
                            logger.info("🛑 Stop command received")
                            await announcement_service.stop_announcement(db)
                            await websocket.send_json({
                                "type": "status",
                                "state": "stopped",
                                "message": "Announcement stopped"
                            })
                            break
                    
                    elif msg_type == "ping":
                        await websocket.send_json({"type": "pong"})
                
            except WebSocketDisconnect:
                logger.info("📞 WebSocket disconnected")
                break
            except Exception as e:
                logger.error(f"❌ Error in WebSocket loop: {e}")
                break
        
    except WebSocketDisconnect:
        logger.info("📞 WebSocket disconnected during setup")
    except Exception as e:
        logger.error(f"❌ WebSocket error: {e}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
    finally:
        if user_id:
            ws_manager.disconnect(user_id)
        
        if announcement_service.is_active:
            await announcement_service.stop_announcement(db)
        
        logger.info("✅ WebSocket connection closed")