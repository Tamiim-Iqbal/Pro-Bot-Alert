import json
import os
import requests
import asyncio
import nest_asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# File to store alerts and access
ALERT_FILE = 'prices.json'
ACCESS_FILE = 'access.json'

def load_alerts():
    if os.path.exists(ALERT_FILE):
        with open(ALERT_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_alerts(data):
    with open(ALERT_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def load_access():
    if os.path.exists(ACCESS_FILE):
        with open(ACCESS_FILE, 'r') as f:
            return json.load(f)
    return {
        "owner": os.getenv("OWNER_ID", "5817239686"),  # Default owner ID
        "users": {},
        "requests": [],
        "coin_requests": []
    }

def save_access(data):
    with open(ACCESS_FILE, 'w') as f:
        json.dump(data, f, indent=2)

# Your Telegram bot token and ping URL
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PING_URL = os.getenv("PING_URL")  # Example: "https://your-app-url.onrailway.app"

# Symbol to CoinGecko ID map
SYMBOL_MAP = {
    "btc": "bitcoin",
    "eth": "ethereum",
    "bnb": "binancecoin",
    "sol": "solana",
    "ada": "cardano",
    "doge": "dogecoin",
    "xrp": "ripple",
    "meme": "meme",
    "moxie": "moxie",
    "degen": "degen-base",
}

# ========== NEW FEATURES ==========

async def request_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    access_data = load_access()
    
    # Check if already has access
    if user_id in access_data["users"]:
        return await update.message.reply_text("✅ You already have access to the bot.")
    
    # Check if already requested
    for req in access_data["requests"]:
        if req["user_id"] == user_id:
            return await update.message.reply_text("⏳ Your access request is pending approval.")
    
    # Add new request
    user = update.effective_user
    access_data["requests"].append({
        "user_id": user_id,
        "username": user.username or user.first_name,
        "timestamp": str(update.message.date)
    })
    save_access(access_data)
    
    # Notify owner
    owner_id = access_data["owner"]
    await context.bot.send_message(
        chat_id=owner_id,
        text=f"🆕 Access Request:\n"
             f"User: {user.username or user.first_name} (@{user.username})\n"
             f"ID: {user_id}\n"
             f"Use /approve {user_id} or /decline {user_id}"
    )
    
    await update.message.reply_text("✅ Your access request has been sent to the admin.")

async def approve_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    access_data = load_access()
    
    # Check if command user is owner
    if user_id != access_data["owner"]:
        return await update.message.reply_text("❌ Only owner can approve users.")
    
    if not context.args:
        return await update.message.reply_text("❗ Usage: /approve USER_ID")
    
    target_id = context.args[0]
    request_idx = None
    
    # Find and process request
    for i, req in enumerate(access_data["requests"]):
        if req["user_id"] == target_id:
            request_idx = i
            break
    
    if request_idx is None:
        return await update.message.reply_text("❗ No pending request found for this user.")
    
    # Add user with default access (only BTC)
    access_data["users"][target_id] = {
        "coins": ["btc"],
        "username": access_data["requests"][request_idx]["username"]
    }
    access_data["requests"].pop(request_idx)
    save_access(access_data)
    
    # Notify owner and user
    await update.message.reply_text(f"✅ Approved access for user {target_id}")
    await context.bot.send_message(
        chat_id=int(target_id),
        text="🎉 Your access has been approved!\n"
             "You can now set alerts for BTC.\n"
             "Use /start to begin."
    )

async def decline_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    access_data = load_access()
    
    # Check if command user is owner
    if user_id != access_data["owner"]:
        return await update.message.reply_text("❌ Only owner can decline users.")
    
    if not context.args:
        return await update.message.reply_text("❗ Usage: /decline USER_ID")
    
    target_id = context.args[0]
    request_idx = None
    
    # Find and process request
    for i, req in enumerate(access_data["requests"]):
        if req["user_id"] == target_id:
            request_idx = i
            break
    
    if request_idx is None:
        return await update.message.reply_text("❗ No pending request found for this user.")
    
    access_data["requests"].pop(request_idx)
    save_access(access_data)
    
    # Notify owner and user
    await update.message.reply_text(f"❌ Declined access for user {target_id}")
    await context.bot.send_message(
        chat_id=int(target_id),
        text="⚠️ Your access request has been declined by the admin."
    )

async def request_coin_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    access_data = load_access()
    
    # Check if user has basic access
    if user_id not in access_data["users"]:
        return await update.message.reply_text("❌ You don't have access to the bot. Use /request to request access.")
    
    if not context.args:
        return await update.message.reply_text("❗ Usage: /request_coin COIN")
    
    coin = context.args[0].lower()
    if coin not in SYMBOL_MAP:
        return await update.message.reply_text("❗ Invalid coin symbol.")
    
    # Check if already has access
    if coin in access_data["users"][user_id]["coins"]:
        return await update.message.reply_text(f"✅ You already have access to {coin.upper()}.")
    
    # Check if already requested
    for req in access_data["coin_requests"]:
        if req["user_id"] == user_id and req["coin"] == coin:
            return await update.message.reply_text(f"⏳ Your request for {coin.upper()} is pending approval.")
    
    # Add new request
    user = update.effective_user
    access_data["coin_requests"].append({
        "user_id": user_id,
        "coin": coin,
        "username": user.username or user.first_name,
        "timestamp": str(update.message.date)
    })
    save_access(access_data)
    
    # Notify owner
    owner_id = access_data["owner"]
    await context.bot.send_message(
        chat_id=owner_id,
        text=f"🆕 Coin Access Request:\n"
             f"User: {user.username or user.first_name} (@{user.username})\n"
             f"ID: {user_id}\n"
             f"Coin: {coin.upper()}\n"
             f"Use /approve_coin {user_id} {coin} or /decline_coin {user_id} {coin}"
    )
    
    await update.message.reply_text(f"✅ Your request for {coin.upper()} access has been sent to the admin.")

async def approve_coin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    access_data = load_access()
    
    # Check if command user is owner
    if user_id != access_data["owner"]:
        return await update.message.reply_text("❌ Only owner can approve coin access.")
    
    if len(context.args) < 2:
        return await update.message.reply_text("❗ Usage: /approve_coin USER_ID COIN")
    
    target_id = context.args[0]
    coin = context.args[1].lower()
    
    if coin not in SYMBOL_MAP:
        return await update.message.reply_text("❗ Invalid coin symbol.")
    
    # Find and process request
    request_idx = None
    for i, req in enumerate(access_data["coin_requests"]):
        if req["user_id"] == target_id and req["coin"] == coin:
            request_idx = i
            break
    
    if request_idx is None:
        return await update.message.reply_text("❗ No pending request found for this coin and user.")
    
    # Grant coin access
    if target_id not in access_data["users"]:
        access_data["users"][target_id] = {"coins": []}
    
    if coin not in access_data["users"][target_id]["coins"]:
        access_data["users"][target_id]["coins"].append(coin)
    
    access_data["coin_requests"].pop(request_idx)
    save_access(access_data)
    
    # Notify owner and user
    await update.message.reply_text(f"✅ Approved {coin.upper()} access for user {target_id}")
    await context.bot.send_message(
        chat_id=int(target_id),
        text=f"🎉 Your access to {coin.upper()} has been approved!\n"
             f"You can now set alerts for {coin.upper()}."
    )

async def decline_coin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    access_data = load_access()
    
    # Check if command user is owner
    if user_id != access_data["owner"]:
        return await update.message.reply_text("❌ Only owner can decline coin access.")
    
    if len(context.args) < 2:
        return await update.message.reply_text("❗ Usage: /decline_coin USER_ID COIN")
    
    target_id = context.args[0]
    coin = context.args[1].lower()
    
    # Find and process request
    request_idx = None
    for i, req in enumerate(access_data["coin_requests"]):
        if req["user_id"] == target_id and req["coin"] == coin:
            request_idx = i
            break
    
    if request_idx is None:
        return await update.message.reply_text("❗ No pending request found for this coin and user.")
    
    access_data["coin_requests"].pop(request_idx)
    save_access(access_data)
    
    # Notify owner and user
    await update.message.reply_text(f"❌ Declined {coin.upper()} access for user {target_id}")
    await context.bot.send_message(
        chat_id=int(target_id),
        text=f"⚠️ Your request for {coin.upper()} access has been declined by the admin."
    )

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    access_data = load_access()
    
    # Check if command user is owner
    if user_id != access_data["owner"]:
        return await update.message.reply_text("❌ Only owner can list users.")
    
    # List approved users
    if not access_data["users"]:
        users_msg = "No approved users."
    else:
        users_msg = "Approved Users:\n"
        for uid, data in access_data["users"].items():
            users_msg += f"- {data.get('username', 'Unknown')} (ID: {uid})\n"
            users_msg += f"  Coins: {', '.join([c.upper() for c in data['coins']])}\n"
    
    # List pending requests
    if not access_data["requests"]:
        requests_msg = "\nNo pending access requests."
    else:
        requests_msg = "\nPending Access Requests:\n"
        for req in access_data["requests"]:
            requests_msg += f"- {req['username']} (ID: {req['user_id']})\n"
    
    # List coin requests
    if not access_data["coin_requests"]:
        coin_requests_msg = "\nNo pending coin requests."
    else:
        coin_requests_msg = "\nPending Coin Requests:\n"
        for req in access_data["coin_requests"]:
            coin_requests_msg += f"- {req['username']} (ID: {req['user_id']}) for {req['coin'].upper()}\n"
    
    await update.message.reply_text(users_msg + requests_msg + coin_requests_msg)

# ========== MODIFIED EXISTING COMMANDS ==========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    access_data = load_access()
    
    if user_id == access_data["owner"]:
        return await update.message.reply_text(
            "👋 Welcome back, Owner!\n\n"
            "Use <b><i>/add COIN PRICE</i></b> or <b><i>/add COIN PRICE below</i></b> - to set a price alert.\n\n"
            "Use <b><i>/list_users</i></b> to manage user access.\n"
            "Use <b><i>/help</i></b> for all commands.",
            parse_mode="HTML"
        )
    
    if user_id not in access_data["users"]:
        return await update.message.reply_text(
            "👋 Welcome to Crypto Alert Bot!\n\n"
            "You need access to use this bot.\n"
            "Use <b><i>/request</i></b> to request access.",
            parse_mode="HTML"
        )
    
    coins = ", ".join([c.upper() for c in access_data["users"][user_id]["coins"]])
    await update.message.reply_text(
        f"👋 Welcome back!\n\n"
        f"You have access to: {coins}\n\n"
        "Use <b><i>/add COIN PRICE</i></b> or <b><i>/add COIN PRICE below</i></b> - to set a price alert.\n\n"
        "Examples:\n"
        "<b><i>/add BTC 100000</i></b>\n"
        "<b><i>/add BTC 100000 below</i></b>\n\n"
        "Use <b><i>/help</i></b> for all commands.",
        parse_mode="HTML"
    )

async def add_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    access_data = load_access()
    
    # Owner has full access
    if user_id != access_data["owner"]:
        if user_id not in access_data["users"]:
            return await update.message.reply_text("❌ You don't have access to the bot. Use /request to request access.")

    if len(context.args) < 2:
        return await update.message.reply_text(
            "❗ Usage: /add COIN PRICE [above|below]\nExample: /add btc 30000 below",
            parse_mode="HTML"
        )

    symbol = context.args[0].lower()
    coin = SYMBOL_MAP.get(symbol)
    if not coin:
        return await update.message.reply_text("❗ Unsupported coin.")
    
    # Check if user has access to this coin (owner bypasses this check)
    if user_id != access_data["owner"] and symbol not in access_data["users"][user_id]["coins"]:
        return await update.message.reply_text(
            f"❌ You don't have access to {symbol.upper()}.\n"
            f"Use /request_coin {symbol} to request access.",
            parse_mode="HTML"
        )

    try:
        price = float(context.args[1])
    except ValueError:
        return await update.message.reply_text("❗ Invalid price.")

    direction = "above"
    if len(context.args) >= 3 and context.args[2].lower() in ["above", "below"]:
        direction = context.args[2].lower()

    alerts = load_alerts()
    user_alerts = alerts.get(user_id, [])
    user_alerts.append({
        "coin": coin,
        "symbol": symbol,
        "price": price,
        "direction": direction
    })
    alerts[user_id] = user_alerts
    save_alerts(alerts)

    await update.message.reply_text(f"✅ Alert set for {symbol.upper()} ${price} ({direction})")

async def coin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    access_data = load_access()
    
    # Owner sees all coins
    if user_id == access_data["owner"]:
        coins = "\n".join([f"• {k.upper()} ({v})" for k, v in SYMBOL_MAP.items()])
        return await update.message.reply_text(
            f"<b>📊 All Coins:</b>\n{coins}\n\n"
            "Use /add COIN PRICE [above|below] to set an alert.\n"
            "Example: /add btc 50000 below\n",
            parse_mode="HTML"
        )
    
    # Regular users see only their accessible coins
    if user_id not in access_data["users"]:
        return await update.message.reply_text("❌ You don't have access to the bot. Use /request to request access.")
    
    accessible_coins = access_data["users"][user_id]["coins"]
    coins = "\n".join([f"• {c.upper()} ({SYMBOL_MAP[c]})" for c in accessible_coins])
    await update.message.reply_text(
        f"<b>📊 Your Coins:</b>\n{coins}\n\n"
        "Use /add COIN PRICE [above|below] to set an alert.\n"
        "Example: /add btc 50000 below\n\n"
        "Use /request_coin COIN to request access to more coins.",
        parse_mode="HTML"
    )

async def get_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    access_data = load_access()
    
    # Owner can check any coin
    if user_id != access_data["owner"]:
        if user_id not in access_data["users"]:
            return await update.message.reply_text("❌ You don't have access to the bot. Use /request to request access.")

    if not context.args:
        return await update.message.reply_text("❗ Usage: /price COIN [COIN2 ...]")

    symbols = [s.lower() for s in context.args]
    
    # For regular users, filter only accessible coins
    if user_id != access_data["owner"]:
        accessible_coins = access_data["users"][user_id]["coins"]
        unauthorized = [s for s in symbols if s not in accessible_coins]
        if unauthorized:
            return await update.message.reply_text(
                f"❌ You don't have access to: {', '.join([c.upper() for c in unauthorized])}\n"
                f"Use /request_coin COIN to request access.",
                parse_mode="HTML"
            )
    
    unknown = [s for s in symbols if s not in SYMBOL_MAP]
    if unknown:
        return await update.message.reply_text(f"❗ Unknown coin(s): {', '.join(unknown)}")

    ids = [SYMBOL_MAP[s] for s in symbols]
    try:
        res = requests.get("https://api.coingecko.com/api/v3/simple/price",
                           params={"ids": ",".join(ids), "vs_currencies": "usd"}).json()
        lines = []
        for s in symbols:
            price = res.get(SYMBOL_MAP[s], {}).get("usd")
            if price is not None:
                lines.append(f"💰 {s.upper()}: ${price:.5f}")
            else:
                lines.append(f"⚠️ {s.upper()}: Price not found")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        print("Error fetching prices:", e)
        await update.message.reply_text("⚠️ Failed to fetch prices.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    access_data = load_access()
    
    is_owner = user_id == access_data["owner"]
    has_access = user_id in access_data["users"]
    
    basic_help = (
        "📌 Basic Commands:\n"
        "/start - Start the bot\n"
        "/request - Request access to the bot\n"
        "/help - Show this help\n"
    )
    
    user_help = (
        "📌 User Commands:\n"
        "/add COIN PRICE [above|below] - Set alert\n"
        "/list - List your alerts\n"
        "/remove NUMBER - Remove alert\n"
        "/coin - Show available coins\n"
        "/price COIN [COIN2 ...] - Get current prices\n"
        "/request_coin COIN - Request access to a coin\n"
    )
    
    owner_help = (
        "\n📌 Owner Commands:\n"
        "/approve USER_ID - Approve user access\n"
        "/decline USER_ID - Decline user access\n"
        "/approve_coin USER_ID COIN - Approve coin access\n"
        "/decline_coin USER_ID COIN - Decline coin access\n"
        "/list_users - List all users and requests\n"
    )
    
    if is_owner:
        await update.message.reply_text(basic_help + user_help + owner_help)
    elif has_access:
        await update.message.reply_text(basic_help + user_help)
    else:
        await update.message.reply_text(basic_help)

# ========== REST OF THE CODE REMAINS THE SAME ==========

async def list_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    access_data = load_access()
    
    if user_id != access_data["owner"] and user_id not in access_data["users"]:
        return await update.message.reply_text("❌ You don't have access to the bot. Use /request to request access.")

    alerts = load_alerts()
    user_alerts = alerts.get(user_id, [])

    if not user_alerts:
        return await update.message.reply_text("You have no active alerts.")

    msg = "📋 Your alerts:\n"
    for i, alert in enumerate(user_alerts, start=1):
        msg += f"{i}. {alert['symbol'].upper()} {alert['direction']} ${alert['price']}\n"
    await update.message.reply_text(msg)

async def remove_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    access_data = load_access()
    
    if user_id != access_data["owner"] and user_id not in access_data["users"]:
        return await update.message.reply_text("❌ You don't have access to the bot. Use /request to request access.")

    if len(context.args) != 1 or not context.args[0].isdigit():
        return await update.message.reply_text("❗ Usage: /remove ALERT_NUMBER")

    idx = int(context.args[0]) - 1
    alerts = load_alerts()
    user_alerts = alerts.get(user_id, [])

    if idx < 0 or idx >= len(user_alerts):
        return await update.message.reply_text("❗ Invalid alert number.")

    removed = user_alerts.pop(idx)
    if user_alerts:
        alerts[user_id] = user_alerts
    else:
        alerts.pop(user_id)
    save_alerts(alerts)
    await update.message.reply_text(
        f"✅ Removed alert for {removed['symbol'].upper()} ${removed['price']} ({removed['direction']})"
    )

async def check_prices(context: ContextTypes.DEFAULT_TYPE):
    alerts = load_alerts()
    if not alerts:
        return

    coins = list({alert['coin'] for alerts in alerts.values() for alert in alerts})
    try:
        prices = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": ",".join(coins), "vs_currencies": "usd"}
        ).json()
    except Exception as e:
        print("Error fetching prices:", e)
        return

    for user_id, user_alerts in list(alerts.items()):
        to_remove = []
        for i, alert in enumerate(user_alerts):
            current = prices.get(alert["coin"], {}).get("usd")
            if current is None:
                continue
            if (alert["direction"] == "above" and current >= alert["price"]) or \
               (alert["direction"] == "below" and current <= alert["price"]):
                await context.bot.send_message(
                    chat_id=int(user_id),
                    text=f"🚨 {alert['symbol'].upper()} is ${current:.5f}, hit {alert['direction']} ${alert['price']}!"
                )
                to_remove.append(i)
        for i in reversed(to_remove):
            user_alerts.pop(i)
        if user_alerts:
            alerts[user_id] = user_alerts
        else:
            alerts.pop(user_id)
    save_alerts(alerts)

async def ping_self():
    while True:
        try:
            if PING_URL:
                requests.get(PING_URL)
                print("🔁 Pinged self")
        except Exception as e:
            print("Ping failed", e)
        await asyncio.sleep(300)  # every 5 minutes

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

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Unknown command. Use /help for help.")

async def main():
    run_ping_server()  # Start the ping server in a separate thread
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Add command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("coin", coin_command))
    app.add_handler(CommandHandler("add", add_alert))
    app.add_handler(CommandHandler("list", list_alerts))
    app.add_handler(CommandHandler("remove", remove_alert))
    app.add_handler(CommandHandler("price", get_price))
    
    # New access control handlers
    app.add_handler(CommandHandler("request", request_access))
    app.add_handler(CommandHandler("approve", approve_user))
    app.add_handler(CommandHandler("decline", decline_user))
    app.add_handler(CommandHandler("approve_coin", approve_coin))
    app.add_handler(CommandHandler("decline_coin", decline_coin))
    app.add_handler(CommandHandler("request_coin", request_coin_access))
    app.add_handler(CommandHandler("list_users", list_users))
    
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    app.job_queue.run_repeating(check_prices, interval=15, first=5)
    asyncio.create_task(ping_self())

    print("🤖 Bot is running...")
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(main())
    except RuntimeError:
        import nest_asyncio
        nest_asyncio.apply()
        asyncio.run(main())