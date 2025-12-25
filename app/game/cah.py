import json, random, time
from app.models import Player, Room
from datetime import datetime, timezone
from app.game.websockets import manager
from app.db import get_db
import asyncio
import logging

# Load cards and questions
with open("cah_cards.json") as f:
    CARD_POOL = json.load(f)

with open("cah_questions.json") as f:
    QUESTION_POOL = json.load(f)

games = {}

def start_cah_game(room_id: int, players: list[str], creator_id: str):
    """Initialize a new Cards Against Humanity game"""
    # Shuffle question pool
    question_pool = QUESTION_POOL.copy()
    random.shuffle(question_pool)
    
    # Deal cards to each player (7 cards to start)
    player_hands = {}
    card_pool = CARD_POOL.copy()
    random.shuffle(card_pool)
    
    for player in players:
        player_hands[player] = []
        for _ in range(7):
            if card_pool:
                player_hands[player].append(card_pool.pop())
    
    games[room_id] = {
        "players": players,
        "creator": creator_id,
        "question_pool": question_pool,
        "card_pool": card_pool,
        "current_question": question_pool.pop() if question_pool else None,
        "player_hands": player_hands,
        "submissions": {},  # {player_id: [card1, card2]}
        "votes": {},  # {voter_id: player_id}
        "phase": "playing",  # playing -> voting -> results
        "start_time": time.time(),
        "duration": 60,  # 60 seconds to play cards
        "scores": {player: 0 for player in players},
        "round": 1,
        "card_czar": players[0],  # First player is czar, rotates each round
        "czar_index": 0
    }

async def get_game_status_logic(room_id, client_id, db):
    """Get current game status for a player"""
    player = db.query(Player).filter_by(user_id=client_id, room_id=room_id).first()
    room = db.query(Room).filter_by(id=room_id).first()
    room_creator = room.creator if room else None

    if player:
        player.last_seen = datetime.now(timezone.utc)
        db.commit()

    game = games.get(room_id)
    if not game:
        return {"status": "no_game"}

    now = time.time()
    remaining = int(game["duration"] - (now - game["start_time"]))
    
    # Get player's username
    player_username = player.username if player else client_id
    
    # Prepare response based on phase
    response = {
        "status": game["phase"],
        "remaining": max(0, remaining),
        "current_question": game["current_question"],
        "scores": game["scores"],
        "round": game["round"],
        "card_czar": game["card_czar"],
        "is_czar": player_username == game["card_czar"],
        "player_hand": game["player_hands"].get(player_username, []),
        "has_submitted": player_username in game["submissions"]
    }
    
    # Add phase-specific data
    if game["phase"] == "voting":
        # Resolve usernames for submissions
        players_in_room = db.query(Player).filter_by(room_id=room_id).all()
        player_id_to_username = {p.user_id: p.username for p in players_in_room}
        
        # Shuffle submissions to anonymize
        submission_list = [
            {
                "player": player_name,
                "cards": cards,
                "username": player_name  # Already using username
            }
            for player_name, cards in game["submissions"].items()
            if player_name != game["card_czar"]  # Don't show czar's submission if any
        ]
        random.shuffle(submission_list)
        
        response["submissions"] = submission_list
        response["has_voted"] = player_username in game["votes"]
        
    elif game["phase"] == "results":
        # Count votes
        vote_counts = {}
        for voted_for in game["votes"].values():
            vote_counts[voted_for] = vote_counts.get(voted_for, 0) + 1
        
        # Find winner of round
        round_winner = None
        if vote_counts:
            max_votes = max(vote_counts.values())
            winners = [p for p, v in vote_counts.items() if v == max_votes]
            round_winner = winners[0] if len(winners) == 1 else None
        
        response["vote_counts"] = vote_counts
        response["round_winner"] = round_winner
        response["submissions"] = [
            {
                "player": player_name,
                "cards": cards,
                "votes": vote_counts.get(player_name, 0)
            }
            for player_name, cards in game["submissions"].items()
            if player_name != game["card_czar"]
        ]
    
    # Phase transitions
    if game["phase"] == "playing":
        # Check if all non-czar players have submitted
        non_czar_players = [p for p in game["players"] if p != game["card_czar"]]
        all_submitted = all(p in game["submissions"] for p in non_czar_players)
        
        if all_submitted or remaining <= 0:
            # Transition to voting phase
            game["phase"] = "voting"
            game["start_time"] = now
            game["duration"] = 30  # 30 seconds to vote
            remaining = game["duration"]
            
            # Broadcast to all players
            players_in_room = db.query(Player).filter_by(room_id=room_id).all()
            
            submission_list = [
                {
                    "player": player_name,
                    "cards": cards,
                    "username": player_name
                }
                for player_name, cards in game["submissions"].items()
                if player_name != game["card_czar"]
            ]
            random.shuffle(submission_list)
            
            await manager.broadcast(room_id, {
                "type": "game_update",
                "status": "voting",
                "submissions": submission_list,
                "remaining": remaining,
                "current_question": game["current_question"],
                "card_czar": game["card_czar"]
        })
        
    elif game["phase"] == "voting" and remaining <= 0:
        # Transition to results phase
        game["phase"] = "results"
        
        # Count votes and award points
        vote_counts = {}
        for voted_for in game["votes"].values():
            vote_counts[voted_for] = vote_counts.get(voted_for, 0) + 1
        
        # Find winner and award point
        if vote_counts:
            max_votes = max(vote_counts.values())
            winners = [p for p, v in vote_counts.items() if v == max_votes]
            if len(winners) == 1:
                game["scores"][winners[0]] += 1
                round_winner = winners[0]
            else:
                round_winner = None
        else:
            round_winner = None
        
        await manager.broadcast(room_id, {
            "type": "game_update",
            "status": "results",
            "round_winner": round_winner,
            "scores": game["scores"],
            "vote_counts": vote_counts,
            "submissions": [
                {
                    "player": player_name,
                    "cards": cards,
                    "votes": vote_counts.get(player_name, 0)
                }
                for player_name, cards in game["submissions"].items()
                if player_name != game["card_czar"]
            ]
        })
    
    return response

