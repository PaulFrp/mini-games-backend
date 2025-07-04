from fastapi import APIRouter, Depends, Cookie, Header
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Room, Player
from app.session import signer
import traceback

router = APIRouter()

@router.get("/room_messages")
def get_messages(
    room_session: str = Cookie(None),
    x_client_id: str = Header(None),
    db: Session = Depends(get_db),
):
    try:
        print(f"[DEBUG] Attempting to unsign: {room_session}")
        room_id = signer.unsign(room_session).decode()
        room = db.query(Room).filter(Room.id == int(room_id)).first()
        players = db.query(Player).filter(Player.room_id == room_id).all()
        player_map = {str(p.user_id): p.username for p in players}
        
        if not room:
            print(f"[DEBUG] Room not found for room_id {room_id}")
            return {"error": "Room not found"}
        
        print(f"[DEBUG] Successfully fetched room {room_id} for client {x_client_id}")
        is_creator = room.creator == x_client_id
        return {
            "room_id": room_id,
            "messages": [f"Welcome to room {room_id}!"],
            "is_creator": is_creator,
            "player_map": player_map,
        }
    except Exception as e:
        print(f"[ERROR] Exception in /room_messages: {e}")
        traceback.print_exc()
        return {"error": "Invalid or missing session"}
