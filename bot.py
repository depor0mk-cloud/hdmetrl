import os
import json
import firebase_admin
from firebase_admin import credentials, db
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor

# 1. ПОДКЛЮЧАЕМ FIREBASE
try:
    # Достаем секрет из настроек GitHub
    cert_json = os.getenv("FIREBASE_JSON")
    cert_dict = json.loads(cert_json)
    
    cred = credentials.Certificate(cert_dict)
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://lbmetr-default-rtdb.firebaseio.com/'
    })
    print("Firebase подключен успешно!")
except Exception as e:
    print(f"Ошибка Firebase: {e}")

# 2. НАСТРОЙКА БОТА
API_TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# Команда /start и /grow
@dp.message_handler(commands=['start', 'grow'])
async def grow_command(message: types.Message):
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

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
