import os
import logging
from threading import Thread
from flask import Flask
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

# Logging Setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- ENVIRONMENT VARIABLES (from Render) ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# --- FLASK SERVER FOR RENDER WEB SERVICE ---
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Bot is running online 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

# --- BOT STATES ---
(
    SELECT_STORE,
    SELECT_PRODUCT,
    UPLOAD_PAYMENT,
    GET_PHONE,
    GET_LOCATION,
    CUSTOM_PICKUP,
    CUSTOM_ITEMS,
    CUSTOM_PHONE,
    CUSTOM_LOCATION,
    ADMIN_ADD_STORE_NAME,
    ADMIN_ADD_PRODUCT_STORE,
    ADMIN_ADD_PRODUCT_NAME,
    ADMIN_ADD_PRODUCT_PRICE,
) = range(13)

# Data Store
stores = {}

# Helper to clear previous messages
async def cleanup_messages(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    msg_ids = context.user_data.get('to_delete', [])
    for msg_id in msg_ids:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass
    context.user_data['to_delete'] = []

def track_msg(context: ContextTypes.DEFAULT_TYPE, message_id: int):
    if 'to_delete' not in context.user_data:
        context.user_data['to_delete'] = []
    context.user_data['to_delete'].append(message_id)


# --- START HANDLER ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_keyboard = [
        ["🛍 ከአጋር ሱቆች ለማዘዝ", "📦 ልዩ ትዕዛዝ (ከማንኛውም ቦታ)"],
        ["📞 ድጋፍ / አድራሻ"]
    ]
    if update.message.from_user.id == ADMIN_ID:
        reply_keyboard.append(["⚙️ አድሚን ፓነል"])

    markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    msg = await update.message.reply_text(
        "ሰላም! እንኳን ወደ እቃ ማድረሻ ቦት በደህና መጡ።\nእባክዎን ከታች ካሉት አማራጮች አንዱን ይምረጡ፡",
        reply_markup=markup
    )
    track_msg(context, msg.message_id)

# --- PARTNER STORES ORDERING ---
async def partner_stores(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not stores:
        msg = await update.message.reply_text("በአሁኑ ሰዓት የተመዘገቡ አጋር ሱቆች የሉም። እባክዎን በኋላ ይሞክሩ ወይም ልዩ ትዕዛዝ ይጠቀሙ።")
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton(store, callback_data=f"store_{store}")] for store in stores.keys()]
    msg = await update.message.reply_text("እባክዎን ዕቃ መግዛት የሚፈልጉበትን ሱቅ ይምረጡ፡", reply_markup=InlineKeyboardMarkup(keyboard))
    track_msg(context, msg.message_id)
    return SELECT_STORE

async def store_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    store_name = query.data.replace("store_", "")
    context.user_data['selected_store'] = store_name

    products = stores.get(store_name, [])
    if not products:
        await query.edit_message_text(f"በ {store_name} ውስጥ ምንም የተመዘገበ ዕቃ የለም።")
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton(f"{p['name']} - {p['price']} ብር", callback_data=f"prod_{i}")] for i, p in enumerate(products)]
    msg = await query.edit_message_text(f"የ {store_name} ዕቃዎች ዝርዝር፦\nለመግዛት የሚፈልጉትን ዕቃ ይምረጡ፡", reply_markup=InlineKeyboardMarkup(keyboard))
    track_msg(context, msg.message_id)
    return SELECT_PRODUCT

async def product_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    prod_idx = int(query.data.replace("prod_", ""))
    store_name = context.user_data['selected_store']
    product = stores[store_name][prod_idx]
    context.user_data['selected_product'] = product

    msg = await query.edit_message_text(
        f"የመረጡት ዕቃ፦ **{product['name']}**\nዋጋ፦ **{product['price']} ብር**\n\n"
        f"💳 እባክዎን የዕቃውን ክፍያ ለሱቁ ገቢ በማድረግ የደረሰኙን (Screenshot) ምስል እዚህ ይላኩ።\n"
        f"*(ማስታወሻ፦ የማድረሻ ክፍያውን ዕቃው ሲደርስዎት በካሽ ይከፍላሉ)*",
        parse_mode="Markdown"
    )
    track_msg(context, msg.message_id)
    return UPLOAD_PAYMENT

