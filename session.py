from itsdangerous import Signer
import os
from dotenv import load_dotenv

load_dotenv()

session_secret = os.getenv("SESSION_SECRET")
if session_secret is None:
	raise ValueError("SESSION_SECRET environment variable is not set")
signer = Signer(session_secret)  # use env var in production
