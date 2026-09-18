# backend/services/websocket_manager.py
from fastapi import WebSocket
from typing import Dict
import logging

logger = logging.getLogger(__name__)

class WebSocketManager:
    """Manager untuk WebSocket connections"""
    
    def __init__(self):
        # Active connections: {user_id: WebSocket}
        self.active_connections: Dict[int, WebSocket] = {}
        # Announcement connection (only one at a time)
        self.announcement_connection: WebSocket | None = None
        self.announcement_user_id: int | None = None
    
    async def connect(self, websocket: WebSocket, user_id: int):
        """Register WebSocket connection (DO NOT call accept here)"""
        # DON'T call await websocket.accept() here - already done in handler
        self.active_connections[user_id] = websocket
        logger.info(f"✅ WebSocket registered: user_id={user_id}")
    
    def disconnect(self, user_id: int):
        """Remove connection"""
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            logger.info(f"🔌 WebSocket disconnected: user_id={user_id}")
        
        # If announcement connection, clear it
        if self.announcement_user_id == user_id:
            self.announcement_connection = None
            self.announcement_user_id = None
            logger.info(f"📢 Announcement connection closed")
    
    def set_announcement_connection(self, websocket: WebSocket, user_id: int):
        """Set active announcement connection"""
        self.announcement_connection = websocket
        self.announcement_user_id = user_id
        logger.info(f"📢 Announcement connection established: user_id={user_id}")
    
    def is_announcement_active(self) -> bool:
        """Check if announcement is active"""
        return self.announcement_connection is not None
    
    async def send_personal_message(self, message: dict, user_id: int):
        """Send message to specific user"""
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].send_json(message)
            except Exception as e:
                logger.error(f"Error sending message: {e}")
                self.disconnect(user_id)
    
    async def broadcast(self, message: dict, exclude_user: int | None = None):
        """Broadcast message to all connected clients"""
        disconnected_users = []
        
        for user_id, connection in self.active_connections.items():
            if exclude_user and user_id == exclude_user:
                continue
            
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting: {e}")
                disconnected_users.append(user_id)
        
        for user_id in disconnected_users:
            self.disconnect(user_id)


# Global instance
ws_manager = WebSocketManager()

def get_ws_manager() -> WebSocketManager:
    return ws_manager