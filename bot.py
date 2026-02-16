import os
import json
import asyncio
import random
import time
import firebase_admin
from firebase_admin import credentials, db
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

# 1. FIREBASE SETUP
try:
    cert_json = os.getenv("FIREBASE_JSON")
    cert_dict = json.loads(cert_json)
    cred = credentials.Certificate(cert_dict)
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://lbmetr-default-rtdb.europe-west1.firebasedatabase.app'
    })
except Exception as e:
    print(f"Firebase error: {e}")

bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()

# Хранилище для антиспама
spam_check = {}

# Команда /toplobok
@dp.message(Command("toplobok"))
async def cmd_top(message: types.Message):
    ref = db.reference('users')
    users = ref.get()

    if not users:
        await message.answer("Список пуст. Стань первым! /lobok")
        return

    top_list = []
    for user_id, data in users.items():
        name = data.get('name', 'Аноним')
        size = data.get('size', 0)
        top_list.append({'name': name, 'size': size})

    top_list.sort(key=lambda x: x['size'], reverse=True)

    text = "🏆 **ТОП-30 ЛОБКОМЕТРОВ ЧАТА** 🏆\n\n"
    for i, user in enumerate(top_list[:30], 1):
        text += f"{i}. {user['name']} — {user['size']} см\n"

    await message.answer(text, parse_mode="Markdown")

# Команда /lobok
@dp.message(Command("lobok"))
async def cmd_grow(message: types.Message):
    user_id = str(message.from_user.id)
    user_name = message.from_user.first_name
    
    if message.from_user.username:
        mention = f"@{message.from_user.username}"
    else:
        mention = f"[{user_name}](tg://user?id={user_id})"

    current_time = int(time.time())
    
    # Анти-спам (1 сек)
    last_click = spam_check.get(user_id, 0)
    if current_time - last_click < 1:
        await message.reply("⚠️ НЕ СПАМЬ!")
        return
    spam_check[user_id] = current_time

    ref = db.reference(f'users/{user_id}')
    user_data = ref.get() or {}

    # ПРОВЕРКА НА РАК (5 часов)
    cancer_until = user_data.get('cancer_until', 0)
    if current_time < cancer_until:
        rem = cancer_until - current_time
        h = rem // 3600
        m = (rem % 3600) // 60
        s = rem % 60
        await message.reply(f"🚨 {mention}, у тебя рак лобка! Лечение: {h}ч {m}м {s}с 🚑")
        return

    # ПРОВЕРКА КД (5 минут)
    last_grow = user_data.get('last_grow', 0)
    cd_sec = 5 * 60
    if current_time - last_grow < cd_sec:
        rem = cd_sec - (current_time - last_grow)
        m = rem // 60
        s = rem % 60
        await message.reply(f"⏳ {mention}, подожди еще {m}м {s}с.")
        return

    # ШАНС РАКА (5%)
    if random.random() < 0.05:
        five_h = 5 * 60 * 60
        ref.update({'cancer_until': current_time + five_h, 'name': user_name})
        await message.reply(f"☣️ ПЛОХИЕ НОВОСТИ! {mention}, у тебя развился рак лобка. Рост заблокирован на 5 часов!")
        return

    # РОСТ (целые + копейки)
    growth = round(random.uniform(1.0, 5.0), 2)
    current_size = user_data.get('size', 0)
    new_size = round(current_size + growth, 2)

    ref.update({
        'size': new_size,
        'last_grow': current_time,
        'name': user_name
    })

    await message.reply(
        f"{mention}, твой лобок вырос на {growth} см! 📏\n"
        f"Текущий размер — {new_size} см. 🍈",
        parse_mode="Markdown"
    )

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("📏 Я Лобкометр!\nКоманды:\n/lobok — вырастить\n/toplobok — топ")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
