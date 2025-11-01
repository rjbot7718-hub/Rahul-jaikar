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
# Flask server ke liye
from flask import Flask
from threading import Thread

# --- Flask Server Setup ---
app = Flask(__name__)
@app.route('/')
def home():
    return "I am alive and running!"
def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# --- Baaki ka Bot Code ---
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
            "_id": "bot_config", "sub_qr_id": None, "donate_qr_id": None, "price": None, 
            "links": {"backup": None, "donate": None, "support": None}
        }
        config_collection.insert_one(default_config)
        return default_config
    return config

# --- Conversation States ---
# YE AB ALAG ALAG CONVERSATIONS KE LIYE HONGE
# Add Anime States
(A_GET_NAME, A_GET_POSTER, A_GET_DESC, A_CONFIRM) = range(4)
# Add Season States
(S_GET_ANIME, S_GET_NUMBER, S_CONFIRM) = range(4, 7)
# Add Episode States
(E_GET_ANIME, E_GET_SEASON, E_GET_NUMBER, E_GET_QUALITY, E_GET_FILE) = range(7, 12)
# Config - Sub QR
(CS_GET_QR,) = range(12, 13)
# Config - Donate QR
(CD_GET_QR,) = range(13, 14)
# Config - Price
(CP_GET_PRICE,) = range(14, 15)
# Config - Links
(CL_GET_BACKUP, CL_GET_DONATE, CL_GET_SUPPORT) = range(15, 18)
# Post Gen States
(PG_MENU, PG_GET_ANIME, PG_GET_SEASON, PG_GET_EPISODE, PG_GET_CHAT) = range(18, 23)
# Manage - Delete Anime
(DA_GET_ANIME, DA_CONFIRM) = range(23, 25)
# Manage - Delete Season
(DS_GET_ANIME, DS_GET_SEASON, DS_CONFIRM) = range(25, 28)

# --- Common Conversation Fallbacks ---
async def conv_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/cancel command se conversation ko band karega"""
    logger.info("User ne conversation /cancel se band kar diya.")
    if update.message:
        await update.message.reply_text("Operation cancel kar diya gaya hai.")
    else:
        await update.callback_query.answer("Operation cancel kar diya gaya hai.")
        await update.callback_query.edit_message_text("Operation cancel kar diya gaya hai.")
    context.user_data.clear() 
    return ConversationHandler.END

async def back_to_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kisi bhi sub-menu se wapas main admin menu pe aayega"""
    query = update.callback_query
    await query.answer()
    await admin_command(update, context, from_callback=True) # Main admin panel ko call karo
    return ConversationHandler.END # Conversation ko poora band kar do

async def back_to_add_content_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Wapas 'Add Content' menu pe aayega"""
    query = update.callback_query
    await query.answer()
    await add_content_menu(update, context)
    return ConversationHandler.END
    
async def back_to_manage_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Wapas 'Manage Content' menu pe aayega"""
    query = update.callback_query
    await query.answer()
    await manage_content_menu(update, context)
    return ConversationHandler.END
    
async def back_to_sub_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Wapas 'Subscription Settings' menu pe aayega"""
    query = update.callback_query
    await query.answer()
    await sub_settings_menu(update, context)
    return ConversationHandler.END
    
async def back_to_donate_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Wapas 'Donation Settings' menu pe aayega"""
    query = update.callback_query
    await query.answer()
    await donate_settings_menu(update, context)
    return ConversationHandler.END

