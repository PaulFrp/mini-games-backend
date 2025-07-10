from fastapi import APIRouter, HTTPException
from app.schemas import CaptionRequest
from fastapi import APIRouter, Depends, Request, Header, HTTPException
from app.db import get_db
from app.schemas import VoteRequest
from app.models import Player, Room


from app.game.meme import games, start_meme_game, meme_game_status_logic, next_meme_logic


router = APIRouter()

@router.post("/start_game/{room_id}")
async def start_game(room_id: int, x_client_id: str = Header(None), db=Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room or room.creator != x_client_id:
        raise HTTPException(status_code=403, detail="Not allowed")
    players = db.query(Player).filter(Player.room_id == room_id).all()
    start_meme_game(room_id, [p.username for p in players])
    return {"status": "game started"}

@router.get("/game_status/{room_id}")
def meme_game_status(room_id: int, request: Request, db=Depends(get_db)):
    return meme_game_status_logic(room_id, request, db)


@router.post("/next_meme/{room_id}")
def next_meme(room_id: int, request: Request, db=Depends(get_db)):
    return next_meme_logic(room_id, request, db)

@router.post("/submit_caption/{room_id}")
def submit_caption(room_id: int, req: CaptionRequest):
    game = games.get(room_id)
    if not game or game["phase"] != "captioning":
        raise HTTPException(status_code=400, detail="Not in caption phase")
    if len(req.captions) != len(game["current_meme"]["caption_slots"]):
        raise HTTPException(status_code=400, detail="Caption count does not match slots")
    
    game["captions"][req.player_id] = req.captions

    #issue in the submissions, the meme_name does not seem to have been changed
    if req.player_id not in game["submissions"]:
        game["submissions"][req.player_id] = {
            "meme": game["current_meme"],
            "captions": req.captions,
        }
    else:
        game["submissions"][req.player_id]["captions"] = req.captions

    return {"status": "caption_received"}

@router.post("/vote/{room_id}")
def vote(room_id: int, vote: VoteRequest):
    game = games.get(room_id)
    if not game or game["phase"] != "voting":
        raise HTTPException(status_code=400, detail="Voting is not active")
    game["votes"][vote.voter_id] = vote.vote_for
    return {"message": "Vote registered"}

from app.game.meme import MEME_POOL  # import it

@router.get("/templates")
def get_meme_templates():
    print("MEME_POOL", MEME_POOL)
    return MEME_POOL