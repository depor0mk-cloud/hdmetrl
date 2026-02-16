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

# 2. BOT SETUP
bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()

# Обработка команды /grow
@dp.message(Command("grow"))
async def cmd_grow(message: types.Message):
    user_id = str(message.from_user.id)
    user_name = message.from_user.first_name
    ref = db.reference(f'users/{user_id}')
    user_data = ref.get()

    current_time = int(time.time())
    five_minutes = 5 * 60  # 300 секунд

    if user_data:
        last_grow = user_data.get('last_grow', 0)
        # Проверка КД (5 минут)
        if current_time - last_grow < five_minutes:
            wait_time = (five_minutes - (current_time - last_grow)) // 60
            await message.answer(f"Погоди, {user_name}! Растить можно раз в 5 минут. Осталось еще примерно {wait_time} мин. ⏳")
            return

    # Генерируем рост (целые + копейки, например от 1.00 до 3.00 см)
    growth = round(random.uniform(1.0, 3.0), 2)
    
    if not user_data:
        new_size = growth
    else:
        current_size = user_data.get('size', 0)
        new_size = round(current_size + growth, 2)

    # Сохраняем в базу размер и время последнего роста
    ref.update({
        'size': new_size,
        'last_grow': current_time
    })

    # Твоё оформление
    text = (
        f"{user_name}, твой лобок вырос на {growth} см! 📏\n"
        f"Текущий размер — {new_size} см. "
    )
    await message.answer(text)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
