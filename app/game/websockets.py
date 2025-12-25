# app/websockets.py

from fastapi import WebSocket
from typing import Dict, List

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, room_id: int, websocket: WebSocket):
        await websocket.accept()
        if room_id not in self.active_connections:
            self.active_connections[room_id] = []
        self.active_connections[room_id].append(websocket)

    def disconnect(self, room_id: int, websocket: WebSocket):
        if room_id in self.active_connections:
            self.active_connections[room_id].remove(websocket)
            if not self.active_connections[room_id]:
                del self.active_connections[room_id]

    async def broadcast(self, room_id: int, message: dict):
        connections = self.active_connections.get(room_id, [])
        print(f"[BROADCAST] Sending to {len(connections)} connections in room {room_id}: {message.get('type', 'unknown')}")
        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                print(f"[BROADCAST] Failed to send to connection: {e}")

manager = ConnectionManager()
