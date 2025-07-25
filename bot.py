import os
import json
import requests
import time
from datetime import datetime
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)
from dotenv import load_dotenv

# Կարգավորումներ
load_dotenv()
TOKEN = os.getenv('TELEGRAM_TOKEN')
RENDER = os.getenv('RENDER', '').lower() == 'true'

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
        print(f"Գնի ստացման սխալ: {e}")
        return None

# Ստանալ փոխանցումները Blockchair-ից
def get_transactions(address):
    try:
        url = f"https://api.blockchair.com/dash/dashboards/address/{address}?limit=1"
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            return response.json().get('data', {}).get(address, {}).get('transactions', [])
    except Exception as e:
        print(f"Փոխանցումների ստացման սխալ: {e}")
    return []

# Ստեղծել ծանուցում
def create_notification(tx, dash_price):
    amount = sum(out['value'] for out in tx['outputs']) / 1e8
    usd_value = amount * dash_price if dash_price else 0
    time_str = datetime.fromtimestamp(tx['time']).strftime('%Y-%m-%d %H:%M')
    
    return (
        f"📥 Նոր փոխանցում #{tx['index'] + 1}\n\n"
        f"💰 Գումար: {amount:.8f} DASH (~{usd_value:.2f}$\n"
        f"⏰ Ժամ: {time_str}\n"
        f"🔗 [Դիտել Blockchair-ում](https://blockchair.com/dash/transaction/{tx['hash']})\n"
        f"🧾 TxID: {tx['hash'][:8]}..."
    )

# Հրամաններ
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Բարի գալուստ! Ուղարկեք ձեր DASH հասցեն:")

async def handle_dash_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    address = update.message.text.strip()
    data = load_data()
    
    if not is_valid_dash_address(address):
        await update.message.reply_text("❌ Սխալ հասցե: Փորձեք կրկին")
        return
    
    data['users'][str(user_id)] = address
    save_data(data)
    await update.message.reply_text(f"✅ Հասցեն գրանցված է:\n`{address}`", parse_mode='Markdown')

# Ստուգել փոխանցումները
async def check_transactions(context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    dash_price = get_dash_price()
    
    for user_id, address in data['users'].items():
        try:
            txs = get_transactions(address)
            if not txs:
                continue
                
            latest_tx = txs[0]
            tx_key = f"{user_id}_{latest_tx['hash']}"
            
            if tx_key not in data['transactions']:
                data['transactions'][tx_key] = True
                save_data(data)
                
                notification = create_notification(latest_tx, dash_price)
                await context.bot.send_message(
                    chat_id=user_id,
                    text=notification,
                    parse_mode='Markdown',
                    disable_web_page_preview=True
                )
        except Exception as e:
            print(f"Սխալ օգտատիրոջ {user_id} համար: {e}")

# Գործարկել բոտը
def main():
    app = Application.builder().token(TOKEN).build()
    
    # Հրամաններ
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_dash_address))
    
    # Աշխատանքային հերթ
    app.job_queue.run_repeating(check_transactions, interval=30.0, first=5.0)
    
    if RENDER:
        PORT = int(os.getenv('PORT', 10000))
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/",
            secret_token="DASH_SECRET_123"  # Փոխարինեք ձեր գաղտնաբառով
        )
    else:
        app.run_polling()

if __name__ == "__main__":
    main()
