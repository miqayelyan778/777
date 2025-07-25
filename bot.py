import os
import json
import requests
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackContext
)
from dotenv import load_dotenv

# Լոգավորում կարգավորում
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Կարգավորումներ
load_dotenv()
TOKEN = os.getenv('TELEGRAM_TOKEN')

# Տվյալների պահպանում
def save_data(data):
    os.makedirs('data', exist_ok=True)
    with open('data/storage.json', 'w') as f:
        json.dump(data, f, indent=4)

def load_data():
    try:
        with open('data/storage.json', 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"users": {}, "transactions": {}}

# DASH հասցեի վավերացում
def is_valid_dash_address(address):
    return (address.startswith('X') and 
            len(address) == 34 and 
            all(c in '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz' for c in address))

# Ստանալ DASH գինը
def get_dash_price():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=dash&vs_currencies=usd"
        response = requests.get(url, timeout=10)
        return response.json().get('dash', {}).get('usd')
    except Exception as e:
        logger.error(f"Գնի ստացման սխալ: {e}")
        return None

# Ստանալ փոխանցումները
def get_transactions(address):
    try:
        url = f"https://api.blockchair.com/dash/dashboards/address/{address}?limit=10"
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            data = response.json()
            if data.get('data') and address in data['data']:
                return data['data'][address].get('transactions', [])
        return []
    except Exception as e:
        logger.error(f"API սխալ: {e}")
        return []

# Ստեղծել ծանուցում
def create_notification(tx, dash_price):
    amount = sum(out['value'] for out in tx['outputs']) / 1e8
    usd_value = amount * dash_price if dash_price else 0
    time_str = datetime.fromtimestamp(tx['time']).strftime('%Y-%m-%d %H:%M')
    return (
        f"📥 Նոր փոխանցում #{tx['index'] + 1}\n"
        f"💰 Գումար: {amount:.8f} DASH (~${usd_value:.2f})\n"
        f"⏰ Ժամ: {time_str}\n"
        f"🔗 TxID: {tx['hash'][:8]}..."
    )

# Հրամաններ
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Բարի գալուստ! Ուղարկեք ձեր DASH հասցեն (սկսում է X-ով):")

async def handle_dash_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    address = update.message.text.strip()
    
    if not is_valid_dash_address(address):
        await update.message.reply_text("❌ Սխալ հասցեի ֆորմատ: Հասցեն պետք է սկսվի X-ով և ունենա 34 նիշ")
        return
    
    data = load_data()
    data['users'][str(user_id)] = address
    save_data(data)
    await update.message.reply_text(f"✅ Հասցեն գրանցված է:\n`{address}`\n\nԵս կծանուցեմ ձեզ նոր փոխանցումների մասին:", parse_mode='MarkdownV2')

# Ստուգել փոխանցումները
async def check_transactions(context: CallbackContext):
    try:
        data = load_data()
        if not data.get('users'):
            return
            
        dash_price = get_dash_price()
        
        for user_id, address in data['users'].items():
            try:
                txs = get_transactions(address)
                if not txs:
                    continue
                    
                latest_tx = txs[0]
                tx_key = f"{user_id}_{latest_tx['hash']}"
                
                if tx_key not in data.get('transactions', {}):
                    data.setdefault('transactions', {})[tx_key] = True
                    save_data(data)
                    
                    notification = create_notification(latest_tx, dash_price)
                    await context.bot.send_message(
                        chat_id=int(user_id),
                        text=notification,
                        parse_mode='MarkdownV2'
                    )
            except Exception as e:
                logger.error(f"Սխալ օգտատիրոջ {user_id} համար: {e}")
    except Exception as e:
        logger.error(f"Ընդհանուր սխալ check_transactions-ում: {e}")

def main():
    try:
        # Ստեղծում ենք հավելվածը
        application = Application.builder().token(TOKEN).build()
        
        # Weak reference սխալի շրջանցում
        if hasattr(application.job_queue, '_application'):
            application.job_queue._application = application
        
        # Հրամաններ
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_dash_address))
        
        # Աշխատանքային հերթ
        application.job_queue.run_repeating(
            check_transactions,
            interval=300.0,  # 5 րոպե
            first=10.0
        )
        
        logger.info("Բոտը գործարկվում է...")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Կրիտիկական սխալ: {e}")

if __name__ == "__main__":
    main()
