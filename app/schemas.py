from pydantic import BaseModel

class JoinRoomRequest(BaseModel):
    username: str
    client_id: str

class VoteRequest(BaseModel):
    voter_id: str
    vote_for: str

class CaptionRequest(BaseModel):
    player_id: str
    captions: list[str]
