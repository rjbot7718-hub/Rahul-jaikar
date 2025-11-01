import os
import logging
from dotenv import load_dotenv
from pymongo import MongoClient
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

# --- Setup ---
load_dotenv()
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Secrets Load Karo ---
try:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    MONGO_URI = os.getenv("MONGO_URI")
    ADMIN_ID = int(os.getenv("ADMIN_ID"))
    if not BOT_TOKEN or not MONGO_URI or not ADMIN_ID:
        logger.error("Error: Secrets missing. Check .env file.")
        exit()
except Exception as e:
    logger.error(f"Error reading secrets: {e}")
    exit()

# --- Database Connection ---
try:
    logger.info("MongoDB se connect karne ki koshish...")
    client = MongoClient(MONGO_URI)
    db = client['AnimeBotDB']
    users_collection = db['users']
    animes_collection = db['animes'] # Naya collection Animes ke liye
    config_collection = db['config'] # Config ke liye (aage use hoga)
    
    client.server_info()
    logger.info("MongoDB se successfully connect ho gaya!")
except Exception as e:
    logger.error(f"MongoDB connection failed: {e}")
    exit()

# --- Admin Check ---
async def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    return user_id == ADMIN_ID

# --- Conversation States (Step 2) ---
# Ye states hain /addanime conversation ke liye
(
    GET_ANIME_NAME,
    GET_ANIME_POSTER,
    GET_ANIME_DESC,
    CONFIRM_ANIME,
) = range(4)

# --- Step 2: /addanime Conversation ---

async def add_anime_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/addanime command ka entry point"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.message.reply_text("Aap admin nahi hain.")
        return ConversationHandler.END
    
    logger.info(f"Admin {user_id} ne /addanime shuru kiya.")
    await update.message.reply_text(
        "Salaam Admin! Chalo naya anime add karte hain.\n\n"
        "Anime ka *Naam* kya hai? (Jaise: One Piece)\n\n"
        "Cancel karne ke liye /cancel type karein."
    )
    return GET_ANIME_NAME

async def get_anime_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Anime ka naam save karega"""
    context.user_data['anime_name'] = update.message.text
    logger.info(f"Anime ka naam mila: {context.user_data['anime_name']}")
    
    await update.message.reply_text(
        "Badhiya! Ab is anime ka *Poster (Photo)* bhejo.\n\n"
        "Cancel karne ke liye /cancel type karein."
    )
    return GET_ANIME_POSTER

async def get_anime_poster(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Anime ka poster save karega (file_id)"""
    if not update.message.photo:
        await update.message.reply_text("Ye photo nahi hai. Please ek photo bhejo.")
        return GET_ANIME_POSTER # Wapas poster maangega
        
    # Hum sabse high quality photo ki file_id store karenge
    poster_file_id = update.message.photo[-1].file_id
    context.user_data['anime_poster_id'] = poster_file_id
    logger.info(f"Anime ka poster file_id mila: {poster_file_id}")
    
    await update.message.reply_text(
        "Poster mil gaya! Ab is anime ka *Description (Synopsis)* bhejo.\n\n"
        "Skip karne ke liye /skip type karein.\n"
        "Cancel karne ke liye /cancel type karein."
    )
    return GET_ANIME_DESC

async def get_anime_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Anime ka description save karega"""
    context.user_data['anime_desc'] = update.message.text
    logger.info("Anime ka description mil gaya.")
    
    # Ab user se confirm karwayenge
    return await confirm_anime_details(update, context)

async def skip_anime_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Description ko skip karega"""
    context.user_data['anime_desc'] = None # Description ko None set kar do
    logger.info("Anime ka description skip kiya.")
    
    # Ab user se confirm karwayenge
    return await confirm_anime_details(update, context)

