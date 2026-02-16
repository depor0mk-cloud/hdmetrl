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

spam_check = {}

@dp.message(Command("toplobok"))
async def cmd_top(message: types.Message):
    ref = db.reference('users')
    users = ref.get()
    if not users:
        await message.answer("Топ пока пуст!")
        return
    top_list = []
    for u_id in users:
        data = users[u_id]
        if isinstance(data, dict):
            name = data.get('display_name', 'Инкогнито')
            size = data.get('size', 0)
            top_list.append({'name': name, 'size': size})
    top_list.sort(key=lambda x: x['size'], reverse=True)
    text = "🏆 **ТОП-30** 🏆\n\n"
    for i, user in enumerate(top_list[:30], 1):
        text += f"{i}. {user['name']} — {user['size']} см\n"
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("lobok"))
async def cmd_grow(message: types.Message):
    if message.chat.type == 'private':
        await message.answer("❌ Добавь меня в группу, чтобы растить лобок!")
        return

    user_id = str(message.from_user.id)
    user_name = message.from_user.first_name
    display_name = f"@{message.from_user.username}" if message.from_user.username else user_name
    mention = f"@{message.from_user.username}" if message.from_user.username else f"[{user_name}](tg://user?id={user_id})"

    current_time = int(time.time())
    
    # Анти-спам
    if user_id in spam_check and current_time - spam_check[user_id] < 1:
        await message.reply("⚠️ НЕ СПАМЬ!")
        return
    spam_check[user_id] = current_time

    ref = db.reference(f'users/{user_id}')
    user_data = ref.get() or {}

    # 1. ПРОВЕРКА НА РАК (самая главная)
    cancer_until = user_data.get('cancer_until', 0)
    if current_time < cancer_until:
        rem = cancer_until - current_time
        h, m, s = rem // 3600, (rem % 3600) // 60, rem % 60
        await message.reply(f"🚨 {mention}, у тебя рак лобка! До конца лечения: {h}ч {m}м {s}с")
        return

    # 2. ПРОВЕРКА КД
    last_grow = user_data.get('last_grow', 0)
    cd_sec = 5 * 60 
    # Если прошло меньше 300 секунд - от ворот поворот
    if current_time < last_grow + cd_sec:
        rem = (last_grow + cd_sec) - current_time
        m, s = rem // 60, rem % 60
        await message.reply(f"⏳ {mention}, лобок еще не восстановился! Подожди еще {m}м {s}с.")
        return

    # --- ЕСЛИ ПРОШЛИ ПРОВЕРКИ, РАСТИМ ---

    # 3. ШАНС РАКА (5%)
    if random.random() < 0.05:
        five_h = 5 * 60 * 60
        ref.update({
            'cancer_until': current_time + five_h,
            'display_name': display_name
        })
        await message.reply(f"☣️ {mention}, ПЛОХИЕ НОВОСТИ! У тебя развился рак лобка. Рост заблокирован на 5 часов.")
        return

    # 4. САМ РОСТ
    growth = round(random.uniform(1.0, 5.0), 2)
    current_size = user_data.get('size', 0)
    new_size = round(current_size + growth, 2)

    # Записываем НОВОЕ время роста ТОЛЬКО ЗДЕСЬ
    ref.update({
        'size': new_size,
        'last_grow': current_time,
        'display_name': display_name
    })

    await message.reply(
        f"{mention}, твой лобок вырос на {growth} см! 📏\n"
        f"Текущий размер — {new_size} см. 🍈",
        parse_mode="Markdown"
    )

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("📏 Бот готов! Добавь меня в чат и пиши /lobok")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
