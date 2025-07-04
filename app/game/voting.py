import time, json, random
from app.models import Player, Room
from datetime import datetime, timezone

with open("questions.json", encoding="utf-8") as f:
    QUESTION_POOL = json.load(f)

games = {}

def start_voting_game(room_id: int, players: list[str]):
    questions = QUESTION_POOL.copy()
    random.shuffle(questions)
    games[room_id] = {
        "players": players,
        "questions": questions,
        "question": questions.pop(),
        "votes": {},
        "start_time": time.time(),
        "duration": 20,
        "finished": False
    }

def game_status_logic(room_id, request, db):
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

    now = time.time()
    if not game["finished"] and now - game["start_time"] < game["duration"]:
        return {
            "status": "voting",
            "question": game["question"],
            "players": game["players"],
            "votes_count": len(game["votes"]),
            "remaining": int(game["duration"] - (now - game["start_time"]))
        }

    if not game["finished"]:
        vote_counts = {}
        for v in game["votes"].values():
            vote_counts[v] = vote_counts.get(v, 0) + 1
        max_votes = max(vote_counts.values(), default=0)
        winners = [p for p, c in vote_counts.items() if c == max_votes]
        game["finished"] = True
        game["winners"] = winners

    return {
        "status": "finished",
        "winners": game.get("winners", []),
        "votes_count": game.get("votes", {}),
        "can_proceed": player and client_id == room_creator,
    }

def next_question_logic(room_id, request, db):
    client_id = request.headers.get("x-client-id")
    player = db.query(Player).filter_by(user_id=client_id, room_id=room_id).first()
    game = games.get(room_id)
    if not game or not game["finished"]:
        return {"status": "cannot_advance"}
    if game["questions"]:
        question = game["questions"].pop()
        game.update({
            "question": question,
            "votes": {},
            "start_time": time.time(),
            "finished": False
        })
        return {"status": "voting", "question": question}
    return {"status": "game_over", "message": "No more questions"}
