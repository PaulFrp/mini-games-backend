from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .db import init_db
from contextlib import asynccontextmanager
from .routes import general, room, voting, meme, websockets
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
    cleanup_task = asyncio.create_task(cleanup_empty_rooms_task())
    yield
        # 🧹 On shutdown
    for task in (cleanup_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(lifespan=lifespan)

frontend_urls = os.getenv("FRONTEND_URLS", "http://localhost:3000")
allowed_origins = [url.strip() for url in frontend_urls.split(",")]

# Log CORS configuration for debugging
print(f"🌐 CORS allowed origins: {allowed_origins}")
print(f"🔐 Environment: {'Production' if os.getenv('DATABASE_URL') else 'Development'}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)





# Routers
app.include_router(general.router)
app.include_router(room.router)
app.include_router(voting.router, prefix="/voting")
app.include_router(meme.router, prefix ="/meme")
app.include_router(websockets.router)