async def back_to_links_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Wapas 'Other Links' menu pe aayega"""
    query = update.callback_query
    await query.answer()
    await other_links_menu(update, context)
    return ConversationHandler.END

# --- Conversation: Add Anime ---
async def add_anime_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = "Salaam Admin! Anime ka **Naam** kya hai?\n\n/cancel - Cancel."
    await query.edit_message_text(text, parse_mode='Markdown') 
    return A_GET_NAME
async def get_anime_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['anime_name'] = update.message.text
    await update.message.reply_text("Badhiya! Ab anime ka **Poster (Photo)** bhejo.\n\n/cancel - Cancel.")
    return A_GET_POSTER
async def get_anime_poster(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("Ye photo nahi hai. Please ek photo bhejo.")
        return A_GET_POSTER 
    context.user_data['anime_poster_id'] = update.message.photo[-1].file_id
    await update.message.reply_text("Poster mil gaya! Ab **Description (Synopsis)** bhejo.\n\n/skip ya /cancel.")
    return A_GET_DESC
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
    keyboard = [[InlineKeyboardButton("✅ Save", callback_data="save_anime")], [InlineKeyboardButton("⬅️ Back", callback_data="back_to_add_content")]]
    await update.message.reply_photo(photo=poster_id, caption=caption, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return A_CONFIRM
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

# --- Conversation: Add Season ---
async def add_season_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    all_animes = list(animes_collection.find({}, {"name": 1}))
    if not all_animes:
        await query.edit_message_text("❌ **Error!** Pehle `➕ Add Anime` se anime add karo.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_to_add_content")]]))
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(anime['name'], callback_data=f"season_anime_{anime['name']}")] for anime in all_animes]
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_to_add_content")])
    text = "Aap kis anime mein season add karna chahte hain?"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return S_GET_ANIME
async def get_anime_for_season(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    anime_name = query.data.replace("season_anime_", "")
    context.user_data['anime_name'] = anime_name
    await query.edit_message_text(f"Aapne **{anime_name}** select kiya hai.\n\nAb is season ka **Number ya Naam** bhejo.\n(Jaise: 1, 2, Movie)\n\n/cancel - Cancel.")
    return S_GET_NUMBER
async def get_season_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    season_name = update.message.text
    context.user_data['season_name'] = season_name
    anime_name = context.user_data['anime_name']
    anime_doc = animes_collection.find_one({"name": anime_name})
    if season_name in anime_doc.get("seasons", {}):
        await update.message.reply_text(f"⚠️ **Error!** '{anime_name}' mein 'Season {season_name}' pehle se hai.\n\nKoi doosra naam/number type karein ya /cancel karein.")
        return S_GET_NUMBER
    keyboard = [[InlineKeyboardButton("✅ Haan, Save Karo", callback_data="save_season")], [InlineKeyboardButton("⬅️ Back", callback_data="back_to_add_content")]]
    await update.message.reply_text(f"**Confirm Karo:**\nAnime: **{anime_name}**\nNaya Season: **{season_name}**\n\nSave kar doon?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return S_CONFIRM
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

# --- Conversation: Add Episode ---
async def add_episode_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    all_animes = list(animes_collection.find({}, {"name": 1}))
    if not all_animes:
        await query.edit_message_text("❌ **Error!** Pehle `➕ Add Anime` se anime add karo.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_to_add_content")]]))
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(anime['name'], callback_data=f"ep_anime_{anime['name']}")] for anime in all_animes]
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_to_add_content")])
    text = "Aap kis anime mein episode add karna chahte hain?"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return E_GET_ANIME
async def get_anime_for_episode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    anime_name = query.data.replace("ep_anime_", "")
    context.user_data['anime_name'] = anime_name
    anime_doc = animes_collection.find_one({"name": anime_name})
    seasons = anime_doc.get("seasons", {})
    if not seasons:
        await query.edit_message_text(f"❌ **Error!** '{anime_name}' mein koi season nahi hai.\n\nPehle `➕ Add Season` se season add karo.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_to_add_content")]]))
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(f"Season {s}", callback_data=f"ep_season_{s}")] for s in seasons]
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_to_add_content")])
    await query.edit_message_text(f"Aapne **{anime_name}** select kiya hai.\n\nAb **Season** select karein:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return E_GET_SEASON
async def get_season_for_episode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    season_name = query.data.replace("ep_season_", "")
    context.user_data['season_name'] = season_name
    await query.edit_message_text(f"Aapne **Season {season_name}** select kiya hai.\n\nAb **Episode Number** bhejo.\n(Jaise: 1, 2, 3...)\n\n/cancel - Cancel.")
    return E_GET_NUMBER
async def get_episode_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['ep_num'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("480p", callback_data="ep_quality_480p"), InlineKeyboardButton("720p", callback_data="ep_quality_720p")],
        [InlineKeyboardButton("1080p", callback_data="ep_quality_1080p"), InlineKeyboardButton("4K", callback_data="ep_quality_4K")],
        [InlineKeyboardButton("⬅️ Back", callback_data="back_to_add_content")]
    ]
    await update.message.reply_text(f"Aapne **Episode {context.user_data['ep_num']}** select kiya hai.\n\nAb **Quality** select karein:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return E_GET_QUALITY
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
    return E_GET_FILE
async def get_episode_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_id = None
    if update.message.video: file_id = update.message.video.file_id
    elif update.message.document: file_id = update.message.document.file_id
    if not file_id:
        await update.message.reply_text("Ye video file nahi hai. Please ek video file forward karein ya /cancel karein.")
        return E_GET_FILE
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

# --- Conversation: Set Subscription QR ---
async def set_sub_qr_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Aapna **Subscription (Payment) QR Code** ki photo bhejo.\n\n/cancel - Cancel.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_to_sub_settings")]]))
    return CS_GET_QR
async def set_sub_qr_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("Ye photo nahi hai. Please ek photo bhejo ya /cancel karein.")
        return CS_GET_QR
    qr_file_id = update.message.photo[-1].file_id
    config_collection.update_one({"_id": "bot_config"}, {"$set": {"sub_qr_id": qr_file_id}}, upsert=True)
    logger.info(f"Subscription QR code update ho gaya.")
    await update.message.reply_text("✅ **Success!** Naya subscription QR code set ho gaya hai.")
    await sub_settings_menu(update, context) # Wapas menu dikhao
    return ConversationHandler.END

# --- Conversation: Set Price ---
async def set_price_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Subscription ka **Price & Duration** bhejo.\n(Example: 50 INR for 30 days)\n\n/cancel - Cancel.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_to_sub_settings")]]))
    return CP_GET_PRICE
async def set_price_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    price_text = update.message.text
    config_collection.update_one({"_id": "bot_config"}, {"$set": {"price": price_text}}, upsert=True)
    logger.info(f"Price update ho gaya: {price_text}")
    await update.message.reply_text(f"✅ **Success!** Naya price set ho gaya hai: '{price_text}'.")
    await sub_settings_menu(update, context) # Wapas menu dikhao
    return ConversationHandler.END

# --- Conversation: Set Donate QR ---
async def set_donate_qr_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Aapna **Donate QR Code** ki photo bhejo.\n\n/cancel - Cancel.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_to_donate_settings")]]))
    return CD_GET_QR
async def set_donate_qr_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("Ye photo nahi hai. Please ek photo bhejo ya /cancel karein.")
        return CD_GET_QR
    qr_file_id = update.message.photo[-1].file_id
    config_collection.update_one({"_id": "bot_config"}, {"$set": {"donate_qr_id": qr_file_id}}, upsert=True)
    logger.info(f"Donate QR code update ho gaya.")
    await update.message.reply_text("✅ **Success!** Naya donate QR code set ho gaya hai.")
    await donate_settings_menu(update, context) # Wapas menu dikhao
    return ConversationHandler.END

# --- Conversation: Set Links ---
async def set_links_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # Pata lagao kaunsa link set karna hai
    link_type = query.data.replace("admin_set_", "") # donate_link, backup_link, support_link
    
    if link_type == "donate_link":
        context.user_data['link_type'] = "donate"
        text = "Aapna **Donate Link** bhejo.\n(Example: https://...)\n\n/skip - Skip.\n/cancel - Cancel."
        back_button = "back_to_donate_settings"
    elif link_type == "backup_link":
        context.user_data['link_type'] = "backup"
        text = "Aapke **Backup Channel** ka link bhejo.\n(Example: https://t.me/mychannel)\n\n/skip - Skip.\n/cancel - Cancel."
        back_button = "back_to_links"
    else: # support_link
        context.user_data['link_type'] = "support"
        text = "Aapke **Support Inbox/Group** ka link bhejo.\n(Example: https://t.me/mygroup)\n\n/skip - Skip.\n/cancel - Cancel."
        back_button = "back_to_links"
        
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=back_button)]]))
    return CL_GET_BACKUP # Ek hi state use karenge sabke liye

async def get_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Link ko save karega"""
    link_url = update.message.text
    link_type = context.user_data['link_type']
    
    config_collection.update_one({"_id": "bot_config"}, {"$set": {f"links.{link_type}": link_url}}, upsert=True)
    logger.info(f"{link_type} link update ho gaya: {link_url}")
    await update.message.reply_text(f"✅ **Success!** Naya {link_type} link set ho gaya hai.")
    
    # Wapas sahi menu pe bhejo
    if link_type == "donate":
        await donate_settings_menu(update, context)
    else:
        await other_links_menu(update, context)
        
    context.user_data.clear()
    return ConversationHandler.END
    