async def payment_uploaded(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        msg = await update.message.reply_text("እባክዎን የክፍያውን ደረሰኝ ምስል (Screenshot) ይላኩ።")
        track_msg(context, msg.message_id)
        return UPLOAD_PAYMENT

    context.user_data['payment_photo'] = update.message.photo[-1].file_id
    
    btn = [[KeyboardButton("📱 ስልክ ቁጥር ለማጋራት ይጫኑ", request_contact=True)]]
    msg = await update.message.reply_text(
        "የክፍያ ደረሰኝዎን ተቀብለናል! 🙏\n\nለማድረስ እንድንደውልልዎት እባክዎን ስልክ ቁጥርዎን ይላኩ፡",
        reply_markup=ReplyKeyboardMarkup(btn, resize_keyboard=True, one_time_keyboard=True)
    )
    track_msg(context, msg.message_id)
    return GET_PHONE

async def phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.contact:
        context.user_data['phone'] = update.message.contact.phone_number
    else:
        context.user_data['phone'] = update.message.text

    btn = [[KeyboardButton("📍 ያለሁበትን ቦታ (Location) ላክ", request_location=True)]]
    msg = await update.message.reply_text(
        "በጣም ጥሩ! አሁን ደግሞ ዕቃው የሚደርስበትን ቦታ (Location) ይላኩልን፡",
        reply_markup=ReplyKeyboardMarkup(btn, resize_keyboard=True, one_time_keyboard=True)
    )
    track_msg(context, msg.message_id)
    return GET_LOCATION

async def location_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.location:
        msg = await update.message.reply_text("እባክዎን የጂፒኤስ ሎኬሽን (Location) ይላኩ።")
        track_msg(context, msg.message_id)
        return GET_LOCATION

    user = update.message.from_user
    lat = update.message.location.latitude
    lon = update.message.location.longitude
    
    store_name = context.user_data['selected_store']
    product = context.user_data['selected_product']
    photo_id = context.user_data['payment_photo']
    phone = context.user_data['phone']

    summary_text = (
        f"🚨 **አዲስ ትዕዛዝ ደርሷል (ከአጋር ሱቅ)!**\n\n"
        f"👤 ደንበኛ: {user.full_name} (@{user.username})\n"
        f"📞 ስልክ: `{phone}`\n"
        f"🏬 ሱቅ: {store_name}\n"
        f"📦 ዕቃ: {product['name']}\n"
        f"💰 የዕቃ ዋጋ: {product['price']} ብር\n"
        f"💵 የማድረሻ ክፍያ: በካሽ የሚቀበሉት"
    )
    
    await cleanup_messages(context, update.effective_chat.id)

    await context.bot.send_photo(chat_id=ADMIN_ID, photo=photo_id, caption=summary_text, parse_mode="Markdown")
    await context.bot.send_location(chat_id=ADMIN_ID, latitude=lat, longitude=lon)

    await update.message.reply_text("ትዕዛዝዎ በተሳካ ሁኔታ ተልኳል! በቅርብ ጊዜ አራሽ ያነጋግርዎታል:: እናመሰግናለን!", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- CUSTOM ORDER FLOW ---
async def custom_order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("ዕቃው የሚነሳበትን/ሚገዛበትን ቦታ አድራሻ በጽሁፍ ይጻፉልን (ምሳሌ፦ ፒያሳ፣ ከበደ ሱቅ)፦")
    track_msg(context, msg.message_id)
    return CUSTOM_PICKUP

async def custom_pickup_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['custom_pickup'] = update.message.text
    msg = await update.message.reply_text("የሚፈልጉትን ዕቃ ዝርዝር በጽሁፍ ይጻፉልን፦")
    track_msg(context, msg.message_id)
    return CUSTOM_ITEMS

async def custom_items_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['custom_items'] = update.message.text
    btn = [[KeyboardButton("📱 ስልክ ቁጥር ለማጋራት ይጫኑ", request_contact=True)]]
    msg = await update.message.reply_text(
        "እባክዎን ስልክ ቁጥርዎን ይላኩልን፦",
        reply_markup=ReplyKeyboardMarkup(btn, resize_keyboard=True, one_time_keyboard=True)
    )
    track_msg(context, msg.message_id)
    return CUSTOM_PHONE

async def custom_phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.contact:
        context.user_data['phone'] = update.message.contact.phone_number
    else:
        context.user_data['phone'] = update.message.text

    btn = [[KeyboardButton("📍 ያለሁበትን ቦታ (Location) ላክ", request_location=True)]]
    msg = await update.message.reply_text(
        "አሁን ዕቃው የሚደርስበትን ቦታ (Location) በቴሌግራም ይላኩልን፦",
        reply_markup=ReplyKeyboardMarkup(btn, resize_keyboard=True, one_time_keyboard=True)
    )
    track_msg(context, msg.message_id)
    return CUSTOM_LOCATION

async def custom_location_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.location:
        msg = await update.message.reply_text("እባክዎን የጂፒኤስ ሎኬሽን (Location) ይላኩ።")
        track_msg(context, msg.message_id)
        return CUSTOM_LOCATION

    user = update.message.from_user
    lat = update.message.location.latitude
    lon = update.message.location.longitude
    pickup = context.user_data['custom_pickup']
    items = context.user_data['custom_items']
    phone = context.user_data['phone']

    summary_text = (
        f"🚨 **አዲስ የልዩ ትዕዛዝ ደርሷል!**\n\n"
        f"👤 ደንበኛ: {user.full_name} (@{user.username})\n"
        f"📞 ስልክ: `{phone}`\n"
        f"📍 የመነሻ ቦታ: {pickup}\n"
        f"📝 የዕቃ ዝርዝር: {items}\n"
        f"💵 ክፍያ: የዕቃውን እና የማድረሻ ክፍያውን በአካል በካሽ የሚቀበሉት"
    )

    await cleanup_messages(context, update.effective_chat.id)

    await context.bot.send_message(chat_id=ADMIN_ID, text=summary_text, parse_mode="Markdown")
    await context.bot.send_location(chat_id=ADMIN_ID, latitude=lat, longitude=lon)

    await update.message.reply_text("የልዩ ትዕዛዝዎ ተመዝግቧል! በቅርቡ አራሽ ደውሎ ያነጋግርዎታል። እናመሰግናለን!", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- ADMIN PANEL ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    keyboard = [
        [InlineKeyboardButton("➕ አዲስ ሱቅ መጨመር", callback_data="admin_add_store")],
        [InlineKeyboardButton("📦 አዲስ ዕቃ መጨመር", callback_data="admin_add_product")]
    ]
    await update.message.reply_text("የአድሚን መቆጣጠሪያ ፓነል፦", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_add_store_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("እባክዎን የአዲሱን ሱቅ ስም ይጻፉ፦")
    return ADMIN_ADD_STORE_NAME

async def admin_store_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store_name = update.message.text
    if store_name not in stores:
        stores[store_name] = []
        await update.message.reply_text(f"ሱቅ '{store_name}' በተሳካ ሁኔታ ተመዝግቧል!")
    else:
        await update.message.reply_text("ይህ ሱቅ ቀድሞ ተመዝግቧል።")
    return ConversationHandler.END

async def admin_add_product_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not stores:
        await query.edit_message_text("እባክዎን በመጀመሪያ ሱቅ ይመዝግቡ።")
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton(store, callback_data=f"addprodstore_{store}")] for store in stores.keys()]
    await query.edit_message_text("ዕቃው የሚጨመረበትን ሱቅ ይምረጡ፦", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_ADD_PRODUCT_STORE

async def admin_add_product_store_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    store_name = query.data.replace("addprodstore_", "")
    context.user_data['target_store'] = store_name
    await query.edit_message_text(f"ለ '{store_name}' የሚጨመረውን የዕቃ ስም ይጻፉ፦")
    return ADMIN_ADD_PRODUCT_NAME

async def admin_product_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_prod_name'] = update.message.text
    await update.message.reply_text("የዕቃውን ዋጋ በብር ብቻ ይጻፉ (ምሳሌ፦ 150)፦")
    return ADMIN_ADD_PRODUCT_PRICE

async def admin_product_price_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = float(update.message.text)
        store_name = context.user_data['target_store']
        prod_name = context.user_data['new_prod_name']
        stores[store_name].append({"name": prod_name, "price": price})
        await update.message.reply_text(f"ዕቃው '{prod_name}' በ {price} ብር ለ '{store_name}' ተጨምሯል!")
    except ValueError:
        await update.message.reply_text("እባክዎን ትክክለኛ ቁጥር ብቻ ያስገቡ።")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ተሰርዟል።")
    return ConversationHandler.END

# --- MAIN ENGINE ---
def main():
    if not TOKEN:
        raise ValueError("BOT_TOKEN environment variable is not set!")

    # Start Flask Server for Render
    keep_alive()

    app = ApplicationBuilder().token(TOKEN).build()

    partner_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🛍 ከአጋር ሱቆች ለማዘዝ$"), partner_stores)],
        states={
            SELECT_STORE: [CallbackQueryHandler(store_selected, pattern="^store_")],
            SELECT_PRODUCT: [CallbackQueryHandler(product_selected, pattern="^prod_")],
            UPLOAD_PAYMENT: [MessageHandler(filters.PHOTO, payment_uploaded)],
            GET_PHONE: [MessageHandler(filters.CONTACT | filters.TEXT, phone_received)],
            GET_LOCATION: [MessageHandler(filters.LOCATION, location_received)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    custom_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📦 ልዩ ትዕዛዝ \(ከማንኛውም ቦታ\)$"), custom_order_start)],
        states={
            CUSTOM_PICKUP: [MessageHandler(filters.TEXT & ~filters.COMMAND, custom_pickup_received)],
            CUSTOM_ITEMS: [MessageHandler(filters.TEXT & ~filters.COMMAND, custom_items_received)],
            CUSTOM_PHONE: [MessageHandler(filters.CONTACT | filters.TEXT, custom_phone_received)],
            CUSTOM_LOCATION: [MessageHandler(filters.LOCATION, custom_location_received)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    admin_store_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_store_start, pattern="^admin_add_store$")],
        states={ADMIN_ADD_STORE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_store_name_received)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    admin_prod_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_product_start, pattern="^admin_add_product$")],
        states={
            ADMIN_ADD_PRODUCT_STORE: [CallbackQueryHandler(admin_add_product_store_selected, pattern="^addprodstore_")],
            ADMIN_ADD_PRODUCT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_product_name_received)],
            ADMIN_ADD_PRODUCT_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_product_price_received)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^⚙️ አድሚን ፓነል$"), admin_panel))
    app.add_handler(partner_conv)
    app.add_handler(custom_conv)
    app.add_handler(admin_store_conv)
    app.add_handler(admin_prod_conv)

    print("Bot is starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
