import os
import json
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, JobQueue
from keep_alive import keep_alive
from dotenv import load_dotenv

# Սկսել keep_alive server-ը Render.com-ի համար
keep_alive()

# Բեռնել environment փոփոխականները
load_dotenv()

# Կոնֆիգուրացիա
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
BLOCKCHAIR_API_KEY = os.getenv('BLOCKCHAIR_API_KEY', '')  # Ոչ պարտադիր
STORAGE_FILE = 'storage.json'
CHECK_INTERVAL = 30  # վայրկյան

def load_storage():
    """Բեռնել պահեստավորված տվյալները"""
    try:
        with open(STORAGE_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {'users': {}}

def save_storage(data):
    """Պահպանել տվյալները"""
    with open(STORAGE_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def is_valid_dash_address(address):
    """Ստուգել Dash հասցեի վավերականությունը"""
    return address.startswith('X') and len(address) == 34

def get_dash_transactions(address):
    """Ստանալ գործարքները Blockchair API-ից"""
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
    """Ստանալ DASH-ի գինը"""
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

def start(update: Update, context: CallbackContext):
    """Սկզբնական հաղորդագրություն"""
    update.message.reply_text(
        "👋 Բարի գալուստ Dash Notifier Bot!\n\n"
        "Ուղարկեք ձեր Dash հասցեն, և ես ձեզ կծանուցեմ նոր գործարքների մասին:\n\n"
        "Օրինակ՝ XrRrm9GZ8N1YwZKo3ZHFHwT5Mb9dF3mK5E"
    )

def handle_address(update: Update, context: CallbackContext):
    """Մշակել օգտատիրոջ կողմից ուղարկված հասցեն"""
    address = update.message.text.strip()
    chat_id = update.message.chat_id
    
    if not is_valid_dash_address(address):
        update.message.reply_text("❌ Անվավեր հասցե: Խնդրում եմ ուղարկել վավեր Dash հասցե (սկսվում է X-ով)")
        return
    
    storage = load_storage()
    
    # Ստուգել արդյոք հասցեն արդեն գրանցված է
    for user_id, user_data in storage['users'].items():
        if user_data.get('address') == address and str(user_id) != str(chat_id):
            update.message.reply_text("❌ Այս հասցեն արդեն գրանցված է այլ օգտատիրոջ կողմից")
            return
    
    # Գրանցել նոր հասցե
    storage['users'][str(chat_id)] = {
        'address': address,
        'last_tx': None,
        'notifications': []
    }
    
    save_storage(storage)
    update.message.reply_text(f"✅ Հաջողությամբ գրանցված է: Կծանուցեմ {address} հասցեի նոր գործարքների մասին")

def check_transactions(context: CallbackContext):
    """Պարբերաբար ստուգել նոր գործարքները"""
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
                user_data['last_tx'] = latest_tx['hash']
                user_data['notifications'].append(latest_tx['hash'])
                
                # Պահպանել միայն վերջին 100 ծանուցումները
                if len(user_data['notifications']) > 100:
                    user_data['notifications'] = user_data['notifications'][-100:]
    
    save_storage(storage)

def send_notification(bot, chat_id, transaction, dash_price):
    """Ուղարկել ծանուցում նոր գործարքի մասին"""
    tx_time = datetime.fromtimestamp(transaction['time']).strftime('%Y-%m-%d %H:%M')
    dash_amount = transaction['balance_change'] / 100000000  # Սատոշիից DASH
    usd_value = dash_amount * dash_price
    tx_link = f"https://blockchair.com/dash/transaction/{transaction['hash']}"
    tx_count = len(get_dash_transactions(transaction['address']))
    
    message = (
        f"📥 Նոր Գործարք #{tx_count}\n\n"
        f"💰 Գումար: {dash_amount:.8f} DASH (~${usd_value:.2f})\n"
        f"⏰ Ժամանակ: {tx_time}\n"
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
    """Գլխավոր ֆունկցիա"""
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN-ը սահմանված չէ!")
        return
    
    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_address))
    
    # Ամեն 30 վայրկյանը մեկ ստուգել գործարքները
    jq = updater.job_queue
    jq.run_repeating(check_transactions, interval=CHECK_INTERVAL, first=0)
    
    print("🤖 Բոտը գործարկված է...")
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
