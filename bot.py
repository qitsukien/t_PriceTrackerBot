import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dotenv import load_dotenv

# загрузка переменных из .env
load_dotenv()

TOKEN = os.getenv("TOKEN")

if not TOKEN:
    raise ValueError("TOKEN not set")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ ТЕСТ ПРОЙДЕН — бот работает!")

def main():
    print("Бот запускается...")

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))

    print("Бот запущен ✅")
    app.run_polling()

if __name__ == "__main__":
    main()
