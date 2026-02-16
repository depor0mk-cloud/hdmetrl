import asyncio
import random
import time
import os
import json
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
import firebase_admin
from firebase_admin import credentials, db

# Берем данные из секретов GitHub (чтобы никто не украл)
BOT_TOKEN = os.getenv("BOT_TOKEN")
FIREBASE_CONFIG = os.getenv("FIREBASE_JSON")
DATABASE_URL = "https://lbmetr-default-rtdb.europe-west1.firebasedatabase.app/"

# Авторизация в Firebase
if FIREBASE_CONFIG:
    cred_json = json.loads(FIREBASE_CONFIG)
    cred = credentials.Certificate(cred_json)
    firebase_admin.initialize_app(cred, {'databaseURL': DATABASE_URL})

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- МАТЕМАТИКА РОСТА ---
def calculate_growth():
    chance = random.random()
    # Шанс на бритву (0.0001% = 0.000001 в коде)
    if chance <= 0.000001:
        return "shave", 0
    elif chance <= 0.70: # 70% на рост
        return "grow", random.randint(1, 10)
    elif chance <= 0.90: # 20% на посидеть на месте
        return "stay", 0
    else: # 10% на уменьшение
        return "shrink", random.randint(1, 5)

# --- КОМАНДЫ ---

@dp.message(Command("grow"))
async def grow_command(message: types.Message):
    user_id = str(message.from_user.id)
    user_name = message.from_user.full_name
    ref = db.reference(f'users/{user_id}')
    user_data = ref.get()

    now = int(time.time())
    
    # КД 5 минут (300 секунд)
    if user_data and (now - user_data.get('last_time', 0)) < 300:
        left = 300 - (now - user_data.get('last_time', 0))
        await message.reply(f"⏳ Рано! Корни еще сохнут. Жди {left} сек.")
        return

    current_len = user_data.get('length', 0) if user_data else 0
    event, value = calculate_growth()

    if event == "shave":
        new_len = 0
        msg = "😱 УПС! На лобок упала бритва... Всё сбрито под ноль!"
    elif event == "grow":
        new_len = current_len + value
        msg = f"🌿 Ого, джунгли растут! +{value} см."
    elif event == "shrink":
        new_len = max(0, current_len - value)
        msg = f"✂️ Неудачный тримминг... -{value} см."
    else:
        new_len = current_len
        msg = "💤 Никаких изменений. Попробуй через 5 минут."

    ref.set({
        'length': new_len,
        'last_time': now,
        'name': user_name
    })

    await message.reply(f"{msg}\n📏 Твоя длина: **{new_len} см**")

@dp.message(Command("top"))
async def top_command(message: types.Message):
    users_ref = db.reference('users').get()
    if not users_ref:
        await message.reply("Тут пока лысая пустыня...")
        return

    # Сортировка по длине
    sorted_users = sorted(users_ref.items(), key=lambda x: x[1].get('length', 0), reverse=True)
    
    top_msg = "🏆 **ТОП КУСТОВ ЧАТА:**\n\n"
    for i, (uid, data) in enumerate(sorted_users[:10], 1):
        name = data.get('name', 'Аноним')
        length = data.get('length', 0)
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "▫️"
        top_msg += f"{medal} {i}. {name} — {length} см\n"
    
    await message.answer(top_msg)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
