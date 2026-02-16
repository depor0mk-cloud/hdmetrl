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

# Константы
ADMIN_USERNAME = "trim_peek"           # админ (без @)
CD_NORMAL = 15 * 60                    # 15 минут
CD_PROFI = 10 * 60                     # 10 минут
PROFI_THRESHOLD = 1000.0
CANCER_CHANCE = 0.005                   # 0.5%
CANCER_DURATION = 5 * 60 * 60           # 5 часов в секундах

@dp.message(Command("toplobok"))
async def cmd_top(message: Message):
    """Глобальный топ-30."""
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

def has_cancer(user_data: dict, current_time: int = None) -> tuple:
    """
    Проверяет, есть ли у пользователя рак.
    Возвращает (есть_рак, оставшееся_время_в_сек, причина)
    """
    if current_time is None:
        current_time = int(time.time())
    
    # 1. Проверяем новое поле cancer
    cancer_flag = user_data.get('cancer')
    if cancer_flag == "Yes":
        # Смотрим время окончания (если есть)
        cancer_until = user_data.get('cancer_until', 0)
        if cancer_until > current_time:
            return True, cancer_until - current_time, "cancer_flag"
        elif cancer_until > 0:
            # Время вышло, но флаг всё ещё Yes - исправляем
            return False, 0, "auto_fix"
    
    # 2. Проверяем старое поле cancer_until (для совместимости)
    cancer_until = user_data.get('cancer_until', 0)
    if cancer_until > current_time:
        return True, cancer_until - current_time, "old_system"
    
    return False, 0, "no_cancer"

