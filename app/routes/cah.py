from fastapi import APIRouter, HTTPException, Depends, Header
from app.db import get_db
from app.models import Player, Room
from app.game.websockets import manager
from app.game.cah import (
    games, 
    start_cah_game, 
    get_game_status_logic,
    submit_cards_logic,
    submit_vote_logic,
    next_round_logic,
    CARD_POOL,
    QUESTION_POOL
)
from pydantic import BaseModel
from typing import List

router = APIRouter()

class CardsSubmission(BaseModel):
    cards: List[str]

class VoteSubmission(BaseModel):
    voted_for: str

@router.post("/start_game/{room_id}")
async def start_game(room_id: int, x_client_id: str = Header(None), db=Depends(get_db)):
    """Start a new Cards Against Humanity game"""
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room or room.creator != x_client_id:
        raise HTTPException(status_code=403, detail="Not allowed")
    
    players = db.query(Player).filter(Player.room_id == room_id).all()
    if len(players) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 players to start")
    
    usernames = [p.username for p in players]
    print(f"[START_CAH_GAME] Room {room_id}: Starting game with {len(players)} players")
    
    start_cah_game(room_id, usernames, room.creator)
    
    game = games[room_id]
    
    # Broadcast to all players
    broadcast_data = {
        "type": "game_update",
        "status": "playing",
        "players": usernames,
        "current_question": game["current_question"],
        "card_czar": game["card_czar"],
        "scores": game["scores"],
        "round": game["round"],
        "remaining": game["duration"]
    }
    
    print(f"[START_CAH_GAME] Broadcasting to room {room_id}")
    print(f"[START_CAH_GAME] Active connections dict keys: {list(manager.active_connections.keys())}")
    print(f"[START_CAH_GAME] Looking for room_id: {room_id} (type: {type(room_id).__name__})")
    active_connections = len(manager.active_connections.get(room_id, []))
    print(f"[START_CAH_GAME] Active WebSocket connections in room {room_id}: {active_connections}")
    await manager.broadcast(room_id, broadcast_data)
    
    return {"status": "game started"}

@router.get("/game_status")
async def game_status(room_id: int, x_client_id: str = Header(None), db=Depends(get_db)):
    """Get current game status (REST fallback)"""
    status = await get_game_status_logic(room_id, x_client_id, db)
    return {"type": "game_update", **status}

@router.post("/submit_cards/{room_id}")
async def submit_cards(
    room_id: int, 
    submission: CardsSubmission,
    x_client_id: str = Header(None), 
    db=Depends(get_db)
):
    """Submit cards for the current question"""
    result = await submit_cards_logic(room_id, x_client_id, submission.cards, db)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@router.post("/submit_vote/{room_id}")
async def submit_vote(
    room_id: int,
    vote: VoteSubmission,
    x_client_id: str = Header(None),
    db=Depends(get_db)
):
    """Card Czar votes for the winning submission"""
    result = await submit_vote_logic(room_id, x_client_id, vote.voted_for, db)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@router.post("/next_round/{room_id}")
async def next_round(room_id: int, x_client_id: str = Header(None), db=Depends(get_db)):
    """Start the next round"""
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room or room.creator != x_client_id:
        raise HTTPException(status_code=403, detail="Not allowed")
    
    result = await next_round_logic(room_id, db)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@router.get("/cards")
def get_cards():
    """Get all available cards (for preview/admin)"""
    return CARD_POOL

@router.get("/questions")
def get_questions():
    """Get all available questions (for preview/admin)"""
    return QUESTION_POOL
