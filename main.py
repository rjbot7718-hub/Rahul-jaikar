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
# NAYA: Flask server ke liye
from flask import Flask
from threading import Thread

# --- Flask Server Setup (Issue 1 Fix) ---
# Ye Render ko zinda rakhega aur Uptime Robot ko reply dega
app = Flask(__name__)

@app.route('/')
def home():
    return "I am alive and running!"

def run_flask():
    # Render $PORT variable use karta hai
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# --- Baaki ka Bot Code ---

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

# --- Config Helper ---
async def get_config():
    """Database se bot config fetch karega"""
    config = config_collection.find_one({"_id": "bot_config"})
    if not config:
        default_config = {
            "_id": "bot_config", 
            "sub_qr_id": None, 
            "donate_qr_id": None, 
            "price": None, 
            "links": {
                "backup": None,
                "donate": None,
                "support": None
            }
        }
        config_collection.insert_one(default_config)
        return default_config
    return config

# --- Conversation States ---
(
    # /addanime states
    GET_ANIME_NAME, GET_ANIME_POSTER, GET_ANIME_DESC, CONFIRM_ANIME,
    
    # /addseason states
    GET_ANIME_FOR_SEASON, GET_SEASON_NUMBER, CONFIRM_SEASON,
    
    # /addepisode states
    GET_ANIME_FOR_EPISODE, GET_SEASON_FOR_EPISODE, GET_EPISODE_NUMBER, GET_EPISODE_QUALITY, GET_EPISODE_FILE,
    
    # /config states
    CONFIG_MENU, 
    GET_SUB_QR, GET_DONATE_QR, GET_PRICE, 
    GET_BACKUP_LINK, GET_DONATE_LINK, GET_SUPPORT_LINK,
    
    # /post_gen states
    POST_GEN_MENU, POST_GEN_SELECT_ANIME, POST_GEN_SELECT_SEASON, POST_GEN_SELECT_EPISODE,
    POST_GEN_GET_CHAT_ID, # NAYA STATE (Issue 3 Fix)
    
    # /manage_content states
    MANAGE_MENU, 
    DELETE_ANIME_SELECT, DELETE_ANIME_CONFIRM,
    DELETE_SEASON_ANIME, DELETE_SEASON_SELECT, DELETE_SEASON_CONFIRM
) = range(30) # Total states (29 se 30 kiya)

# --- Step 2: /addanime Conversation ---

async def add_anime_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        if update.callback_query: await update.callback_query.answer("Aap admin nahi hain.", show_alert=True)
        else: await update.message.reply_text("Aap admin nahi hain.")
        return ConversationHandler.END
    logger.info(f"Admin {user_id} ne /addanime shuru kiya.")
    text = "Salaam Admin! Anime ka **Naam** kya hai?\n\n/cancel - Cancel."
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(text, parse_mode='Markdown') 
    else: await update.message.reply_text(text, parse_mode='Markdown')
    return GET_ANIME_NAME

async def get_anime_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['anime_name'] = update.message.text
    await update.message.reply_text("Badhiya! Ab anime ka **Poster (Photo)** bhejo.\n\n/cancel - Cancel.")
    return GET_ANIME_POSTER

async def get_anime_poster(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("Ye photo nahi hai. Please ek photo bhejo.")
        return GET_ANIME_POSTER 
    context.user_data['anime_poster_id'] = update.message.photo[-1].file_id
    await update.message.reply_text("Poster mil gaya! Ab **Description (Synopsis)** bhejo.\n\n/skip ya /cancel.")
    return GET_ANIME_DESC

async def get_anime_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['anime_desc'] = update.message.text
    return await confirm_anime_details(update, context)

async def skip_anime_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['anime_desc'] = None 
    return await confirm_anime_details(update, context)

async def confirm_anime_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data['anime_name']
    poster_id = context.user_data['anime_poster_id']
    desc = context.user_data['anime_desc']
    caption = f"**{name}**\n\n{desc if desc else ''}\n\n--- Details Check Karo ---"
    keyboard = [[InlineKeyboardButton("✅ Save", callback_data="save_anime")], [InlineKeyboardButton("❌ Cancel", callback_data="cancel_conv")]]
    await update.message.reply_photo(photo=poster_id, caption=caption, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return CONFIRM_ANIME

async def save_anime_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() 
    try:
        name = context.user_data['anime_name']
        if animes_collection.find_one({"name": name}):
            await query.edit_message_caption(caption=f"⚠️ **Error:** Ye anime naam '{name}' pehle se hai.")
            return ConversationHandler.END
        anime_document = {"name": name, "poster_id": context.user_data['anime_poster_id'], "description": context.user_data['anime_desc'], "seasons": {}}
        animes_collection.insert_one(anime_document)
        await query.edit_message_caption(caption=f"✅ **Success!** '{name}' add ho gaya hai.")
    except Exception as e:
        logger.error(f"Anime save karne me error: {e}")
        await query.edit_message_caption(caption=f"❌ **Error!** Database me save nahi kar paya.")
    context.user_data.clear() 
    return ConversationHandler.END

# --- Step 2.6: /addseason Conversation ---

async def add_season_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("Aap admin nahi hain.", show_alert=True)
        return ConversationHandler.END
    logger.info(f"Admin {user_id} ne /addseason shuru kiya.")
    all_animes = list(animes_collection.find({}, {"name": 1}))
    if not all_animes:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("❌ **Error!** Pehle `➕ Add Anime` se anime add karo.")
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(anime['name'], callback_data=f"season_anime_{anime['name']}")] for anime in all_animes]
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_conv")])
    text = "Aap kis anime mein season add karna chahte hain?"
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return GET_ANIME_FOR_SEASON

