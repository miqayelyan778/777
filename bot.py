import os
import json
import time
import requests
from datetime import datetime
from dotenv import load_dotenv
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# Keep alive for Render.com
from keep_alive import keep_alive
keep_alive()

# Load environment variables
load_dotenv()

# Configuration
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
BLOCKCHAIR_API_KEY = os.getenv('BLOCKCHAIR_API_KEY')
STORAGE_FILE = 'storage.json'
CHECK_INTERVAL = 30  # seconds

# Initialize storage
def load_storage():
    try:
        with open(STORAGE_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {'users': {}, 'last_checked': 0}

def save_storage(data):
    with open(STORAGE_FILE, 'w') as f:
        json.dump(data, f, indent=2)

# Dash address validation
def is_valid_dash_address(address):
    # Basic validation - in a real app you'd want more thorough validation
    return address.startswith('X') and len(address) == 34

# Blockchair API functions
def get_dash_transactions(address):
    url = f"https://api.blockchair.com/dash/dashboards/address/{address}"
    if BLOCKCHAIR_API_KEY:
        url += f"?key={BLOCKCHAIR_API_KEY}"
    
    try:
        response = requests.get(url)
        data = response.json()
        if 'data' in data and address in data['data']:
            return data['data'][address]['transactions']
        return []
    except Exception as e:
        print(f"Error fetching transactions: {e}")
        return []

def get_dash_price():
    url = "https://api.blockchair.com/dash/stats"
    if BLOCKCHAIR_API_KEY:
        url += f"?key={BLOCKCHAIR_API_KEY}"
    
    try:
        response = requests.get(url)
        data = response.json()
        return data['data']['market_price_usd']
    except Exception as e:
        print(f"Error fetching Dash price: {e}")
        return 0

# Telegram bot handlers
def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "👋 Welcome to Dash Notifier Bot!\n\n"
        "Please send me your Dash wallet address and I'll notify you "
        "whenever you receive new transactions.\n\n"
        "Just send your Dash address like this: XonCSL19SseRbeThdAJAeRju1jEWke1gSc"
    )

def handle_address(update: Update, context: CallbackContext):
    address = update.message.text.strip()
    chat_id = update.message.chat_id
    
    storage = load_storage()
    
    if not is_valid_dash_address(address):
        update.message.reply_text("❌ Invalid Dash address. Please send a valid Dash address starting with 'X'.")
        return
    
    # Check if address is already registered by another user
    for user_id, user_data in storage['users'].items():
        if user_data.get('address') == address and str(user_id) != str(chat_id):
            update.message.reply_text("❌ This address is already being monitored by another user.")
            return
    
    # Save or update address
    if str(chat_id) not in storage['users']:
        storage['users'][str(chat_id)] = {
            'address': address,
            'last_tx': None,
            'notifications': []
        }
    else:
        storage['users'][str(chat_id)]['address'] = address
        storage['users'][str(chat_id)]['last_tx'] = None
    
    save_storage(storage)
    update.message.reply_text(f"✅ Success! I'll notify you about new transactions to:\n{address}")

def check_transactions(context: CallbackContext):
    storage = load_storage()
    dash_price = get_dash_price()
    
    for chat_id, user_data in storage['users'].items():
        address = user_data['address']
        transactions = get_dash_transactions(address)
        
        if not transactions:
            continue
        
        # Get the most recent transaction
        latest_tx = transactions[0]
        
        # Check if this is a new transaction
        if user_data['last_tx'] != latest_tx['hash']:
            # Store notification to avoid duplicates
            if latest_tx['hash'] not in user_data['notifications']:
                # Send notification
                send_notification(context.bot, chat_id, latest_tx, dash_price)
                
                # Update storage
                storage['users'][chat_id]['last_tx'] = latest_tx['hash']
                storage['users'][chat_id]['notifications'].append(latest_tx['hash'])
                
                # Keep only the last 100 notifications to prevent storage bloat
                if len(storage['users'][chat_id]['notifications']) > 100:
                    storage['users'][chat_id]['notifications'] = storage['users'][chat_id]['notifications'][-100:]
    
    save_storage(storage)

def send_notification(bot, chat_id, transaction, dash_price):
    tx_time = datetime.fromtimestamp(transaction['time']).strftime('%Y-%m-%d %H:%M')
    dash_amount = transaction['balance_change'] / 100000000  # Convert from satoshis
    usd_value = dash_amount * dash_price
    
    # Create the transaction link
    tx_link = f"https://blockchair.com/dash/transaction/{transaction['hash']}"
    
    # Count total transactions for this address (would need to be stored)
    tx_count = len(get_dash_transactions(transaction['address']))
    
    message = (
        f"📥 New Transaction #{tx_count}\n\n"
        f"💰 Amount: {dash_amount:.8f} DASH (~{usd_value:.2f}$)\n"
        f"⏰ Time: {tx_time}\n"
        f"🔗 [View on Blockchair]({tx_link})\n"
        f"🧾 TxID: {transaction['hash'][:8]}..."
    )
    
    keyboard = [[InlineKeyboardButton("View Transaction", url=tx_link)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    bot.send_message(
        chat_id=chat_id,
        text=message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

def main():
    # Create bot
    updater = Updater(TELEGRAM_TOKEN)
    dispatcher = updater.dispatcher
    
    # Add handlers
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_address))
    
    # Start periodic checking
    job_queue = updater.job_queue
    job_queue.run_repeating(check_transactions, interval=CHECK_INTERVAL, first=0)
    
    # Start bot
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
