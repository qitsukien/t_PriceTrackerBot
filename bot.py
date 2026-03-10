import sqlite3
import requests
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext, MessageHandler, Filters

# --- База данных ---
conn = sqlite3.connect('prices.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS products
                  (id INTEGER PRIMARY KEY, user_id INTEGER, url TEXT, name TEXT, price REAL)''')
conn.commit()

# --- Парсинг ---
def get_price_and_name(url):
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    if 'wildberries' in url:
        title_tag = soup.find('h1', class_='same-name')
        name = title_tag.text.strip() if title_tag else "Товар Wildberries"
        price_tag = soup.find('ins', class_='price__current')
        price = float(price_tag.text.replace('₽','').replace(' ','').replace('\xa0','')) if price_tag else None
    elif 'ozon' in url:
        title_tag = soup.find('h1')
        name = title_tag.text.strip() if title_tag else "Товар Ozon"
        price_tag = soup.find('span', class_='a8e2')  # Проверить актуальность класса
        price = float(price_tag.text.replace('₽','').replace(' ','').replace('\xa0','')) if price_tag else None
    else:
        return None, None
    
    return price, name

# --- Команды ---
def start(update: Update, context: CallbackContext):
    update.message.reply_text("Привет! Добавляй товары для отслеживания с помощью кнопок ниже.",
                              reply_markup=main_menu())

def main_menu():
    keyboard = [
        [InlineKeyboardButton("Добавить товар", callback_data='add')],
        [InlineKeyboardButton("Мои товары", callback_data='list')],
    ]
    return InlineKeyboardMarkup(keyboard)

def add_prompt(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    query.message.reply_text("Отправь ссылку на товар с Wildberries или Ozon:")

def add_product(update: Update, context: CallbackContext):
    url = update.message.text
    price, name = get_price_and_name(url)
    if price is None:
        update.message.reply_text("Не удалось получить цену. Проверь ссылку.")
        return
    cursor.execute("INSERT INTO products (user_id, url, name, price) VALUES (?, ?, ?, ?)",
                   (update.message.from_user.id, url, name, price))
    conn.commit()
    update.message.reply_text(f"Товар '{name}' добавлен. Текущая цена: {price} ₽", reply_markup=main_menu())

def list_products(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    cursor.execute("SELECT id, name, price FROM products WHERE user_id=?", (query.from_user.id,))
    rows = cursor.fetchall()
    if not rows:
        query.message.reply_text("Нет товаров для отслеживания.", reply_markup=main_menu())
        return
    keyboard = [[InlineKeyboardButton(f"Удалить {name}", callback_data=f"del_{prod_id}")]
                for prod_id, name, price in rows]
    query.message.reply_text("Ваши товары:", reply_markup=InlineKeyboardMarkup(keyboard))

def remove_product(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    prod_id = int(query.data.split("_")[1])
    cursor.execute("DELETE FROM products WHERE id=? AND user_id=?", (prod_id, query.from_user.id))
    conn.commit()
    query.message.reply_text("Товар удалён.", reply_markup=main_menu())

# --- Проверка цен ---
def check_prices(context: CallbackContext):
    cursor.execute("SELECT id, user_id, url, price, name FROM products")
    for prod_id, user_id, url, old_price, name in cursor.fetchall():
        new_price, _ = get_price_and_name(url)
        if new_price and new_price != old_price:
            context.bot.send_message(chat_id=user_id,
                                     text=f"Цена изменилась для '{name}'!\nСтарая: {old_price} ₽\nНовая: {new_price} ₽\n{url}")
            cursor.execute("UPDATE products SET price=? WHERE id=?", (new_price, prod_id))
    conn.commit()

# --- Обработчики кнопок ---
def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    if query.data == 'add':
        add_prompt(update, context)
    elif query.data == 'list':
        list_products(update, context)
    elif query.data.startswith('del_'):
        remove_product(update, context)

# --- Запуск бота ---
TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
updater = Updater(TOKEN, use_context=True)
dp = updater.dispatcher

dp.add_handler(CommandHandler("start", start))
dp.add_handler(MessageHandler(Filters.text & ~Filters.command, add_product))
dp.add_handler(CallbackQueryHandler(button_handler))

updater.job_queue.run_repeating(check_prices, interval=1800, first=10)

updater.start_polling()
updater.idle()