async def get_anime_for_season(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    anime_name = query.data.replace("season_anime_", "")
    context.user_data['anime_name'] = anime_name
    await query.edit_message_text(f"Aapne **{anime_name}** select kiya hai.\n\nAb is season ka **Number ya Naam** bhejo.\n(Jaise: 1, 2, Movie)\n\n/cancel - Cancel.")
    return GET_SEASON_NUMBER

async def get_season_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    season_name = update.message.text
    context.user_data['season_name'] = season_name
    anime_name = context.user_data['anime_name']
    anime_doc = animes_collection.find_one({"name": anime_name})
    if season_name in anime_doc.get("seasons", {}):
        await update.message.reply_text(f"⚠️ **Error!** '{anime_name}' mein 'Season {season_name}' pehle se hai.\n\nKoi doosra naam/number type karein ya /cancel karein.")
        return GET_SEASON_NUMBER
    keyboard = [[InlineKeyboardButton("✅ Haan, Save Karo", callback_data="save_season")], [InlineKeyboardButton("❌ Cancel", callback_data="cancel_conv")]]
    await update.message.reply_text(f"**Confirm Karo:**\nAnime: **{anime_name}**\nNaya Season: **{season_name}**\n\nSave kar doon?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return CONFIRM_SEASON

async def save_season(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        anime_name = context.user_data['anime_name']
        season_name = context.user_data['season_name']
        animes_collection.update_one({"name": anime_name}, {"$set": {f"seasons.{season_name}": {}}})
        await query.edit_message_text(f"✅ **Success!**\n**{anime_name}** mein **Season {season_name}** add ho gaya hai.")
    except Exception as e:
        logger.error(f"Season save karne me error: {e}")
        await query.edit_message_text(f"❌ **Error!** Database me save nahi kar paya.")
    context.user_data.clear()
    return ConversationHandler.END

# --- Step 2.7: /addepisode Conversation ---

async def add_episode_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("Aap admin nahi hain.", show_alert=True)
        return ConversationHandler.END
    logger.info(f"Admin {user_id} ne /addepisode shuru kiya.")
    all_animes = list(animes_collection.find({}, {"name": 1}))
    if not all_animes:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("❌ **Error!** Pehle `➕ Add Anime` se anime add karo.")
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(anime['name'], callback_data=f"ep_anime_{anime['name']}")] for anime in all_animes]
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_conv")])
    text = "Aap kis anime mein episode add karna chahte hain?"
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return GET_ANIME_FOR_EPISODE
async def get_anime_for_episode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    anime_name = query.data.replace("ep_anime_", "")
    context.user_data['anime_name'] = anime_name
    anime_doc = animes_collection.find_one({"name": anime_name})
    seasons = anime_doc.get("seasons", {})
    if not seasons:
        await query.edit_message_text(f"❌ **Error!** '{anime_name}' mein koi season nahi hai.\n\nPehle `➕ Add Season` se season add karo.")
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(f"Season {s}", callback_data=f"ep_season_{s}")] for s in seasons]
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_conv")])
    await query.edit_message_text(f"Aapne **{anime_name}** select kiya hai.\n\nAb **Season** select karein:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return GET_SEASON_FOR_EPISODE

async def get_season_for_episode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    season_name = query.data.replace("ep_season_", "")
    context.user_data['season_name'] = season_name
    await query.edit_message_text(f"Aapne **Season {season_name}** select kiya hai.\n\nAb **Episode Number** bhejo.\n(Jaise: 1, 2, 3...)\n\n/cancel - Cancel.")
    return GET_EPISODE_NUMBER

async def get_episode_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['ep_num'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("480p", callback_data="ep_quality_480p"), InlineKeyboardButton("720p", callback_data="ep_quality_720p")],
        [InlineKeyboardButton("1080p", callback_data="ep_quality_1080p"), InlineKeyboardButton("4K", callback_data="ep_quality_4K")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_conv")]
    ]
    await update.message.reply_text(f"Aapne **Episode {context.user_data['ep_num']}** select kiya hai.\n\nAb **Quality** select karein:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return GET_EPISODE_QUALITY

async def get_episode_quality(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    quality = query.data.replace("ep_quality_", "")
    context.user_data['quality'] = quality
    anime_name, season_name, ep_num = context.user_data['anime_name'], context.user_data['season_name'], context.user_data['ep_num']
    await query.edit_message_text(
        f"**Ready!**\nAnime: **{anime_name}** | Season: **{season_name}** | Ep: **{ep_num}** | Quality: **{quality}**\n\n"
        "Ab mujhe is episode ki **Video File** forward karo.\n\n/cancel - Cancel.",
        parse_mode='Markdown'
    )
    return GET_EPISODE_FILE

async def get_episode_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_id = None
    if update.message.video: file_id = update.message.video.file_id
    elif update.message.document: file_id = update.message.document.file_id
    if not file_id:
        await update.message.reply_text("Ye video file nahi hai. Please ek video file forward karein ya /cancel karein.")
        return GET_EPISODE_FILE
    try:
        anime_name, season_name, ep_num, quality = context.user_data['anime_name'], context.user_data['season_name'], context.user_data['ep_num'], context.user_data['quality']
        dot_notation_key = f"seasons.{season_name}.{ep_num}.{quality}"
        animes_collection.update_one({"name": anime_name}, {"$set": {dot_notation_key: file_id}})
        logger.info(f"Naya episode save ho gaya: {anime_name} S{season_name} E{ep_num} {quality}")
        await update.message.reply_text(f"✅ **Success!**\nEpisode **{ep_num} ({quality})** save ho gaya hai.")
    except Exception as e:
        logger.error(f"Episode file save karne me error: {e}")
        await update.message.reply_text(f"❌ **Error!** Database me file save nahi kar paya.")
    context.user_data.clear()
    return ConversationHandler.END

# --- Common Conversation Fallbacks ---

async def conv_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("User ne conversation /cancel se band kar diya.")
    await update.message.reply_text("Operation cancel kar diya gaya hai.")
    context.user_data.clear() 
    return ConversationHandler.END

async def conv_cancel_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    logger.info("User ne conversation 'Cancel' button se band kar diya.")
    await query.edit_message_text("Operation cancel kar diya gaya hai.")
    context.user_data.clear()
    return ConversationHandler.END

# --- Step 3: /config Conversation (Poora) ---

async def config_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Config menu ka entry point"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        if update.callback_query: await update.callback_query.answer("Aap admin nahi hain.", show_alert=True)
        return ConversationHandler.END
        
    logger.info(f"Admin {user_id} ne /config menu khola.")
    query = update.callback_query
    if query: await query.answer()
    
    config = await get_config()
    
    sub_qr_status = "✅" if config.get('sub_qr_id') else "❌"
    donate_qr_status = "✅" if config.get('donate_qr_id') else "❌"
    price_status = "✅" if config.get('price') else "❌"
    links_status = "✅" if config.get('links', {}).get('backup') else "❌"

    keyboard = [
        [InlineKeyboardButton(f"Set Subscription QR {sub_qr_status}", callback_data="config_set_sub_qr")],
        [InlineKeyboardButton(f"Set Donate QR {donate_qr_status}", callback_data="config_set_donate_qr")],
        [InlineKeyboardButton(f"Set Price {price_status}", callback_data="config_set_price")],
        [InlineKeyboardButton(f"Set Links {links_status}", callback_data="config_set_links")],
        [InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_menu")]
    ]
    
    text = "⚙️ **Bot Configuration** ⚙️\n\nAap yahan se bot ki settings badal sakte hain."
    
    if query:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        
    return CONFIG_MENU

async def config_set_sub_qr_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Aapna **Subscription (Payment) QR Code** ki photo bhejo.\n\n/cancel - Cancel.")
    return GET_SUB_QR

async def config_set_sub_qr_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("Ye photo nahi hai. Please ek photo bhejo ya /cancel karein.")
        return GET_SUB_QR
    qr_file_id = update.message.photo[-1].file_id
    config_collection.update_one({"_id": "bot_config"}, {"$set": {"sub_qr_id": qr_file_id}}, upsert=True)
    logger.info(f"Subscription QR code update ho gaya.")
    await update.message.reply_text("✅ **Success!** Naya subscription QR code set ho gaya hai. Wapas config menu me jaa raha hoon...")
    return await config_menu(update, context)

async def config_set_donate_qr_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Aapna **Donate QR Code** ki photo bhejo.\n\n/cancel - Cancel.")
    return GET_DONATE_QR

async def config_set_donate_qr_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("Ye photo nahi hai. Please ek photo bhejo ya /cancel karein.")
        return GET_DONATE_QR
    qr_file_id = update.message.photo[-1].file_id
    config_collection.update_one({"_id": "bot_config"}, {"$set": {"donate_qr_id": qr_file_id}}, upsert=True)
    logger.info(f"Donate QR code update ho gaya.")
    await update.message.reply_text("✅ **Success!** Naya donate QR code set ho gaya hai. Wapas config menu me jaa raha hoon...")
    return await config_menu(update, context)

async def config_set_price_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Subscription ka **Price & Duration** bhejo.\n(Example: 50 INR for 30 days)\n\n/cancel - Cancel.")
    return GET_PRICE

async def config_set_price_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    price_text = update.message.text
    config_collection.update_one({"_id": "bot_config"}, {"$set": {"price": price_text}}, upsert=True)
    logger.info(f"Price update ho gaya: {price_text}")
    await update.message.reply_text(f"✅ **Success!** Naya price set ho gaya hai: '{price_text}'. Wapas config menu me jaa raha hoon...")
    return await config_menu(update, context)

async def config_set_links_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Aapke **Backup Channel** ka link bhejo.\n(Example: https://t.me/mychannel)\n\n/skip - Skip.\n/cancel - Cancel.")
    return GET_BACKUP_LINK

async def get_backup_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['backup_link'] = update.message.text
    await update.message.reply_text("Backup link save ho gaya.\n\nAb **Donate Link** bhejo.\n(Example: https://...)\n\n/skip - Skip.\n/cancel - Cancel.")
    return GET_DONATE_LINK

async def skip_backup_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['backup_link'] = None
    await update.message.reply_text("Backup link skip kiya.\n\nAb **Donate Link** bhejo.\n(Example: https://...)\n\n/skip - Skip.\n/cancel - Cancel.")
    return GET_DONATE_LINK

async def get_donate_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['donate_link'] = update.message.text
    await update.message.reply_text("Donate link save ho gaya.\n\nAb **Support Inbox/Group** ka link bhejo.\n(Example: https://t.me/mygroup)\n\n/skip - Skip.\n/cancel - Cancel.")
    return GET_SUPPORT_LINK

async def skip_donate_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['donate_link'] = None
    await update.message.reply_text("Donate link skip kiya.\n\nAb **Support Inbox/Group** ka link bhejo.\n(Example: https://t.me/mygroup)\n\n/skip - Skip.\n/cancel - Cancel.")
    return GET_SUPPORT_LINK

async def get_support_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['support_link'] = update.message.text
    await save_links(update, context)

async def skip_support_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['support_link'] = None
    await save_links(update, context)

async def save_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    links = {
        "backup": context.user_data.get('backup_link'),
        "donate": context.user_data.get('donate_link'),
        "support": context.user_data.get('support_link')
    }
    config_collection.update_one({"_id": "bot_config"}, {"$set": {"links": links}}, upsert=True)
    logger.info(f"Links update ho gaye: {links}")
    await update.message.reply_text("✅ **Success!** Saare links set ho gaye hain. Wapas config menu me jaa raha hoon...")
    context.user_data.clear()
    return await config_menu(update, context)

# --- Post Generator Conversation (Issue 3 Fix) ---

async def post_gen_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Post Generator ka main menu"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("Aap admin nahi hain.", show_alert=True)
        return ConversationHandler.END
    logger.info(f"Admin {user_id} ne Post Generator khola.")
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("✍️ Season Post", callback_data="post_gen_season")],
        [InlineKeyboardButton("✍️ Episode Post", callback_data="post_gen_episode")],
        [InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_menu")]
    ]
    await query.edit_message_text(
        "✍️ **Post Generator** ✍️\n\nAap kis tarah ka post generate karna chahte hain?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return POST_GEN_MENU

async def post_gen_select_anime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Anime select karwayega (dono post type ke liye)"""
    query = update.callback_query
    await query.answer()
    post_type = query.data
    context.user_data['post_type'] = post_type
    all_animes = list(animes_collection.find({}, {"name": 1}))
    if not all_animes:
        await query.edit_message_text("❌ **Error!** Database mein koi anime nahi hai.")
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(anime['name'], callback_data=f"post_anime_{anime['name']}")] for anime in all_animes]
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_conv")])
    await query.edit_message_text("Kaunsa **Anime** select karna hai?", reply_markup=InlineKeyboardMarkup(keyboard))
    return POST_GEN_SELECT_ANIME

async def post_gen_select_season(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Season select karwayega (dono post type ke liye)"""
    query = update.callback_query
    await query.answer()
    anime_name = query.data.replace("post_anime_", "")
    context.user_data['anime_name'] = anime_name
    anime_doc = animes_collection.find_one({"name": anime_name})
    seasons = anime_doc.get("seasons", {})
    if not seasons:
        await query.edit_message_text(f"❌ **Error!** '{anime_name}' mein koi season nahi hai.")
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(f"Season {s}", callback_data=f"post_season_{s}")] for s in seasons]
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_conv")])
    await query.edit_message_text(f"Aapne **{anime_name}** select kiya hai.\n\nAb **Season** select karein:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return POST_GEN_SELECT_SEASON

async def post_gen_select_episode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Episode select karwayega (sirf episode post ke liye)"""
    query = update.callback_query
    await query.answer()
    season_name = query.data.replace("post_season_", "")
    context.user_data['season_name'] = season_name
    anime_name = context.user_data['anime_name']
    anime_doc = animes_collection.find_one({"name": anime_name})
    episodes = anime_doc.get("seasons", {}).get(season_name, {})
    if not episodes:
        await query.edit_message_text(f"❌ **Error!** '{anime_name}' - Season {season_name} mein koi episode nahi hai.")
        return ConversationHandler.END
    if context.user_data['post_type'] == 'post_gen_season':
        return await generate_post_ask_chat(update, context) # Naya function
    keyboard = [[InlineKeyboardButton(f"Episode {ep}", callback_data=f"post_ep_{ep}")] for ep in episodes]
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_conv")])
    await query.edit_message_text(f"Aapne **Season {season_name}** select kiya hai.\n\nAb **Episode** select karein:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return POST_GEN_SELECT_EPISODE

async def post_gen_final_episode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Final episode select hone ke baad post generate karega"""
    query = update.callback_query
    await query.answer()
    ep_num = query.data.replace("post_ep_", "")
    context.user_data['ep_num'] = ep_num
    return await generate_post_ask_chat(update, context) # Naya function
async def generate_post_ask_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Post ready karega aur admin se chat_id poochega (Issue 3 Fix)"""
    query = update.callback_query
    
    try:
        config = await get_config()
        anime_name = context.user_data['anime_name']
        season_name = context.user_data.get('season_name')
        ep_num = context.user_data.get('ep_num')
        
        anime_doc = animes_collection.find_one({"name": anime_name})
        
        # --- Caption Tayyar Karo ---
        if ep_num: # Episode Post
            caption = f"✨ **Episode {ep_num} Added** ✨\n\n🎬 **Anime:** {anime_name}\n➡️ **Season:** {season_name}\n\nNeeche [Download] button dabake download karein!"
            poster_id = anime_doc['poster_id']
        else: # Season Post
            caption = f"✅ **{anime_name}**\n"
            if season_name: caption += f"**[ S{season_name} ]**\n\n"
            if anime_doc.get('description'): caption += f"**📖 Synopsis:**\n{anime_doc['description']}\n\n"
            caption += "Neeche [Download] button dabake download karein!"
            poster_id = anime_doc['poster_id']
            
        # --- Buttons Tayyar Karo ---
        links = config.get('links', {})
        dl_callback_data = f"dl_{anime_name}"
        if season_name: dl_callback_data += f"_{season_name}"
        if ep_num: dl_callback_data += f"_{ep_num}"
            
        btn_backup = InlineKeyboardButton("Backup", url=links.get('backup', "https://t.me/"))
        btn_donate = InlineKeyboardButton("Donate", url=links.get('donate', "https://t.me/"))
        btn_support = InlineKeyboardButton("Support", url=links.get('support', "https://t.me/"))
        btn_download = InlineKeyboardButton("Download", callback_data=dl_callback_data)
        
        keyboard = [[btn_backup, btn_donate], [btn_support, btn_download]]
        
        # Post data ko context me save karo
        context.user_data['post_caption'] = caption
        context.user_data['post_poster_id'] = poster_id
        context.user_data['post_keyboard'] = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "✅ **Post Ready!**\n\nAb uss **Channel ka @username** ya **Group/Channel ki Chat ID** bhejo jahaan ye post karna hai.\n"
            "(Example: @MyAnimeChannel ya -100123456789)\n\n/cancel - Cancel."
        )
        return POST_GEN_GET_CHAT_ID

    except Exception as e:
        logger.error(f"Post generate karne me error: {e}")
        await query.answer("Error! Post generate nahi kar paya.", show_alert=True)
        await query.edit_message_text("❌ **Error!** Post generate nahi ho paya. Logs check karein.")
        context.user_data.clear()
        return ConversationHandler.END

async def post_gen_send_to_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Post ko final channel/group me bhejega (Issue 3 Fix)"""
    chat_id = update.message.text
    try:
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=context.user_data['post_poster_id'],
            caption=context.user_data['post_caption'],
            parse_mode='Markdown',
            reply_markup=context.user_data['post_keyboard']
        )
        await update.message.reply_text(f"✅ **Success!**\nPost ko '{chat_id}' par bhej diya gaya hai.")
    except Exception as e:
        logger.error(f"Post channel me bhejme me error: {e}")
        await update.message.reply_text(f"❌ **Error!**\nPost '{chat_id}' par nahi bhej paya. Check karo ki bot uss channel me admin hai ya ID sahi hai.\nError: {e}")
        
    context.user_data.clear()
    return ConversationHandler.END

# --- Manage Content Conversation ---

async def manage_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("Aap admin nahi hain.", show_alert=True)
        return ConversationHandler.END
    logger.info(f"Admin {user_id} ne Manage Content khola.")
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("🗑️ Delete Anime", callback_data="manage_del_anime")],
        [InlineKeyboardButton("🗑️ Delete Season", callback_data="manage_del_season")],
        [InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_menu")]
    ]
    await query.edit_message_text("📂 **Manage Content** 📂\n\nAap yahan se puraana content delete kar sakte hain.", reply_markup=InlineKeyboardMarkup(keyboard))
    return MANAGE_MENU

async def delete_anime_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    all_animes = list(animes_collection.find({}, {"name": 1}))
    if not all_animes:
        await query.edit_message_text("❌ **Error!** Database mein koi anime nahi hai.")
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(anime['name'], callback_data=f"del_anime_{anime['name']}")] for anime in all_animes]
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_conv")])
    await query.edit_message_text("Kaunsa **Anime** delete karna hai? (Ye permanent hoga)", reply_markup=InlineKeyboardMarkup(keyboard))
    return DELETE_ANIME_SELECT

