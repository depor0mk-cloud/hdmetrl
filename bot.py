import os
import json
import asyncio
import firebase_admin
from firebase_admin import credentials, db
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

# 1. ПОДКЛЮЧАЕМ FIREBASE
try:
    # Берем данные из секрета GitHub
    cert_json = os.getenv("FIREBASE_JSON")
    cert_dict = json.loads(cert_json)
    
    cred = credentials.Certificate(cert_dict)
    firebase_admin.initialize_app(cred, {
        # Твой правильный европейский адрес:
        'databaseURL': 'https://lbmetr-default-rtdb.europe-west1.firebasedatabase.app'
    })
    print("Firebase успешно подключен! ✅")
except Exception as e:
    print(f"Ошибка Firebase: {e}")

# 2. НАСТРОЙКА БОТА
# Берем токен из секрета GitHub
API_TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Обработка команд /start и /grow
@dp.message(Command("start", "grow"))
async def cmd_grow(message: types.Message):
    user_id = str(message.from_user.id)
    # Путь в базе данных
    ref = db.reference(f'users/{user_id}')
    
    user_data = ref.get()
    
    if not user_data:
        size = 1
        ref.set({'size': size})
        await message.answer(f"Привет! Твой метр начал расти. Сейчас он: {size} см 📏")
    else:
        # Увеличиваем размер на 1
        new_size = user_data.get('size', 0) + 1
        ref.update({'size': new_size})
        await message.answer(f"Ого! Твой метр вырос. Теперь он: {new_size} см 📏")

# Главная функция запуска
async def main():
    print("Бот запущен и слушает сообщения...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
