import logging
import os
import json
import requests
import firebase_admin
from firebase_admin import credentials, db
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Load environment variables
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

# Firebase initialization
cred = credentials.Certificate(json.loads(os.environ['GOOGLE_CREDENTIALS']))
firebase_admin.initialize_app(cred, {
    'databaseURL': os.getenv("FIREBASE_DB_URL")
})

# Telegram logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# ----------------------- Firebase Storage -----------------------

def load_alerts():
    ref = db.reference("/alerts")
    data = ref.get()
    return data if data else {}

def save_alerts(data):
    ref = db.reference("/alerts")
    ref.set(data)

# ----------------------- Crypto Price Fetch -----------------------

def get_price(coin):
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies=usd"
    try:
        res = requests.get(url)
        data = res.json()
        return data[coin]["usd"]
    except:
        return None

# ----------------------- Command Handlers -----------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Welcome! Use /set <coin> <price> to set an alert.\nExample: /set bitcoin 50000")

async def set_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = str(update.effective_chat.id)
        coin = context.args[0].lower()
        target_price = float(context.args[1])

        alerts = load_alerts()
        if coin not in alerts:
            alerts[coin] = []

        alerts[coin].append({"chat_id": chat_id, "target_price": target_price})
        save_alerts(alerts)

        await update.message.reply_text(f"🔔 Alert set for {coin.upper()} at ${target_price}")
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Usage: /set <coin> <price>")

async def list_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    alerts = load_alerts()
    user_alerts = []

    for coin, entries in alerts.items():
        for entry in entries:
            if entry["chat_id"] == chat_id:
                user_alerts.append(f"{coin.upper()} at ${entry['target_price']}")

    if user_alerts:
        await update.message.reply_text("🔔 Your Alerts:\n" + "\n".join(user_alerts))
    else:
        await update.message.reply_text("📭 No active alerts.")

# ----------------------- Alert Checker -----------------------

async def check_alerts(app):
    alerts = load_alerts()
    new_alerts = {}

    for coin, entries in alerts.items():
        price = get_price(coin)
        if price is None:
            continue

        for entry in entries:
            chat_id = entry["chat_id"]
            target = entry["target_price"]

            if (price >= target):
                try:
                    await app.bot.send_message(chat_id=chat_id, text=f"🚀 {coin.upper()} reached ${price} (target: ${target})!")
                except Exception as e:
                    print(f"Error sending message to {chat_id}: {e}")
            else:
                # Keep this alert
                if coin not in new_alerts:
                    new_alerts[coin] = []
                new_alerts[coin].append(entry)

    save_alerts(new_alerts)

# ----------------------- Bot Runner -----------------------

async def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("set", set_alert))
    app.add_handler(CommandHandler("alerts", list_alerts))

    # Run alert checker every 60 seconds
    async def scheduler():
        while True:
            await check_alerts(app)
            await asyncio.sleep(60)

    import asyncio
    asyncio.create_task(scheduler())
    print("✅ Bot is running...")
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
