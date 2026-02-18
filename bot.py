import os
import json
import asyncio
import random
import time
import firebase_admin
from firebase_admin import credentials, db
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from keep_alive import keep_alive

# Запускаем Flask-заглушку для Render
keep_alive()

# Firebase setup
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
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

spam_check = {}

# Константы
ADMIN_USERNAME = "trim_peek"           # админ (без @)
CD_NORMAL = 15 * 60                    # 15 минут
CD_PROFI = 10 * 60                     # 10 минут
PROFI_THRESHOLD = 1000.0
CANCER_CHANCE = 0.005                   # 0.5%
CANCER_DURATION = 5 * 60 * 60           # 5 часов в секундах
INFINITY_VALUE = 999999999.99           # Значение для "бесконечности"

# Состояния для FSM
class AdminStates(StatesGroup):
    waiting_for_action = State()
    waiting_for_user = State()
    waiting_for_number = State()
    waiting_for_text = State()
    waiting_for_second_user = State()
    waiting_for_hours = State()
    waiting_for_minutes = State()
    action_data = State()

# Вспомогательная функция проверки наличия рака
def has_cancer(user_data: dict, current_time: int = None) -> tuple:
    if current_time is None:
        current_time = int(time.time())
    
    cancer_flag = user_data.get('cancer')
    if cancer_flag == "Yes":
        cancer_until = user_data.get('cancer_until', 0)
        if cancer_until > current_time:
            return True, cancer_until - current_time, "cancer_flag"
        elif cancer_until > 0:
            return False, 0, "auto_fix"
    
    cancer_until = user_data.get('cancer_until', 0)
    if cancer_until > current_time:
        return True, cancer_until - current_time, "old_system"
    
    return False, 0, "no_cancer"

# Поиск пользователя по username в Firebase
async def find_user_by_username(username: str):
    username = username.lower().lstrip('@')
    ref = db.reference('users')
    all_users = ref.get()
    if not all_users:
        return None
    for uid, data in all_users.items():
        if not isinstance(data, dict):
            continue
        if data.get('username') == username:
            return uid, data
        display = data.get('display_name', '').lower()
        if display == username or display == f'@{username}':
            return uid, data
    return None

# Форматирование числа с бесконечностью
def format_size(size):
    if abs(size - INFINITY_VALUE) < 0.01:
        return "∞"
    else:
        return f"{size:.2f}"

# ========== КОМАНДЫ ДЛЯ ИГРОКОВ ==========

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "📏 **Лобкометр**\n\n"
        "🔹 Добавь меня в группу\n"
        "🔹 Пиши /lobok — каждые 15 мин (при 1000+ см — 10 мин)\n"
        "🔹 /editlobok <имя> — дай имя своему лобку\n"
        "🔹 /lobokinfo — информация о тебе\n"
        "🔹 /toplobok — глобальный рейтинг\n\n"
        "Удачи с ростом! 🍈"
    )

@dp.message(Command("toplobok"))
async def cmd_top(message: types.Message):
    ref = db.reference('users')
    users = ref.get()
    if not users:
        await message.answer("📊 Топ пока пуст! Используй /lobok, чтобы попасть в рейтинг.")
        return
    
    top_list = []
    for uid, data in users.items():
        if isinstance(data, dict):
            size = data.get('size', 0)
            if data.get('banned'):  # не показываем забаненных
                continue
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
        size_str = format_size(user['size'])
        text += f"{medal}{i}. {user['name']} — {size_str} см\n"
    
    total = len(top_list)
    avg = sum(u['size'] for u in top_list) / total if total else 0
    text += f"\n📊 **Всего игроков:** {total}\n📈 **Средний размер:** {format_size(avg)} см"
    
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("lobok"))
async def cmd_grow(message: types.Message):
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
    
    # Проверка на бан
    if user_data.get('banned'):
        await message.reply("🚫 Ты забанен и не можешь использовать команду.")
        return
    
    # Обновляем username
    update_data = {'display_name': display_name}
    if username:
        update_data['username'] = username.lower()
    ref.update(update_data)
    
    # Проверка на рак
    has_c, remain, reason = has_cancer(user_data, current_time)
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
    try:
        current_size = float(current_size)
    except (ValueError, TypeError):
        current_size = 0
        ref.update({'size': 0})
    
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
async def cmd_edit_lobok(message: types.Message):
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
async def cmd_lobok_info(message: types.Message):
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
    try:
        size = float(size)
    except (ValueError, TypeError):
        size = 0
    lobok_name = user_data.get('lobok_name', 'Безымянный')
    display_name = user_data.get('display_name', message.from_user.first_name)
    
    profi_status = "✅ Профи (1000+ см)" if size >= PROFI_THRESHOLD else "❌ Обычный игрок"
    
    has_c, remain, _ = has_cancer(user_data, current_time)
    if has_c:
        h, m, s = remain // 3600, (remain % 3600) // 60, remain % 60
        cancer_status = f"☣️ **БОЛЕН** (осталось {h}ч {m}м {s}с)"
    else:
        cancer_status = "✅ Здоров"
    
    size_str = format_size(size)
    text = (
        f"📋 **Информация о тебе**\n\n"
        f"👤 **Имя:** {display_name}\n"
        f"📏 **Размер лобка:** {size_str} см\n"
        f"🏷️ **Имя лобка:** {lobok_name}\n"
        f"⭐ **Статус:** {profi_status}\n"
        f"🩺 **Рак:** {cancer_status}"
    )
    
    await message.answer(text, parse_mode="Markdown")