async def confirm_anime_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Details confirm karne ke liye message bhejega"""
    name = context.user_data['anime_name']
    poster_id = context.user_data['anime_poster_id']
    desc = context.user_data['anime_desc']

    caption = f"{name}\n\n"
    if desc:
        caption += f"{desc}\n\n"
    caption += "--- Details Check Karo ---"
    
    keyboard = [
        [InlineKeyboardButton("✅ Save to Database", callback_data="save_anime")],
        [InlineKeyboardButton("❌ Cancel (Start Over)", callback_data="cancel_add_anime")]
    ]
    
    # Poster ke saath details bhejega
    await update.message.reply_photo(
        photo=poster_id,
        caption=caption,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return CONFIRM_ANIME

async def save_anime_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback query jab admin 'Save' button dabayega"""
    query = update.callback_query
    await query.answer() # Button click ko register karo
    
    try:
        name = context.user_data['anime_name']
        poster_id = context.user_data['anime_poster_id']
        desc = context.user_data['anime_desc']

        # Database document
        anime_document = {
            "name": name,
            "poster_id": poster_id,
            "description": desc,
            "seasons": {} # Seasons hum agle step mein add karenge
        }
        
        # Check karo kahi ye anime pehle se to nahi hai
        existing_anime = animes_collection.find_one({"name": name})
        if existing_anime:
            await query.edit_message_caption(caption="⚠ *Error:* Ye anime naam '"+name+"' pehle se database mein hai.")
            return ConversationHandler.END

        # Naya anime database me insert karo
        animes_collection.insert_one(anime_document)
        
        logger.info(f"Naya Anime DB mein save ho gaya: {name}")
        await query.edit_message_caption(caption=f"✅ *Success!*\n\n'{name}' ko database mein add kar diya gaya hai.")
        
    except Exception as e:
        logger.error(f"Anime save karne me error: {e}")
        await query.edit_message_caption(caption=f"❌ *Error!*\n\nDatabase me save nahi kar paya. Details ke liye logs check karein.")
        
    context.user_data.clear() # Temporary data clear karo
    return ConversationHandler.END

async def cancel_add_anime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback query jab admin 'Cancel' button dabayega"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_caption(caption="❌ *Cancelled.* Naya anime add karne ka process rok diya gaya hai.")
    
    context.user_data.clear() # Temporary data clear karo
    return ConversationHandler.END

async def conv_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/cancel command se conversation ko band karega"""
    logger.info("User ne conversation /cancel se band kar diya.")
    await update.message.reply_text(
        "Operation cancel kar diya gaya hai."
    )
    context.user_data.clear() # Temporary data clear karo
    return ConversationHandler.END

# --- Purane Handlers (Step 1) ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    first_name = user.first_name
    logger.info(f"User {user_id} ({first_name}) ne /start dabaya.")
    
    user_data = users_collection.find_one({"_id": user_id})
    if not user_data:
        new_user = {
            "_id": user_id, "first_name": first_name, "username": user.username,
            "subscribed": False, "expiry_date": None, "last_screenshot_time": None
        }
        users_collection.insert_one(new_user)
        logger.info(f"Naya user database me add kiya: {user_id}")
    
    await update.message.reply_text(
        f"Salaam {first_name}! 👋\n"
        "Main aapka Anime Bot hoon.\n"
        "Menu dekhne ke liye /menu type karein."
    )

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panel ka main menu (abhi basic hai)"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.message.reply_text("Aap admin nahi hain.")
        return

    logger.info("Admin ne /admin command use kiya.")
    admin_menu_text = """
👑 *Salaam Admin! Control Panel* 👑

Naya content add karne ke liye in commands ka istemaal karein:

/addanime - Naya Anime/Movie add karo.
/addseason - (Jald aa raha hai...)
/addepisode - (Jald aa raha hai...)

Configuration ke liye:
/config - (Jald aa raha hai...)

Cancel karne ke liye /cancel type karein.
    """
    await update.message.reply_text(admin_menu_text, parse_mode='Markdown')

# --- Main Bot Function ---
def main():
    logger.info("Application ban raha hai...")
    application = Application.builder().token(BOT_TOKEN).build()

    # --- Naya: ConversationHandler for /addanime (Step 2) ---
    add_anime_conv = ConversationHandler(
        entry_points=[CommandHandler("addanime", add_anime_start)],
        states={
            GET_ANIME_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_anime_name)],
            GET_ANIME_POSTER: [MessageHandler(filters.PHOTO, get_anime_poster)],
            GET_ANIME_DESC: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_anime_desc),
                CommandHandler("skip", skip_anime_desc)
            ],
            CONFIRM_ANIME: [
                CallbackQueryHandler(save_anime_details, pattern="^save_anime$"),
                CallbackQueryHandler(cancel_add_anime, pattern="^cancel_add_anime$")
            ]
        },
        fallbacks=[CommandHandler("cancel", conv_cancel)],
        per_user=True, # Taki har admin ka data alag store ho
        per_chat=True
    )
    
    application.add_handler(add_anime_conv) # Naya handler add kiya

    # --- Puraane Handlers (Step 1) ---
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("admin", admin_command))

    logger.info("Bot polling start kar raha hai...")
    application.run_polling()

if __name__ == "__main__":
    main()