async def skip_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Link ko skip karega (None set karega)"""
    link_type = context.user_data['link_type']
    
    config_collection.update_one({"_id": "bot_config"}, {"$set": {f"links.{link_type}": None}}, upsert=True)
    logger.info(f"{link_type} link skip kiya (None set).")
    await update.message.reply_text(f"✅ **Success!** {link_type} link remove kar diya gaya hai.")

    # Wapas sahi menu pe bhejo
    if link_type == "donate":
        await donate_settings_menu(update, context)
    else:
        await other_links_menu(update, context)
        
    context.user_data.clear()
    return ConversationHandler.END

# --- Conversation: Post Generator ---
async def post_gen_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("✍️ Season Post", callback_data="post_gen_season")],
        [InlineKeyboardButton("✍️ Episode Post", callback_data="post_gen_episode")],
        [InlineKeyboardButton("⬅️ Back", callback_data="admin_menu")]
    ]
    await query.edit_message_text("✍️ **Post Generator** ✍️\n\nAap kis tarah ka post generate karna chahte hain?", reply_markup=InlineKeyboardMarkup(keyboard))
    return PG_MENU
async def post_gen_select_anime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    post_type = query.data
    context.user_data['post_type'] = post_type
    all_animes = list(animes_collection.find({}, {"name": 1}))
    if not all_animes:
        await query.edit_message_text("❌ **Error!** Database mein koi anime nahi hai.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="admin_menu")]]))
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(anime['name'], callback_data=f"post_anime_{anime['name']}")] for anime in all_animes]
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_menu")])
    await query.edit_message_text("Kaunsa **Anime** select karna hai?", reply_markup=InlineKeyboardMarkup(keyboard))
    return PG_GET_ANIME
async def post_gen_select_season(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    anime_name = query.data.replace("post_anime_", "")
    context.user_data['anime_name'] = anime_name
    anime_doc = animes_collection.find_one({"name": anime_name})
    seasons = anime_doc.get("seasons", {})
    if not seasons:
        await query.edit_message_text(f"❌ **Error!** '{anime_name}' mein koi season nahi hai.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="admin_menu")]]))
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(f"Season {s}", callback_data=f"post_season_{s}")] for s in seasons]
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_menu")])
    await query.edit_message_text(f"Aapne **{anime_name}** select kiya hai.\n\nAb **Season** select karein:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return PG_GET_SEASON
async def post_gen_select_episode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    season_name = query.data.replace("post_season_", "")
    context.user_data['season_name'] = season_name
    anime_name = context.user_data['anime_name']
    if context.user_data['post_type'] == 'post_gen_season':
        return await generate_post_ask_chat(update, context)
    anime_doc = animes_collection.find_one({"name": anime_name})
    episodes = anime_doc.get("seasons", {}).get(season_name, {})
    if not episodes:
        await query.edit_message_text(f"❌ **Error!** '{anime_name}' - Season {season_name} mein koi episode nahi hai.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="admin_menu")]]))
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(f"Episode {ep}", callback_data=f"post_ep_{ep}")] for ep in episodes]
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_menu")])
    await query.edit_message_text(f"Aapne **Season {season_name}** select kiya hai.\n\nAb **Episode** select karein:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return PG_GET_EPISODE
async def post_gen_final_episode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ep_num = query.data.replace("post_ep_", "")
    context.user_data['ep_num'] = ep_num
    return await generate_post_ask_chat(update, context)
async def generate_post_ask_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        config = await get_config()
        anime_name = context.user_data['anime_name']
        season_name = context.user_data.get('season_name')
        ep_num = context.user_data.get('ep_num')
        anime_doc = animes_collection.find_one({"name": anime_name})
        if ep_num:
            caption = f"✨ **Episode {ep_num} Added** ✨\n\n🎬 **Anime:** {anime_name}\n➡️ **Season:** {season_name}\n\nNeeche [Download] button dabake download karein!"
            poster_id = anime_doc['poster_id']
        else:
            caption = f"✅ **{anime_name}**\n"
            if season_name: caption += f"**[ S{season_name} ]**\n\n"
            if anime_doc.get('description'): caption += f"**📖 Synopsis:**\n{anime_doc['description']}\n\n"
            caption += "Neeche [Download] button dabake download karein!"
            poster_id = anime_doc['poster_id']
        
        links = config.get('links', {})
        dl_callback_data = f"dl_{anime_name}"
        if season_name: dl_callback_data += f"_{season_name}"
        if ep_num: dl_callback_data += f"_{ep_num}"
        
        # --- NAYA URL FIX ---
        backup_url = links.get('backup')
        if not backup_url or not backup_url.startswith(("http", "t.me")):
            backup_url = "https://t.me/" # Default placeholder
        
        donate_url = links.get('donate')
        if not donate_url or not donate_url.startswith(("http", "t.me")):
            donate_url = "https://t.me/" # Default placeholder

        support_url = links.get('support')
        if not support_url or not support_url.startswith(("http", "t.me")):
            support_url = "https://t.me/" # Default placeholder
            
        btn_backup = InlineKeyboardButton("Backup", url=backup_url)
        btn_donate = InlineKeyboardButton("Donate", url=donate_url)
        btn_support = InlineKeyboardButton("Support", url=support_url)
        # --- END FIX ---
        
        btn_download = InlineKeyboardButton("Download", callback_data=dl_callback_data)
        keyboard = [[btn_backup, btn_donate], [btn_support, btn_download]]
        
        context.user_data['post_caption'] = caption
        context.user_data['post_poster_id'] = poster_id
        context.user_data['post_keyboard'] = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "✅ **Post Ready!**\n\nAb uss **Channel ka @username** ya **Group/Channel ki Chat ID** bhejo jahaan ye post karna hai.\n"
            "(Example: @MyAnimeChannel ya -100123456789)\n\n/cancel - Cancel."
        )
        return PG_GET_CHAT
    except Exception as e:
        logger.error(f"Post generate karne me error: {e}")
        await query.answer("Error! Post generate nahi kar paya.", show_alert=True)
        await query.edit_message_text("❌ **Error!** Post generate nahi ho paya. Logs check karein.")
        context.user_data.clear()
        return ConversationHandler.END
async def post_gen_send_to_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

# --- Conversation: Delete Anime ---
async def delete_anime_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    all_animes = list(animes_collection.find({}, {"name": 1}))
    if not all_animes:
        await query.edit_message_text("❌ **Error!** Database mein koi anime nahi hai.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_to_manage")]]))
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(anime['name'], callback_data=f"del_anime_{anime['name']}")] for anime in all_animes]
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_to_manage")])
    await query.edit_message_text("Kaunsa **Anime** delete karna hai? (Ye permanent hoga)", reply_markup=InlineKeyboardMarkup(keyboard))
    return DA_GET_ANIME
async def delete_anime_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    anime_name = query.data.replace("del_anime_", "")
    context.user_data['anime_name'] = anime_name
    keyboard = [[InlineKeyboardButton(f"✅ Haan, {anime_name} ko Delete Karo", callback_data="del_anime_confirm_yes")], [InlineKeyboardButton("⬅️ Back", callback_data="back_to_manage")]]
    await query.edit_message_text(f"⚠️ **FINAL WARNING** ⚠️\n\nAap **{anime_name}** ko delete karne wale hain. Iske saare seasons aur episodes delete ho jayenge.\n\n**Are you sure?**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return DA_CONFIRM
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

# --- Conversation: Delete Season ---
async def delete_season_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    all_animes = list(animes_collection.find({}, {"name": 1}))
    if not all_animes:
        await query.edit_message_text("❌ **Error!** Database mein koi anime nahi hai.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_to_manage")]]))
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(anime['name'], callback_data=f"del_season_anime_{anime['name']}")] for anime in all_animes]
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_to_manage")])
    await query.edit_message_text("Kaunse **Anime** ka season delete karna hai?", reply_markup=InlineKeyboardMarkup(keyboard))
    return DS_GET_ANIME
async def delete_season_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    anime_name = query.data.replace("del_season_anime_", "")
    context.user_data['anime_name'] = anime_name
    anime_doc = animes_collection.find_one({"name": anime_name})
    seasons = anime_doc.get("seasons", {})
    if not seasons:
        await query.edit_message_text(f"❌ **Error!** '{anime_name}' mein koi season nahi hai.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_to_manage")]]))
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(f"Season {s}", callback_data=f"del_season_{s}")] for s in seasons]
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_to_manage")])
    await query.edit_message_text(f"Aapne **{anime_name}** select kiya hai.\n\nKaunsa **Season** delete karna hai?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return DS_GET_SEASON
async def delete_season_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    season_name = query.data.replace("del_season_", "")
    context.user_data['season_name'] = season_name
    anime_name = context.user_data['anime_name']
    keyboard = [[InlineKeyboardButton(f"✅ Haan, Season {season_name} Delete Karo", callback_data="del_season_confirm_yes")], [InlineKeyboardButton("⬅️ Back", callback_data="back_to_manage")]]
    await query.edit_message_text(f"⚠️ **FINAL WARNING** ⚠️\n\nAap **{anime_name}** ka **Season {season_name}** delete karne wale hain. Iske saare episodes delete ho jayenge.\n\n**Are you sure?**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return DS_CONFIRM
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

# --- Admin Panel: Sub-Menu Functions ---
async def add_content_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'Add Content' ka sub-menu dikhayega"""
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("➕ Add Anime", callback_data="admin_add_anime")],
        [InlineKeyboardButton("➕ Add Season", callback_data="admin_add_season")],
        [InlineKeyboardButton("➕ Add Episode", callback_data="admin_add_episode")],
        [InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_menu")]
    ]
    await query.edit_message_text("➕ **Add Content** ➕\n\nAap kya add karna chahte hain?", reply_markup=InlineKeyboardMarkup(keyboard))
    