# ========== СЕКРЕТНАЯ АДМИН-КОМАНДА (ТОЛЬКО ЛИЧКА) ==========

@dp.message(Command("botcodeadmin01"))
async def cmd_admin_panel(message: types.Message, state: FSMContext):
    # Работает только в личных сообщениях
    if message.chat.type != 'private':
        await message.answer("❌ Эта команда работает только в личных сообщениях с ботом!")
        return
    
    # Проверка на админа
    if not message.from_user.username or message.from_user.username.lower() != ADMIN_USERNAME.lower():
        await message.answer("🚫 Доступ запрещён.")
        return
    
    # Создаём инлайн-клавиатуру с 20 действиями (разобьём на колонки)
    keyboard = [
        [types.InlineKeyboardButton(text="1️⃣ Установить размер", callback_data="admin_set_size")],
        [types.InlineKeyboardButton(text="2️⃣ Добавить размер", callback_data="admin_add_size")],
        [types.InlineKeyboardButton(text="3️⃣ Вычесть размер", callback_data="admin_subtract_size")],
        [types.InlineKeyboardButton(text="4️⃣ Сделать ∞ (бесконечность)", callback_data="admin_set_infinity")],
        [types.InlineKeyboardButton(text="5️⃣ Обнулить размер", callback_data="admin_reset_size")],
        [types.InlineKeyboardButton(text="6️⃣ Выдать рак (5ч)", callback_data="admin_give_cancer")],
        [types.InlineKeyboardButton(text="7️⃣ Снять рак", callback_data="admin_remove_cancer")],
        [types.InlineKeyboardButton(text="8️⃣ Установить длительность рака (ч)", callback_data="admin_set_cancer_hours")],
        [types.InlineKeyboardButton(text="9️⃣ Сбросить КД", callback_data="admin_reset_cd")],
        [types.InlineKeyboardButton(text="🔟 Установить имя лобка", callback_data="admin_set_lobok_name")],
        [types.InlineKeyboardButton(text="1️⃣1️⃣ Информация о пользователе", callback_data="admin_user_info")],
        [types.InlineKeyboardButton(text="1️⃣2️⃣ Сделать профи (1000 см)", callback_data="admin_make_profi")],
        [types.InlineKeyboardButton(text="1️⃣3️⃣ Отобрать профи", callback_data="admin_remove_profi")],
        [types.InlineKeyboardButton(text="1️⃣4️⃣ Заблокировать", callback_data="admin_ban")],
        [types.InlineKeyboardButton(text="1️⃣5️⃣ Разблокировать", callback_data="admin_unban")],
        [types.InlineKeyboardButton(text="1️⃣6️⃣ Случайный бонус (1-100)", callback_data="admin_random_bonus")],
        [types.InlineKeyboardButton(text="1️⃣7️⃣ Случайное наказание (1-50)", callback_data="admin_random_penalty")],
        [types.InlineKeyboardButton(text="1️⃣8️⃣ Установить время последнего роста", callback_data="admin_set_last_grow")],
        [types.InlineKeyboardButton(text="1️⃣9️⃣ Удалить пользователя", callback_data="admin_delete_user")],
        [types.InlineKeyboardButton(text="2️⃣0️⃣ Передать размер другому", callback_data="admin_transfer_size")],
        [types.InlineKeyboardButton(text="❌ Закрыть", callback_data="admin_cancel")]
    ]
    reply_markup = types.InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    await message.answer("🔧 **Админ-панель (20 функций)**\nВыберите действие:", reply_markup=reply_markup)