async def delete_anime_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    anime_name = query.data.replace("del_anime_", "")
    context.user_data['anime_name'] = anime_name
    keyboard = [[InlineKeyboardButton(f"✅ Haan, {anime_name} ko Delete Karo", callback_data="del_anime_confirm_yes")], [InlineKeyboardButton("❌ Nahi, Cancel Karo", callback_data="cancel_conv")]]
    await query.edit_message_text(f"⚠️ **FINAL WARNING** ⚠️\n\nAap **{anime_name}** ko delete karne wale hain. Iske saare seasons aur episodes delete ho jayenge.\n\n**Are you sure?**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return DELETE_ANIME_CONFIRM

async def delete_anime_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Deleting...")
    anime_name = context.user_data['anime_name']
    try:
        animes_collection.delete_one({"name": anime_name})
        logger.info(f"Anime deleted: {anime_name}")
        await query.edit_message_text(f"✅ **Success!**\nAnime '{anime_name}' delete ho gaya hai.")
    except Exception as e:
        logger.error(f"Anime delete karne me error: {e}")
        await query.edit_message_text("❌ **Error!** Anime delete nahi ho paya.")
    context.user_data.clear()
    return ConversationHandler.END

async def delete_season_anime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    all_animes = list(animes_collection.find({}, {"name": 1}))
    if not all_animes:
        await query.edit_message_text("❌ **Error!** Database mein koi anime nahi hai.")
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(anime['name'], callback_data=f"del_season_anime_{anime['name']}")] for anime in all_animes]
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_conv")])
    await query.edit_message_text("Kaunse **Anime** ka season delete karna hai?", reply_markup=InlineKeyboardMarkup(keyboard))
    return DELETE_SEASON_ANIME

