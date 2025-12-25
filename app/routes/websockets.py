# app/routes/ws.py

import json
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.game.websockets import manager
from app.db import get_db
from app.models import Player, Room
from app.game.meme import games, get_game_status_logic, next_meme_logic, MEME_POOL
from app.game import cah

router = APIRouter()

@router.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: int):
    client_id = websocket.query_params.get("client_id")
    print(f"[WS] Client {client_id} connecting to room {room_id}")
    await manager.connect(room_id, websocket)
    print(f"[WS] Client {client_id} connected. Active connections: {len(manager.active_connections.get(room_id, []))}")

    # Keepalive task to prevent Heroku timeout (55s)
    async def send_keepalive():
        try:
            while True:
                await asyncio.sleep(30)  # Send ping every 30 seconds
                try:
                    await websocket.send_json({"type": "ping"})
                except:
                    break
        except asyncio.CancelledError:
            pass

    keepalive_task = asyncio.create_task(send_keepalive())

    try:
        db = next(get_db())

        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            msg_type = message.get("type")

            # --- 0. Ping/Pong for keepalive ---
            if msg_type == "pong":
                # Client responded to ping, connection is alive
                continue

            # --- 1. Game status sync ---
            if msg_type == "get_status":
                status = await get_game_status_logic(room_id, client_id, db)
                await websocket.send_json({ "type": "game_update", **status })

            # --- 2. Caption submission ---
            elif msg_type == "submit_caption":
                captions = message.get("caption")
                game = games.get(room_id)

                if not game or game["phase"] != "captioning":
                    await websocket.send_json({ "error": "Not in captioning phase" })
                    continue

                if not captions or len(captions) != len(game["current_meme"]["caption_slots"]):
                    await websocket.send_json({ "error": "Invalid caption count" })
                    continue

                # Ensure 'captions' and 'submissions' dicts are initialized
                if "captions" not in game:
                    game["captions"] = {}

                if "submissions" not in game:
                    game["submissions"] = {}

                game["captions"][client_id] = captions

                if client_id not in game["submissions"]:
                    game["submissions"][client_id] = {
                        "meme": game["current_meme"],
                        "captions": captions,
                    }
                else:
                    game["submissions"][client_id]["captions"] = captions

                status = await get_game_status_logic(room_id, client_id, db)
                await manager.broadcast(room_id, {
                    "type": "game_update",
                    **status
                })


            # --- 3. Voting submission ---
            elif msg_type == "submit_vote":
                vote_for = message.get("vote_for")
                try:
                    points = int(message.get("points") or 0)
                except (ValueError, TypeError):
                    points = 0  # fallback
                    
                print(f"Received vote from {client_id} for {vote_for} with points: {points} (type: {type(points)})")
                game = games.get(room_id)

                if not game or game["phase"] != "voting":
                    await websocket.send_json({"error": "Voting is not active"})
                    continue

                # Check if already voted FIRST
                if client_id in game["votes"]:
                    await websocket.send_json({"error": "You already voted"})
                    continue

                if client_id == vote_for:
                    await websocket.send_json({"error": "You can't vote for yourself!"})
                    continue

                # Register the vote
                game["votes"][client_id] = vote_for

                # Apply points
                game.setdefault("player_points", {})
                game["player_points"][vote_for] = game["player_points"].get(vote_for, 0) + points

                status = await get_game_status_logic(room_id, client_id, db)
                await manager.broadcast(room_id, {
                    "type": "game_update",
                    **status
                })


            # --- 4. Next meme (if game master triggers it) ---
            elif msg_type == "next_meme":
                room = db.query(Room).filter(Room.id == room_id).first()
                if not room or room.creator != client_id:
                    await websocket.send_json({ "error": "Only creator can trigger next meme" })
                    continue

                result = next_meme_logic(room_id, client_id, db)

                if result["status"] == "next_meme":
                    print("[WS] Next meme triggered. Broadcasting...")
                    status = await get_game_status_logic(room_id, client_id, db)
                    await manager.broadcast(room_id, {
                        "type": "game_update",
                        **status
                    })

                elif result["status"] == "game_over":
                    print("[WS] No more memes. Game over.")
                    await manager.broadcast(room_id, {
                        "type": "game_over"
                    })

                elif result["status"] == "cannot_advance":
                    await websocket.send_json({ "error": "Can't proceed yet." })

                elif result["status"] == "unauthorized":
                    await websocket.send_json({ "error": "Unauthorized to trigger next meme." })


            # --- Optional: unknown message ---
            else:
                await websocket.send_json({ "error": "Unknown message type" })

    except WebSocketDisconnect:
        print(f"[WS] Client {client_id} disconnected from room {room_id}")
        keepalive_task.cancel()
        manager.disconnect(room_id, websocket)
    except Exception as e:
        print(f"[WS] Error for client {client_id} in room {room_id}: {e}")
        keepalive_task.cancel()
        manager.disconnect(room_id, websocket)