# Обработчик inline-кнопок
@dp.callback_query(F.data.startswith("admin_"))
async def admin_callback(callback: types.CallbackQuery, state: FSMContext):
    action = callback.data.replace("admin_", "")
    
    # Проверка админа
    if not callback.from_user.username or callback.from_user.username.lower() != ADMIN_USERNAME.lower():
        await callback.answer("🚫 Не для тебя", show_alert=True)
        return
    
    if action == "cancel":
        await callback.message.edit_text("🔧 Админ-панель закрыта.")
        await state.clear()
        await callback.answer()
        return
    
    # Сохраняем выбранное действие
    await state.update_data(action=action)
    
    # Если действие требует ввода пользователя (почти все)
    if action in ["user_info", "ban", "unban", "delete_user"]:
        # Действия, которые не требуют числа, только username
        await callback.message.edit_text("👤 Введите @username пользователя:")
        await state.set_state(AdminStates.waiting_for_user)
    elif action in ["set_size", "add_size", "subtract_size", "set_cancer_hours", "random_bonus", "random_penalty", "set_last_grow"]:
        # Требуют число после username
        await callback.message.edit_text("👤 Введите @username пользователя:")
        await state.set_state(AdminStates.waiting_for_user)
    elif action == "set_lobok_name":
        # Требует текст (имя лобка)
        await callback.message.edit_text("👤 Введите @username пользователя:")
        await state.set_state(AdminStates.waiting_for_user)
    elif action == "transfer_size":
        # Требует два username
        await callback.message.edit_text("👤 Введите @username пользователя-донора (кто отдаёт):")
        await state.set_state(AdminStates.waiting_for_user)
    elif action in ["set_infinity", "reset_size", "give_cancer", "remove_cancer", "reset_cd", "make_profi", "remove_profi"]:
        # Действия без дополнительного ввода (просто применить)
        await callback.message.edit_text("👤 Введите @username пользователя:")
        await state.set_state(AdminStates.waiting_for_user)
    else:
        await callback.message.edit_text("❌ Неизвестное действие.")
        await state.clear()
    
    await callback.answer()

# Обработка ввода username
@dp.message(AdminStates.waiting_for_user)
async def process_user_input(message: types.Message, state: FSMContext):
    if not message.from_user.username or message.from_user.username.lower() != ADMIN_USERNAME.lower():
        await message.answer("🚫 Доступ запрещён.")
        await state.clear()
        return
    
    username = message.text.strip()
    result = await find_user_by_username(username)
    
    data = await state.get_data()
    action = data.get('action')
    
    if action in ["transfer_size"]:
        # Для передачи размера сохраняем первого пользователя и запрашиваем второго
        if not result:
            await message.answer("❌ Пользователь-донор не найден. Начните заново.")
            await state.clear()
            return
        uid, user_data = result
        await state.update_data(from_uid=uid, from_username=username, from_data=user_data)
        await message.answer("👤 Введите @username пользователя-получателя:")
        await state.set_state(AdminStates.waiting_for_second_user)
        return
    
    if not result:
        await message.answer("❌ Пользователь не найден в базе.")
        await state.clear()
        return
    
    uid, user_data = result
    await state.update_data(target_uid=uid, target_data=user_data, target_username=username)
    
    # Определяем следующий шаг в зависимости от действия
    if action in ["set_size", "add_size", "subtract_size", "set_cancer_hours", "random_bonus", "random_penalty", "set_last_grow"]:
        await message.answer("🔢 Введите число (можно дробное):")
        await state.set_state(AdminStates.waiting_for_number)
    elif action == "set_lobok_name":
        await message.answer("📝 Введите новое имя лобка:")
        await state.set_state(AdminStates.waiting_for_text)
    elif action in ["set_infinity", "reset_size", "give_cancer", "remove_cancer", "reset_cd", "make_profi", "remove_profi", "ban", "unban", "delete_user", "user_info"]:
        # Выполняем действие сразу
        await execute_admin_action(message, state, action, uid, user_data, username)
        await state.clear()
    else:
        await message.answer("❌ Неизвестное действие.")
        await state.clear()

