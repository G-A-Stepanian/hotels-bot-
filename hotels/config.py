import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
RAPIDAPI_HOST = "apidojo-booking-v1.p.rapidapi.com"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")  # DEBUG/INFO/WARNING/ERROR
