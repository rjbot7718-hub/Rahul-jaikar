import os
import logging
import threading
import re # <-- NEW: Text check karne ke liye
from flask import Flask
from pymongo import MongoClient
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, PhotoSize, Document, Video
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler, # <-- NEW: Multi-step process ke liye
    MessageHandler,        # <-- NEW: Text/Photo/Video messages ke liye
    filters,               # <-- NEW: Message type check karne ke liye
)

# --- Logging (Errors dekhne ke liye) ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Environment Variables (Yeh Render mein daalna) ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URI = os.environ.get("MONGO_URI")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
PORT = int(os.environ.get("PORT", 8080))
# <-- NEW: Isse hum bot ka username store karenge
BOT_USERNAME = "" # Yeh bot khud fetch kar lega

# --- Error Checks ---
if not BOT_TOKEN:
    logger.critical("!!! BOT_TOKEN environment variable nahi mila !!!")
    exit(1)
if not MONGO_URI:
    logger.critical("!!! MONGO_URI environment variable nahi mila !!!")
    exit(1)
if ADMIN_ID == 0:
    logger.critical("!!! ADMIN_ID environment variable nahi mila ya 0 hai !!!")
    exit(1)

# --- Flask App (Uptime Robot ke liye) ---
app = Flask(__name__)
@app.route('/')
def hello():
    return "Bot is alive and running!"

def run_flask():
    logger.info(f"Flask server ko http://0.0.0.0:{PORT} par start kar raha hoon...")
    app.run(host="0.0.0.0", port=PORT)

# --- Database Setup ---
try:
    client = MongoClient(MONGO_URI)
    db = client.get_database() # URI se default DB lega
    # <-- NEW: Saare collections define kar diye
    users_collection = db['users']
    config_collection = db['config']
    content_collection = db['content'] # Naya content collection
    pending_payments_collection = db['pending_payments'] # Payment ke liye
    
    config_collection.update_one(
        {"config_id": "main_config"},
        {"$setOnInsert": {"admin_id": ADMIN_ID}},
        upsert=True
    )
    logger.info("MongoDB se connect ho gaya!")
except Exception as e:
    logger.critical(f"MongoDB se connect nahi ho paya: {e}")
    exit(1)

# --- Conversation States (Add Content flow ke steps) ---
# Yeh bot ko batata hai ki conversation kaunse step par hai
(ASK_CONTENT_TYPE, ASK_TITLE, ASK_THUMBNAIL, ASK_DESCRIPTION, 
 ASK_SEASON_NUM, ASK_EPISODE_NUM, ASK_QUALITY, ASK_FILE, 
 GENERATE_POST, CHECK_ANOTHER_EP) = range(10) # <-- NEW: 10 steps