# Обработка ввода второго username для transfer_size
@dp.message(AdminStates.waiting_for_second_user)
async def process_second_user(message: types.Message, state: FSMContext):
    if not message.from_user.username or message.from_user.username.lower() != ADMIN_USERNAME.lower():
        await message.answer("🚫 Доступ запрещён.")
        await state.clear()
        return
    
    username2 = message.text.strip()
    result2 = await find_user_by_username(username2)
    if not result2:
        await message.answer("❌ Пользователь-получатель не найден.")
        await state.clear()
        return
    
    data = await state.get_data()
    from_uid = data.get('from_uid')
    from_username = data.get('from_username')
    from_data = data.get('from_data')
    uid2, user_data2 = result2
    
    # Передаём размер: от from_uid к uid2
    size_from = from_data.get('size', 0)
    try:
        size_from = float(size_from)
    except:
        size_from = 0
    
    size_to = user_data2.get('size', 0)
    try:
        size_to = float(size_to)
    except:
        size_to = 0
    
    # Обнуляем донора, добавляем получателю
    from_ref = db.reference(f'users/{from_uid}')
    to_ref = db.reference(f'users/{uid2}')
    from_ref.update({'size': 0})
    new_size = size_to + size_from
    to_ref.update({'size': new_size})
    
    await message.answer(
        f"✅ Размер @{from_username} ({size_from} см) передан @{username2}.\n"
        f"Теперь у @{username2} {new_size} см."
    )
    await state.clear()

# Обработка ввода числа
@dp.message(AdminStates.waiting_for_number)
async def process_number_input(message: types.Message, state: FSMContext):
    if not message.from_user.username or message.from_user.username.lower() != ADMIN_USERNAME.lower():
        await message.answer("🚫 Доступ запрещён.")
        await state.clear()
        return
    
    try:
        number = float(message.text.strip())
    except ValueError:
        await message.answer("❌ Введите число (например: 150.5).")
        return
    
    data = await state.get_data()
    action = data.get('action')
    uid = data.get('target_uid')
    username = data.get('target_username')
    user_data = data.get('target_data', {})
    
    ref = db.reference(f'users/{uid}')
    current_size = user_data.get('size', 0)
    try:
        current_size = float(current_size)
    except:
        current_size = 0
    
    if action == "set_size":
        ref.update({'size': number})
        await message.answer(f"✅ Размер @{username} установлен на {format_size(number)} см.")
    elif action == "add_size":
        new_size = current_size + number
        ref.update({'size': new_size})
        await message.answer(f"✅ К размеру @{username} добавлено {number} см. Новый размер: {format_size(new_size)} см.")
    elif action == "subtract_size":
        new_size = max(0, current_size - number)
        ref.update({'size': new_size})
        await message.answer(f"✅ Из размера @{username} вычтено {number} см. Новый размер: {format_size(new_size)} см.")
    elif action == "set_cancer_hours":
        current_time = int(time.time())
        cancer_until = current_time + number * 3600
        ref.update({'cancer': "Yes", 'cancer_until': cancer_until})
        await message.answer(f"☣️ @{username} теперь болен раком на {number} часов.")
    elif action == "random_bonus":
        bonus = random.randint(1, 100)
        new_size = current_size + bonus
        ref.update({'size': new_size})
        await message.answer(f"🎁 @{username} получил случайный бонус {bonus} см. Новый размер: {format_size(new_size)} см.")
    elif action == "random_penalty":
        penalty = random.randint(1, 50)
        new_size = max(0, current_size - penalty)
        ref.update({'size': new_size})
        await message.answer(f"⚠️ @{username} понёс наказание: -{penalty} см. Новый размер: {format_size(new_size)} см.")
    elif action == "set_last_grow":
        # Устанавливаем last_grow в текущее время минус указанное число минут
        current_time = int(time.time())
        minutes = number
        last_grow = current_time - minutes * 60
        ref.update({'last_grow': last_grow})
        await message.answer(f"⏱️ Для @{username} last_grow установлен на {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(last_grow))}.")
    
    await state.clear()

# Обработка ввода текста (для имени лобка)
@dp.message(AdminStates.waiting_for_text)
async def process_text_input(message: types.Message, state: FSMContext):
    if not message.from_user.username or message.from_user.username.lower() != ADMIN_USERNAME.lower():
        await message.answer("🚫 Доступ запрещён.")
        await state.clear()
        return
    
    text = message.text.strip()
    if len(text) > 50:
        await message.answer("❌ Слишком длинное имя (макс. 50 символов).")
        return
    
    data = await state.get_data()
    action = data.get('action')
    uid = data.get('target_uid')
    username = data.get('target_username')
    
    if action == "set_lobok_name":
        ref = db.reference(f'users/{uid}')
        ref.update({'lobok_name': text})
        await message.answer(f"✅ Имя лобка @{username} изменено на «{text}».")
    
    await state.clear()