async def manage_content_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'Manage Content' ka sub-menu dikhayega"""
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("🗑️ Delete Anime", callback_data="admin_del_anime")],
        [InlineKeyboardButton("🗑️ Delete Season", callback_data="admin_del_season")],
        [InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_menu")]
    ]
    await query.edit_message_text("✏️ **Manage Content** ✏️\n\nAap kya manage karna chahte hain?", reply_markup=InlineKeyboardMarkup(keyboard))
    
async def sub_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'Subscription Settings' ka sub-menu dikhayega"""
    query = update.callback_query
    if query: await query.answer()
    config = await get_config()
    sub_qr_status = "✅" if config.get('sub_qr_id') else "❌"
    price_status = "✅" if config.get('price') else "❌"
    keyboard = [
        [InlineKeyboardButton(f"Set Subscription QR {sub_qr_status}", callback_data="admin_set_sub_qr")],
        [InlineKeyboardButton(f"Set Price {price_status}", callback_data="admin_set_price")],
        [InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_menu")]
    ]
    text = "💲 **Subscription Settings** 💲\n\nSubscription se judi settings yahan badlein."
    if query: await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else: await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def donate_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'Donation Settings' ka sub-menu dikhayega"""
    query = update.callback_query
    if query: await query.answer()
    config = await get_config()
    donate_qr_status = "✅" if config.get('donate_qr_id') else "❌"
    donate_link_status = "✅" if config.get('links', {}).get('donate') else "❌"
    keyboard = [
        [InlineKeyboardButton(f"Set Donate QR {donate_qr_status}", callback_data="admin_set_donate_qr")],
        [InlineKeyboardButton(f"Set Donate Link {donate_link_status}", callback_data="admin_set_donate_link")],
        [InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_menu")]
    ]
    text = "❤️ **Donation Settings** ❤️\n\nDonation se judi settings yahan badlein."
    if query: await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else: await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def other_links_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'Other Links' ka sub-menu dikhayega"""
    query = update.callback_query
    if query: await query.answer()
    config = await get_config()
    backup_status = "✅" if config.get('links', {}).get('backup') else "❌"
    support_status = "✅" if config.get('links', {}).get('support') else "❌"
    keyboard = [
        [InlineKeyboardButton(f"Set Backup Link {backup_status}", callback_data="admin_set_backup_link")],
        [InlineKeyboardButton(f"Set Support Link {support_status}", callback_data="admin_set_support_link")],
        [InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_menu")]
    ]
    text = "🔗 **Other Links** 🔗\n\nDoosre links yahan set karein."
    if query: await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else: await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
# --- User Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """NAYA: Smart /start command"""
    user = update.effective_user
    user_id, first_name = user.id, user.first_name
    logger.info(f"User {user_id} ({first_name}) ne /start dabaya.")
    
    # User ko DB me add karo agar nahi hai
    user_data = users_collection.find_one({"_id": user_id})
    if not user_data:
        users_collection.insert_one({"_id": user_id, "first_name": first_name, "username": user.username, "subscribed": False, "expiry_date": None, "last_screenshot_time": None})
        logger.info(f"Naya user database me add kiya: {user_id}")
    
    # Check karo admin hai ya user
    if await is_admin(user_id):
        logger.info("Admin detected. Admin panel dikha raha hoon.")
        await admin_command(update, context) # Admin panel call karo
    else:
        logger.info("User detected. User menu dikha raha hoon.")
        await menu_command(update, context) # User menu call karo

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User ka main menu (/menu)"""
    user = update.effective_user
    user_id = user.id
    logger.info(f"User {user_id} ne /menu khola.")
    
    config = await get_config()
    user_data = users_collection.find_one({"_id": user_id}) or {}
    
    links = config.get('links', {})
    
    # Check subscription status
    if user_data.get('subscribed', False):
        expiry = user_data.get('expiry_date', 'N/A')
        sub_text = f"✅ Subscribed (Expires: {expiry})"
        sub_cb = "user_check_sub" # Placeholder
    else:
        sub_text = "💰 Subscribe Now"
        sub_cb = "user_subscribe" # Step 4 me banega
    
    # --- NAYA URL FIX ---
    backup_url = links.get('backup')
    if not backup_url or not backup_url.startswith(("http", "t.me")):
        backup_url = "https://t.me/" # Default placeholder
    
    donate_url = links.get('donate')
    if not donate_url or not donate_url.startswith(("http", "t.me")):
        donate_url = "https://t.me/" # Default placeholder

    support_url = links.get('support')
    if not support_url or not support_url.startswith(("http", "t.me")):
        support_url = "https://t.me/" # Default placeholder
        
    btn_backup = InlineKeyboardButton("Backup", url=backup_url)
    btn_donate = InlineKeyboardButton("Donate", url=donate_url)
    btn_support = InlineKeyboardButton("Support", url=support_url)
    # --- END FIX ---
    
    btn_sub = InlineKeyboardButton(sub_text, callback_data=sub_cb)
    keyboard = [[btn_sub], [btn_backup, btn_donate], [btn_support]]
    
    await update.message.reply_text(f"Salaam {user.first_name}! Ye raha aapka menu:", reply_markup=InlineKeyboardMarkup(keyboard))

# --- Admin Panel (Naya Layout) ---

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE, from_callback: bool = False):
    """Admin panel ka main menu (Naya Layout)"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        if not from_callback: await update.message.reply_text("Aap admin nahi hain.")
        return
        
    logger.info("Admin ne /admin command use kiya.")
    
    # TODO: Pending payments count yahan fetch kar sakte hain
    pending_count = 0 
    
    keyboard = [
        [InlineKeyboardButton("➕ Add Content", callback_data="admin_menu_add_content")],
        [InlineKeyboardButton("✏️ Manage Content", callback_data="admin_menu_manage_content")],
        [InlineKeyboardButton("✍️ Post Generator", callback_data="admin_post_gen")],
        [InlineKeyboardButton("💲 Subscription Settings", callback_data="admin_menu_sub_settings")],
        [InlineKeyboardButton("❤️ Donation Settings", callback_data="admin_menu_donate_settings")],
        [InlineKeyboardButton("🔗 Other Links", callback_data="admin_menu_other_links")],
        [InlineKeyboardButton(f"🔔 Pending Payments ({pending_count})", callback_data="admin_pending_payments")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    admin_menu_text = f"Salaam, Admin Boss! 👑\nAapka control panel taiyyar hai."
    
    if from_callback:
        # Agar 'Back' button se aaye hain, to message edit karo
        try:
            await update.callback_query.edit_message_text(admin_menu_text, reply_markup=reply_markup, parse_mode='Markdown')
        except Exception as e:
            logger.warning(f"Admin menu edit nahi kar paya (shayad message same tha): {e}")
            await update.callback_query.answer() # Button click ko register karo
    else:
        # Agar /admin command se aaye hain, to naya message bhejo
        await update.message.reply_text(admin_menu_text, reply_markup=reply_markup, parse_mode='Markdown')

async def placeholder_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer(f"Button '{query.data}' jald aa raha hai...", show_alert=True)

# --- Error Handler ---
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error} \nUpdate: {update}", exc_info=True)

# --- Main Bot Function ---
def main():
    logger.info("Flask web server start ho raha hai (Render port ke liye)...")
    flask_thread = Thread(target=run_flask)
    flask_thread.start()
    
    logger.info("Bot Application ban raha hai...")
    application = Application.builder().token(BOT_TOKEN).build()
    
    # --- Saare Conversation Handlers ---
    
    # Fallbacks
    admin_menu_fallback = [CallbackQueryHandler(back_to_admin_menu, pattern="^admin_menu$")]
    add_content_fallback = [CallbackQueryHandler(back_to_add_content_menu, pattern="^back_to_add_content$")]
    manage_fallback = [CallbackQueryHandler(back_to_manage_menu, pattern="^back_to_manage$")]
    sub_settings_fallback = [CallbackQueryHandler(back_to_sub_settings_menu, pattern="^back_to_sub_settings$")]
    donate_settings_fallback = [CallbackQueryHandler(back_to_donate_settings_menu, pattern="^back_to_donate_settings$")]
    links_fallback = [CallbackQueryHandler(back_to_links_menu, pattern="^back_to_links$")]
    cancel_fallback = [CommandHandler("cancel", conv_cancel)]

    # 1. Add Anime
    add_anime_conv = ConversationHandler(entry_points=[CallbackQueryHandler(add_anime_start, pattern="^admin_add_anime$")], states={A_GET_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_anime_name)], A_GET_POSTER: [MessageHandler(filters.PHOTO, get_anime_poster)], A_GET_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_anime_desc), CommandHandler("skip", skip_anime_desc)], A_CONFIRM: [CallbackQueryHandler(save_anime_details, pattern="^save_anime$")]}, fallbacks=cancel_fallback + add_content_fallback)
    # 2. Add Season
    add_season_conv = ConversationHandler(entry_points=[CallbackQueryHandler(add_season_start, pattern="^admin_add_season$")], states={S_GET_ANIME: [CallbackQueryHandler(get_anime_for_season, pattern="^season_anime_")], S_GET_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_season_number)], S_CONFIRM: [CallbackQueryHandler(save_season, pattern="^save_season$")]}, fallbacks=cancel_fallback + add_content_fallback)
    # 3. Add Episode
    add_episode_conv = ConversationHandler(entry_points=[CallbackQueryHandler(add_episode_start, pattern="^admin_add_episode$")], states={E_GET_ANIME: [CallbackQueryHandler(get_anime_for_episode, pattern="^ep_anime_")], E_GET_SEASON: [CallbackQueryHandler(get_season_for_episode, pattern="^ep_season_")], E_GET_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_episode_number)], E_GET_QUALITY: [CallbackQueryHandler(get_episode_quality, pattern="^ep_quality_")], E_GET_FILE: [MessageHandler(filters.VIDEO | filters.Document.ALL, get_episode_file)]}, fallbacks=cancel_fallback + add_content_fallback)
    # 4. Set Sub QR
    set_sub_qr_conv = ConversationHandler(entry_points=[CallbackQueryHandler(set_sub_qr_start, pattern="^admin_set_sub_qr$")], states={CS_GET_QR: [MessageHandler(filters.PHOTO, set_sub_qr_save)]}, fallbacks=cancel_fallback + sub_settings_fallback)
    # 5. Set Price
    set_price_conv = ConversationHandler(entry_points=[CallbackQueryHandler(set_price_start, pattern="^admin_set_price$")], states={CP_GET_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_price_save)]}, fallbacks=cancel_fallback + sub_settings_fallback)
    # 6. Set Donate QR
    set_donate_qr_conv = ConversationHandler(entry_points=[CallbackQueryHandler(set_donate_qr_start, pattern="^admin_set_donate_qr$")], states={CD_GET_QR: [MessageHandler(filters.PHOTO, set_donate_qr_save)]}, fallbacks=cancel_fallback + donate_settings_fallback)
    # 7. Set Links
    set_links_conv = ConversationHandler(entry_points=[CallbackQueryHandler(set_links_start, pattern="^admin_set_donate_link$|^admin_set_backup_link$|^admin_set_support_link$")], states={CL_GET_BACKUP: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_link), CommandHandler("skip", skip_link)]}, fallbacks=cancel_fallback + links_fallback + donate_settings_fallback)
    # 8. Post Generator
    post_gen_conv = ConversationHandler(entry_points=[CallbackQueryHandler(post_gen_menu, pattern="^admin_post_gen$")], states={PG_MENU: [CallbackQueryHandler(post_gen_select_anime, pattern="^post_gen_season$"), CallbackQueryHandler(post_gen_select_anime, pattern="^post_gen_episode$")], PG_GET_ANIME: [CallbackQueryHandler(post_gen_select_season, pattern="^post_anime_")], PG_GET_SEASON: [CallbackQueryHandler(post_gen_select_episode, pattern="^post_season_")], PG_GET_EPISODE: [CallbackQueryHandler(post_gen_final_episode, pattern="^post_ep_")], PG_GET_CHAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, post_gen_send_to_chat)]}, fallbacks=cancel_fallback + admin_menu_fallback)
    # 9. Delete Anime
    del_anime_conv = ConversationHandler(entry_points=[CallbackQueryHandler(delete_anime_start, pattern="^admin_del_anime$")], states={DA_GET_ANIME: [CallbackQueryHandler(delete_anime_confirm, pattern="^del_anime_")], DA_CONFIRM: [CallbackQueryHandler(delete_anime_do, pattern="^del_anime_confirm_yes$")]}, fallbacks=cancel_fallback + manage_fallback)
    # 10. Delete Season
    del_season_conv = ConversationHandler(entry_points=[CallbackQueryHandler(delete_season_start, pattern="^admin_del_season$")], states={DS_GET_ANIME: [CallbackQueryHandler(delete_season_select, pattern="^del_season_anime_")], DS_GET_SEASON: [CallbackQueryHandler(delete_season_confirm, pattern="^del_season_")], DS_CONFIRM: [CallbackQueryHandler(delete_season_do, pattern="^del_season_confirm_yes$")]}, fallbacks=cancel_fallback + manage_fallback)

    # --- Handlers ko Add Karo ---
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CallbackQueryHandler(admin_command, pattern="^admin_menu$")) # Main "Back" button
    
    # Admin Sub-Menu Handlers
    application.add_handler(CallbackQueryHandler(add_content_menu, pattern="^admin_menu_add_content$"))
    application.add_handler(CallbackQueryHandler(manage_content_menu, pattern="^admin_menu_manage_content$"))
    application.add_handler(CallbackQueryHandler(sub_settings_menu, pattern="^admin_menu_sub_settings$"))
    application.add_handler(CallbackQueryHandler(donate_settings_menu, pattern="^admin_menu_donate_settings$"))
    application.add_handler(CallbackQueryHandler(other_links_menu, pattern="^admin_menu_other_links$"))

    # Conversations
    application.add_handler(add_anime_conv)
    application.add_handler(add_season_conv)
    application.add_handler(add_episode_conv)
    application.add_handler(set_sub_qr_conv)
    application.add_handler(set_price_conv)
    application.add_handler(set_donate_qr_conv)
    application.add_handler(set_links_conv)
    application.add_handler(post_gen_conv)
    application.add_handler(del_anime_conv)
    application.add_handler(del_season_conv)
    
    # Placeholders
    application.add_handler(CallbackQueryHandler(placeholder_button_handler, pattern="^admin_pending_payments$"))
    application.add_handler(CallbackQueryHandler(placeholder_button_handler, pattern="^user_check_sub$"))
    application.add_handler(CallbackQueryHandler(placeholder_button_handler, pattern="^user_subscribe$"))

    application.add_error_handler(error_handler)

    logger.info("Bot polling start kar raha hai...")
    application.run_polling()

if __name__ == "__main__":
    main()
