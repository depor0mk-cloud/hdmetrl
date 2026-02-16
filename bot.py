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

# Приветствие при /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я Лобкометр. 📏\n\n"
        "Здесь всё серьезно — растим, замеряем, гордимся.\n"
        "Чтобы начать рост, вводи команду: /lobok"
    )

# Основная команда /lobok
@dp.message(Command("lobok"))
async def cmd_grow(message: types.Message):
    user_id = str(message.from_user.id)
    user_name = message.from_user.first_name
    ref = db.reference(f'users/{user_id}')
    user_data = ref.get()

    current_time = int(time.time())
    cd_seconds = 5 * 60  # 5 минут в секундах

    # Проверяем КД
    if user_data and 'last_grow' in user_data:
        last_grow = user_data['last_grow']
        if current_time - last_grow < cd_seconds:
            seconds_left = cd_seconds - (current_time - last_grow)
            minutes_left = seconds_left // 60
            await message.answer(f"Рано еще! ⏳ Подожди еще {minutes_left} мин. и попробуй снова.")
            return

    # Генерируем рост (от 1.00 до 5.00 см)
    growth = round(random.uniform(1.0, 5.0), 2)
    
    if not user_data:
        new_size = growth
    else:
        current_size = user_data.get('size', 0)
        new_size = round(current_size + growth, 2)

    # Сохраняем всё в базу (ОБЯЗАТЕЛЬНО update)
    ref.update({
        'size': new_size,
        'last_grow': current_time
    })

    # ТВОЕ ОФОРМЛЕНИЕ
    text = (
        f"{user_name}, твой лобок вырос на {growth} см! 📏\n"
        f"Текущий размер — {new_size} см. 🍈"
    )
    await message.answer(text)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