async def delete_season_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    anime_name = query.data.replace("del_season_anime_", "")
    context.user_data['anime_name'] = anime_name
    anime_doc = animes_collection.find_one({"name": anime_name})
    seasons = anime_doc.get("seasons", {})
    if not seasons:
        await query.edit_message_text(f"❌ **Error!** '{anime_name}' mein koi season nahi hai.")
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(f"Season {s}", callback_data=f"del_season_{s}")] for s in seasons]
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_conv")])
    await query.edit_message_text(f"Aapne **{anime_name}** select kiya hai.\n\nKaunsa **Season** delete karna hai?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return DELETE_SEASON_SELECT

async def delete_season_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    season_name = query.data.replace("del_season_", "")
    context.user_data['season_name'] = season_name
    anime_name = context.user_data['anime_name']
    keyboard = [[InlineKeyboardButton(f"✅ Haan, Season {season_name} Delete Karo", callback_data="del_season_confirm_yes")], [InlineKeyboardButton("❌ Nahi, Cancel Karo", callback_data="cancel_conv")]]
    await query.edit_message_text(f"⚠️ **FINAL WARNING** ⚠️\n\nAap **{anime_name}** ka **Season {season_name}** delete karne wale hain. Iske saare episodes delete ho jayenge.\n\n**Are you sure?**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return DELETE_SEASON_CONFIRM

async def delete_season_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Deleting...")
    anime_name = context.user_data['anime_name']
    season_name = context.user_data['season_name']
    try:
        animes_collection.update_one({"name": anime_name}, {"$unset": {f"seasons.{season_name}": ""}})
        logger.info(f"Season deleted: {anime_name} - S{season_name}")
        await query.edit_message_text(f"✅ **Success!**\nSeason '{season_name}' delete ho gaya hai.")
    except Exception as e:
        logger.error(f"Season delete karne me error: {e}")
        await query.edit_message_text("❌ **Error!** Season delete nahi ho paya.")
    context.user_data.clear()
    return ConversationHandler.END

async def back_to_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await admin_command(update, context, from_callback=True)
    return ConversationHandler.END

# --- Step 1 Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id, first_name = user.id, user.first_name
    logger.info(f"User {user_id} ({first_name}) ne /start dabaya.")
    if not users_collection.find_one({"_id": user_id}):
        users_collection.insert_one({"_id": user_id, "first_name": first_name, "username": user.username, "subscribed": False, "expiry_date": None, "last_screenshot_time": None})
        logger.info(f"Naya user database me add kiya: {user_id}")
    await update.message.reply_text(f"Salaam {first_name}! 👋\nMain aapka Anime Bot hoon.\n/menu - Menu dekho.")

# --- Admin Panel (Buttons ke Saath) ---

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE, from_callback: bool = False):
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.message.reply_text("Aap admin nahi hain.")
        return
    logger.info("Admin ne /admin command use kiya.")
    keyboard = [
        [InlineKeyboardButton("➕ Add Anime", callback_data="admin_add_anime"), InlineKeyboardButton("➕ Add Season", callback_data="admin_add_season")],
        [InlineKeyboardButton("➕ Add Episode", callback_data="admin_add_episode"), InlineKeyboardButton("⚙️ Bot Config", callback_data="admin_config")],
        [InlineKeyboardButton("✍️ Post Generator", callback_data="admin_post_gen"), InlineKeyboardButton("📂 Manage Content", callback_data="admin_manage_content")],
        [InlineKeyboardButton("👥 User Management", callback_data="admin_user_manage")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    admin_menu_text = "👑 **Salaam Admin! Control Panel** 👑\n\nContent add karne ya settings change karne ke liye buttons use karein."
    
    if from_callback:
        await update.callback_query.edit_message_text(admin_menu_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(admin_menu_text, reply_markup=reply_markup, parse_mode='Markdown')

async def placeholder_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer(f"Button '{query.data}' jald aa raha hai...", show_alert=True)

# --- Error Handler ---
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error} \nUpdate: {update}", exc_info=True)

# --- Main Bot Function ---
def main():
    # NAYA: Flask server ko alag thread me start karo (Issue 1 Fix)
    logger.info("Flask web server start ho raha hai (Render port ke liye)...")
    flask_thread = Thread(target=run_flask)
    flask_thread.start()
    
    logger.info("Bot Application ban raha hai...")
    application = Application.builder().token(BOT_TOKEN).build()
    
    conv_fallbacks = [CommandHandler("cancel", conv_cancel), CallbackQueryHandler(conv_cancel_button, pattern="^cancel_conv$")]
    admin_menu_fallback = [CallbackQueryHandler(back_to_admin_menu, pattern="^admin_menu$")]

    # --- Content Conversations ---
    add_anime_conv = ConversationHandler(entry_points=[CallbackQueryHandler(add_anime_start, pattern="^admin_add_anime$")], states={GET_ANIME_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_anime_name)], GET_ANIME_POSTER: [MessageHandler(filters.PHOTO, get_anime_poster)], GET_ANIME_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_anime_desc), CommandHandler("skip", skip_anime_desc)], CONFIRM_ANIME: [CallbackQueryHandler(save_anime_details, pattern="^save_anime$")]}, fallbacks=conv_fallbacks, per_user=True, per_chat=True)
    add_season_conv = ConversationHandler(entry_points=[CallbackQueryHandler(add_season_start, pattern="^admin_add_season$")], states={GET_ANIME_FOR_SEASON: [CallbackQueryHandler(get_anime_for_season, pattern="^season_anime_")], GET_SEASON_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_season_number)], CONFIRM_SEASON: [CallbackQueryHandler(save_season, pattern="^save_season$")]}, fallbacks=conv_fallbacks, per_user=True, per_chat=True)
    add_episode_conv = ConversationHandler(entry_points=[CallbackQueryHandler(add_episode_start, pattern="^admin_add_episode$")], states={GET_ANIME_FOR_EPISODE: [CallbackQueryHandler(get_anime_for_episode, pattern="^ep_anime_")], GET_SEASON_FOR_EPISODE: [CallbackQueryHandler(get_season_for_episode, pattern="^ep_season_")], GET_EPISODE_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_episode_number)], GET_EPISODE_QUALITY: [CallbackQueryHandler(get_episode_quality, pattern="^ep_quality_")], GET_EPISODE_FILE: [MessageHandler(filters.VIDEO | filters.Document.ALL, get_episode_file)]}, fallbacks=conv_fallbacks, per_user=True, per_chat=True)

    # --- Config Conversation ---
    config_conv = ConversationHandler(entry_points=[CallbackQueryHandler(config_menu, pattern="^admin_config$")], states={CONFIG_MENU: [CallbackQueryHandler(config_set_sub_qr_start, pattern="^config_set_sub_qr$"), CallbackQueryHandler(config_set_donate_qr_start, pattern="^config_set_donate_qr$"), CallbackQueryHandler(config_set_price_start, pattern="^config_set_price$"), CallbackQueryHandler(config_set_links_start, pattern="^config_set_links$"), ], GET_SUB_QR: [MessageHandler(filters.PHOTO, config_set_sub_qr_save)], GET_DONATE_QR: [MessageHandler(filters.PHOTO, config_set_donate_qr_save)], GET_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, config_set_price_save)], GET_BACKUP_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_backup_link), CommandHandler("skip", skip_backup_link)], GET_DONATE_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_donate_link), CommandHandler("skip", skip_donate_link)], GET_SUPPORT_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_support_link), CommandHandler("skip", skip_support_link)], }, fallbacks=conv_fallbacks + admin_menu_fallback, per_user=True, per_chat=True)

    # --- Post Generator Conversation (Updated for Issue 3 Fix) ---
    post_gen_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(post_gen_menu, pattern="^admin_post_gen$")],
        states={
            POST_GEN_MENU: [CallbackQueryHandler(post_gen_select_anime, pattern="^post_gen_season$"), CallbackQueryHandler(post_gen_select_anime, pattern="^post_gen_episode$"), ],
            POST_GEN_SELECT_ANIME: [CallbackQueryHandler(post_gen_select_season, pattern="^post_anime_")],
            POST_GEN_SELECT_SEASON: [CallbackQueryHandler(post_gen_select_episode, pattern="^post_season_")],
            POST_GEN_SELECT_EPISODE: [CallbackQueryHandler(post_gen_final_episode, pattern="^post_ep_")],
            POST_GEN_GET_CHAT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, post_gen_send_to_chat)] # Naya handler
        },
        fallbacks=conv_fallbacks + admin_menu_fallback,
        per_user=True, per_chat=True
    )
    
    # --- Manage Content Conversation ---
    manage_conv = ConversationHandler(entry_points=[CallbackQueryHandler(manage_menu, pattern="^admin_manage_content$")], states={MANAGE_MENU: [CallbackQueryHandler(delete_anime_select, pattern="^manage_del_anime$"), CallbackQueryHandler(delete_season_anime, pattern="^manage_del_season$"), ], DELETE_ANIME_SELECT: [CallbackQueryHandler(delete_anime_confirm, pattern="^del_anime_")], DELETE_ANIME_CONFIRM: [CallbackQueryHandler(delete_anime_do, pattern="^del_anime_confirm_yes$")], DELETE_SEASON_ANIME: [CallbackQueryHandler(delete_season_select, pattern="^del_season_anime_")], DELETE_SEASON_SELECT: [CallbackQueryHandler(delete_season_confirm, pattern="^del_season_")], DELETE_SEASON_CONFIRM: [CallbackQueryHandler(delete_season_do, pattern="^del_season_confirm_yes$")]}, fallbacks=conv_fallbacks + admin_menu_fallback, per_user=True, per_chat=True)

    # --- Handlers ko Add Karo ---
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CallbackQueryHandler(admin_command, pattern="^admin_menu$"))
    
    application.add_handler(add_anime_conv)
    application.add_handler(add_season_conv)
    application.add_handler(add_episode_conv)
    application.add_handler(config_conv)
    application.add_handler(post_gen_conv)
    application.add_handler(manage_conv)
    
    # --- Placeholder buttons ---
    application.add_handler(CallbackQueryHandler(placeholder_button_handler, pattern="^admin_user_manage$"))

    application.add_error_handler(error_handler)

    logger.info("Bot polling start kar raha hai...")
    application.run_polling()

if __name__ == "__main__":
    main()
