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
        logger.error("Error: Secrets missing. Check .env file or Render env variables.")
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
    animes_collection = db['animes'] 
    config_collection = db['config'] 
    client.server_info()
    logger.info("MongoDB se successfully connect ho gaya!")
except Exception as e:
    logger.error(f"MongoDB connection failed: {e}")
    exit()

# --- Admin Check ---
async def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    return user_id == ADMIN_ID

# --- Conversation States ---
# /addanime states
(
    GET_ANIME_NAME,
    GET_ANIME_POSTER,
    GET_ANIME_DESC,
    CONFIRM_ANIME,
) = range(4)

# NAYA: /addseason states
(
    GET_ANIME_FOR_SEASON,
    GET_SEASON_NUMBER,
    CONFIRM_SEASON,
) = range(4, 7) # Range 4 se start

# --- Step 2: /addanime Conversation (Same as before) ---

async def add_anime_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        if update.callback_query:
            await update.callback_query.answer("Aap admin nahi hain.", show_alert=True)
            return ConversationHandler.END
        await update.message.reply_text("Aap admin nahi hain.")
        return ConversationHandler.END
    
    logger.info(f"Admin {user_id} ne /addanime shuru kiya.")
    text = (
        "Salaam Admin! Chalo naya anime add karte hain.\n\n"
        "Anime ka *Naam* kya hai? (Jaise: One Piece)\n\n"
        "Cancel karne ke liye /cancel type karein."
    )
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(text, parse_mode='Markdown') 
    else:
        await update.message.reply_text(text, parse_mode='Markdown')
    return GET_ANIME_NAME

async def get_anime_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['anime_name'] = update.message.text
    logger.info(f"Anime ka naam mila: {context.user_data['anime_name']}")
    await update.message.reply_text("Badhiya! Ab is anime ka *Poster (Photo)* bhejo.")
    return GET_ANIME_POSTER

async def get_anime_poster(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("Ye photo nahi hai. Please ek photo bhejo.")
        return GET_ANIME_POSTER 
    poster_file_id = update.message.photo[-1].file_id
    context.user_data['anime_poster_id'] = poster_file_id
    logger.info(f"Anime ka poster file_id mila: {poster_file_id}")
    await update.message.reply_text("Poster mil gaya! Ab is anime ka *Description (Synopsis)* bhejo.\n\n/skip ya /cancel.")
    return GET_ANIME_DESC

async def get_anime_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['anime_desc'] = update.message.text
    logger.info("Anime ka description mil gaya.")
    return await confirm_anime_details(update, context)

async def skip_anime_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['anime_desc'] = None 
    logger.info("Anime ka description skip kiya.")
    return await confirm_anime_details(update, context)

async def confirm_anime_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data['anime_name']
    poster_id = context.user_data['anime_poster_id']
    desc = context.user_data['anime_desc']
    caption = f"{name}\n\n{desc if desc else ''}\n\n--- Details Check Karo ---"
    keyboard = [
        [InlineKeyboardButton("✅ Save to Database", callback_data="save_anime")],
        [InlineKeyboardButton("❌ Cancel (Start Over)", callback_data="cancel_add_anime")]
    ]
    await update.message.reply_photo(
        photo=poster_id, caption=caption, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown'
    )
    return CONFIRM_ANIME

async def save_anime_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() 
    try:
        name = context.user_data['anime_name']
        poster_id = context.user_data['anime_poster_id']
        desc = context.user_data['anime_desc']
        anime_document = {"name": name, "poster_id": poster_id, "description": desc, "seasons": {}}
        existing_anime = animes_collection.find_one({"name": name})
        if existing_anime:
            await query.edit_message_caption(caption=f"⚠ *Error:* Ye anime naam '{name}' pehle se hai.")
            return ConversationHandler.END
        animes_collection.insert_one(anime_document)
        logger.info(f"Naya Anime DB mein save ho gaya: {name}")
        await query.edit_message_caption(caption=f"✅ *Success!* '{name}' add ho gaya hai.")
    except Exception as e:
        logger.error(f"Anime save karne me error: {e}")
        await query.edit_message_caption(caption=f"❌ *Error!* Database me save nahi kar paya.")
    context.user_data.clear() 
    return ConversationHandler.END

async def cancel_add_anime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_caption(caption="❌ *Cancelled.* Naya anime add karne ka process rok diya gaya hai.")
    context.user_data.clear() 
    return ConversationHandler.END

# --- NAYA: Step 2.6: /addseason Conversation ---

async def add_season_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/addseason command ya button ka entry point"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("Aap admin nahi hain.", show_alert=True)
        return ConversationHandler.END

    logger.info(f"Admin {user_id} ne /addseason shuru kiya.")
    
    # Database se saare anime names fetch karo
    all_animes = animes_collection.find({}, {"name": 1}) # Sirf 'name' field lo
    anime_list = list(all_animes) # Cursor ko list me convert karo
    
    if not anime_list:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "❌ *Error!* Database mein koi anime nahi hai.\n\n"
            "Pehle ➕ Add Anime button se anime add karo."
        )
        return ConversationHandler.END

    # Har anime ke liye ek button banao
    keyboard = []
    for anime in anime_list:
        # Callback data mein 'season_anime_ANIME_NAME' bhejenge
        button = [InlineKeyboardButton(anime['name'], callback_data=f"season_anime_{anime['name']}")]
        keyboard.append(button)
    
    # Cancel button
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_conv")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "Aap kis anime mein season add karna chahte hain?"
    
    # Admin menu message ko edit karo
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(text, reply_markup=reply_markup)
    
    return GET_ANIME_FOR_SEASON

