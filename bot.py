import json
import os
import requests
import asyncio
import psutil
import signal
from telegram import Update
from telegram.error import Conflict
from telegram.ext import ContextTypes
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

# ========== INITIALIZATION ==========
# Load environment variables
load_dotenv()

# File paths
ALERT_FILE = 'prices.json'
ACCESS_FILE = 'access.json'
SYMBOL_MAP_FILE = 'symbols.json'

# Configuration
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PING_URL = os.getenv("PING_URL", "http://localhost:10001")
OWNER_ID = os.getenv("OWNER_ID", "5817239686")



# Crypto symbol mapping
def load_symbol_map():
    try:
        if os.path.exists(SYMBOL_MAP_FILE):
            with open(SYMBOL_MAP_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading symbol map: {e}")
    # Default symbols if file doesn't exist
    return {
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

def save_symbol_map(data):
    try:
        with open(SYMBOL_MAP_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error saving symbol map: {e}")

# Replace the hardcoded SYMBOL_MAP with:
SYMBOL_MAP = load_symbol_map()

# ========== INSTANCE MANAGEMENT ==========
def kill_previous_instances():
    current_pid = os.getpid()
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if ('python' in proc.info['name'].lower() or 
                'python3' in proc.info['name'].lower()):
                if ('bot.py' in ' '.join(proc.info['cmdline']) or 
                    'python3 bot.py' in ' '.join(proc.info['cmdline'])):
                    if proc.info['pid'] != current_pid:
                        print(f"⚠️ Killing previous instance (PID: {proc.info['pid']})")
                        try:
                            os.kill(proc.info['pid'], signal.SIGTERM)
                        except ProcessLookupError:
                            pass
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

def cleanup_ports():
    for port in [10001, 10002, 10003]:
        try:
            for conn in psutil.net_connections():
                if conn.laddr.port == port:
                    print(f"⚠️ Killing process using port {port} (PID: {conn.pid})")
                    try:
                        os.kill(conn.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
        except Exception as e:
            print(f"Port cleanup warning: {e}")

# ========== DATA MANAGEMENT ==========
def load_alerts():
    try:
        if os.path.exists(ALERT_FILE):
            with open(ALERT_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading alerts: {e}")
    return {}

def save_alerts(data):
    try:
        with open(ALERT_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error saving alerts: {e}")

def load_access():
    try:
        if os.path.exists(ACCESS_FILE):
            with open(ACCESS_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading access: {e}")
    return {
        "owner": OWNER_ID,
        "users": {},
        "requests": [],
        "coin_requests": []
    }

def save_access(data):
    try:
        with open(ACCESS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error saving access: {e}")

# ========== PING SERVER ==========
class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Pong")

def run_ping_server():
    def server_thread():
        ports = [10001, 10002, 10003]
        for port in ports:
            try:
                server = HTTPServer(('0.0.0.0', port), PingHandler)
                print(f"✅ Ping server running on port {port}")
                if PING_URL != f"http://localhost:{port}":
                    print(f"ℹ️ Update PING_URL to: http://localhost:{port}")
                server.serve_forever()
                break
            except OSError as e:
                if e.errno == 48:
                    print(f"Port {port} in use, trying next...")
                    continue
                print(f"Server error: {e}")
                break
    Thread(target=server_thread, daemon=True).start()

# ========== COMMAND HANDLERS ==========
# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    access = load_access()
    
    if user_id == access["owner"]:
        await update.message.reply_text(
            "👋 Owner commands:\n"
            "/add COIN PRICE [above|below]\n"
            "/list_users\n"
            "/help"
        )
        return
    
    if user_id not in access["users"]:
        await update.message.reply_text(
            "👋 Use /request to ask for access\n"
            "Then /request_coin COIN for specific coins"
        )
        return
    
    coins = ", ".join([c.upper() for c in access["users"][user_id]["coins"]])
    await update.message.reply_text(f"✅ Your coins: {coins}\nUse /add to set alerts")

# Help command
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    access = load_access()
    
    is_owner = user_id == access["owner"]
    has_access = user_id in access["users"]
    
    basic_help = (
        "📌 Basic Commands:\n"
        "/start - Start the bot\n"
        "/help - Show this help\n"
    )
    
    if not has_access and not is_owner:
        basic_help += "/request - Request bot access\n"
        await update.message.reply_text(basic_help)
        return
    
    user_help = (
        "\n📌 User Commands:\n"
        "/add COIN PRICE [above|below] - Set alert\n"
        "/list - List your alerts\n"
        "/remove NUMBER - Remove alert\n"
        "/coin - Show accessible coins\n"
        "/price COIN [COIN2 ...] - Get prices\n"
        "/request_coin COIN - Request coin access\n"
    )
    
    owner_help = ""
    if is_owner:
        owner_help = (
            "\n📌 Owner Commands:\n"
            "/approve USER_ID - Approve user\n"
            "/decline USER_ID - Decline user\n"
            "/approve_coin USER_ID COIN - Approve coin\n"
            "/decline_coin USER_ID COIN - Decline coin\n"
            "/list_users - List all users\n"
            "/new_coin SYMBOL COINGECKO_ID - Add new cryptocurrency\n"
        )
    
    await update.message.reply_text(basic_help + user_help + owner_help)
# new coin command
async def new_coin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    access = load_access()
    
    if user_id != access["owner"]:
        await update.message.reply_text("❌ Only owner can add new coins.")
        return
    
    if len(context.args) != 2:
        await update.message.reply_text("❗ Usage: /new_coin SYMBOL COINGECKO_ID\nExample: /new_coin btc bitcoin")
        return
    
    symbol = context.args[0].lower()
    coin_id = context.args[1].lower()
    
    # Load current symbols
    symbol_map = load_symbol_map()
    
    if symbol in symbol_map:
        await update.message.reply_text(f"⚠️ {symbol.upper()} already exists in the symbol map.")
        return
    
    # Test the coin ID with CoinGecko
    try:
        test_price = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": coin_id, "vs_currencies": "usd"},
            timeout=10
        ).json()
        
        if not test_price.get(coin_id):
            await update.message.reply_text(f"❌ CoinGecko ID '{coin_id}' not found. Please check the ID.")
            return
            
        # Add the new coin
        symbol_map[symbol] = coin_id
        save_symbol_map(symbol_map)
        
        # Update the in-memory map
        global SYMBOL_MAP
        SYMBOL_MAP = symbol_map
        
        await update.message.reply_text(
            f"✅ Added new coin:\n"
            f"Symbol: {symbol.upper()}\n"
            f"CoinGecko ID: {coin_id}\n\n"
            f"Users can now set alerts for {symbol.upper()}."
        )
    except Exception as e:
        print(f"Error testing new coin: {e}")
        await update.message.reply_text("⚠️ Failed to verify coin with CoinGecko. Please try again.")

# ========== ACCESS MANAGEMENT ==========
async def request_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    access = load_access()
    
    if user_id in access["users"]:
        await update.message.reply_text("✅ You already have access!")
        return
    
    for req in access["requests"]:
        if req["user_id"] == user_id:
            await update.message.reply_text("⏳ Your request is already pending.")
            return
    
    user = update.effective_user
    access["requests"].append({
        "user_id": user_id,
        "username": user.username or user.first_name,
        "timestamp": str(update.message.date)
    })
    save_access(access)
    
    await context.bot.send_message(
        chat_id=access["owner"],
        text=f"🆕 Access Request:\n"
             f"User: {user.username or user.first_name} (@{user.username})\n"
             f"ID: {user_id}\n"
             f"Use /approve {user_id} or /decline {user_id}"
    )
    
    await update.message.reply_text("✅ Your request has been sent to admin.")

# = Approve/Decline User Commands ==========
async def approve_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    access = load_access()
    
    if user_id != access["owner"]:
        await update.message.reply_text("❌ Only owner can approve users.")
        return
    
    if not context.args:
        await update.message.reply_text("❗ Usage: /approve USER_ID")
        return
    
    target_id = context.args[0]
    request_idx = None
    
    for i, req in enumerate(access["requests"]):
        if req["user_id"] == target_id:
            request_idx = i
            break
    
    if request_idx is None:
        await update.message.reply_text("❗ No pending request for this user.")
        return
    
    access["users"][target_id] = {
        "coins": ["btc"],
        "username": access["requests"][request_idx]["username"]
    }
    access["requests"].pop(request_idx)
    save_access(access)
    
    await update.message.reply_text(f"✅ Approved access for user {target_id}")
    await context.bot.send_message(
        chat_id=int(target_id),
        text="🎉 Your access has been approved!\n"
             "You can now set alerts for BTC.\n"
             "Use /request_coin COIN to request more coins."
    )

async def decline_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    access = load_access()
    
    if user_id != access["owner"]:
        await update.message.reply_text("❌ Only owner can decline users.")
        return
    
    if not context.args:
        await update.message.reply_text("❗ Usage: /decline USER_ID")
        return
    
    target_id = context.args[0]
    request_idx = None
    
    for i, req in enumerate(access["requests"]):
        if req["user_id"] == target_id:
            request_idx = i
            break
    
    if request_idx is None:
        await update.message.reply_text("❗ No pending request for this user.")
        return
    
    access["requests"].pop(request_idx)
    save_access(access)
    
    await update.message.reply_text(f"❌ Declined access for user {target_id}")
    await context.bot.send_message(
        chat_id=int(target_id),
        text="⚠️ Your access request has been declined."
    )

# ========== COIN ACCESS MANAGEMENT ==========
async def request_coin_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    access = load_access()
    
    if user_id not in access["users"]:
        await update.message.reply_text("❌ You don't have access. Use /request first.")
        return
    
    if not context.args:
        await update.message.reply_text("❗ Usage: /request_coin COIN")
        return
    
    coin = context.args[0].lower()
    if coin not in SYMBOL_MAP:
        await update.message.reply_text("❗ Invalid coin symbol.")
        return
    
    if coin in access["users"][user_id]["coins"]:
        await update.message.reply_text(f"✅ You already have access to {coin.upper()}.")
        return
    
    for req in access["coin_requests"]:
        if req["user_id"] == user_id and req["coin"] == coin:
            await update.message.reply_text(f"⏳ Your request for {coin.upper()} is pending.")
            return
    
    user = update.effective_user
    access["coin_requests"].append({
        "user_id": user_id,
        "coin": coin,
        "username": user.username or user.first_name,
        "timestamp": str(update.message.date)
    })
    save_access(access)
    
    await context.bot.send_message(
        chat_id=access["owner"],
        text=f"🆕 Coin Access Request:\n"
             f"User: {user.username or user.first_name} (@{user.username})\n"
             f"ID: {user_id}\n"
             f"Coin: {coin.upper()}\n"
             f"Use /approve_coin {user_id} {coin} or /decline_coin {user_id} {coin}"
    )
    
    await update.message.reply_text(f"✅ Request for {coin.upper()} sent to admin.")

async def approve_coin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    access = load_access()
    
    if user_id != access["owner"]:
        await update.message.reply_text("❌ Only owner can approve coins.")
        return
    
    if len(context.args) < 2:
        await update.message.reply_text("❗ Usage: /approve_coin USER_ID COIN")
        return
    
    target_id = context.args[0]
    coin = context.args[1].lower()
    
    if coin not in SYMBOL_MAP:
        await update.message.reply_text("❗ Invalid coin symbol.")
        return
    
    request_idx = None
    for i, req in enumerate(access["coin_requests"]):
        if req["user_id"] == target_id and req["coin"] == coin:
            request_idx = i
            break
    
    if request_idx is None:
        await update.message.reply_text("❗ No pending request for this coin and user.")
        return
    
    if target_id not in access["users"]:
        access["users"][target_id] = {"coins": []}
    
    if coin not in access["users"][target_id]["coins"]:
        access["users"][target_id]["coins"].append(coin)
    
    access["coin_requests"].pop(request_idx)
    save_access(access)
    
    await update.message.reply_text(f"✅ Approved {coin.upper()} for user {target_id}")
    await context.bot.send_message(
        chat_id=int(target_id),
        text=f"🎉 You now have access to {coin.upper()}!"
    )

async def decline_coin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    access = load_access()
    
    if user_id != access["owner"]:
        await update.message.reply_text("❌ Only owner can decline coins.")
        return
    
    if len(context.args) < 2:
        await update.message.reply_text("❗ Usage: /decline_coin USER_ID COIN")
        return
    
    target_id = context.args[0]
    coin = context.args[1].lower()
    
    request_idx = None
    for i, req in enumerate(access["coin_requests"]):
        if req["user_id"] == target_id and req["coin"] == coin:
            request_idx = i
            break
    
    if request_idx is None:
        await update.message.reply_text("❗ No pending request for this coin and user.")
        return
    
    access["coin_requests"].pop(request_idx)
    save_access(access)
    
    await update.message.reply_text(f"❌ Declined {coin.upper()} for user {target_id}")
    await context.bot.send_message(
        chat_id=int(target_id),
        text=f"⚠️ Your request for {coin.upper()} was declined."
    )

# ========== USER MANAGEMENT ==========
async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    access = load_access()
    
    if user_id != access["owner"]:
        await update.message.reply_text("❌ Only owner can list users.")
        return
    
    if not access["users"]:
        users_msg = "No approved users."
    else:
        users_msg = "Approved Users:\n"
        for uid, data in access["users"].items():
            users_msg += f"- {data.get('username', 'Unknown')} (ID: {uid})\n"
            users_msg += f"  Coins: {', '.join([c.upper() for c in data['coins']])}\n"
    
    if not access["requests"]:
        requests_msg = "\nNo pending access requests."
    else:
        requests_msg = "\nPending Access Requests:\n"
        for req in access["requests"]:
            requests_msg += f"- {req['username']} (ID: {req['user_id']})\n"
    
    if not access["coin_requests"]:
        coin_requests_msg = "\nNo pending coin requests."
    else:
        coin_requests_msg = "\nPending Coin Requests:\n"
        for req in access["coin_requests"]:
            coin_requests_msg += f"- {req['username']} (ID: {req['user_id']}) for {req['coin'].upper()}\n"
    
    await update.message.reply_text(users_msg + requests_msg + coin_requests_msg)

# ========== ALERT MANAGEMENT ==========
async def add_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    access = load_access()
    
    if user_id != access["owner"] and user_id not in access["users"]:
        await update.message.reply_text("❌ You don't have access. Use /request first.")
        return
    
    if len(context.args) < 2:
        await update.message.reply_text("❗ Usage: /add COIN PRICE [above|below]")
        return
    
    symbol = context.args[0].lower()
    coin = SYMBOL_MAP.get(symbol)
    if not coin:
        await update.message.reply_text("❗ Unsupported coin.")
        return
    
    if user_id != access["owner"] and symbol not in access["users"][user_id]["coins"]:
        await update.message.reply_text(f"❌ No access to {symbol.upper()}. Use /request_coin {symbol}")
        return
    
    try:
        price = float(context.args[1])
    except ValueError:
        await update.message.reply_text("❗ Invalid price.")
        return
    
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

async def list_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    access = load_access()
    
    if user_id != access["owner"] and user_id not in access["users"]:
        await update.message.reply_text("❌ You don't have access. Use /request first.")
        return
    
    alerts = load_alerts()
    user_alerts = alerts.get(user_id, [])
    
    if not user_alerts:
        await update.message.reply_text("You have no active alerts.")
        return
    
    msg = "📋 Your alerts:\n"
    for i, alert in enumerate(user_alerts, start=1):
        msg += f"{i}. {alert['symbol'].upper()} {alert['direction']} ${alert['price']}\n"
    await update.message.reply_text(msg)

async def remove_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    access = load_access()
    
    if user_id != access["owner"] and user_id not in access["users"]:
        await update.message.reply_text("❌ You don't have access. Use /request first.")
        return
    
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("❗ Usage: /remove ALERT_NUMBER")
        return
    
    idx = int(context.args[0]) - 1
    alerts = load_alerts()
    user_alerts = alerts.get(user_id, [])
    
    if idx < 0 or idx >= len(user_alerts):
        await update.message.reply_text("❗ Invalid alert number.")
        return
    
    removed = user_alerts.pop(idx)
    if user_alerts:
        alerts[user_id] = user_alerts
    else:
        alerts.pop(user_id)
    save_alerts(alerts)
    
    await update.message.reply_text(
        f"✅ Removed alert for {removed['symbol'].upper()} ${removed['price']} ({removed['direction']})"
    )

# ========== COIN COMMAND ==========
async def coin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    access = load_access()
    
    default_coin = "BTC"
    reply_lines = [f"<b>💰 Your default coin:</b> {default_coin}"]

    if user_id == access["owner"]:
        accessible_coins = list(SYMBOL_MAP.keys())  # owner sees all coins as accessible
        reply_lines.append("<b>📊 Owner Access:</b> You can manage all coins.")
        reply_lines.append("\nUse /add COIN PRICE [above|below] to set an alert.")
    elif user_id in access["users"]:
        accessible_coins = access["users"][user_id].get("coins", [])
        coins_list = "\n".join([f"• {c.upper()} ({SYMBOL_MAP.get(c, 'Unknown')})" for c in accessible_coins])
        reply_lines.append(f"<b>📊 Your Coins:</b>\n{coins_list}")
        reply_lines.append("\nUse /request_coin COIN to request more.")
    else:
        accessible_coins = []
        reply_lines.append("\n❌ You don't have access. Use /request first.")

    # Now add all available coins for everyone at the bottom
    all_coins_list = "\n".join([f"• {k.upper()} ({v})" for k, v in SYMBOL_MAP.items()])
    reply_lines.append(f"\n<b>🌐 All Available Coins:</b>\n{all_coins_list}")

    await update.message.reply_text("\n".join(reply_lines), parse_mode="HTML")


# ========== PRICE COMMAND ==========
async def get_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    access = load_access()
    
    if user_id != access["owner"] and user_id not in access["users"]:
        await update.message.reply_text("❌ You don't have access. Use /request first.")
        return
    
    if not context.args:
        await update.message.reply_text("❗ Usage: /price COIN [COIN2 ...]")
        return
    
    symbols = [s.lower() for s in context.args]
    
    if user_id != access["owner"]:
        accessible_coins = access["users"][user_id]["coins"]
        unauthorized = [s for s in symbols if s not in accessible_coins]
        if unauthorized:
            await update.message.reply_text(
                f"❌ No access to: {', '.join([c.upper() for c in unauthorized])}\n"
                f"Use /request_coin COIN to request access."
            )
            return
    
    unknown = [s for s in symbols if s not in SYMBOL_MAP]
    if unknown:
        await update.message.reply_text(f"❗ Unknown coin(s): {', '.join(unknown)}")
        return
    
    ids = [SYMBOL_MAP[s] for s in symbols]
    try:
        res = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": ",".join(ids), "vs_currencies": "usd"},
            timeout=10
        ).json()
        
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
        await update.message.reply_text("⚠️ Failed to fetch prices. Try again later.")

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Unknown command. Use /help for available commands.")

# ========== PRICE CHECKING ==========
async def check_prices(context: ContextTypes.DEFAULT_TYPE):
    try:
        alerts = load_alerts()
        if not alerts:
            return

        coins = list({alert['coin'] for alerts in alerts.values() for alert in alerts})
        prices = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": ",".join(coins), "vs_currencies": "usd"},
            timeout=10
        ).json()

        for user_id, user_alerts in list(alerts.items()):
            to_remove = []
            for i, alert in enumerate(user_alerts):
                current = prices.get(alert["coin"], {}).get("usd")
                if current is None:
                    continue
                
                condition_met = (
                    (alert["direction"] == "above" and current >= alert["price"]) or
                    (alert["direction"] == "below" and current <= alert["price"])
                )
                
                if condition_met:
                    try:
                        await context.bot.send_message(
                            chat_id=int(user_id),
                            text=f"🚨 {alert['symbol'].upper()} ${current:.2f} hit {alert['direction']} ${alert['price']}!"
                        )
                        to_remove.append(i)
                    except Exception as e:
                        print(f"Failed to notify user {user_id}: {e}")
            
            for i in reversed(to_remove):
                user_alerts.pop(i)
            
            if user_alerts:
                alerts[user_id] = user_alerts
            else:
                alerts.pop(user_id)
        
        save_alerts(alerts)
    except Exception as e:
        print(f"Price check error: {e}")

# ========== SELF-PINGING ==========
async def ping_self():
    while True:
        try:
            if PING_URL:
                response = requests.get(PING_URL, timeout=5)
                print(f"🔄 Ping successful: {response.status_code}")
        except Exception as e:
            print(f"⚠️ Ping failed: {str(e)}")
        await asyncio.sleep(300)

# ========== MAIN APPLICATION ==========
async def main():
    # Clean up previous instances
    kill_previous_instances()
    cleanup_ports()
    
    print("🤖 Starting bot...")
    run_ping_server()
    
    try:
        app = ApplicationBuilder().token(BOT_TOKEN).build()
        try:
            # Test if this token is already in use
            me = await app.bot.get_me()
            print(f"✅ Running as @{me.username}")
        except Conflict as e:
            print("❌ Bot already running elsewhere. Exiting.")
            return
        # Add command handlers
        commands = [
            ("start", start),
            ("help", help_command),
            ("request", request_access),
            ("approve", approve_user),
            ("decline", decline_user),
            ("new_coin", new_coin),
            ("request_coin", request_coin_access),
            ("approve_coin", approve_coin),
            ("decline_coin", decline_coin),
            ("list_users", list_users),
            ("add", add_alert),
            ("list", list_alerts),
            ("remove", remove_alert),
            ("coin", coin_command),
            ("price", get_price)
        ]
        
        for cmd, handler in commands:
            app.add_handler(CommandHandler(cmd, handler))
        
        app.add_handler(MessageHandler(filters.COMMAND, unknown_command))
        
        # Start jobs
        app.job_queue.run_repeating(check_prices, interval=15, first=5)
        asyncio.create_task(ping_self())
        
        # Start bot
        print("🤖 Bot is running...")
        
        
        # Notify owner
        try:
            await app.bot.send_message(chat_id=OWNER_ID, text="🤖 Bot started successfully!")
        except Exception as e:
            print(f"Owner notification failed: {e}")
        await app.run_polling()
        # Keep running
        while True:
            await asyncio.sleep(3600)
            
    except Exception as e:
        print(f"🔥 Error: {e}")
    finally:
        if 'app' in locals():
            await app.stop()
        print("🤖 Bot stopped")

if __name__ == "__main__":
    # Install required packages if not already installed
    try:
        import psutil
        import nest_asyncio
    except ImportError:
        import subprocess
        subprocess.run(["pip", "install", "psutil", "nest-asyncio"])
    
    try:
        asyncio.run(main())
    except RuntimeError:
        import nest_asyncio
        nest_asyncio.apply()
        asyncio.run(main())