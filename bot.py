import os
import requests
import nest_asyncio
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
import json

# Load .env variables
load_dotenv()

# Telegram and Firebase setup
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PING_URL = os.getenv("PING_URL")

if not TELEGRAM_BOT_TOKEN:
    raise Exception("Missing TELEGRAM_BOT_TOKEN environment variable")

# Firebase setup
cred_json = os.getenv("FIREBASE_CREDENTIALS")
if not cred_json:
    raise Exception("Missing FIREBASE_CREDENTIALS environment variable")

# Parse JSON string and initialize Firebase
cred_dict = json.loads(cred_json)
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)

# Initialize Firestore
db = firestore.client()

ADMINS = ["5817239686"]  # Replace with your Telegram user ID(s) as string(s)

nest_asyncio.apply()

# Firestore collections
ALERTS_COLLECTION = "alerts"
USERS_COLLECTION = "users"

# Ping server
class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Pong")

def run_ping_server():
    def server_thread():
        server = HTTPServer(('0.0.0.0', 10001), PingHandler)
        server.serve_forever()
    Thread(target=server_thread, daemon=True).start()

# Self-ping every 5 minutes
async def ping_self():
    while True:
        try:
            requests.get(PING_URL)
        except Exception as e:
            print("Ping failed:", e)
        await asyncio.sleep(300)

# Telegram commands ...

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_doc = db.collection(USERS_COLLECTION).document(user_id).get()

    if user_doc.exists:
        if user_doc.to_dict().get("approved"):
            await update.message.reply_text("✅ You’re approved! Use /alert <coin> to set alerts.")
        else:
            await update.message.reply_text("⏳ You’re waiting for approval. Please wait.")
    else:
        db.collection(USERS_COLLECTION).document(user_id).set({
            "approved": False,
            "name": update.effective_user.full_name,
        })
        await update.message.reply_text("📩 Request received. Wait for admin approval.")

async def alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_doc = db.collection(USERS_COLLECTION).document(user_id).get()

    if not user_doc.exists or not user_doc.to_dict().get("approved"):
        await update.message.reply_text("❌ You are not approved yet.")
        return

    if len(context.args) != 1:
        await update.message.reply_text("❌ Usage: /alert <coin>")
        return

    coin = context.args[0].lower()
    db.collection(ALERTS_COLLECTION).document(user_id).set({
        "coin": coin,
        "timestamp": firestore.SERVER_TIMESTAMP
    })
    await update.message.reply_text(f"✅ Alert set for {coin.upper()}!")

async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = str(update.effective_user.id)
    if admin_id not in ADMINS:
        await update.message.reply_text("❌ You’re not an admin.")
        return

    if len(context.args) != 1:
        await update.message.reply_text("❌ Usage: /approve <user_id>")
        return

    user_id = context.args[0]
    db.collection(USERS_COLLECTION).document(user_id).update({"approved": True})
    await update.message.reply_text(f"✅ User {user_id} approved.")

async def list_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = str(update.effective_user.id)
    if admin_id not in ADMINS:
        await update.message.reply_text("❌ You’re not an admin.")
        return

    docs = db.collection(USERS_COLLECTION).where("approved", "==", False).stream()
    pending = [f"{doc.id} - {doc.to_dict().get('name')}" for doc in docs]

    if pending:
        await update.message.reply_text("Pending Requests:\n" + "\n".join(pending))
    else:
        await update.message.reply_text("✅ No pending requests.")

# Delete existing webhook to avoid conflicts
def delete_webhook():
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteWebhook"
    try:
        res = requests.get(url)
        print("Webhook delete response:", res.json())
    except Exception as e:
        print("Failed to delete webhook:", e)

# Main bot loop
async def main():
    # Delete any existing webhook before starting polling
    delete_webhook()

    run_ping_server()

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("alert", alert))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("list_requests", list_requests))

    # Start self-ping task
    asyncio.create_task(ping_self())

    # Start polling
    await app.run_polling()

if __name__ == "__main__":
    # If you are running in an environment with an existing event loop (like Jupyter),
    # you might want to use: asyncio.run(main())
    # or, in those environments, use nest_asyncio and run main directly:
    asyncio.run(main())
