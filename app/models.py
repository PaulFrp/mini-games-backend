from sqlalchemy import Column, Integer, String, create_engine, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy import DateTime
from datetime import datetime, timezone

Base = declarative_base()

class Room(Base):
    __tablename__ = "rooms"
    id = Column(Integer, primary_key=True)
    status = Column(String)
    creator = Column(String, nullable=True)
    players = relationship("Player", back_populates="room", cascade="all, delete-orphan", passive_deletes=True)

class Player(Base):
    __tablename__ = "players"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, unique=False, index=True)  # client_id
    username = Column(String, unique=False, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id", ondelete="CASCADE"))
    last_seen = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    room = relationship("Room", back_populates="players")

