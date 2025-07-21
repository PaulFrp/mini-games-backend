import json, random, time
from app.models import Player, Room
from datetime import datetime, timezone
from app.game.websockets import manager
from app.db import get_db
import asyncio

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
        "duration": 10,
        "points":{}
    }

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
        for v in game.get("votes", {}).values():
            vote_counts[v] = vote_counts.get(v, 0) + 1
        max_votes = max(vote_counts.values(), default=0)
        winners = [p for p, c in vote_counts.items() if c == max_votes]
    
    

    # === Phase switching logic ===
    if game["phase"] == "captioning" and remaining <= 0:
        game["phase"] = "voting"
        game["start_time"] = now
        game["duration"] = 15
        remaining = game["duration"]
        # 🔔 Broadcast voting phase to all
        await manager.broadcast(room_id, {
            "type": "game_update",
            "status": "voting",
            "submissions": [
                {
                    "user_id": player_id,
                    "meme": sub["meme"],
                    "captions": sub["captions"],
                    "username": player_id  # or resolve real username
                }
                for player_id, sub in game["submissions"].items()
            ],
            "remaining": remaining,
        })

    elif game["phase"] == "voting" and remaining <= 0:
        game["phase"] = "results"
        # 🔔 Broadcast results
        await manager.broadcast(room_id, {
            "type": "game_update",
            "status": "results",
            "winners": winners,
            "votes": game.get("votes", {}),
            "captions": game.get("captions", {}),
            "can_proceed": player and client_id == room_creator,
        })

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
        return {
            "status": "voting",
            "submissions": [
                {
                    "user_id": player_id,
                    "meme": sub["meme"],
                    "captions": sub["captions"],
                }
                for player_id, sub in game["submissions"].items()
            ],
            "remaining": remaining,
            "is_creator": client_id == room_creator,
        }

    if game["phase"] == "results":
        # Calculate total points received by each player
        player_points = {}
        vote_points = game.get("vote_points", {})

        for voter_id, voted_id in game.get("votes", {}).items():
            points = vote_points.get(voter_id, 0)  # default to 0 if not found
            if voted_id in player_points:
                player_points[voted_id] += points
            else:
                player_points[voted_id] = points

        return {
            "status": "results",
            "winners": winners,
            "votes": game.get("votes", {}),
            "captions": game.get("captions", {}),
            "submissions": game.get("submissions", []),
            "player_points": game.get("player_points", {}),
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
            "duration": 10,
        })
        return {"status": "next_meme", "current_meme": next_meme}

    return {"status": "game_over", "message": "No more memes"}
   
async def game_phase_watcher():
    while True:
        db = next(get_db())  # get a DB session

        for room_id, game in list(games.items()):
            now = time.time()
            remaining = game["duration"] - (now - game["start_time"])

            if remaining <= 0:
                # call your existing logic to advance phase
                # but get_game_status_logic expects client_id & db,
                # we'll just pick the creator as client_id for broadcast purposes
                # (or just pick the first player)
                client_id = game.get("creator") or (game["players"][0] if game["players"] else None)

                if client_id is not None:
                    status = await get_game_status_logic(room_id, client_id, db)
                    # Broadcast updated game state to the room
                    await manager.broadcast(room_id, {
                        "type": "game_update",
                        **status,
                    })

        await asyncio.sleep(1)  # check every 1 second