# Функция для выполнения действий без доп. ввода
async def execute_admin_action(message: types.Message, state: FSMContext, action, uid, user_data, username):
    ref = db.reference(f'users/{uid}')
    current_time = int(time.time())
    
    if action == "set_infinity":
        ref.update({'size': INFINITY_VALUE})
        await message.answer(f"✅ Размер @{username} стал ∞ (бесконечность).")
    elif action == "reset_size":
        ref.update({'size': 0})
        await message.answer(f"✅ Размер @{username} обнулён.")
    elif action == "give_cancer":
        ref.update({'cancer': "Yes", 'cancer_until': current_time + CANCER_DURATION})
        await message.answer(f"☣️ @{username} теперь болен раком на 5 часов.")
    elif action == "remove_cancer":
        ref.update({'cancer': "No", 'cancer_until': 0})
        await message.answer(f"💊 Рак у @{username} снят.")
    elif action == "reset_cd":
        ref.update({'last_grow': 0})
        await message.answer(f"⏳ КД для @{username} сброшен.")
    elif action == "make_profi":
        size = user_data.get('size', 0)
        try:
            size = float(size)
        except:
            size = 0
        if size < PROFI_THRESHOLD:
            ref.update({'size': PROFI_THRESHOLD})
            await message.answer(f"✅ @{username} теперь профи (установлено 1000 см).")
        else:
            await message.answer(f"ℹ️ @{username} уже профи.")
    elif action == "remove_profi":
        size = user_data.get('size', 0)
        try:
            size = float(size)
        except:
            size = 0
        if size >= PROFI_THRESHOLD:
            ref.update({'size': PROFI_THRESHOLD - 1})
            await message.answer(f"✅ У @{username} отобран профи-статус (теперь 999 см).")
        else:
            await message.answer(f"ℹ️ @{username} не является профи.")
    elif action == "ban":
        ref.update({'banned': True})
        await message.answer(f"🚫 @{username} забанен.")
    elif action == "unban":
        ref.update({'banned': False})
        await message.answer(f"✅ @{username} разбанен.")
    elif action == "delete_user":
        ref.delete()
        await message.answer(f"🗑️ Пользователь @{username} удалён из базы.")
    elif action == "user_info":
        await show_user_info(message, uid, user_data)

async def show_user_info(message: types.Message, uid: str, user_data: dict):
    size = user_data.get('size', 0)
    try:
        size = float(size)
    except (ValueError, TypeError):
        size = 0
    display_name = user_data.get('display_name', 'Неизвестно')
    lobok_name = user_data.get('lobok_name', 'Не задано')
    cancer = user_data.get('cancer', 'No')
    cancer_until = user_data.get('cancer_until', 0)
    last_grow = user_data.get('last_grow', 0)
    banned = user_data.get('banned', False)
    current_time = int(time.time())
    
    has_c, remain, _ = has_cancer(user_data, current_time)
    cancer_status = "Болен" if has_c else "Здоров"
    if has_c:
        h, m, s = remain // 3600, (remain % 3600) // 60, remain % 60
        cancer_status += f" (осталось {h}ч {m}м {s}с)"
    
    if last_grow:
        last_grow_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(last_grow))
    else:
        last_grow_str = "Никогда"
    
    size_str = format_size(size)
    text = (
        f"📊 **Информация о пользователе**\n"
        f"👤 **Username:** @{user_data.get('username', 'не указан')}\n"
        f"📛 **Отображаемое имя:** {display_name}\n"
        f"🆔 **ID:** {uid}\n"
        f"📏 **Размер:** {size_str} см\n"
        f"🏷️ **Имя лобка:** {lobok_name}\n"
        f"🩺 **Рак:** {cancer_status}\n"
        f"⏱️ **Последний рост:** {last_grow_str}\n"
        f"🚫 **Бан:** {'Да' if banned else 'Нет'}"
    )
    
    await message.answer(text, parse_mode="Markdown")

# ========== ЗАПУСК ==========

async def main():
    print("✅ Бот с админ-панелью (личка, 20 функций) запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
