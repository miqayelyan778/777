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
    ContextTypes,
    JobQueue
)
from dotenv import load_dotenv

# Կարգավորումներ
load_dotenv()
TOKEN = os.getenv('TELEGRAM_TOKEN')
RENDER = os.getenv('RENDER', '').lower() == 'true'

# Տվյալների պահպանում JSON ֆայլում
def save_data(data):
    with open('data/storage.json', 'w') as f:
        json.dump(data, f, indent=4)

def load_data():
    try:
        with open('data/storage.json', 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"users": {}, "cache": {}}

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
        print(f"Error fetching price: {e}")
        return None

# Ստանալ փոխանցումները Blockchair-ից
def get_transactions(address):
    try:
        url = f"https://api.blockchair.com/dash/dashboards/address/{address}?limit=1"
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            return response.json().get('data', {}).get(address, {}).get('transactions', [])
        elif response.status_code == 429:  # Too Many Requests
            time.sleep(10)
            return []
    except Exception as e:
        print(f"Error fetching transactions: {e}")
        return []

# Ստեղծել ծանուցում
def create_notification(tx, dash_price):
    amount = sum(out['value'] for out in tx['outputs']) / 1e8
    usd_value = amount * dash_price if dash_price else 0
    time_str = datetime.fromtimestamp(tx['time']).strftime('%Y-%m-%d %H:%M')
    
    return (
        f"📥 New Transaction #{tx['index'] + 1}\n\n"
        f"💰 Amount: {amount:.8f} DASH (~{usd_value:.2f}$)\n"
        f"⏰ Time: {time_str}\n"
        f"🔗 [View on Blockchair](https://blockchair.com/dash/transaction/{tx['hash']})\n"
        f"🧾 TxID: {tx['hash'][:8]}..."
    )

# Telegram հրամաններ
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome! Send your DASH address to receive notifications")

async def handle_dash_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    address = update.message.text.strip()
    data = load_data()
    
    if not is_valid_dash_address(address):
        await update.message.reply_text("❌ Invalid address. Try again:")
        return
    
    data['users'][str(user_id)] = address
    save_data(data)
    await update.message.reply_text(f"✅ Address registered:\n`{address}`", parse_mode='Markdown')

# Ստուգել նոր փոխանցումները
async def check_transactions(context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    dash_price = get_dash_price()
    
    for user_id, address in data['users'].items():
        last_tx_hash = data.get("cache", {}).get(address)
        new_txs = get_transactions(address)
        
        if new_txs and new_txs[0]['hash'] != last_tx_hash:
            notification = create_notification(new_txs[0], dash_price)
            await context.bot.send_message(
                chat_id=user_id,
                text=notification,
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
            # Update cache
            data["cache"] = {address: new_txs[0]['hash']}
            save_data(data)

# Գործարկել բոտը
def main():
    # Create data directory if not exists
    os.makedirs('data', exist_ok=True)
    
    app = Application.builder().token(TOKEN).build()
    
    # Verify JobQueue is initialized
    if not hasattr(app, 'job_queue'):
        print("❌ JobQueue not initialized! Ensure 'python-telegram-bot[job-queue]' is installed")
        return
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_dash_address))
    
    # Start job queue
    app.job_queue.run_repeating(check_transactions, interval=30.0, first=5.0)
    
    if RENDER:
        PORT = int(os.getenv('PORT', 10000))
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/"  # Render-ն ավտոմատ կլրացնի
            secret_token="DASH_BOT_SECRET"
        )
    else:
        app.run_polling()

if __name__ == "__main__":
    print("🚀 Starting DASH Notification Bot...")
    main()
