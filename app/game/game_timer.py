"""
Centralized game timer manager to prevent desync issues.
Handles phase transitions in the background instead of during individual player status requests.
"""
import asyncio
import time
import logging
import random
from app.game.websockets import manager

logger = logging.getLogger(__name__)

# Active game timers
_active_timers = {}

async def game_timer_loop(room_id: int, games_dict: dict, db_factory):
    """
    Background task that monitors game state and triggers phase transitions.
    This runs independently of player requests to ensure all players see the same state.
    """
    logger.info(f"[TIMER] Starting game timer for room {room_id}")
    
    try:
        while room_id in games_dict:
            game = games_dict[room_id]
            now = time.time()
            elapsed = now - game["start_time"]
            remaining = int(game["duration"] - elapsed)
            
            # Check for phase transitions
            if game["phase"] == "playing":
                # Check if all non-czar players have submitted
                non_czar_players = [p for p in game["players"] if p != game["card_czar"]]
                all_submitted = all(p in game["submissions"] for p in non_czar_players)
                
                if all_submitted or remaining <= 0:
                    logger.info(f"[TIMER] Room {room_id}: Transitioning from 'playing' to 'voting'")
                    # Transition to voting phase
                    game["phase"] = "voting"
                    game["start_time"] = now
                    game["duration"] = 30  # 30 seconds to vote
                    
                    # Prepare submissions for voting
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
                    
                    # Broadcast to all players
                    await manager.broadcast(room_id, {
                        "type": "game_update",
                        "status": "voting",
                        "submissions": submission_list,
                        "remaining": game["duration"],
                        "current_question": game["current_question"],
                        "card_czar": game["card_czar"],
                        "scores": game["scores"],
                        "round": game["round"]
                    })
                    
            elif game["phase"] == "voting":
                if remaining <= 0:
                    logger.info(f"[TIMER] Room {room_id}: Transitioning from 'voting' to 'results'")
                    # Transition to results phase
                    game["phase"] = "results"
                    
                    # Count votes and award points
                    vote_counts = {}
                    for voted_for in game["votes"].values():
                        vote_counts[voted_for] = vote_counts.get(voted_for, 0) + 1
                    
                    # Find winner and award point
                    round_winner = None
                    if vote_counts:
                        max_votes = max(vote_counts.values())
                        winners = [p for p, v in vote_counts.items() if v == max_votes]
                        if len(winners) == 1:
                            game["scores"][winners[0]] += 1
                            round_winner = winners[0]
                    
                    # Broadcast results
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
            
            # Sleep for 1 second before next check
            await asyncio.sleep(1)
            
    except asyncio.CancelledError:
        logger.info(f"[TIMER] Game timer cancelled for room {room_id}")
        raise
    except Exception as e:
        logger.error(f"[TIMER] Error in game timer for room {room_id}: {e}", exc_info=True)
    finally:
        logger.info(f"[TIMER] Game timer stopped for room {room_id}")
        if room_id in _active_timers:
            del _active_timers[room_id]

def start_game_timer(room_id: int, games_dict: dict, db_factory=None):
    """Start a background timer task for a game room"""
    if room_id in _active_timers:
        logger.warning(f"[TIMER] Timer already running for room {room_id}")
        return
    
    task = asyncio.create_task(game_timer_loop(room_id, games_dict, db_factory))
    _active_timers[room_id] = task
    logger.info(f"[TIMER] Started timer task for room {room_id}")

def stop_game_timer(room_id: int):
    """Stop the background timer task for a game room"""
    if room_id in _active_timers:
        task = _active_timers[room_id]
        task.cancel()
        del _active_timers[room_id]
        logger.info(f"[TIMER] Stopped timer task for room {room_id}")

def get_active_timers():
    """Get list of room IDs with active timers (for debugging)"""
    return list(_active_timers.keys())
