import os
import json
import asyncio
import random
import time
import firebase_admin
from firebase_admin import credentials, db
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message

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

# ID админа (лучше по user_id, но пока по username)
ADMIN_USERNAME = "trim_peek"  # без @

# Константы
CD_NORMAL = 15 * 60          # 15 минут
CD_PROFI = 10 * 60           # 10 минут
PROFI_THRESHOLD = 1000.0
CANCER_CHANCE = 0.005        # 0.5%

@dp.message(Command("toplobok"))
async def cmd_top(message: Message):
    ref = db.reference('users')
    users = ref.get()
    if not users:
        await message.answer("📊 Топ пока пуст! Используй /lobok, чтобы попасть в рейтинг.")
        return
    
    top_list = []
    for uid, data in users.items():
        if isinstance(data, dict):
            size = data.get('size', 0)
            if size > 0:
                name = data.get('display_name', 'Инкогнито')
                if name.startswith('@'):
                    name = name[1:]
                top_list.append({'name': name, 'size': size})
    
    top_list.sort(key=lambda x: x['size'], reverse=True)
    
    if not top_list:
        await message.answer("📊 Топ пока пуст! Используй /lobok, чтобы попасть в рейтинг.")
        return
    
    text = "🏆 **ГЛОБАЛЬНЫЙ ТОП-30** 🏆\n\n"
    for i, user in enumerate(top_list[:30], 1):
        medal = ""
        if i == 1:
            medal = "🥇 "
        elif i == 2:
            medal = "🥈 "
        elif i == 3:
            medal = "🥉 "
        text += f"{medal}{i}. {user['name']} — {user['size']:.2f} см\n"
    
    total = len(top_list)
    avg = sum(u['size'] for u in top_list) / total if total else 0
    text += f"\n📊 **Всего игроков:** {total}\n📈 **Средний размер:** {avg:.2f} см"
    
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("lobok"))
async def cmd_grow(message: Message):
    if message.chat.type == 'private':
        await message.answer("❌ Добавь меня в группу, чтобы растить лобок!")
        return
    
    user_id = str(message.from_user.id)
    user_name = message.from_user.first_name
    display_name = user_name
    mention = f"[{user_name}](tg://user?id={user_id})"
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
    
    # Определяем КД в зависимости от размера
    current_size = user_data.get('size', 0)
    cd_seconds = CD_PROFI if current_size >= PROFI_THRESHOLD else CD_NORMAL
    
    last_grow = user_data.get('last_grow', 0)
    if current_time < last_grow + cd_seconds:
        rem = (last_grow + cd_seconds) - current_time
        minutes = rem // 60
        seconds = rem % 60
        await message.reply(f"⏳ {mention}, лобок ещё не восстановился! Подожди ещё {minutes}м {seconds}с.", parse_mode="Markdown")
        return
    
    # Шанс на рак
    if random.random() < CANCER_CHANCE:
        five_h = 5 * 60 * 60
        ref.update({
            'cancer_until': current_time + five_h,
            'display_name': display_name
            # last_grow не трогаем, чтобы после лечения не было лишнего КД
        })
        await message.reply(f"☣️ {mention}, ПЛОХИЕ НОВОСТИ! У тебя развился рак лобка. Рост заблокирован на 5 часов.", parse_mode="Markdown")
        return
    
    # Определяем диапазон роста в зависимости от статуса профи
    if current_size >= PROFI_THRESHOLD:
        growth = round(random.uniform(10.0, 20.0), 2)
    else:
        growth = round(random.uniform(1.0, 5.0), 2)
    
    new_size = round(current_size + growth, 2)
    
    ref.update({
        'size': new_size,
        'last_grow': current_time,
        'display_name': display_name
    })
    
    # Если перешагнули порог профи, добавим поздравление
    if current_size < PROFI_THRESHOLD <= new_size:
        await message.reply(
            f"🎉 {mention}, ПОЗДРАВЛЯЮ! Твой лобок превысил 1000 см! Теперь ты ПРОФИ и получаешь +10-20 см за раз! 🍈\n\n"
            f"Твой лобок вырос на {growth} см! 📏\n"
            f"Текущий размер — {new_size} см. 🍈",
            parse_mode="Markdown"
        )
    else:
        await message.reply(
            f"{mention}, твой лобок вырос на {growth} см! 📏\n"
            f"Текущий размер — {new_size} см. 🍈",
            parse_mode="Markdown"
        )

