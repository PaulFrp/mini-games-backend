from fastapi import APIRouter, Depends, Request, Header, HTTPException
from app.db import get_db
from app.schemas import VoteRequest
from app.models import Player, Room
from app.game.voting import games, start_voting_game

import time
from datetime import datetime, timezone

router = APIRouter()

@router.post("/start_game/{room_id}")
async def start_game(room_id: int, x_client_id: str = Header(None), db=Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room or room.creator != x_client_id:
        raise HTTPException(status_code=403, detail="Not allowed")
    players = db.query(Player).filter(Player.room_id == room_id).all()
    start_voting_game(room_id, [p.username for p in players])
    return {"status": "game started"}

@router.get("/game_status/{room_id}")
def game_status(room_id: int, request: Request, db=Depends(get_db)):
    from app.game.voting import game_status_logic
    return game_status_logic(room_id, request, db)

@router.post("/next_question/{room_id}")
def next_question(room_id: int, request: Request, db=Depends(get_db)):
    from app.game.voting import next_question_logic
    return next_question_logic(room_id, request, db)

@router.post("/vote/{room_id}")
def vote(room_id: int, vote: VoteRequest):
    game = games.get(room_id)
    if not game or game["finished"]:
        raise HTTPException(status_code=400, detail="Voting is not active")
    game["votes"][vote.voter_id] = vote.vote_for
    return {"message": "Vote registered"}
