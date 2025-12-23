from fastapi import APIRouter, Response, Depends, Header, Cookie
from app.schemas import JoinRoomRequest
from app.db import get_db
from app.models import Room, Player
from sqlalchemy.orm import Session
from app.session import signer

router = APIRouter()

@router.post("/create_room")
def create_room(response: Response, db: Session = Depends(get_db), x_client_id: str = Header(None)):
    if not x_client_id:
        return {"error": "x-client-id header is required"}
    
    room = Room(status="waiting", creator=x_client_id)
    db.add(room)
    db.commit()
    db.refresh(room)
    response.set_cookie(
        key="room_session",
        value=signer.sign(str(room.id)).decode(),
        httponly=True, samesite="none", secure=True
    )
    return {"room_id": room.id}

@router.post("/join_room_with_username/{room_id}")
def join_room_with_username(room_id: int, data: JoinRoomRequest, response: Response, db: Session = Depends(get_db)):
    player = db.query(Player).filter_by(user_id=data.client_id, room_id=room_id).first()
    if player:
        player.username = data.username
    else:
        player = Player(user_id=data.client_id, username=data.username, room_id=room_id)
        db.add(player)
    db.commit()

    response.set_cookie(
        key="room_session",
        value=signer.sign(str(room_id)).decode(),
        httponly=True, samesite="none", secure=True
    )

    return {"message": f"User '{data.username}' joined room {room_id}"}