async def submit_cards_logic(room_id, client_id, selected_cards, db):
    """Handle a player submitting their cards"""
    player = db.query(Player).filter_by(user_id=client_id, room_id=room_id).first()
    if not player:
        return {"error": "Player not found"}
    
    game = games.get(room_id)
    if not game or game["phase"] != "playing":
        return {"error": "Cannot submit cards now"}
    
    player_username = player.username
    
    # Don't allow card czar to submit
    if player_username == game["card_czar"]:
        return {"error": "Card Czar cannot submit cards"}
    
    # Check if player already submitted
    if player_username in game["submissions"]:
        return {"error": "You already submitted your cards"}
    
    # Validate cards are in player's hand
    player_hand = game["player_hands"].get(player_username, [])
    for card in selected_cards:
        if card not in player_hand:
            return {"error": "Invalid card selection"}
    
    # Validate number of cards matches question blanks
    required_cards = game["current_question"]["blanks"]
    if len(selected_cards) != required_cards:
        return {"error": f"Must submit exactly {required_cards} card(s)"}
    
    # Remove cards from hand
    for card in selected_cards:
        player_hand.remove(card)
    
    # Refill hand to 7 cards
    while len(player_hand) < 7 and game["card_pool"]:
        player_hand.append(game["card_pool"].pop())
    
    game["submissions"][player_username] = selected_cards
    
    # Send individual status updates to each player (don't broadcast full status which includes hands)
    # Just notify that a player submitted
    await manager.broadcast(room_id, {
        "type": "player_submitted",
        "player": player_username,
        "total_submissions": len(game["submissions"])
    })
    
    return {"success": True}

async def submit_vote_logic(room_id, client_id, voted_for, db):
    """Handle card czar voting for winner"""
    player = db.query(Player).filter_by(user_id=client_id, room_id=room_id).first()
    if not player:
        return {"error": "Player not found"}
    
    game = games.get(room_id)
    if not game or game["phase"] != "voting":
        return {"error": "Cannot vote now"}
    
    player_username = player.username
    
    # Only card czar can vote
    if player_username != game["card_czar"]:
        return {"error": "Only Card Czar can vote"}
    
    # Validate voted_for is in submissions
    if voted_for not in game["submissions"]:
        return {"error": "Invalid vote"}
    
    game["votes"][player_username] = voted_for
    
    return {"success": True}

async def next_round_logic(room_id, db):
    """Start the next round"""
    game = games.get(room_id)
    if not game or game["phase"] != "results":
        return {"error": "Cannot start next round"}
    
    # Check if game should end (first to 5 points wins)
    max_score = max(game["scores"].values()) if game["scores"] else 0
    if max_score >= 5:
        winners = [p for p, s in game["scores"].items() if s == max_score]
        await manager.broadcast(room_id, {
            "type": "game_over",
            "winners": winners,
            "final_scores": game["scores"]
        })
        return {"game_over": True, "winners": winners}
    
    # Rotate card czar
    game["czar_index"] = (game["czar_index"] + 1) % len(game["players"])
    game["card_czar"] = game["players"][game["czar_index"]]
    
    # Get next question
    if not game["question_pool"]:
        # Reshuffle if we run out
        game["question_pool"] = QUESTION_POOL.copy()
        random.shuffle(game["question_pool"])
    
    game["current_question"] = game["question_pool"].pop()
    game["submissions"] = {}
    game["votes"] = {}
    game["phase"] = "playing"
    game["start_time"] = time.time()
    game["duration"] = 60
    game["round"] += 1
    
    # Broadcast new round
    await manager.broadcast(room_id, {
        "type": "game_update",
        "status": "playing",
        "current_question": game["current_question"],
        "card_czar": game["card_czar"],
        "round": game["round"],
        "scores": game["scores"],
        "remaining": game["duration"]
    })
    
    return {"success": True}
