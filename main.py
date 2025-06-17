from fastapi import FastAPI, Request, Response, Depends, Cookie
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from uuid import uuid4
from session import signer
from db import get_db, init_db, SessionLocal
from models import Room, Player
from contextlib import asynccontextmanager
from fastapi import Header
import time
from fastapi import FastAPI, HTTPException, BackgroundTasks
from typing import Dict, List
from pydantic import BaseModel
import json
import random
import time
from contextlib import asynccontextmanager
import asyncio
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import joinedload
import traceback
import pytz
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from dotenv import load_dotenv

# start back end server with: uvicorn main:app --reload
if not os.getenv("DATABASE_URL"):
    load_dotenv()
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    # Start cleanup task at startup
    cleanup_task = asyncio.create_task(cleanup_empty_rooms_task())

    yield  # Application runs here

    # Cancel cleanup task at shutdown
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL],  # frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_index():
    return FileResponse("frontend/build/index.html")

@app.post("/create_room")
def create_room(response: Response, db: Session = Depends(get_db),  x_client_id: str = Header(None)):
    room = Room(status="waiting", creator=x_client_id)
    db.add(room)
    db.commit()
    db.refresh(room)
    cookie_value = signer.sign(str(room.id)).decode()
    response.set_cookie(key="room_session", value=cookie_value, httponly=True, samesite="lax", secure=False)
    return {"room_id": room.id}

# This join room function is deprecated and will be removed in the future.
@app.post("/join_room/{room_id}")
def join_room(room_id: int, response: Response):
    cookie_value = signer.sign(str(room_id)).decode()
    response.set_cookie(key="room_session", value=cookie_value, httponly=True, samesite="lax", secure=False)
    return {"message": f"Joined room {room_id}"}


class JoinRoomRequest(BaseModel):
    username: str
    client_id: str

