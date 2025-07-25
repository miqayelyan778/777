import os
import json
import requests
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, JobQueue

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
    return address.startswith('X') and len(address) == 34

# Blockchair API functions
def get_dash_transactions(address):
    url = f"https://api.blockchair.com/dash/dashboards/address/{address}"
    if BLOCKCHAIR_API_KEY:
        url += f"?key={BLOCKCHAIR_API_KEY}"
    
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        return data.get('data', {}).get(address, {}).get('transactions', [])
    except Exception as e:
        print(f"Error fetching transactions: {e}")
        return []

def get_dash_price():
    url = "https://api.blockchair.com/dash/stats"
    if BLOCKCHAIR_API_KEY:
        url += f"?key={BLOCKCHAIR_API_KEY}"
    
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        return data.get('data', {}).get('market_price_usd', 0)
    except Exception as e:
        print(f"Error fetching Dash price: {e}")
        return 0

# Telegram bot handlers
def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "👋 Բարի գալուստ Dash Notifier Bot!\n\n"
        "Խնդրում եմ ուղարկեք ձեր Dash դրամապանակի հասցեն, և ես ձեզ կծանուցեմ\n"
        "երբ նոր գործարքներ ստանաք:\n\n"
        "Ուղարկեք ձեր հասցեն այսպես՝ XonCSL19SseRbeThdAJAeRju1jEWke1gSc"
    )

def handle_address(update: Update, context: CallbackContext):
    address = update.message.text.strip()
    chat_id = update.message.chat_id
    
    storage = load_storage()
    
    if not is_valid_dash_address(address):
        update.message.reply_text("❌ Սխալ Dash հասցե: Խնդրում եմ ուղարկեք հասցե, որը սկսվում է 'X'-ով:")
        return
    
    # Check if address is already registered
    for user_id, user_data in storage['users'].items():
        if user_data.get('address') == address and str(user_id) != str(chat_id):
            update.message.reply_text("❌ Այս հասցեն արդեն գրանցված է մեկ այլ օգտատիրոջ կողմից:")
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
    update.message.reply_text(f"✅ Հաջողություն: Ես կծանուցեմ ձեզ նոր գործարքների մասին այս հասցեի համար:\n{address}")

def check_transactions(context: CallbackContext):
    storage = load_storage()
    dash_price = get_dash_price()
    
    for chat_id, user_data in storage['users'].items():
        address = user_data['address']
        transactions = get_dash_transactions(address)
        
        if not transactions:
            continue
        
        latest_tx = transactions[0]
        
        if user_data['last_tx'] != latest_tx['hash']:
            if latest_tx['hash'] not in user_data['notifications']:
                send_notification(context.bot, chat_id, latest_tx, dash_price)
                storage['users'][chat_id]['last_tx'] = latest_tx['hash']
                storage['users'][chat_id]['notifications'].append(latest_tx['hash'])
                
                if len(storage['users'][chat_id]['notifications']) > 100:
                    storage['users'][chat_id]['notifications'] = storage['users'][chat_id]['notifications'][-100:]
    
    save_storage(storage)

def send_notification(bot, chat_id, transaction, dash_price):
    tx_time = datetime.fromtimestamp(transaction['time']).strftime('%Y-%m-%d %H:%M')
    dash_amount = transaction['balance_change'] / 100000000
    usd_value = dash_amount * dash_price
    tx_link = f"https://blockchair.com/dash/transaction/{transaction['hash']}"
    tx_count = len(get_dash_transactions(transaction['address']))
    
    message = (
        f"📥 Նոր Գործարք #{tx_count}\n\n"
        f"💰 Գումար՝ {dash_amount:.8f} DASH (~{usd_value:.2f}$)\n"
        f"⏰ Ժամանակ՝ {tx_time}\n"
        f"🔗 [Դիտել Blockchair-ում]({tx_link})\n"
        f"🧾 TxID: {transaction['hash'][:8]}..."
    )
    
    keyboard = [[InlineKeyboardButton("Դիտել Գործարքը", url=tx_link)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    bot.send_message(
        chat_id=chat_id,
        text=message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

def main():
    if not TELEGRAM_TOKEN:
        print("❌ Սխալ: TELEGRAM_BOT_TOKEN environment փոփոխականը սահմանված չէ!")
        print("Խնդրում եմ ստացեք ձեր token-ը @BotFather-ից և ավելացրեք Render.com-ի environment փոփոխականներում")
        return

    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_address))
    
    jq = updater.job_queue
    jq.run_repeating(check_transactions, interval=CHECK_INTERVAL, first=0)
    
    print("🤖 Բոտը գործարկվում է...")
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
