from fastapi import APIRouter, HTTPException
from app.schemas import CaptionRequest
from fastapi import APIRouter, Depends, Request, Header, HTTPException
from app.db import get_db
from app.schemas import VoteRequest
from app.models import Player, Room
from app.game.websockets import manager

from app.game.meme import MEME_POOL  # import it


from app.game.meme import games, start_meme_game


router = APIRouter()

@router.post("/start_game/{room_id}")
async def start_game(room_id: int, x_client_id: str = Header(None), db=Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room or room.creator != x_client_id:
        raise HTTPException(status_code=403, detail="Not allowed")
    
    players = db.query(Player).filter(Player.room_id == room_id).all()
    usernames = [p.username for p in players]
    start_meme_game(room_id, usernames, room.creator)
    await manager.broadcast(room_id, {
        "type": "game_update",
        "status": "captioning",
        "players": usernames,
        "current_meme": games[room_id]["current_meme"],
        "remaining": games[room_id]["duration"]
    })

    return {"status": "game started"}



@router.get("/templates")
def get_meme_templates():
    print("MEME_POOL", MEME_POOL)
    return MEME_POOL