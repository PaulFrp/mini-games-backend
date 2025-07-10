import json, random, time
from app.models import Player, Room
from datetime import datetime, timezone

with open("memes.json") as f:
    MEME_POOL = json.load(f)

games = {}

def start_meme_game(room_id: int, players: list[str]):
    meme_pool = MEME_POOL.copy()
    random.shuffle(meme_pool)
    games[room_id] = {
        "players": players,
        "meme_pool": meme_pool,
        "current_meme": meme_pool.pop(),
        "captions": {},
        "votes": {},
        "phase": "captioning",
        "start_time": time.time(),
        "duration": 60,
    }

# app/game/meme.py

def meme_game_status_logic(room_id, request, db):
    client_id = request.headers.get("x-client-id")
    player = db.query(Player).filter_by(user_id=client_id, room_id=room_id).first()
    room = db.query(Room).filter_by(id=room_id).first()
    room_creator = room.creator
    if player:
        player.last_seen = datetime.now(timezone.utc)
        db.commit()

    game = games.get(room_id)
    if not game:
        return {"status": "no_game"}

    print(f"[DEBUG] Game status for room {room_id}: {game}")
    now = time.time()
    remaining = int(game["duration"] - (now - game["start_time"]))

    # === Phase switching logic ===
    if game["phase"] == "captioning" and remaining <= 0:
        game["phase"] = "voting"
        game["start_time"] = now
        game["duration"] = 30  # Set voting phase duration
        remaining = game["duration"]

    elif game["phase"] == "voting" and remaining <= 0:
        game["phase"] = "results"

    # === Phase responses ===
    if "submissions" not in game:
        game["submissions"] = {}

    if game["phase"] == "captioning":
        return {
            "status": "captioning",
            "current_meme": game["current_meme"],
            "captions_submitted": len(game["captions"]),
            "players": game["players"],
            "remaining": remaining
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
        }

    elif game["phase"] == "results":
        vote_counts = {}
        for v in game["votes"].values():
            vote_counts[v] = vote_counts.get(v, 0) + 1
        max_votes = max(vote_counts.values(), default=0)
        winners = [p for p, c in vote_counts.items() if c == max_votes]
        return {
            "status": "results",
            "winners": winners,
            "votes": game["votes"],
            "captions": game["captions"],
            "can_proceed": player and client_id == room_creator,
        }

    return {"status": "unknown"}


def next_meme_logic(room_id, request, db):
    client_id = request.headers.get("x-client-id")
    player = db.query(Player).filter_by(user_id=client_id, room_id=room_id).first()
    room = db.query(Room).filter_by(id=room_id).first()
    room_creator = room.creator

    game = games.get(room_id)
    if not game or game["phase"] != "results":
        return {"status": "cannot_advance"}

    if not player or not client_id == room_creator:
        return {"status": "unauthorized"}

    if game["meme_pool"]:
        next_meme = game["meme_pool"].pop()
        game.update({
            "current_meme": next_meme,
            "captions": {},
            "votes": {},
            "phase": "captioning",
            "start_time": time.time(),
            "duration": 60,
        })
        return {"status": "next_meme", "current_meme": next_meme}
    
    return {"status": "game_over", "message": "No more memes"}
