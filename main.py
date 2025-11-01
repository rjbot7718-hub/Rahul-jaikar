import os
import logging
from dotenv import load_dotenv
from pymongo import MongoClient
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --- Setup ---
# .env file se secrets load karo (sirf local testing ke liye)
load_dotenv()

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Secrets Load Karo ---
try:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    MONGO_URI = os.getenv("MONGO_URI")
    ADMIN_ID = int(os.getenv("ADMIN_ID")) # Admin ki Telegram ID

    if not BOT_TOKEN or not MONGO_URI or not ADMIN_ID:
        logger.error("Error: BOT_TOKEN, MONGO_URI, ya ADMIN_ID set nahi hai. Check .env file.")
        exit()
        
except Exception as e:
    logger.error(f"Error .env file padhne mein: {e}")
    exit()

# --- Database Connection ---
try:
    logger.info("MongoDB se connect karne ki koshish...")
    client = MongoClient(MONGO_URI)
    db = client['AnimeBotDB'] # Database ka naam
    users_collection = db['users'] # Users ka data yaha store hoga
    
    # Connection test karne ke liye
    client.server_info()
    logger.info("MongoDB se successfully connect ho gaya!")

except Exception as e:
    logger.error(f"MongoDB connection failed: {e}")
    exit() # Agar database connect nahi hua to bot band kar do

# --- Bot Handlers (Commands) ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Jab user /start command bhejega tab ye function chalega"""
    user = update.effective_user
    user_id = user.id
    first_name = user.first_name
    
    logger.info(f"User {user_id} ({first_name}) ne /start dabaya.")
    
    # User ko database me check karo
    user_data = users_collection.find_one({"_id": user_id})
    
    if not user_data:
        # Agar naya user hai, to database me add karo
        new_user = {
            "_id": user_id,
            "first_name": first_name,
            "username": user.username,
            "subscribed": False,
            "expiry_date": None,
            "last_screenshot_time": None
        }
        users_collection.insert_one(new_user)
        logger.info(f"Naya user database me add kiya: {user_id}")
    
    await update.message.reply_text(
        f"Salaam {first_name}! 👋\n"
        "Main aapka Anime Bot hoon.\n"
        "Menu dekhne ke liye /menu type karein."
    )

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin ke liye special command"""
    user_id = update.effective_user.id
    
    if user_id == ADMIN_ID:
        logger.info("Admin ne /admin command use kiya.")
        await update.message.reply_text(f"Salaam Admin! Aapka Admin Panel (Step 2) jald hi yaha hoga.")
    else:
        logger.warning(f"Non-admin user {user_id} ne /admin try kiya.")
        await update.message.reply_text("Aap admin nahi hain.")

# --- Main Bot Function ---
def main():
    """Bot ko start karo"""
    logger.info("Application ban raha hai...")
    application = Application.builder().token(BOT_TOKEN).build()

    # Handlers (commands) add karo
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("admin", admin_command))

    # Bot ko run karo
    logger.info("Bot polling start kar raha hai...")
    application.run_polling()

if __name__ == "__main__":
    main()