# --- Keyboards (Buttons) ---
def get_admin_keyboard() -> InlineKeyboardMarkup:
    # (Pending count ko future mein update karenge)
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
    keyboard = [
        [InlineKeyboardButton("📅 Subscription Expiry", callback_data="user_expiry")],
        [InlineKeyboardButton("💸 Donate Now", callback_data="user_donate")],
        [InlineKeyboardButton("🔗 Join Backup Channel", callback_data="user_backup")],
        [InlineKeyboardButton("💬 Support Inbox", callback_data="user_support")],
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Helper Function (Sharable Post banane ke liye) ---
def get_sharable_post_markup(content_id: str) -> InlineKeyboardMarkup:
    # <-- NEW: Yeh function group post ke 4 button banayega
    # Jab user 'Download' click karega, toh bot ko "start=content_id" ka signal milega
    keyboard = [
        [
            InlineKeyboardButton("📥 Download", url=f"https"f"://t.me/{BOT_USERNAME}?start={content_id}"),
            InlineKeyboardButton("🔗 Join Backup", callback_data=f"user_backup") # Removed content_id, as it's general
        ],
        [
            InlineKeyboardButton("💸 Donate", callback_data=f"user_donate"),
            InlineKeyboardButton("💬 Support Inbox", callback_data=f"user_support")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Bot Command Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start command ka handler"""
    user = update.effective_user
    user_id = user.id
    
    # <-- NEW: 'start' ke saath agar content_id aaya hai (e.g., /start naruto_s1)
    # Yeh 'Download' button se aane wale users ko handle karega
    if context.args:
        content_id = context.args[0]
        logger.info(f"User {user_id} ne content {content_id} ke liye start kiya.")
        
        # User ko DB mein add karo agar nahi hai
        user_data = users_collection.find_one({"user_id": user_id})
        if not user_data:
            users_collection.insert_one({
                "user_id": user_id, "username": user.username, "first_name": user.first_name,
                "is_subscribed": False, "subscription_expiry": None, "last_payment_attempt": None
            })
            logger.info(f"Naya user add hua (deep link se): {user.username} ({user_id})")
        
        # (Step 4/5 mein hum yahan subscription check logic likhenge)
        await update.message.reply_text(f"Welcome, {user.first_name}!\n\nAap '{content_id}' download karna chahte hain.\n(Abhi ke liye WIP. Yeh Step 4/5 mein banega)")
        
        # Store karo ki user kya download karna chahta hai
        context.user_data['wants_to_download'] = content_id
        
        # TODO: Yahan se seedha download ya payment flow shuru karna hai
        
        return

    # Normal /start (bina content_id ke)
    if user_id == ADMIN_ID:
        await update.message.reply_text(
            f"Salaam, Admin Boss! 🫡\nAapka control panel taiyyar hai.",
            reply_markup=get_admin_keyboard()
        )
    else:
        user_data = users_collection.find_one({"user_id": user_id})
        if not user_data:
            users_collection.insert_one({
                "user_id": user_id, "username": user.username, "first_name": user.first_name,
                "is_subscribed": False, "subscription_expiry": None, "last_payment_attempt": None
            })
            logger.info(f"Naya user add hua: {user.username} ({user_id})")

        await update.message.reply_text(
            f"Welcome, {user.first_name}!\n\nMain menu neeche hai:",
            reply_markup=get_user_keyboard()
        )

# --- NEW: "Add Content" Conversation Flow ---

async def admin_add_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 1: 'Add Content' button click karne par. Type poochega."""
    query = update.callback_query
    await query.answer()
    
    # user_data mein info store karna shuru karenge
    context.user_data['content'] = {}
    
    keyboard = [
        [
            InlineKeyboardButton("Anime", callback_data="add_anime"),
            InlineKeyboardButton("Movie", callback_data="add_movie")
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_conv")]
    ]
    await query.edit_message_text(
        "Aap kya add karna chahte hain?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ASK_CONTENT_TYPE

async def ask_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 2: Type select karne par. Title poochega."""
    query = update.callback_query
    await query.answer()
    
    content_type = query.data.split('_')[1] # 'add_anime' se 'anime' nikalega
    context.user_data['content']['type'] = content_type
    
    await query.edit_message_text(f"Nayi {content_type} ka *Title* bhejo:")
    return ASK_THUMBNAIL

async def ask_thumbnail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 3: Title milne par. Thumbnail poochega."""
    title = update.message.text
    # content_id title se banayenge (e.g., "Naruto Shippuden" -> "naruto_shippuden")
    # Replace anything that's not a letter, number, or underscore
    content_id = re.sub(r'[^a-z0-9_]', '', title.lower().replace(' ', '_'))
    
    # Check karo ki yeh title/ID pehle se toh nahi hai
    existing_content = content_collection.find_one({"content_id": content_id})
    if existing_content:
        # Title pehle se hai, thumbnail aur description skip kar denge
        context.user_data['content']['title'] = existing_content['title']
        context.user_data['content']['content_id'] = existing_content['content_id']
        context.user_data['content']['thumbnail_file_id'] = existing_content['thumbnail_file_id']
        context.user_data['content']['description'] = existing_content.get('description', '')
        context.user_data['content']['type'] = existing_content['type'] # Type bhi purana use karo
        
        await update.message.reply_text(f"{title}** pehle se database mein hai.\nNaya season/episode add kar rahe hain...")
        
        if existing_content['type'] == 'Movie':
             await update.message.reply_text("Movie ka episode number bhejo (e.g., 2 agar naya part hai):")
             return ASK_EPISODE_NUM
        else:
            await update.message.reply_text("Ab *Season Number* bhejo (e.g., 2):")
            return ASK_EPISODE_NUM # Seedha Episode pe jao
            
    else:
        # Naya title hai, poora flow chalao
        context.user_data['content']['title'] = title
        context.user_data['content']['content_id'] = content_id
        await update.message.reply_text("Ab iska *Poster/Thumbnail* bhejo:")
        return ASK_DESCRIPTION

async def ask_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 4: Thumbnail milne par. Description poochega."""
    # Sabse best quality ki photo ka file_id nikalenge
    thumbnail_file_id = update.message.photo[-1].file_id
    context.user_data['content']['thumbnail_file_id'] = thumbnail_file_id
    
    await update.message.reply_text("Ab is post ke liye *Description* bhejo (ya /skip):")
    return ASK_SEASON_NUM

async def ask_season_num(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 5: Description milne par. Season number poochega."""
    if update.message.text and update.message.text != '/skip':
        context.user_data['content']['description'] = update.message.text
    else:
        context.user_data['content']['description'] = "" # Khali description
    
    # Agar Movie hai, toh season nahi poochenge
    if context.user_data['content']['type'] == 'Movie':
        context.user_data['content']['season_num'] = "1" # Default "1" rakho movie ke liye
        await update.message.reply_text("Movie ka episode number bhejo (e.g., 1 agar ek hi part hai):")
        return ASK_EPISODE_NUM # Seedha Episode pe jao
        
    await update.message.reply_text("Ab *Season Number* bhejo (e.g., 1):")
    return ASK_EPISODE_NUM # Yeh actual mein ASK_EPISODE_NUM state pe jaana chahiye

async def ask_episode_num(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 6: Season number milne par. Episode number poochega."""
    # Agar Anime hai toh Season num save karo
    if context.user_data['content']['type'] == 'Anime':
        # Yeh check karo ki season num pehle step se aaya ya abhi
        if 'season_num' not in context.user_data['content']:
             context.user_data['content']['season_num'] = update.message.text
        
    await update.message.reply_text("Ab *Episode Number* bhejo (e.g., 1):")
    return ASK_QUALITY

async def ask_quality(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 7: Episode number milne par. Quality poochega."""
    context.user_data['content']['episode_num'] = update.message.text
    # Nayi quality add karne se pehle, purani clear karo
    context.user_data['content']['qualities'] = {}
    
    keyboard = [
        [
            InlineKeyboardButton("480p", callback_data="qual_480p"),
            InlineKeyboardButton("720p", callback_data="qual_720p"),
        ],
        [
            InlineKeyboardButton("1080p", callback_data="qual_1080p"),
            InlineKeyboardButton("4K", callback_data="qual_4k"),
        ],
        [InlineKeyboardButton("DONE (Quality Add Ho Gayi)", callback_data="qual_done")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_conv")]
    ]
    await update.message.reply_text("Kis *Quality* ki file add karni hai?\n(Aap ek se zyada add kar sakte ho)", reply_markup=InlineKeyboardMarkup(keyboard))
    return ASK_FILE

async def ask_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 8: Quality select karne par. File forward karne ko bolega."""
    query = update.callback_query
    await query.answer()
    
    quality = query.data.split('_')[1] # 'qual_480p' se '480p'
    context.user_data['content']['current_quality'] = quality # Store karo kaunsi quality maangi hai
    
    await query.edit_message_text(f"Ab {quality} wali *Video File* forward karo.")
    return GENERATE_POST # Agla step file receive karna hai

async def receive_file_and_ask_more_quality(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 9: File milne par. Save karega aur poochega 'aur quality?'"""
    
    file_id = None
    if update.message.video:
        file_id = update.message.video.file_id
    elif update.message.document:
        file_id = update.message.document.file_id
    
    if not file_id:
        await update.message.reply_text("Yeh file type support nahi karta. Please video ya file forward karo.")
        return GENERATE_POST # Wapas isi state mein raho file ka wait karte hue

    # Jo quality maangi thi (e.g., '480p'), uske against file_id save karo
    quality = context.user_data['content']['current_quality']
    context.user_data['content']['qualities'][quality] = file_id
    
    await update.message.reply_text(f"✅ {quality} file saved!")

    # Wapas quality selection menu dikhao
    keyboard = [
        [
            InlineKeyboardButton("480p", callback_data="qual_480p"),
            InlineKeyboardButton("720p", callback_data="qual_720p"),
        ],
        [
            InlineKeyboardButton("1080p", callback_data="qual_1080p"),
            InlineKeyboardButton("4K", callback_data="qual_4k"),
        ],
        [InlineKeyboardButton("✅ DONE (Agla Episode)", callback_data="qual_done")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_conv")]
    ]
    await update.message.reply_text(
        "Isi episode ki aur quality add karni hai? Ya 'DONE' pe click karke aage badho.", 
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ASK_FILE # Wapas quality selection state pe jao


async def save_to_db_and_generate_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 10: Jab user 'DONE' (qual_done) click karega. DB mein save karega."""
    query = update.callback_query
    await query.answer()

    data = context.user_data['content']
    
    # --- Data ko MongoDB mein save karne ka logic ---
    content_id = data['content_id']
    
    # Keys ko safe banayenge (dot '.' allowed nahi hai keys mein)
    season_key = f"s_{data['season_num']}"
    episode_key = f"ep_{data['episode_num']}"
    
    # Nested path for update
    # e.g., seasons.s_1.episodes.ep_1
    update_path_prefix = f"seasons.{season_key}.episodes.{episode_key}"

    # upsert=True naya content bana dega agar nahi hai
    # $set se data add/update karega
    content_collection.update_one(
        {"content_id": content_id},
        {
            "$set": {
                "title": data['title'],
                "type": data['type'],
                "thumbnail_file_id": data['thumbnail_file_id'],
                "description": data.get('description', ''),
                f"seasons.{season_key}.season_title": f"Season {data['season_num']}", # Helper
                f"{update_path_prefix}.episode_title": f"Episode {data['episode_num']}", # Helper
                f"{update_path_prefix}.qualities": data['qualities'] # Poora quality object
            },
            "$setOnInsert": { "content_id": content_id } # Sirf pehli baar set hoga
        },
        upsert=True
    )
    
    logger.info(f"Admin ne naya content add kiya: {content_id} S{data['season_num']} E{data['episode_num']}")
    await query.edit_message_text("✅ Episode data saved successfully!")

    # --- Sharable Post Generate Karo ---
    caption = f"{data['title']}\n\n"
    if data['description']:
        caption += f"{data['description']}\n\n"
    
    if data['type'] == 'Anime':
        caption += f"✨ SEASON {data['season_num']} - EPISODE {data['episode_num']} ADDED ✨"
    else:
        caption += f"✨ MOVIE/PART {data['episode_num']} ADDED ✨"

    # Bot se post ka thumbnail+caption+button maango
    await context.bot.send_photo(
        chat_id=update.effective_chat.id,
        photo=data['thumbnail_file_id'],
        caption=caption,
        reply_markup=get_sharable_post_markup(content_id)
    )
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Yeh raha aapka sharable post. Isse seedha group mein forward kar do."
    )

    # --- NEW: Poocho ki aur episode add karna hai? ---
    keyboard = [
        [
            InlineKeyboardButton("✅ Haan (Isi Season ka Agla Episode)", callback_data="add_next_ep"),
            InlineKeyboardButton("🆕 Naya Season", callback_data="add_new_season"),
        ],
        [
            InlineKeyboardButton("🖼 Poore Season Ka Post", callback_data="generate_season_post"),
        ],
        [InlineKeyboardButton("❌ Nahi (Finish)", callback_data="cancel_conv")]
    ]
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Ab kya karna hai?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    # qualities aur episode num clear karo, lekin season/title rehne do
    context.user_data['content'].pop('episode_num', None)
    context.user_data['content'].pop('qualities', None)
    context.user_data['content'].pop('current_quality', None)

    return CHECK_ANOTHER_EP # Agle step ka wait karo

async def check_another_ep_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 11: User ke 'Add Next Ep' ya 'Finish' click ko handle karega."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "add_next_ep":
        # Isi season ka agla episode
        await query.edit_message_text("Ab agla *Episode Number* bhejo:")
        return ASK_QUALITY # Wapas episode num -> quality flow pe jao
    
    elif data == "add_new_season":
        # Naya season
        # season num clear karo taaki naya maang sake
        context.user_data['content'].pop('season_num', None) 
        await query.edit_message_text("Ab naya *Season Number* bhejo:")
        return ASK_EPISODE_NUM # Wapas season num -> episode num flow pe jao

    elif data == "generate_season_post":
        # --- Demo 2: Full Season Post ---
        c_data = context.user_data['content']
        
        # Check karo ki season num hai ya nahi (agar movie hui toh)
        if c_data['type'] == 'Anime':
            caption = f"{c_data['title']}\n\n"
            if c_data.get('description'):
                caption += f"{c_data['description']}\n\n"
            
            caption += f"🔥 SEASON {c_data['season_num']} COMPLETE 🔥"

            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=c_data['thumbnail_file_id'],
                caption=caption,
                reply_markup=get_sharable_post_markup(c_data['content_id'])
            )
            await query.edit_message_text("Poore season ka post generate ho gaya! Conversation finished.")
        else:
            await query.answer("Yeh option sirf Anime ke liye hai.", show_alert=True)
            # Finish mat karo, wapas options do
            return CHECK_ANOTHER_EP

        context.user_data.clear()
        return ConversationHandler.END

    elif data == "cancel_conv":
        # Finish
        await query.edit_message_text("✅ Done! Conversation finished.")
        context.user_data.clear()
        return ConversationHandler.END

    return CHECK_ANOTHER_EP # Agar koi aur button daba


async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Conversation ko beech mein cancel karne ke liye."""
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("❌ Action Cancelled.")
    else:
        await update.message.reply_text("❌ Action Cancelled.")
        
    context.user_data.clear()
    return ConversationHandler.END

# --- Normal Button Handler (Jo Conversation ka part nahi hain) ---

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Saare Inline Buttons ka handler (Jo 'Add Content' mein nahi hain)"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    # Admin check
    if user_id != ADMIN_ID and data.startswith("admin_"):
        await query.answer("Yeh sirf admin ke liye hai!", show_alert=True)
        return

    # ---- ADMIN BUTTONS (WIP) ----
    if data == "admin_manage_content":
        await query.edit_message_text(text="Admin: Aap 'Manage Content' section mein hain. (WIP)")
    elif data == "admin_sub_settings":
        await query.edit_message_text(text="Admin: Aap 'Subscription Settings' section mein hain. (WIP - Step 3 mein banega)")
    elif data == "admin_donation_settings":
        await query.edit_message_text(text="Admin: Aap 'Donation Settings' section mein hain. (WIP - Step 3 mein banega)")
    elif data == "admin_other_links":
        await query.edit_message_text(text="Admin: Aap 'Other Links' section mein hain. (WIP - Step 3 mein banega)")
    elif data == "admin_pending_payments":
        await query.edit_message_text(text="Admin: Aap 'Pending Payments' section mein hain. (WIP - Step 4 mein banega)")

    # ---- USER BUTTONS (WIP) ----
    elif data == "user_expiry":
        await query.answer("Checking... (WIP)", show_alert=False)
        await query.edit_message_text(text="Aapki subscription details yahan dikhengi. (WIP - Step 6)")
    elif data == "user_donate":
        await query.answer("Loading... (WIP)", show_alert=False)
        await query.edit_message_text(text="Donation ki info yahan dikhegi. (WIP - Step 3/6)")
    elif data == "user_backup":
        await query.answer("Fetching link... (WIP)", show_alert=False)
        await query.edit_message_text(text="Backup channel ka link yahan dikhega. (WIP - Step 3/6)")
    elif data == "user_support":
        await query.edit_message_text(text="Aap 'Support' section mein hain. (WIP)\nAapka agla message admin ko bhej diya jayega. (WIP - Step 6)")
    
    # Agar button ka command samajh na aaye, menu reset kar do
    else:
        # Check karo ki user admin hai ya normal
        if user_id == ADMIN_ID:
             await query.edit_message_text(
                text=f"Salaam, Admin Boss! 🫡\nAapka control panel taiyyar hai.",
                reply_markup=get_admin_keyboard()
            )
        else:
            await query.edit_message_text(
                text=f"Welcome, {query.from_user.first_name}!\n\nMain menu neeche hai:",
                reply_markup=get_user_keyboard()
            )


# --- Bot ko Start karne ka Function ---
def main() -> None:
    """Bot ko start karta hai."""
    global BOT_USERNAME # Global variable ko update karenge
    
    logger.info("Flask server ko background mein start kar raha hoon...")
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    
    logger.info("Telegram Bot ko start kar raha hoon...")
    application = Application.builder().token(BOT_TOKEN).build()
    
    # <-- NEW: Bot ka username fetch karo (Download link ke liye zaroori)
    try:
        BOT_USERNAME = application.bot.get_me().username
        if not BOT_USERNAME:
            raise Exception("Username was empty")
        logger.info(f"Bot ka username hai: @{BOT_USERNAME}")
    except Exception as e:
        logger.critical(f"Bot ka username fetch nahi kar paya! Error: {e}")
        logger.critical("CHECK KI BOT TOKEN SAHI HAI YA NAHI.")
        exit(1)
        
    # --- NEW: Conversation Handler (Add Content ke liye) ---
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_content, pattern="^admin_add_content$")],
        states={
            ASK_CONTENT_TYPE: [CallbackQueryHandler(ask_title, pattern="^(add_anime|add_movie)$")],
            ASK_THUMBNAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_thumbnail)],
            ASK_DESCRIPTION: [MessageHandler(filters.PHOTO, ask_description)],
            ASK_SEASON_NUM: [MessageHandler(filters.TEXT | filters.COMMAND, ask_season_num)], # /skip handle karega
            ASK_EPISODE_NUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_episode_num)],
            ASK_QUALITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_quality)],
            ASK_FILE: [
                CallbackQueryHandler(ask_file, pattern="^qual_(480p|720p|1080p|4k)$"),
                CallbackQueryHandler(save_to_db_and_generate_post, pattern="^qual_done$")
            ],
            GENERATE_POST: [MessageHandler(filters.VIDEO | filters.DOCUMENT, receive_file_and_ask_more_quality)],
            CHECK_ANOTHER_EP: [CallbackQueryHandler(check_another_ep_handler, pattern="^(add_next_ep|add_new_season|generate_season_post|cancel_conv)$")]
        },
        fallbacks=[
            CallbackQueryHandler(cancel_conv, pattern="^cancel_conv$"),
            CommandHandler("cancel", cancel_conv)
        ],
        per_message=False # Ek hi user se saari conversation
    )
    
    application.add_handler(conv_handler) # <-- NEW
    
    # Baaki normal handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(button_handler)) # Baaki buttons ke liye

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