@dp.message(Command("lobok"))
async def cmd_grow(message: Message):
    """Увеличить лобок."""
    if message.chat.type == 'private':
        await message.answer("❌ Добавь меня в группу, чтобы растить лобок!")
        return
    
    user_id = str(message.from_user.id)
    user_name = message.from_user.first_name
    username = message.from_user.username
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
    
    # Всегда обновляем display_name и username
    update_data = {'display_name': display_name}
    if username:
        update_data['username'] = username.lower()
    ref.update(update_data)
    
    # Проверка на рак (используем новую функцию)
    has_c, remain, reason = has_cancer(user_data, current_time)
    
    # Если рак был по времени, но флаг не исправлен - исправляем
    if reason == "auto_fix":
        ref.update({'cancer': "No", 'cancer_until': 0})
        has_c = False
    
    if has_c:
        h, m, s = remain // 3600, (remain % 3600) // 60, remain % 60
        await message.reply(
            f"🚨 {mention}, у тебя рак лобка! До конца лечения: {h}ч {m}м {s}с",
            parse_mode="Markdown"
        )
        return
    
    # Определяем КД в зависимости от размера
    current_size = user_data.get('size', 0)
    cd_seconds = CD_PROFI if current_size >= PROFI_THRESHOLD else CD_NORMAL
    
    last_grow = user_data.get('last_grow', 0)
    if current_time < last_grow + cd_seconds:
        rem = (last_grow + cd_seconds) - current_time
        minutes = rem // 60
        seconds = rem % 60
        await message.reply(
            f"⏳ {mention}, лобок ещё не восстановился! Подожди ещё {minutes}м {seconds}с.",
            parse_mode="Markdown"
        )
        return
    
    # Шанс на рак
    if random.random() < CANCER_CHANCE:
        ref.update({
            'cancer': "Yes",
            'cancer_until': current_time + CANCER_DURATION
            # last_grow не трогаем
        })
        await message.reply(
            f"☣️ {mention}, ПЛОХИЕ НОВОСТИ! У тебя развился рак лобка. Рост заблокирован на 5 часов.",
            parse_mode="Markdown"
        )
        return
    
    # Определяем диапазон роста
    if current_size >= PROFI_THRESHOLD:
        growth = round(random.uniform(10.0, 20.0), 2)
    else:
        growth = round(random.uniform(1.0, 5.0), 2)
    
    new_size = round(current_size + growth, 2)
    
    ref.update({
        'size': new_size,
        'last_grow': current_time,
    })
    
    # Если перешагнули порог профи
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
    username = message.from_user.username
    
    update_data = {
        'lobok_name': lobok_name,
        'display_name': message.from_user.first_name
    }
    if username:
        update_data['username'] = username.lower()
    
    ref.update(update_data)
    
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
    
    current_time = int(time.time())
    size = user_data.get('size', 0)
    lobok_name = user_data.get('lobok_name', 'Безымянный')
    display_name = user_data.get('display_name', message.from_user.first_name)
    
    # Статус профи
    profi_status = "✅ Профи (1000+ см)" if size >= PROFI_THRESHOLD else "❌ Обычный игрок"
    
    # Статус рака через новую функцию
    has_c, remain, _ = has_cancer(user_data, current_time)
    
    if has_c:
        h, m, s = remain // 3600, (remain % 3600) // 60, remain % 60
        cancer_status = f"☣️ **БОЛЕН** (осталось {h}ч {m}м {s}с)"
    else:
        cancer_status = "✅ Здоров"
    
    text = (
        f"📋 **Информация о тебе**\n\n"
        f"👤 **Имя:** {display_name}\n"
        f"📏 **Размер лобка:** {size:.2f} см\n"
        f"🏷️ **Имя лобка:** {lobok_name}\n"
        f"⭐ **Статус:** {profi_status}\n"
        f"🩺 **Рак:** {cancer_status}"
    )
    
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("rak"))
async def cmd_toggle_cancer(message: Message):
    """Админская команда для переключения рака. Использование: /rak @username [Yes/No]"""
    if message.chat.type == 'private':
        await message.answer("❌ Эта команда работает только в группах!")
        return
    
    # Проверка прав
    if not message.from_user.username or message.from_user.username.lower() != ADMIN_USERNAME.lower():
        await message.answer("🚫 У тебя нет прав на использование этой команды.")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Укажи пользователя. Пример:\n/rak @username Yes\n/rak @username No")
        return
    
    target_username = args[1].lstrip('@').lower()
    
    # Определяем действие (если указано)
    action = None
    if len(args) >= 3:
        action = args[2].capitalize()
        if action not in ["Yes", "No"]:
            await message.answer("❌ Укажи Yes или No. Пример: /rak @username Yes")
            return
    
    # Ищем пользователя в базе
    ref = db.reference('users')
    all_users = ref.get()
    
    if not all_users:
        await message.answer("❌ В базе пока нет пользователей.")
        return
    
    target_id = None
    target_data = None
    target_name = None
    
    for uid, user_data in all_users.items():
        if not isinstance(user_data, dict):
            continue
        
        # Проверяем username из БД
        saved_username = user_data.get('username', '').lower()
        saved_name = user_data.get('display_name', '').lower()
        
        if target_username == saved_username or target_username in saved_name:
            target_id = uid
            target_data = user_data
            target_name = user_data.get('display_name', 'Пользователь')
            break
    
    if not target_id:
        await message.answer(f"❌ Пользователь @{target_username} не найден в базе данных.")
        return
    
    current_time = int(time.time())
    has_c, remain, _ = has_cancer(target_data, current_time)
    
    # Если действие не указано - показываем текущий статус
    if action is None:
        status = "болен 🤒" if has_c else "здоров 💪"
        if has_c:
            h, m, s = remain // 3600, (remain % 3600) // 60, remain % 60
            time_left = f" (осталось {h}ч {m}м {s}с)"
        else:
            time_left = ""
        
        await message.answer(
            f"📊 **Статус пользователя** @{target_username}\n\n"
            f"👤 Имя: {target_name}\n"
            f"🩺 Рак: {status}{time_left}\n\n"
            f"Чтобы изменить, напиши:\n"
            f"/rak @{target_username} Yes — дать рак\n"
            f"/rak @{target_username} No — вылечить",
            parse_mode="Markdown"
        )
        return
    
    # Изменяем статус
    user_ref = db.reference(f'users/{target_id}')
    
    if action == "Yes":
        # Даём рак на 5 часов
        user_ref.update({
            'cancer': "Yes",
            'cancer_until': current_time + CANCER_DURATION
        })
        await message.answer(
            f"☣️ **Админ @{message.from_user.username} выдал рак**\n"
            f"👤 Пользователь: {target_name}\n"
            f"⏱️ Срок: 5 часов\n"
            f"🤒 Теперь пусть мучается!",
            parse_mode="Markdown"
        )
        print(f"☣️ Админ @{message.from_user.username} выдал рак @{target_username}")
    
    else:  # action == "No"
        # Снимаем рак
        user_ref.update({
            'cancer': "No",
            'cancer_until': 0
        })
        await message.answer(
            f"💊 **Админ @{message.from_user.username} вылечил рак**\n"
            f"👤 Пользователь: {target_name}\n"
            f"✅ Теперь он снова может расти!",
            parse_mode="Markdown"
        )
        print(f"💊 Админ @{message.from_user.username} вылечил рак @{target_username}")

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "📏 **Лобкометр (обновлённая версия)**\n\n"
        "🔹 Добавь меня в группу\n"
        "🔹 Пиши /lobok — каждые 15 мин (при 1000+ см — 10 мин)\n"
        "🔹 /editlobok <имя> — дай имя своему лобку\n"
        "🔹 /lobokinfo — информация о тебе\n"
        "🔹 /toplobok — глобальный рейтинг\n\n"
        "**Для админа:**\n"
        "🔹 /rak @username — проверить статус\n"
        "🔹 /rak @username Yes — выдать рак\n"
        "🔹 /rak @username No — вылечить\n\n"
        "Удачи с ростом! 🍈"
    )

async def main():
    print("✅ Бобёр с новой системой рака запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
