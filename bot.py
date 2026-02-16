import os
import json
import asyncio
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
        'databaseURL': 'https://lbmetr-default-rtdb.firebaseio.com/'
    })
except Exception as e:
    print(f"Firebase error: {e}")

# 2. BOT SETUP
bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()

# Обработка команд /start и /grow
@dp.message(Command("start", "grow"))
async def cmd_grow(message: types.Message):
    user_id = str(message.from_user.id)
    ref = db.reference(f'users/{user_id}')
    user_data = ref.get()

    if not user_data:
        size = 1
        ref.set({'size': size})
        await message.answer(f"Привет! Твой метр начал расти. Сейчас он: {size} см 📏")
    else:
        size = user_data.get('size', 0) + 1
        ref.update({'size': size})
        await message.answer(f"Ого! Твой метр вырос. Теперь он: {size} см 📏")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