@app.post("/join_room_with_username/{room_id}")
def join_room_with_username(
    room_id: int,
    data: JoinRoomRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    # Add user to DB if not exists
    player = db.query(Player).filter_by(user_id=data.client_id, room_id=room_id).first()
    if player:
        player.username = data.username
    else:
        player = Player(user_id=data.client_id, username=data.username, room_id=room_id)
        db.add(player)
    db.commit()

    # Set signed session cookie like the old endpoint
    cookie_value = signer.sign(str(room_id)).decode()
    response.set_cookie(
        key="room_session",
        value=cookie_value,
        httponly=True,
        samesite="lax",
        secure=False,  # Set to True in production with HTTPS
    )

    return {"message": f"User '{data.username}' joined room {room_id}"}


@app.get("/room_messages")
def get_messages(
    room_session: str = Cookie(None),
    x_client_id: str = Header(None),
    db: Session = Depends(get_db),
):
    try:
        room_id = signer.unsign(room_session).decode()
        room = db.query(Room).filter(Room.id == int(room_id)).first()
        if not room:
            return {"error": "Room not found"}

        is_creator = room.creator == x_client_id
        return {
            "room_id": room_id,
            "messages": [f"Welcome to room {room_id}!"],
            "is_creator": is_creator,
        }
    except Exception:
        return {"error": "Invalid or missing session"}



rooms_status = {} 

@app.post("/start_game/{room_id}")
async def start_game(room_id: int, x_client_id: str = Header(None), db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    print(f"[DEBUG] room_id: {room_id}")
    print(f"[DEBUG] x_client_id header: {x_client_id}")
    print(f"[DEBUG] room.creator in DB: {room.creator}")
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    if room.creator != x_client_id:
        raise HTTPException(status_code=403, detail="Only the creator can start the game")

    players = db.query(Player).filter(Player.room_id == room_id).all()
    player_names = [p.username for p in players]

    start_voting_game(room_id, player_names)
    return {"status": "game started", "room_id": room_id}

@app.get("/room_status/{room_id}")
async def room_status(room_id: int):
    status = rooms_status.get(room_id, "waiting")
    return {"room_id": room_id, "status": status}



# Store game state in memory
games = {}  # room_id -> game info

class VoteRequest(BaseModel):
    voter_id: str
    vote_for: str  # player name/id

with open("questions.json") as f:
    QUESTION_POOL = json.load(f)

games = {}  # room_id -> game state

def start_voting_game(room_id: int, players: list[str]):
    questions = QUESTION_POOL.copy()
    random.shuffle(questions)
    next_question = questions.pop()

    games[room_id] = {
        "players": players,
        "questions": questions,
        "question": next_question,
        "votes": {},
        "start_time": time.time(),
        "duration": 10,  # voting duration
        "finished": False,
        "round_end_time": None,
    }



@app.get("/game_status/{room_id}")
def game_status(room_id: int, db: Session = Depends(get_db), request: Request = None):
    player = None
    client_id = request.headers.get("x-client-id")
    if client_id:
        player = db.query(Player).filter_by(user_id=client_id, room_id=room_id).first()
        if player:
            player.last_seen = datetime.now(timezone.utc)
            print(f"[Ping] Updated last_seen for user {player.user_id} in room {room_id}")
            db.commit()

    game = games.get(room_id)
    if not game:
        return {"status": "no_game"}

    now = time.time()
    time_elapsed = now - game["start_time"]

    # Check if voting period is still active
    if not game["finished"] and time_elapsed < game["duration"]:
        return {
            "status": "voting",
            "question": game["question"],
            "players": game["players"],
            "votes_count": len(game["votes"]),
            "remaining": int(game["duration"] - time_elapsed),
        }

    # Voting is finished, tally votes once
    if not game["finished"]:
        # Count votes
        vote_counts = {}
        for voted in game["votes"].values():
            vote_counts[voted] = vote_counts.get(voted, 0) + 1

        if vote_counts:
            max_votes = max(vote_counts.values())
            winners = [p for p, count in vote_counts.items() if count == max_votes]
        else:
            winners = []

        game["finished"] = True
        game["winners"] = winners
        game["round_end_time"] = now

        return {
            "status": "finished",
            "winners": winners,
            "votes_count": vote_counts,
        }


    # Voting finished, waiting for manual next question
    return {
        "status": "finished",
        "winners": game.get("winners", []),
        "votes_count": game.get("votes", {}),
        "can_proceed": True if player and player.is_creator else False,
    }

@app.post("/next_question/{room_id}")
def next_question(room_id: int, db: Session = Depends(get_db), request: Request = None):
    client_id = request.headers.get("x-client-id")
    player = db.query(Player).filter_by(user_id=client_id, room_id=room_id).first()

    if not player:
        raise HTTPException(status_code=403, detail="Only the creator can proceed to the next question.")

    game = games.get(room_id)
    if not game or not game["finished"]:
        return {"status": "cannot_advance", "reason": "Game not finished or doesn't exist"}

    if game["questions"]:
        next_question = game["questions"].pop()
        now = time.time()
        game["question"] = next_question
        game["votes"] = {}
        game["start_time"] = now
        game["finished"] = False
        game["round_end_time"] = None

        return {
            "status": "voting",
            "question": game["question"],
            "players": game["players"],
            "votes_count": 0,
            "remaining": game["duration"],
        }
    else:
        return {
            "status": "game_over",
            "message": "No more questions left.",
        }

@app.post("/vote/{room_id}")
async def vote(room_id: int, vote: VoteRequest):
    game = games.get(room_id)
    if not game or game["finished"]:
        raise HTTPException(status_code=400, detail="No active voting or voting finished")

    if vote.vote_for not in game["players"]:
        raise HTTPException(status_code=400, detail="Invalid player")

    # Register vote
    game["votes"][vote.voter_id] = vote.vote_for
    return {"message": f"Voted for {vote.vote_for}"}


local_tz = pytz.timezone("Europe/Paris")

def to_utc_aware(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Convert naive local datetime to aware UTC datetime
        local_dt = local_tz.localize(dt)
        return local_dt.astimezone(timezone.utc)
    return dt


async def cleanup_empty_rooms_task():
    while True:
        await asyncio.sleep(30)
        with SessionLocal() as db:
            now = datetime.now(timezone.utc)
            timeout = now - timedelta(minutes=5)

            rooms = db.query(Room).options(joinedload(Room.players)).all()
            for room in rooms:
                active_players = [
                    p for p in room.players
                    if p.last_seen and to_utc_aware(p.last_seen) > timeout
                ]
                print(f"[Cleanup] Room {room.id} has {len(room.players)} total players, {len(active_players)} active")
                print(f"[Cleanup] Room {room.id} last seen time: {room.players[0].last_seen if room.players else 'N/A'}")

                if not active_players:
                    print(f"[Cleanup] Deleting empty room {room.id}")
                    db.delete(room)

            db.commit()


