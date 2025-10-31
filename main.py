import os
import logging
import threading  # Uptime Robot ke liye zaroori
from flask import Flask  # Urobot ke liye web server
from pymongo import MongoClient
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# --- Logging (Errors dekhne ke liye) ---
# Yeh console mein errors dikhayega
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Environment Variables (Yeh Render mein daalna) ---
# Aapne 5 variables bataye the, lekin Step 1 ke liye sirf 3 chahiye:

# 1. BOT_TOKEN (BotFather se)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    logger.critical("!!! BOT_TOKEN environment variable nahi mila !!!")
    exit(1) # Bot band kar do

# 2. MONGO_URI (MongoDB Atlas se)
MONGO_URI = os.environ.get("MONGO_URI")
if not MONGO_URI:
    logger.critical("!!! MONGO_URI environment variable nahi mila !!!")
    exit(1) # Bot band kar do

# 3. ADMIN_ID (Aapki Telegram User ID)
try:
    ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
    if ADMIN_ID == 0:
        logger.critical("!!! ADMIN_ID environment variable nahi mila ya 0 hai !!!")
        exit(1)
except ValueError:
    logger.critical("!!! ADMIN_ID number nahi hai !!!")
    exit(1)

# Render yeh 'PORT' variable khud deta hai
PORT = int(os.environ.get("PORT", 8080))


# --- Flask App (Uptime Robot ke liye) ---
# Ek chhota sa web server jo Uptime Robot ko "Bot zinda hai" batayega
app = Flask(__name__)

@app.route('/')
def hello():
    """Render ko batane ke liye ki bot alive hai."""
    return "Bot is alive and running!"

def run_flask():
    """Flask server ko ek alag thread mein run karta hai."""
    logger.info(f"Flask server ko http://0.0.0.0:{PORT} par start kar raha hoon...")
    # Host '0.0.0.0' zaroori hai Render ke liye
    app.run(host="0.0.0.0", port=PORT)


# --- Database Setup ---
try:
    client = MongoClient(MONGO_URI)
    # Aapke database ka naam (URI se default lega)
    db = client.get_database() 
    
    # Collections (Tables)
    users_collection = db['users']
    config_collection = db['config']
    
    logger.info("MongoDB se connect ho gaya!")
    
    # Pehli baar Admin ID ko config mein daalo (agar pehle se nahi hai)
    config_collection.update_one(
        {"config_id": "main_config"},
        {"$setOnInsert": {"admin_id": ADMIN_ID}},
        upsert=True # Agar 'main_config' nahi hai, toh bana do
    )
except Exception as e:
    logger.critical(f"MongoDB se connect nahi ho paya: {e}")
    exit(1)


# --- Keyboards (Buttons) ---

def get_admin_keyboard() -> InlineKeyboardMarkup:
    """Admin ka main menu"""
    keyboard = [
        [InlineKeyboardButton("➕ Add Content", callback_data="admin_add_content")],
        [InlineKeyboardButton("✏ Manage Content", callback_data="admin_manage_content")],
        [InlineKeyboardButton("💰 Subscription Settings", callback_data="admin_sub_settings")],
        [InlineKeyboardButton("❤ Donation Settings", callback_data="admin_donation_settings")],
        [InlineKeyboardButton("🔗 Other Links", callback_data="admin_other_links")],
        [InlineKeyboardButton("🔔 Pending Payments (0)", callback_data="admin_pending_payments")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_user_keyboard() -> InlineKeyboardMarkup:
    """Normal user ka main menu"""
    keyboard = [
        [InlineKeyboardButton("📅 Subscription Expiry", callback_data="user_expiry")],
        [InlineKeyboardButton("💸 Donate Now", callback_data="user_donate")],
        [InlineKeyboardButton("🔗 Join Backup Channel", callback_data="user_backup")],
        [InlineKeyboardButton("💬 Support Inbox", callback_data="user_support")],
    ]
    return InlineKeyboardMarkup(keyboard)


# --- Bot Command Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start command ka handler"""
    user = update.effective_user
    user_id = user.id
    
    # Check karo ki user ADMIN hai ya nahi
    if user_id == ADMIN_ID:
        # ---- ADMIN FLOW ----
        await update.message.reply_text(
            f"Salaam, Admin Boss! 🫡\nAapka control panel taiyyar hai.",
            reply_markup=get_admin_keyboard()
        )
    else:
        # ---- NORMAL USER FLOW ----
        # Check karo ki user database mein hai ya nahi
        user_data = users_collection.find_one({"user_id": user_id})
        
        if not user_data:
            # Naya user hai, toh database mein add karo
            new_user_doc = {
                "user_id": user_id,
                "username": user.username,
                "first_name": user.first_name,
                "is_subscribed": False,
                "subscription_expiry": None,
                "last_payment_attempt": None
            }
            users_collection.insert_one(new_user_doc)
            logger.info(f"Naya user add hua: {user.username} ({user_id})")

        await update.message.reply_text(
            f"Welcome, {user.first_name}!\n\nMain menu neeche hai:",
            reply_markup=get_user_keyboard()
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Saare Inline Buttons ka handler"""
    query = update.callback_query
    await query.answer()  # Button click ko confirm karo (loading icon hatata hai)
    
    data = query.data
    user_id = query.from_user.id

    # Admin check (agar user admin nahi hai aur admin button dabata hai)
    if user_id != ADMIN_ID and data.startswith("admin_"):
        await query.answer("Yeh sirf admin ke liye hai!", show_alert=True)
        return

    # ---- ADMIN BUTTONS (Work In Progress) ----
    if data.startswith("admin_"):
        await query.edit_message_text(text=f"Admin: Aapne '{data}' click kiya. (Yeh hum agle steps mein banayenge)")

    # ---- USER BUTTONS (Work In Progress) ----
    elif data.startswith("user_"):
        await query.edit_message_text(text=f"User: Aapne '{data}' click kiya. (Yeh hum agle steps mein banayenge)")


# --- Bot ko Start karne ka Function ---
def main() -> None:
    """Bot ko start karta hai."""
    
    # --- Pehle, Flask server ko thread mein chalu karo ---
    # Taaki Uptime Robot isse ping kar sake
    logger.info("Flask server ko background mein start kar raha hoon...")
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    
    # --- Ab, Telegram Bot ko chalu karo ---
    logger.info("Telegram Bot ko start kar raha hoon (polling)...")
    application = Application.builder().token(BOT_TOKEN).build()

    # Handlers (commands, buttons) ko register karo
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(button_handler)) # Saare buttons ke liye

    # Bot ko chalao jab tak band na karein (Ctrl+C)
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
