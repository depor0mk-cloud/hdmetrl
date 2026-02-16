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
    # Убрали фильтрацию по чату — показываем ВСЕХ игроков (глобальный топ)
    ref = db.reference('users')
    users = ref.get()
    if not users:
        await message.answer("📊 Топ пока пуст! Используй /lobok, чтобы попасть в рейтинг.")
        return
    
    top_list = []
    for u_id, data in users.items():
        if isinstance(data, dict):
            size = data.get('size', 0)
            if size > 0:
                # Берём имя: если есть display_name, убираем @ если он там есть
                name = data.get('display_name', 'Инкогнито')
                if name.startswith('@'):
                    name = name[1:]  # убираем @
                top_list.append({'name': name, 'size': size})
    
    top_list.sort(key=lambda x: x['size'], reverse=True)
    
    if not top_list:
        await message.answer("📊 В этом чате пока нет игроков! Напиши /lobok, чтобы начать.")
        return
    
    text = "🏆 **ГЛОБАЛЬНЫЙ ТОП-30** 🏆\n\n"
    for i, user in enumerate(top_list[:30], 1):
        # Медальки для первых трёх
        medal = ""
        if i == 1:
            medal = "🥇 "
        elif i == 2:
            medal = "🥈 "
        elif i == 3:
            medal = "🥉 "
        text += f"{medal}{i}. {user['name']} — {user['size']:.2f} см\n"
    
    # Статистика
    total = len(top_list)
    avg = sum(u['size'] for u in top_list) / total if total > 0 else 0
    text += f"\n📊 **Всего игроков:** {total}\n📈 **Средний размер:** {avg:.2f} см"
    
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("lobok"))
async def cmd_grow(message: types.Message):
    if message.chat.type == 'private':
        await message.answer("❌ Добавь меня в группу, чтобы растить лобок!")
        return
    
    user_id = str(message.from_user.id)
    user_name = message.from_user.first_name
    # Для отображения в БД сохраняем просто имя (без @)
    display_name = user_name
    mention = f"[{user_name}](tg://user?id={user_id})"  # для ответов используем mention без @
    current_time = int(time.time())
    
    # Анти-спам
    if user_id in spam_check and current_time - spam_check[user_id] < 1:
        await message.reply("⚠️ НЕ СПАМЬ!")
        return
    spam_check[user_id] = current_time
    
    ref = db.reference(f'users/{user_id}')
    user_data = ref.get() or {}
    
    # Проверка на рак
    cancer_until = user_data.get('cancer_until', 0)
    if current_time < cancer_until:
        rem = cancer_until - current_time
        h, m, s = rem // 3600, (rem % 3600) // 60, rem % 60
        await message.reply(f"🚨 {mention}, у тебя рак лобка! До конца лечения: {h}ч {m}м {s}с", parse_mode="Markdown")
        return
    
    # Проверка КД
    last_grow = user_data.get('last_grow', 0)
    cd_sec = 5 * 60 
    if current_time < last_grow + cd_sec:
        rem = (last_grow + cd_sec) - current_time
        m, s = rem // 60, rem % 60
        await message.reply(f"⏳ {mention}, лобок еще не восстановился! Подожди еще {m}м {s}с.", parse_mode="Markdown")
        return
    
    # Шанс на рак (5%)
    if random.random() < 0.05:
        five_h = 5 * 60 * 60
        # ВАЖНО: не обновляем last_grow при раке, чтобы после лечения не было лишнего КД
        ref.update({
            'cancer_until': current_time + five_h,
            'display_name': display_name
            # last_grow не трогаем!
        })
        await message.reply(f"☣️ {mention}, ПЛОХИЕ НОВОСТИ! У тебя развился рак лобка. Рост заблокирован на 5 часов.", parse_mode="Markdown")
        return
    
    # Нормальный рост
    growth = round(random.uniform(1.0, 5.0), 2)
    current_size = user_data.get('size', 0)
    new_size = round(current_size + growth, 2)
    
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
    await message.answer(
        "📏 **Лобкометр запущен!**\n\n"
        "🔹 Добавь меня в группу\n"
        "🔹 Пиши /lobok каждые 5 минут\n"
        "🔹 Смотри /toplobok — глобальный рейтинг\n\n"
        "Удачи с ростом! 🍈"
    )

async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
