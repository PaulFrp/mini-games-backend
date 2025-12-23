# app/routes/ws.py

import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.game.websockets import manager
from app.db import get_db
from app.models import Player, Room
from app.game.meme import games, get_game_status_logic, next_meme_logic, MEME_POOL

router = APIRouter()

@router.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: int):
    client_id = websocket.query_params.get("client_id")
    await manager.connect(room_id, websocket)

    try:
        db = next(get_db())

        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            msg_type = message.get("type")

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
        manager.disconnect(room_id, websocket)