async def get_anime_for_season(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Jab admin anime select karega"""
    query = update.callback_query
    await query.answer()
    
    # Callback data se anime ka naam nikalo (e.g., "season_anime_One Piece")
    anime_name = query.data.replace("season_anime_", "")
    context.user_data['season_anime_name'] = anime_name
    
    logger.info(f"Season ke liye anime select kiya: {anime_name}")
    
    await query.edit_message_text(
        f"Aapne *{anime_name}* select kiya hai.\n\n"
        "Ab is season ka *Number ya Naam* bhejo.\n"
        "(Jaise: 1, 2, Movie, Special)\n\n"
        "Cancel karne ke liye /cancel type karein."
    )
    return GET_SEASON_NUMBER

async def get_season_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Season ka number/naam save karega"""
    season_name = update.message.text
    context.user_data['season_name'] = season_name
    anime_name = context.user_data['season_anime_name']
    
    logger.info(f"Season ka naam mila: {season_name} (Anime: {anime_name})")

    # Check karo kahi ye season pehle se to nahi hai
    anime_doc = animes_collection.find_one({"name": anime_name})
    if season_name in anime_doc.get("seasons", {}):
        await update.message.reply_text(
            f"⚠ *Error!* '{anime_name}' mein 'Season {season_name}' pehle se hai.\n\n"
            "Koi doosra naam/number type karein ya /cancel karein."
        )
        return GET_SEASON_NUMBER # Wapas se number maango
        
    # Confirmation maango
    keyboard = [
        [InlineKeyboardButton("✅ Haan, Save Karo", callback_data="save_season")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_conv")]
    ]
    await update.message.reply_text(
        f"*Confirm Karo:*\n"
        f"Anime: *{anime_name}*\n"
        f"Naya Season: *{season_name}*\n\n"
        "Kya main isse database mein save kar doon?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return CONFIRM_SEASON

async def save_season(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Season ko database me save karega"""
    query = update.callback_query
    await query.answer()
    
    try:
        anime_name = context.user_data['season_anime_name']
        season_name = context.user_data['season_name']
        
        # MongoDB me update query
        # Hum seasons dict me naya key add kar rahe hain (e.g., seasons.1 = {})
        animes_collection.update_one(
            {"name": anime_name},
            {"$set": {f"seasons.{season_name}": {}}} # Naya season as an empty object
        )
        
        logger.info(f"Naya season save ho gaya: {season_name} (Anime: {anime_name})")
        await query.edit_message_text(
            f"✅ *Success!*\n\n"
            f"{anime_name}** mein *Season {season_name}* add ho gaya hai."
        )
        
    except Exception as e:
        logger.error(f"Season save karne me error: {e}")
        await query.edit_message_text(f"❌ *Error!* Database me save nahi kar paya.")
        
    context.user_data.clear()
    return ConversationHandler.END

async def conv_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/cancel command se conversation ko band karega"""
    logger.info("User ne conversation /cancel se band kar diya.")
    await update.message.reply_text("Operation cancel kar diya gaya hai.")
    context.user_data.clear() 
    return ConversationHandler.END

async def conv_cancel_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'Cancel' button se conversation ko band karega"""
    query = update.callback_query
    await query.answer()
    logger.info("User ne conversation 'Cancel' button se band kar diya.")
    await query.edit_message_text("Operation cancel kar diya gaya hai.")
    context.user_data.clear()
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

# --- Admin Panel (Buttons ke Saath) ---

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panel ka main menu (Buttons ke saath)"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.message.reply_text("Aap admin nahi hain.")
        return

    logger.info("Admin ne /admin command use kiya.")
    keyboard = [
        [
            InlineKeyboardButton("➕ Add Anime", callback_data="admin_add_anime"),
            InlineKeyboardButton("➕ Add Season", callback_data="admin_add_season")
        ],
        [
            InlineKeyboardButton("➕ Add Episode", callback_data="admin_add_episode"),
            InlineKeyboardButton("⚙ Bot Config", callback_data="admin_config")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    admin_menu_text = "👑 *Salaam Admin! Control Panel* 👑\n\nContent add karne ya settings change karne ke liye buttons use karein."
    await update.message.reply_text(admin_menu_text, reply_markup=reply_markup, parse_mode='Markdown')

async def placeholder_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Ye feature jald aa raha hai...", show_alert=True)

# --- Error Handler ---
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors caused by Updates."""
    logger.error(f"Error: {context.error} \nUpdate: {update}", exc_info=True)

# --- Main Bot Function ---
def main():
    logger.info("Application ban raha hai...")
    application = Application.builder().token(BOT_TOKEN).build()

    # --- ConversationHandler for /addanime ---
    add_anime_conv = ConversationHandler(
        entry_points=[
            CommandHandler("addanime", add_anime_start),
            CallbackQueryHandler(add_anime_start, pattern="^admin_add_anime$")
        ],
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
        fallbacks=[
            CommandHandler("cancel", conv_cancel),
            CallbackQueryHandler(conv_cancel_button, pattern="^cancel_conv$")
        ],
        per_user=True, per_chat=True
    )
    
    # --- NAYA: ConversationHandler for /addseason ---
    add_season_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(add_season_start, pattern="^admin_add_season$")
        ],
        states={
            GET_ANIME_FOR_SEASON: [CallbackQueryHandler(get_anime_for_season, pattern="^season_anime_")],
            GET_SEASON_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_season_number)],
            CONFIRM_SEASON: [CallbackQueryHandler(save_season, pattern="^save_season$")]
        },
        fallbacks=[
            CommandHandler("cancel", conv_cancel),
            CallbackQueryHandler(conv_cancel_button, pattern="^cancel_conv$")
        ],
        per_user=True, per_chat=True
    )

    # --- Handlers ko Add Karo ---
    application.add_handler(add_anime_conv)
    application.add_handler(add_season_conv) # Naya handler add kiya

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("admin", admin_command)) 
    
    # --- Placeholder buttons ---
    application.add_handler(CallbackQueryHandler(placeholder_button_handler, pattern="^admin_add_episode$"))
    application.add_handler(CallbackQueryHandler(placeholder_button_handler, pattern="^admin_config$"))

    application.add_error_handler(error_handler)

    logger.info("Bot polling start kar raha hai...")
    application.run_polling()

if _name_ == "__main__":
    main()
