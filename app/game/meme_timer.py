"""
Centralized meme game timer manager to prevent desync issues.
Handles phase transitions in the background instead of during individual player status requests.
"""
import asyncio
import time
import logging
from app.game.websockets import manager

logger = logging.getLogger(__name__)

# Active meme game timers
_active_meme_timers = {}

async def meme_timer_loop(room_id: int, games_dict: dict, db_factory):
    """
    Background task that monitors meme game state and triggers phase transitions.
    This runs independently of player requests to ensure all players see the same state.
    """
    logger.info(f"[MEME_TIMER] Starting meme game timer for room {room_id}")
    
    try:
        while room_id in games_dict:
            game = games_dict[room_id]
            now = time.time()
            elapsed = now - game["start_time"]
            remaining = int(game["duration"] - elapsed)
            
            # Check for phase transitions
            if game["phase"] == "captioning" and remaining <= 0:
                logger.info(f"[MEME_TIMER] Room {room_id}: Transitioning from 'captioning' to 'voting'")
                game["phase"] = "voting"
                game["start_time"] = now
                game["duration"] = 60
                
                # Prepare submissions for voting (need db to resolve usernames)
                # For now, use player IDs as fallback
                submissions = [
                    {
                        "user_id": player_id,
                        "meme": sub["meme"],
                        "captions": sub["captions"],
                        "username": player_id  # Will be resolved on client side or via polling
                    }
                    for player_id, sub in game["submissions"].items()
                ]
                
                # Broadcast to all players
                await manager.broadcast(room_id, {
                    "type": "game_update",
                    "status": "voting",
                    "submissions": submissions,
                    "remaining": game["duration"],
                })
                
            elif game["phase"] == "voting" and remaining <= 0:
                logger.info(f"[MEME_TIMER] Room {room_id}: Transitioning from 'voting' to 'results'")
                game["phase"] = "results"
                
                # Calculate winners based on points
                player_points = game.get("player_points", {})
                vote_counts = {}
                for voted_for in game.get("votes", {}).values():
                    vote_counts[voted_for] = vote_counts.get(voted_for, 0) + 1
                
                winners = []
                if player_points:
                    max_points = max(player_points.values(), default=0)
                    winners = [p for p, pts in player_points.items() if pts == max_points]
                else:
                    # Fallback to vote count
                    max_votes = max(vote_counts.values(), default=0)
                    winners = [p for p, c in vote_counts.items() if c == max_votes]
                
                # Broadcast results
                await manager.broadcast(room_id, {
                    "type": "game_update",
                    "status": "results",
                    "winners": winners,
                    "votes": game.get("votes", {}),
                    "player_points": player_points,
                    "vote_counts": vote_counts
                })
            
            # Sleep for 1 second before next check
            await asyncio.sleep(1)
            
    except asyncio.CancelledError:
        logger.info(f"[MEME_TIMER] Meme game timer cancelled for room {room_id}")
        raise
    except Exception as e:
        logger.error(f"[MEME_TIMER] Error in meme game timer for room {room_id}: {e}", exc_info=True)
    finally:
        logger.info(f"[MEME_TIMER] Meme game timer stopped for room {room_id}")
        if room_id in _active_meme_timers:
            del _active_meme_timers[room_id]

def start_meme_timer(room_id: int, games_dict: dict, db_factory=None):
    """Start a background timer task for a meme game room"""
    if room_id in _active_meme_timers:
        logger.warning(f"[MEME_TIMER] Timer already running for room {room_id}")
        return
    
    task = asyncio.create_task(meme_timer_loop(room_id, games_dict, db_factory))
    _active_meme_timers[room_id] = task
    logger.info(f"[MEME_TIMER] Started timer task for room {room_id}")

def stop_meme_timer(room_id: int):
    """Stop the background timer task for a meme game room"""
    if room_id in _active_meme_timers:
        task = _active_meme_timers[room_id]
        task.cancel()
        del _active_meme_timers[room_id]
        logger.info(f"[MEME_TIMER] Stopped timer task for room {room_id}")

def get_active_meme_timers():
    """Get list of room IDs with active meme timers (for debugging)"""
    return list(_active_meme_timers.keys())
