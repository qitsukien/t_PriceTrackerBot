import os
import asyncio
import sqlite3
import requests
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils import executor
from bs4 import BeautifulSoup

# ====== Настройки ======
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")  # токен через переменную окружения
CHECK_INTERVAL = 3600  # проверка цен каждые 60 минут

# ====== Инициализация бота ======
bot = Bot(token=TOKEN)
dp = Dispatcher(bot)

# ====== База данных ======
conn = sqlite3.connect("products.db")
c = conn.cursor()
c.execute('''
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    marketplace TEXT,
    product_id TEXT,
    last_price REAL,
    url TEXT
)
''')
conn.commit()

# ====== /start ======
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я отслеживаю цены на OZON и WB.\n"
        "Команды:\n"
        "/add - добавить товар\n"
        "/list - показать список\n"
        "/remove - удалить товар"
    )

# ====== /add ======
@dp.message_handler(commands=['add'])
async def cmd_add(message: types.Message):
    await message.answer("Отправьте ссылку на товар для отслеживания:")

# ====== Добавление товара ======
@dp.message_handler(lambda message: "http" in message.text)
async def add_product(message: types.Message):
    url = message.text.strip()
    marketplace = "OZON" if "ozon" in url else "WB" if "wildberries" in url or "wb.ru" in url else None
    if not marketplace:
        await message.answer("Поддерживаются только OZON и WB.")
        return

    product_id = extract_id(url, marketplace)
    if not product_id:
        await message.answer("Не удалось извлечь ID товара.")
        return

    price = get_price(url, marketplace)
    if price is None:
        await message.answer("Не удалось получить цену товара.")
        return

    c.execute(
        "INSERT INTO products (user_id, marketplace, product_id, last_price, url) VALUES (?, ?, ?, ?, ?)",
        (message.from_user.id, marketplace, product_id, price, url)
    )
    conn.commit()
    await message.answer(f"Товар добавлен.\nТекущая цена: {price} ₽")

# ====== /list ======
@dp.message_handler(commands=['list'])
async def cmd_list(message: types.Message):
    c.execute("SELECT id, marketplace, url, last_price FROM products WHERE user_id=?", (message.from_user.id,))
    rows = c.fetchall()
    if not rows:
        await message.answer("Список пуст.")
        return

    for row in rows:
        item_id, marketplace, url, price = row
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("Удалить", callback_data=f"del_{item_id}"))
        await message.answer(f"[{marketplace}] {url}\nЦена: {price} ₽", reply_markup=kb)

# ====== Inline кнопка для удаления ======
@dp.callback_query_handler(lambda c: c.data.startswith("del_"))
async def del_callback(call: types.CallbackQuery):
    item_id = int(call.data.split("_")[1])
    c.execute("DELETE FROM products WHERE id=?", (item_id,))
    conn.commit()
    await call.message.edit_text("Товар удалён.")
    await call.answer()

# ====== Получение ID товара ======
def extract_id(url, marketplace):
    if marketplace == "WB":
        if "nm=" in url:
            return url.split("nm=")[-1].split("&")[0]
        else:
            return url.rstrip("/").split("-")[-1]
    elif marketplace == "OZON":
        return url.rstrip("/").split("/")[-1].split("?")[0]
    return None

# ====== Парсер OZON с fallback-селекторами ======
def get_price_ozon(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers)
        soup = BeautifulSoup(resp.text, "html.parser")

        # список селекторов для цены
        selectors = [
            {"tag": "span", "class": "f0g"},  # основной
            {"tag": "div", "class": "a0g"},   # запасной
            {"tag": "meta", "itemprop": "price"}  # fallback meta
        ]

        for sel in selectors:
            if sel["tag"] == "meta":
                price_tag = soup.find("meta", itemprop="price")
                if price_tag and price_tag.get("content"):
                    return float(price_tag["content"])
            else:
                price_tag = soup.find(sel["tag"], class_=sel["class"])
                if price_tag:
                    price_text = "".join(filter(str.isdigit, price_tag.text))
                    if price_text:
                        return float(price_text)

        print(f"[OZON] Не удалось найти цену для {url}")
        return None
    except Exception as e:
        print(f"[OZON] Ошибка при получении цены: {e}")
        return None

# ====== Получение цены ======
def get_price(url, marketplace):
    try:
        if marketplace == "WB":
            product_id = extract_id(url, "WB")
            resp = requests.get(f"https://card.wb.ru/cards/detail?nm={product_id}&locale=ru")
            data = resp.json()
            return data['data']['products'][0]['priceU'] / 100
        elif marketplace == "OZON":
            return get_price_ozon(url)
    except Exception as e:
        print("Ошибка при получении цены:", e)
        return None

# ====== Проверка цен ======
async def price_checker():
    while True:
        c.execute("SELECT * FROM products")
        rows = c.fetchall()
        for row in rows:
            user_id, marketplace, product_id, last_price, url = row[1:6]
            new_price = get_price(url, marketplace)
            if new_price is not None and new_price != last_price:
                await bot.send_message(user_id, f"Цена изменилась на {url}:\n{last_price} ₽ → {new_price} ₽")
                c.execute("UPDATE products SET last_price=? WHERE id=?", (new_price, row[0]))
                conn.commit()
        await asyncio.sleep(CHECK_INTERVAL)

# ====== Запуск бота ======
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(price_checker())
    executor.start_polling(dp, skip_updates=True)