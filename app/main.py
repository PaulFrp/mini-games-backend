from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .db import init_db
from contextlib import asynccontextmanager
from .routes import general, room, voting, meme
from .tasks.cleanup import cleanup_empty_rooms_task
import asyncio
import os
from dotenv import load_dotenv



# uvicorn app.main:app --reload

if not os.getenv("DATABASE_URL"):
    load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = asyncio.create_task(cleanup_empty_rooms_task())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_URL", "http://localhost:3000")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(general.router)
app.include_router(room.router)
app.include_router(voting.router, prefix="/voting")
app.include_router(meme.router, prefix ="/meme")
