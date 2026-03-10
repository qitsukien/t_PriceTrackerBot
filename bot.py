import os
import json
import aiohttp
import asyncio
from bs4 import BeautifulSoup
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, Update
from telegram.ext import (
    ApplicationBuilder, CallbackQueryHandler, MessageHandler, CommandHandler, ConversationHandler,
    ContextTypes, filters
)

# ===== Настройки =====
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
CHECK_INTERVAL = 600  # Проверка каждые 10 минут
PRICES_FILE = "prices.json"
PRODUCTS_FILE = "products.json"

# ===== Состояния для Conversation =====
ADD_NAME, ADD_URL, ADD_TYPE, ADD_PERCENT, CHANGE_PERCENT = range(5)

# ===== Инициализация данных =====
products = {}
last_prices = {}

def load_json(file):
    try:
        with open(file, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=2)

products = load_json(PRODUCTS_FILE)
last_prices = load_json(PRICES_FILE)

# ===== Парсинг цен =====
async def fetch(session, url):
    headers = {"User-Agent": "Mozilla/5.0"}
    async with session.get(url, headers=headers) as response:
        return await response.text()

async def get_price_ozon(session, url):
    html = await fetch(session, url)
    soup = BeautifulSoup(html, "html.parser")
    price_tag = soup.select_one("span[data-test-id='price']")
    if price_tag:
        return int(''.join(filter(str.isdigit, price_tag.text)))
    return None

async def get_price_wb(session, url):
    html = await fetch(session, url)
    soup = BeautifulSoup(html, "html.parser")
    price_tag = soup.select_one("ins") or soup.select_one("span[class*='price']")
    if price_tag:
        return int(''.join(filter(str.isdigit, price_tag.text)))
    return None

async def get_price(session, product):
    if product["type"] == "ozon":
        return await get_price_ozon(session, product["url"])
    elif product["type"] == "wb":
        return await get_price_wb(session, product["url"])
    return None

# ===== Проверка цен =====
async def check_prices():
    async with aiohttp.ClientSession() as session:
        for key, p in products.items():
            price = await get_price(session, p)
            if price is None:
                continue
            last_price = last_prices.get(p["url"])
            percent = p.get("percent", 5)
            if last_price is None:
                last_prices[p["url"]] = price
            elif price < last_price:
                drop = ((last_price - price) / last_price) * 100
                if drop >= percent:
                    message = (
                        f"💰 Цена снизилась для {p['name']}!\n"
                        f"Старая: {last_price} ₽\nНовая: {price} ₽\n"
                        f"Снижение: {drop:.1f}%\nСсылка: {p['url']}"
                    )
                    await bot.send_message(chat_id=CHAT_ID, text=message)
                last_prices[p["url"]] = price
        save_json(PRICES_FILE, last_prices)

# ===== Команды бота =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[KeyboardButton("/list")], [KeyboardButton("/add")]]
    await update.message.reply_text(
        "Привет! Я бот для отслеживания цен.\n"
        "Используйте кнопки ниже:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )

# ===== Список товаров с кнопками =====
async def list_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not products:
        await update.message.reply_text("Список товаров пуст.")
        return
    keyboard = []
    async with aiohttp.ClientSession() as session:
        for key, p in products.items():
            price = await get_price(session, p) or last_prices.get(p["url"], "—")
            keyboard.append([
                InlineKeyboardButton(f"{p['name']} — {price} ₽ ({p.get('percent',5)}%)", callback_data=f"noop"),
                InlineKeyboardButton("Удалить", callback_data=f"delete:{key}"),
                InlineKeyboardButton("Изменить %", callback_data=f"change:{key}")
            ])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Список товаров:", reply_markup=reply_markup)

# ===== Обработка кнопок =====
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("delete:"):
        key = data.split(":")[1]
        name = products[key]["name"]
        del products[key]
        save_json(PRODUCTS_FILE, products)
        await query.edit_message_text(f"Товар '{name}' удален.")
    elif data.startswith("change:"):
        key = data.split(":")[1]
        context.user_data["edit_key"] = key
        await query.edit_message_text("Введите новый процент для уведомления:")
        return CHANGE_PERCENT

# ===== Conversation: изменить процент =====
async def change_percent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        percent = float(update.message.text)
    except ValueError:
        await update.message.reply_text("Введите число, например 5:")
        return CHANGE_PERCENT
    key = context.user_data["edit_key"]
    products[key]["percent"] = percent
    save_json(PRODUCTS_FILE, products)
    await update.message.reply_text(f"Процент уведомления для '{products[key]['name']}' изменен на {percent}%!")
    return ConversationHandler.END

# ===== Conversation: добавить товар =====
async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Введите название товара:")
    return ADD_NAME

async def add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text
    await update.message.reply_text("Введите ссылку на товар:")
    return ADD_URL

async def add_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["url"] = update.message.text
    keyboard = [[InlineKeyboardButton("Ozon", callback_data="ozon"),
                 InlineKeyboardButton("Wildberries", callback_data="wb")]]
    await update.message.reply_text("Выберите тип товара:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADD_TYPE

async def add_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    type_ = update.callback_query.data
    context.user_data["type"] = type_
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Введите процент снижения для уведомления (например 5):")
    return ADD_PERCENT

async def add_percent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        percent = float(update.message.text)
    except ValueError:
        await update.message.reply_text("Введите число, например 5:")
        return ADD_PERCENT
    key = str(len(products)+1)
    products[key] = {
        "name": context.user_data["name"],
        "url": context.user_data["url"],
        "type": context.user_data["type"],
        "percent": percent
    }
    save_json(PRODUCTS_FILE, products)
    await update.message.reply_text(f"Товар '{context.user_data['name']}' добавлен с уведомлением {percent}%!")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отмена.")
    return ConversationHandler.END

# ===== Асинхронный цикл проверки цен =====
async def price_loop(app):
    while True:
        try:
            await check_prices()
        except Exception as e:
            print("Ошибка:", e)
        await asyncio.sleep(CHECK_INTERVAL)

# ===== Запуск бота =====
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    bot = app.bot

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("list", list_products))

    conv_add = ConversationHandler(
        entry_points=[CommandHandler("add", add_start)],
        states={
            ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_name)],
            ADD_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_url)],
            ADD_TYPE: [CallbackQueryHandler(add_type, pattern="^(ozon|wb)$")],
            ADD_PERCENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_percent)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    app.add_handler(conv_add)

    conv_change = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^change:")],
        states={CHANGE_PERCENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_percent)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    app.add_handler(conv_change)

    loop = asyncio.get_event_loop()
    loop.create_task(price_loop(app))
    app.run_polling()