@router.websocket("/ws/cah/{room_id}")
async def cah_websocket_endpoint(websocket: WebSocket, room_id: int):
    """WebSocket endpoint for Cards Against Humanity game"""
    client_id = websocket.query_params.get("client_id")
    print(f"[CAH_WS] Client {client_id} connecting to CAH room {room_id}")
    await manager.connect(room_id, websocket)
    print(f"[CAH_WS] Client {client_id} connected. Active connections: {len(manager.active_connections.get(room_id, []))}")

    # Keepalive task to prevent Heroku timeout
    async def send_keepalive():
        try:
            while True:
                await asyncio.sleep(30)
                try:
                    await websocket.send_json({"type": "ping"})
                except:
                    break
        except asyncio.CancelledError:
            pass

    keepalive_task = asyncio.create_task(send_keepalive())

    try:
        db = next(get_db())

        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            msg_type = message.get("type")

            # --- 0. Ping/Pong for keepalive ---
            if msg_type == "pong":
                continue

            # --- 1. Game status sync ---
            if msg_type == "get_status":
                status = await cah.get_game_status_logic(room_id, client_id, db)
                await websocket.send_json({"type": "game_update", **status})

            # --- 2. Submit cards ---
            elif msg_type == "submit_cards":
                selected_cards = message.get("cards", [])
                result = await cah.submit_cards_logic(room_id, client_id, selected_cards, db)
                
                if "error" in result:
                    await websocket.send_json({"error": result["error"]})
                # Don't broadcast full status here - that will update player hands globally
                # The frontend handles hasSubmitted state locally

            # --- 3. Submit vote (Card Czar only) ---
            elif msg_type == "submit_vote":
                voted_for = message.get("voted_for")
                result = await cah.submit_vote_logic(room_id, client_id, voted_for, db)
                
                if "error" in result:
                    await websocket.send_json({"error": result["error"]})
                else:
                    # Immediately transition to results
                    game = cah.games.get(room_id)
                    if game:
                        game["phase"] = "results"
                        
                        # Count votes and award points
                        vote_counts = {}
                        for voted_player in game["votes"].values():
                            vote_counts[voted_player] = vote_counts.get(voted_player, 0) + 1
                        
                        # Find winner
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

            # --- 4. Next round ---
            elif msg_type == "next_round":
                room = db.query(Room).filter(Room.id == room_id).first()
                if not room or room.creator != client_id:
                    await websocket.send_json({"error": "Only creator can start next round"})
                    continue

                result = await cah.next_round_logic(room_id, db)
                
                if "error" in result:
                    await websocket.send_json({"error": result["error"]})
                elif result.get("game_over"):
                    await manager.broadcast(room_id, {
                        "type": "game_over",
                        "winners": result["winners"],
                        "final_scores": cah.games[room_id]["scores"]
                    })
                # Otherwise, next_round_logic already broadcasted the new round

            # --- Unknown message ---
            else:
                await websocket.send_json({"error": "Unknown message type"})

    except WebSocketDisconnect:
        print(f"[CAH_WS] Client {client_id} disconnected from CAH room {room_id}")
        keepalive_task.cancel()
        manager.disconnect(room_id, websocket)
    except Exception as e:
        print(f"[CAH_WS] Error for client {client_id} in CAH room {room_id}: {e}")
        keepalive_task.cancel()
        manager.disconnect(room_id, websocket)

