import asyncio
from datetime import datetime, timezone, timedelta
from app.db import SessionLocal
from app.models import Room
from sqlalchemy.orm import joinedload
import pytz

local_tz = pytz.timezone("Europe/Paris")

def to_utc_aware(dt):
    if not dt: return None
    if dt.tzinfo is None:
        local_dt = local_tz.localize(dt)
        return local_dt.astimezone(timezone.utc)
    return dt

async def cleanup_empty_rooms_task():
    while True:
        await asyncio.sleep(30)
        with SessionLocal() as db:
            now = datetime.now(timezone.utc)
            timeout = now - timedelta(minutes=120)
            rooms = db.query(Room).options(joinedload(Room.players)).all()
            for room in rooms:
                if not any(p.last_seen and to_utc_aware(p.last_seen) > timeout for p in room.players):
                    db.delete(room)
            db.commit()
