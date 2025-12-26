import json, random, time
from app.models import Player, Room
from datetime import datetime, timezone
from app.game.websockets import manager
from app.game.meme_timer import start_meme_timer, stop_meme_timer
from app.db import get_db
import asyncio
import logging

with open("memes.json") as f:
    MEME_POOL = json.load(f)

games = {}

def start_meme_game(room_id: int, players: list[str], creator_id: str):
    meme_pool = MEME_POOL.copy()
    random.shuffle(meme_pool)
    games[room_id] = {
        "players": players,
        "creator": creator_id,
        "meme_pool": meme_pool,
        "current_meme": meme_pool.pop(),
        "captions": {},
        "votes": {},
        "phase": "captioning",
        "start_time": time.time(),
        "duration": 60,
        "points":{},
        "submissions": {}
    }
    
    # Start background timer to handle phase transitions
    start_meme_timer(room_id, games)

# app/game/meme.py

async def get_game_status_logic(room_id, client_id, db):
    player = db.query(Player).filter_by(user_id=client_id, room_id=room_id).first()
    room = db.query(Room).filter_by(id=room_id).first()
    room_creator = room.creator

    if player:
        player.last_seen = datetime.now(timezone.utc)
        db.commit()

    game = games.get(room_id)
    if not game:
        return {"status": "no_game"}

    now = time.time()
    remaining = int(game["duration"] - (now - game["start_time"]))

    # Prepare vote counts & winners - only if in voting or results
    vote_counts = {}
    winners = []
    if game["phase"] in ("voting", "results"):
        # Count votes for display purposes
        for v in game.get("votes", {}).values():
            vote_counts[v] = vote_counts.get(v, 0) + 1
        
        # Calculate winners based on POINTS, not vote count
        player_points = game.get("player_points", {})
        if player_points:
            max_points = max(player_points.values(), default=0)
            winners = [p for p, pts in player_points.items() if pts == max_points]
        else:
            # Fallback to vote count if no points system
            max_votes = max(vote_counts.values(), default=0)
            winners = [p for p, c in vote_counts.items() if c == max_votes]
    
    # NOTE: Phase transitions are handled by the background meme_timer, not here
    # This prevents race conditions where different players see different states

    # === Phase responses ===
    if "submissions" not in game:
        game["submissions"] = {}

    if game["phase"] == "captioning":
        return {
            "status": "captioning",
            "current_meme": game["current_meme"],
            "captions_submitted": len(game.get("captions", {})),
            "players": game.get("players", []),
            "remaining": remaining,
            "is_creator": client_id == room_creator,
        }

    if game["phase"] == "voting":
        # Resolve usernames from database
        players_in_room = db.query(Player).filter_by(room_id=room_id).all()
        player_id_to_username = {p.user_id: p.username for p in players_in_room}
        
        return {
            "status": "voting",
            "submissions": [
                {
                    "user_id": player_id,
                    "meme": sub["meme"],
                    "captions": sub["captions"],
                    "username": player_id_to_username.get(player_id, player_id)
                }
                for player_id, sub in game["submissions"].items()
            ],
            "remaining": remaining,
            "is_creator": client_id == room_creator,
        }

    if game["phase"] == "results":
        # Use the player_points that were accumulated during voting
        player_points = game.get("player_points", {})
        
        # Resolve usernames from database
        players_in_room = db.query(Player).filter_by(room_id=room_id).all()
        player_id_to_username = {p.user_id: p.username for p in players_in_room}
        
        # Add usernames to submissions for results display
        submissions_with_usernames = {
            player_id: {
                **sub,
                "username": player_id_to_username.get(player_id, player_id)
            }
            for player_id, sub in game.get("submissions", {}).items()
        }

        return {
            "status": "results",
            "winners": winners,
            "votes": game.get("votes", {}),
            "captions": game.get("captions", {}),
            "submissions": submissions_with_usernames,
            "player_points": player_points,
            "can_proceed": player and client_id == room_creator,
            "is_creator": client_id == room_creator,
        }

    return {"status": "unknown"}



def next_meme_logic(room_id, client_id, db):
    player = db.query(Player).filter_by(user_id=client_id, room_id=room_id).first()
    room = db.query(Room).filter_by(id=room_id).first()
    room_creator = room.creator

    game = games.get(room_id)
    if not game or game["phase"] != "results":
        return {"status": "cannot_advance"}

    if not player or client_id != room_creator:
        return {"status": "unauthorized"}

    if game["meme_pool"]:
        next_meme = game["meme_pool"].pop()
        game.update({
            "current_meme": next_meme,
            "captions": {},
            "votes": {},
            "phase": "captioning",
            "start_time": time.time(),
            "submissions": {},
            "player_points": {},  # Reset points for new round
            "duration": 60,
        })
        return {"status": "next_meme", "current_meme": next_meme}

    return {"status": "game_over", "message": "No more memes"}
   