@dp.message(Command("editlobok"))
async def cmd_edit_lobok(message: Message):
    """Установить имя своему лобку."""
    if message.chat.type == 'private':
        await message.answer("❌ Эта команда работает только в группах!")
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Укажи имя для лобка. Пример:\n/editlobok Мой Большой Друг")
        return
    
    lobok_name = args[1].strip()
    if len(lobok_name) > 50:
        await message.answer("❌ Слишком длинное имя (макс. 50 символов).")
        return
    
    user_id = str(message.from_user.id)
    ref = db.reference(f'users/{user_id}')
    user_data = ref.get() or {}
    
    # Сохраняем имя лобка
    ref.update({'lobok_name': lobok_name})
    
    await message.reply(f"✅ Имя твоего лобка сохранено: «{lobok_name}»")

@dp.message(Command("lobokinfo"))
async def cmd_lobok_info(message: Message):
    """Показать информацию о себе и лобке."""
    if message.chat.type == 'private':
        await message.answer("❌ Эта команда работает только в группах!")
        return
    
    user_id = str(message.from_user.id)
    ref = db.reference(f'users/{user_id}')
    user_data = ref.get()
    
    if not user_data:
        await message.answer("❌ Ты ещё не начинал рост! Напиши /lobok")
        return
    
    size = user_data.get('size', 0)
    lobok_name = user_data.get('lobok_name', 'Безымянный')
    display_name = user_data.get('display_name', message.from_user.first_name)
    
    # Статус профи
    profi_status = "✅ Профи (1000+ см)" if size >= PROFI_THRESHOLD else "❌ Обычный игрок"
    
    text = (
        f"📋 **Информация о тебе**\n\n"
        f"👤 **Имя:** {display_name}\n"
        f"📏 **Размер лобка:** {size:.2f} см\n"
        f"🏷️ **Имя лобка:** {lobok_name}\n"
        f"⭐ **Статус:** {profi_status}"
    )
    
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("rak"))
async def cmd_remove_cancer(message: Message):
    """Админская команда для снятия рака. Использование: /rak @username"""
    if message.chat.type == 'private':
        await message.answer("❌ Эта команда работает только в группах!")
        return
    
    # Проверка прав (по username)
    if not message.from_user.username or message.from_user.username.lower() != ADMIN_USERNAME.lower():
        await message.answer("🚫 У тебя нет прав на использование этой команды.")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Укажи пользователя. Пример:\n/rak @username")
        return
    
    target_username = args[1].lstrip('@')  # убираем @ если есть
    
    # Ищем пользователя в чате по username
    try:
        async for member in bot.get_chat_members(message.chat.id):
            user = member.user
            if user.username and user.username.lower() == target_username.lower():
                target_id = str(user.id)
                break
        else:
            await message.answer(f"❌ Пользователь @{target_username} не найден в этом чате.")
            return
    except Exception as e:
        await message.answer("❌ Не удалось получить список участников. Попробуй позже.")
        return
    
    # Снимаем рак
    ref = db.reference(f'users/{target_id}')
    user_data = ref.get()
    if not user_data:
        await message.answer(f"❌ Пользователь @{target_username} ещё не начинал игру.")
        return
    
    cancer_until = user_data.get('cancer_until', 0)
    current_time = int(time.time())
    if current_time >= cancer_until:
        await message.answer(f"✅ У @{target_username} и так нет рака.")
        return
    
    # Убираем рак (ставим cancer_until = 0)
    ref.update({'cancer_until': 0})
    await message.answer(f"☑️ Админ @{message.from_user.username} снял рак с @{target_username}. Теперь он снова может расти!")

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "📏 **Лобкометр (обновлённая версия)**\n\n"
        "🔹 Добавь меня в группу\n"
        "🔹 Пиши /lobok каждые 15 мин (при 1000+ см — 10 мин)\n"
        "🔹 /editlobok <имя> — дай имя своему лобку\n"
        "🔹 /lobokinfo — информация о тебе\n"
        "🔹 /toplobok — глобальный рейтинг\n\n"
        "Удачи с ростом! 🍈"
    )

async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
