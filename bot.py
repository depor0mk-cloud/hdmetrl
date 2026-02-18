import os
import json
import asyncio
import random
import time
from datetime import datetime
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

# ---------- Firebase ----------
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

# ---------- Константы ----------
ADMIN_USERNAME = "trim_peek"
CD_NORMAL = 15 * 60
CD_PROFI = 10 * 60
PROFI_THRESHOLD = 1000.0
CANCER_CHANCE = 0.005
CANCER_DURATION = 5 * 60 * 60
INFINITY_VALUE = 999999999.99

# ---------- FSM состояния (для админок) ----------
class AdminStates(StatesGroup):
    waiting_for_action = State()
    waiting_for_user = State()
    waiting_for_number = State()
    waiting_for_text = State()
    waiting_for_second_user = State()
    action_data = State()

class AdminRewardsStates(StatesGroup):
    waiting_for_user = State()

# ---------- Вспомогательные функции ----------
def has_cancer(user_data: dict, current_time: int = None) -> tuple:
    if current_time is None:
        current_time = int(time.time())
    flag = user_data.get('cancer')
    if flag == "Yes":
        until = user_data.get('cancer_until', 0)
        if until > current_time:
            return True, until - current_time, "flag"
        elif until > 0:
            return False, 0, "auto_fix"
    until = user_data.get('cancer_until', 0)
    if until > current_time:
        return True, until - current_time, "old"
    return False, 0, "no"

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

def format_size(size):
    if abs(size - INFINITY_VALUE) < 0.01:
        return "∞"
    return f"{size:.2f}"

def today_str():
    return datetime.now().strftime("%Y-%m-%d")

async def register_chat(chat_id: int, chat_type: str, chat_title: str = ""):
    """Сохраняет чат в базу для рассылки"""
    ref = db.reference(f'chats/{chat_id}')
    ref.update({
        'id': chat_id,
        'type': chat_type,
        'title': chat_title,
        'last_seen': int(time.time())
    })

async def update_usage_stats(user_id: str, user_data: dict, ref):
    """Обновляет счётчики использований"""
    today = today_str()
    total = user_data.get('total_uses', 0) + 1
    daily = user_data.get('daily', {})
    daily_today = daily.get(today, 0) + 1
    daily[today] = daily_today

    last_date = user_data.get('last_use_date')
    streak = user_data.get('consecutive_days', 0)
    if last_date:
        ld = datetime.strptime(last_date, "%Y-%m-%d").date()
        td = datetime.now().date()
        if (td - ld).days == 1:
            streak += 1
        elif (td - ld).days > 1:
            streak = 1
    else:
        streak = 1

    ref.update({
        'total_uses': total,
        'daily': daily,
        'consecutive_days': streak,
        'last_use_date': today
    })
    return total, daily_today, streak

async def collect_available_rewards(user_data: dict):
    """Возвращает список доступных наград для пользователя"""
    rewards = user_data.get('rewards', {})
    total = user_data.get('total_uses', 0)
    today = today_str()
    daily_today = user_data.get('daily', {}).get(today, 0)
    streak = user_data.get('consecutive_days', 0)

    available = []

    if not rewards.get('reward_10') and total >= 10:
        available.append(('10', '🏅 10 использований (5-10 см)'))
    if not rewards.get('reward_150') and total >= 150:
        available.append(('150', '🏅 150 использований (100-350 см)'))
    key_daily = f"daily_20_{today}"
    if not rewards.get(key_daily) and daily_today >= 20:
        available.append(('daily', '⚡ 20 за сегодня (10 см)'))
    if not rewards.get('reward_streak_10') and streak >= 10:
        available.append(('streak', '🔥 10 дней подряд (45 см)'))

    return available

async def claim_reward(user_id: str, reward_id: str, user_data: dict, ref):
    """Выдаёт конкретную награду и возвращает сообщение о получении"""
    rewards = user_data.get('rewards', {})
    size = float(user_data.get('size', 0))
    today = today_str()
    msg = ""

    if reward_id == '10' and not rewards.get('reward_10'):
        bonus = round(random.uniform(5.0, 10.0), 2)
        size += bonus
        rewards['reward_10'] = True
        msg = f"🏅 +{bonus} см"
    elif reward_id == '150' and not rewards.get('reward_150'):
        bonus = round(random.uniform(100.0, 350.0), 2)
        size += bonus
        rewards['reward_150'] = True
        msg = f"🏅 +{bonus} см"
    elif reward_id == 'daily':
        key = f"daily_20_{today}"
        if not rewards.get(key):
            bonus = 10.0
            size += bonus
            rewards[key] = True
            msg = f"⚡ +{bonus} см"
    elif reward_id == 'streak' and not rewards.get('reward_streak_10'):
        bonus = 45.0
        size += bonus
        rewards['reward_streak_10'] = True
        msg = f"🔥 +{bonus} см"
    else:
        return None

    ref.update({'size': size, 'rewards': rewards})
    return msg

# ========== ЭТУ ФУНКЦИЮ ТЫ ДОЛЖЕН ДОБАВИТЬ СЮДА ==========
async def check_rewards(user_id: str, user_data: dict, ref):
    """Проверяет и автоматически выдаёт награды (вызывается после /lobok)"""
    rewards = user_data.get('rewards', {})
    size = float(user_data.get('size', 0))
    changed = False
    msgs = []

    if not rewards.get('reward_10') and user_data.get('total_uses', 0) >= 10:
        bonus = round(random.uniform(5.0, 10.0), 2)
        size += bonus
        rewards['reward_10'] = True
        changed = True
        msgs.append(f"🏅 За 10 использований: +{bonus} см")

    if not rewards.get('reward_150') and user_data.get('total_uses', 0) >= 150:
        bonus = round(random.uniform(100.0, 350.0), 2)
        size += bonus
        rewards['reward_150'] = True
        changed = True
        msgs.append(f"🏅 За 150 использований: +{bonus} см")

    today = today_str()
    daily = user_data.get('daily', {})
    daily_today = daily.get(today, 0)
    key_daily = f"daily_20_{today}"
    if not rewards.get(key_daily) and daily_today >= 20:
        bonus = 10.0
        size += bonus
        rewards[key_daily] = True
        changed = True
        msgs.append(f"⚡ За 20 использований сегодня: +{bonus} см")

    if not rewards.get('reward_streak_10') and user_data.get('consecutive_days', 0) >= 10:
        bonus = 45.0
        size += bonus
        rewards['reward_streak_10'] = True
        changed = True
        msgs.append(f"🔥 За 10 дней подряд: +{bonus} см")

    if changed:
        ref.update({'size': size, 'rewards': rewards})
    return msgs

# ========== ДАЛЬШЕ ИДУТ КОМАНДЫ ДЛЯ ИГРОКОВ ==========
# (сюда ты вставишь следующие части кода)
# ========== КОМАНДЫ ДЛЯ ИГРОКОВ ==========

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "📏 **Лобкометр**\n\n"
        "🔹 Добавь меня в группу\n"
        "🔹 Пиши /lobok — каждые 15 мин (при 1000+ см — 10 мин)\n"
        "🔹 /editlobok <имя> — дай имя своему лобку\n"
        "🔹 /lobokinfo — информация о тебе\n"
        "🔹 /lucky — получить награды за активность\n"
        "🔹 /toplobok — глобальный рейтинг\n\n"
        "Удачи с ростом! 🍈"
    )

@dp.message(Command("toplobok"))
async def cmd_top(message: types.Message):
    if message.chat.type != 'private':
        await register_chat(message.chat.id, message.chat.type, message.chat.title)

    ref = db.reference('users')
    users = ref.get()
    if not users:
        await message.answer("📊 Топ пока пуст! Используй /lobok, чтобы попасть в рейтинг.")
        return

    top = []
    for uid, data in users.items():
        if isinstance(data, dict) and not data.get('banned'):
            size = data.get('size', 0)
            if size > 0:
                name = data.get('display_name', 'Инкогнито')
                if name.startswith('@'):
                    name = name[1:]
                top.append({'name': name, 'size': size})

    top.sort(key=lambda x: x['size'], reverse=True)
    if not top:
        await message.answer("📊 Топ пока пуст! Используй /lobok, чтобы попасть в рейтинг.")
        return

    text = "🏆 **ГЛОБАЛЬНЫЙ ТОП-30** 🏆\n\n"
    for i, u in enumerate(top[:30], 1):
        medal = ""
        if i == 1:
            medal = "🥇 "
        elif i == 2:
            medal = "🥈 "
        elif i == 3:
            medal = "🥉 "
        text += f"{medal}{i}. {u['name']} — {format_size(u['size'])} см\n"

    total = len(top)
    avg = sum(u['size'] for u in top) / total if total else 0
    text += f"\n📊 **Всего игроков:** {total}\n📈 **Средний размер:** {format_size(avg)} см"
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("lobok"))
async def cmd_grow(message: types.Message):
    if message.chat.type == 'private':
        await message.answer("❌ Добавь меня в группу, чтобы растить лобок!")
        return

    await register_chat(message.chat.id, message.chat.type, message.chat.title)

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

    # Бан
    if user_data.get('banned'):
        await message.reply("🚫 Ты забанен.")
        return

    # Обновляем username/display_name
    update_data = {'display_name': display_name}
    if username:
        update_data['username'] = username.lower()
    ref.update(update_data)

    # Проверка рака
    has_c, remain, _ = has_cancer(user_data, current_time)
    if has_c:
        h, m, s = remain // 3600, (remain % 3600) // 60, remain % 60
        await message.reply(f"🚨 {mention}, у тебя рак лобка! До конца лечения: {h}ч {m}м {s}с", parse_mode="Markdown")
        return

    # Текущий размер
    current_size = user_data.get('size', 0)
    try:
        current_size = float(current_size)
    except:
        current_size = 0
        ref.update({'size': 0})

    # Проверка КД
    cd_seconds = CD_PROFI if current_size >= PROFI_THRESHOLD else CD_NORMAL
    last_grow = user_data.get('last_grow', 0)
    if current_time < last_grow + cd_seconds:
        rem = (last_grow + cd_seconds) - current_time
        minutes, seconds = rem // 60, rem % 60
        await message.reply(f"⏳ {mention}, лобок ещё не восстановился! Подожди ещё {minutes}м {seconds}с.", parse_mode="Markdown")
        return

    # Шанс рака
    if random.random() < CANCER_CHANCE:
        ref.update({'cancer': "Yes", 'cancer_until': current_time + CANCER_DURATION})
        await message.reply(f"☣️ {mention}, ПЛОХИЕ НОВОСТИ! У тебя развился рак лобка. Рост заблокирован на 5 часов.", parse_mode="Markdown")
        return

    # Рост
    if current_size >= PROFI_THRESHOLD:
        growth = round(random.uniform(10.0, 20.0), 2)
    else:
        growth = round(random.uniform(1.0, 5.0), 2)
    new_size = round(current_size + growth, 2)
    ref.update({'size': new_size, 'last_grow': current_time})

    # Обновление счётчиков
    total_uses, daily_today, streak = await update_usage_stats(user_id, user_data, ref)

    # Проверка и выдача наград (может сработать сразу, если набрано)
    reward_msgs = await check_rewards(user_id, {**user_data, 'size': new_size, 'total_uses': total_uses}, ref)

    reply = f"{mention}, твой лобок вырос на {growth} см! 📏\nТекущий размер — {new_size} см. 🍈"
    if current_size < PROFI_THRESHOLD <= new_size:
        reply = f"🎉 {mention}, ПОЗДРАВЛЯЮ! Твой лобок превысил 1000 см! Теперь ты ПРОФИ и получаешь +10-20 см за раз! 🍈\n\n{reply}"
    if reward_msgs:
        reply += "\n\n🎁 **Получены награды:**\n" + "\n".join(reward_msgs)

    await message.reply(reply, parse_mode="Markdown")

@dp.message(Command("editlobok"))
async def cmd_edit_lobok(message: types.Message):
    if message.chat.type == 'private':
        await message.answer("❌ Эта команда работает только в группах!")
        return

    await register_chat(message.chat.id, message.chat.type, message.chat.title)

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Укажи имя для лобка. Пример:\n/editlobok Мой Большой Друг")
        return
    name = args[1].strip()
    if len(name) > 50:
        await message.answer("❌ Слишком длинное имя (макс. 50 символов).")
        return

    user_id = str(message.from_user.id)
    ref = db.reference(f'users/{user_id}')
    uname = message.from_user.username
    upd = {'lobok_name': name, 'display_name': message.from_user.first_name}
    if uname:
        upd['username'] = uname.lower()
    ref.update(upd)

    await message.reply(f"✅ Имя твоего лобка сохранено: «{name}»")

@dp.message(Command("lobokinfo"))
async def cmd_lobok_info(message: types.Message):
    if message.chat.type == 'private':
        await message.answer("❌ Эта команда работает только в группах!")
        return

    await register_chat(message.chat.id, message.chat.type, message.chat.title)

    user_id = str(message.from_user.id)
    ref = db.reference(f'users/{user_id}')
    user_data = ref.get()
    if not user_data:
        await message.answer("❌ Ты ещё не начинал рост! Напиши /lobok")
        return

    size = user_data.get('size', 0)
    try:
        size = float(size)
    except:
        size = 0

    lobok_name = user_data.get('lobok_name', 'Безымянный')
    display_name = user_data.get('display_name', message.from_user.first_name)
    profi = "✅ Профи (1000+ см)" if size >= PROFI_THRESHOLD else "❌ Обычный игрок"

    has_c, remain, _ = has_cancer(user_data, int(time.time()))
    if has_c:
        h, m, s = remain // 3600, (remain % 3600) // 60, remain % 60
        cancer = f"☣️ Болен (осталось {h}ч {m}м {s}с)"
    else:
        cancer = "✅ Здоров"

    total = user_data.get('total_uses', 0)
    today = today_str()
    daily_today = user_data.get('daily', {}).get(today, 0)
    streak = user_data.get('consecutive_days', 0)

    # Доступные награды
    available = await collect_available_rewards(user_data)
    if available:
        avail_list = "\n".join([f"• {desc}" for _, desc in available])
    else:
        avail_list = "Нет доступных наград"

    text = (
        f"📋 **Информация о тебе**\n\n"
        f"👤 **Имя:** {display_name}\n"
        f"📏 **Размер:** {format_size(size)} см\n"
        f"🏷️ **Имя лобка:** {lobok_name}\n"
        f"⭐ **Статус:** {profi}\n"
        f"🩺 **Рак:** {cancer}\n\n"
        f"📊 **Активность:**\n"
        f"└ Всего использований: {total}\n"
        f"└ Сегодня: {daily_today}\n"
        f"└ Дней подряд: {streak}\n\n"
        f"🎁 **Доступные награды:**\n{avail_list}"
    )
    await message.answer(text, parse_mode="Markdown")

# ========== КОМАНДА /lucky (НОВАЯ, С КНОПКОЙ ЗАБРАТЬ ВСЁ) ==========

@dp.message(Command("lucky"))
async def cmd_lucky(message: types.Message):
    user_id = str(message.from_user.id)
    ref = db.reference(f'users/{user_id}')
    user_data = ref.get()
    if not user_data:
        await message.answer("❌ Сначала напиши /lobok, чтобы начать игру!")
        return

    available = await collect_available_rewards(user_data)

    if not available:
        await message.answer("🎁 У тебя пока нет доступных наград. Используй /lobok, чтобы копить статистику!")
        return

    # Формируем клавиатуру: кнопки для каждой награды + кнопка "Забрать всё"
    kb = []
    for rew_id, desc in available:
        kb.append([types.InlineKeyboardButton(text=desc, callback_data=f"claim_{rew_id}")])

    # Кнопка "Забрать всё"
    kb.append([types.InlineKeyboardButton(text="🎁 Забрать всё", callback_data="claim_all")])
    kb.append([types.InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_lucky")])

    markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
    await message.answer("🎁 **Доступные награды:**\nНажми на кнопку, чтобы получить.", reply_markup=markup)

@dp.callback_query(F.data.startswith(('claim_', 'refresh_lucky')))
async def lucky_callbacks(callback: types.CallbackQuery):
    user_id = str(callback.from_user.id)
    ref = db.reference(f'users/{user_id}')
    user_data = ref.get()
    if not user_data:
        await callback.answer("Ошибка: нет данных", show_alert=True)
        return

    if callback.data == 'refresh_lucky':
        await callback.message.delete()
        await cmd_lucky(callback.message)
        await callback.answer()
        return

    if callback.data == 'claim_all':
        # Собираем все доступные награды
        available = await collect_available_rewards(user_data)
        if not available:
            await callback.answer("Нет доступных наград", show_alert=True)
            return

        total_msg = []
        size = float(user_data.get('size', 0))
        rewards = user_data.get('rewards', {})
        today = today_str()
        changed = False

        for rew_id, _ in available:
            if rew_id == '10' and not rewards.get('reward_10'):
                bonus = round(random.uniform(5.0, 10.0), 2)
                size += bonus
                rewards['reward_10'] = True
                total_msg.append(f"🏅 +{bonus}")
                changed = True
            elif rew_id == '150' and not rewards.get('reward_150'):
                bonus = round(random.uniform(100.0, 350.0), 2)
                size += bonus
                rewards['reward_150'] = True
                total_msg.append(f"🏅 +{bonus}")
                changed = True
            elif rew_id == 'daily':
                key = f"daily_20_{today}"
                if not rewards.get(key):
                    bonus = 10.0
                    size += bonus
                    rewards[key] = True
                    total_msg.append(f"⚡ +{bonus}")
                    changed = True
            elif rew_id == 'streak' and not rewards.get('reward_streak_10'):
                bonus = 45.0
                size += bonus
                rewards['reward_streak_10'] = True
                total_msg.append(f"🔥 +{bonus}")
                changed = True

        if changed:
            ref.update({'size': size, 'rewards': rewards})
            await callback.answer("Награды получены!", show_alert=True)
            await callback.message.edit_text(
                f"🎁 **Получено:**\n" + "\n".join(total_msg) + f"\n\nНовый размер: {format_size(size)} см"
            )
        else:
            await callback.answer("Не удалось получить награды", show_alert=True)
        return

    # Одиночная награда
    rew_id = callback.data.replace('claim_', '')
    msg = await claim_reward(user_id, rew_id, user_data, ref)
    if msg:
        # Получаем обновлённые данные
        new_data = ref.get()
        new_size = new_data.get('size', 0)
        await callback.answer(msg, show_alert=True)
        # Обновляем сообщение с наградами (убираем полученную кнопку)
        await cmd_lucky(callback.message)
    else:
        await callback.answer("Награда уже получена или недоступна", show_alert=True)

# ========== СТАРАЯ АДМИН-ПАНЕЛЬ (20 ФУНКЦИЙ) ==========
@dp.message(Command("botcodeadmin01"))
async def cmd_admin_panel(message: types.Message, state: FSMContext):
    if message.chat.type != 'private':
        return
    if not message.from_user.username or message.from_user.username.lower() != ADMIN_USERNAME.lower():
        await message.answer("🚫 Доступ запрещён.")
        return
    
    # Клавиатура 20 функций
    keyboard = [
        [types.InlineKeyboardButton(text="1️⃣ Установить размер", callback_data="admin_set_size")],
        [types.InlineKeyboardButton(text="2️⃣ Добавить размер", callback_data="admin_add_size")],
        [types.InlineKeyboardButton(text="3️⃣ Вычесть размер", callback_data="admin_subtract_size")],
        [types.InlineKeyboardButton(text="4️⃣ Сделать ∞", callback_data="admin_set_infinity")],
        [types.InlineKeyboardButton(text="5️⃣ Обнулить", callback_data="admin_reset_size")],
        [types.InlineKeyboardButton(text="6️⃣ Выдать рак", callback_data="admin_give_cancer")],
        [types.InlineKeyboardButton(text="7️⃣ Снять рак", callback_data="admin_remove_cancer")],
        [types.InlineKeyboardButton(text="8️⃣ Рак на N часов", callback_data="admin_set_cancer_hours")],
        [types.InlineKeyboardButton(text="9️⃣ Сбросить КД", callback_data="admin_reset_cd")],
        [types.InlineKeyboardButton(text="🔟 Сменить имя лобка", callback_data="admin_set_lobok_name")],
        [types.InlineKeyboardButton(text="1️⃣1️⃣ Инфо", callback_data="admin_user_info")],
        [types.InlineKeyboardButton(text="1️⃣2️⃣ Сделать профи", callback_data="admin_make_profi")],
        [types.InlineKeyboardButton(text="1️⃣3️⃣ Отобрать профи", callback_data="admin_remove_profi")],
        [types.InlineKeyboardButton(text="1️⃣4️⃣ Забанить", callback_data="admin_ban")],
        [types.InlineKeyboardButton(text="1️⃣5️⃣ Разбанить", callback_data="admin_unban")],
        [types.InlineKeyboardButton(text="1️⃣6️⃣ Рандом бонус", callback_data="admin_random_bonus")],
        [types.InlineKeyboardButton(text="1️⃣7️⃣ Рандом пенальти", callback_data="admin_random_penalty")],
        [types.InlineKeyboardButton(text="1️⃣8️⃣ Установить last_grow", callback_data="admin_set_last_grow")],
        [types.InlineKeyboardButton(text="1️⃣9️⃣ Удалить юзера", callback_data="admin_delete_user")],
        [types.InlineKeyboardButton(text="2️⃣0️⃣ Передать размер", callback_data="admin_transfer_size")],
        [types.InlineKeyboardButton(text="❌ Закрыть", callback_data="admin_cancel")]
    ]
    markup = types.InlineKeyboardMarkup(inline_keyboard=keyboard)
    await message.answer("🔧 **Админ-панель (20 функций)**", reply_markup=markup)

# ---------- Обработчики для 20 функций ----------
@dp.callback_query(F.data.startswith("admin_"))
async def admin_callback(callback: types.CallbackQuery, state: FSMContext):
    if not callback.from_user.username or callback.from_user.username.lower() != ADMIN_USERNAME.lower():
        await callback.answer("🚫", show_alert=True)
        return
    
    action = callback.data.replace("admin_", "")
    if action == "cancel":
        await callback.message.edit_text("Закрыто.")
        await state.clear()
        await callback.answer()
        return
    
    await state.update_data(admin_action=action)
    await callback.message.edit_text("👤 Введи @username:")
    await state.set_state(AdminStates.waiting_for_user)
    await callback.answer()

@dp.message(AdminStates.waiting_for_user)
async def admin_user_input(message: types.Message, state: FSMContext):
    if not message.from_user.username or message.from_user.username.lower() != ADMIN_USERNAME.lower():
        await message.answer("🚫")
        await state.clear()
        return
    
    username = message.text.strip()
    result = await find_user_by_username(username)
    if not result:
        await message.answer("❌ Не найден")
        await state.clear()
        return
    
    uid, user_data = result
    data = await state.get_data()
    action = data.get('admin_action')
    
    # Действия, требующие числа
    if action in ["set_size", "add_size", "subtract_size", "set_cancer_hours", "random_bonus", "random_penalty", "set_last_grow"]:
        await state.update_data(target_uid=uid, target_username=username, target_data=user_data)
        await message.answer("🔢 Введи число:")
        await state.set_state(AdminStates.waiting_for_number)
    elif action == "set_lobok_name":
        await state.update_data(target_uid=uid, target_username=username)
        await message.answer("📝 Введи новое имя лобка:")
        await state.set_state(AdminStates.waiting_for_text)
    elif action == "transfer_size":
        await state.update_data(from_uid=uid, from_username=username, from_data=user_data)
        await message.answer("👤 Введи @username получателя:")
        await state.set_state(AdminStates.waiting_for_second_user)
    else:
        # Действия без доп. ввода
        await execute_admin_action(message, action, uid, user_data, username)
        await state.clear()

@dp.message(AdminStates.waiting_for_number)
async def admin_number_input(message: types.Message, state: FSMContext):
    if not message.from_user.username or message.from_user.username.lower() != ADMIN_USERNAME.lower():
        await message.answer("🚫")
        await state.clear()
        return
    
    try:
        num = float(message.text.strip())
    except:
        await message.answer("❌ Это не число")
        return
    
    data = await state.get_data()
    action = data.get('admin_action')
    uid = data.get('target_uid')
    username = data.get('target_username')
    user_data = data.get('target_data', {})
    ref = db.reference(f'users/{uid}')
    
    if action == "set_size":
        ref.update({'size': num})
        await message.answer(f"✅ Размер @{username} = {format_size(num)} см")
    elif action == "add_size":
        current = float(user_data.get('size', 0))
        new = current + num
        ref.update({'size': new})
        await message.answer(f"✅ Добавлено {num} см, теперь {format_size(new)} см")
    elif action == "subtract_size":
        current = float(user_data.get('size', 0))
        new = max(0, current - num)
        ref.update({'size': new})
        await message.answer(f"✅ Вычтено {num} см, теперь {format_size(new)} см")
    elif action == "set_cancer_hours":
        until = int(time.time()) + int(num * 3600)
        ref.update({'cancer': "Yes", 'cancer_until': until})
        await message.answer(f"☣️ Рак на {num} часов выдан")
    elif action == "random_bonus":
        bonus = random.randint(1, 100)
        current = float(user_data.get('size', 0))
        new = current + bonus
        ref.update({'size': new})
        await message.answer(f"🎁 Бонус {bonus} см, теперь {format_size(new)} см")
    elif action == "random_penalty":
        penalty = random.randint(1, 50)
        current = float(user_data.get('size', 0))
        new = max(0, current - penalty)
        ref.update({'size': new})
        await message.answer(f"⚠️ Штраф {penalty} см, теперь {format_size(new)} см")
    elif action == "set_last_grow":
        current_time = int(time.time())
        minutes = num
        last_grow = current_time - int(minutes * 60)
        ref.update({'last_grow': last_grow})
        await message.answer(f"⏱️ last_grow установлен")
    
    await state.clear()

@dp.message(AdminStates.waiting_for_text)
async def admin_text_input(message: types.Message, state: FSMContext):
    if not message.from_user.username or message.from_user.username.lower() != ADMIN_USERNAME.lower():
        await message.answer("🚫")
        await state.clear()
        return
    
    text = message.text.strip()
    if len(text) > 50:
        await message.answer("❌ Слишком длинное")
        return
    
    data = await state.get_data()
    action = data.get('admin_action')
    uid = data.get('target_uid')
    username = data.get('target_username')
    
    if action == "set_lobok_name":
        ref = db.reference(f'users/{uid}')
        ref.update({'lobok_name': text})
        await message.answer(f"✅ Имя лобка @{username} изменено")
    
    await state.clear()

@dp.message(AdminStates.waiting_for_second_user)
async def admin_second_user(message: types.Message, state: FSMContext):
    if not message.from_user.username or message.from_user.username.lower() != ADMIN_USERNAME.lower():
        await message.answer("🚫")
        await state.clear()
        return
    
    username2 = message.text.strip()
    res = await find_user_by_username(username2)
    if not res:
        await message.answer("❌ Получатель не найден")
        await state.clear()
        return
    
    uid2, data2 = res
    data = await state.get_data()
    from_uid = data.get('from_uid')
    from_username = data.get('from_username')
    from_data = data.get('from_data')
    
    size_from = float(from_data.get('size', 0))
    size_to = float(data2.get('size', 0))
    
    db.reference(f'users/{from_uid}').update({'size': 0})
    db.reference(f'users/{uid2}').update({'size': size_to + size_from})
    
    await message.answer(f"✅ Передано {format_size(size_from)} см от @{from_username} к @{username2}")
    await state.clear()

async def execute_admin_action(message: types.Message, action: str, uid: str, user_data: dict, username: str):
    ref = db.reference(f'users/{uid}')
    current_time = int(time.time())
    
    if action == "set_infinity":
        ref.update({'size': INFINITY_VALUE})
        await message.answer(f"✅ ∞")
    elif action == "reset_size":
        ref.update({'size': 0})
        await message.answer(f"✅ Обнулено")
    elif action == "give_cancer":
        ref.update({'cancer': "Yes", 'cancer_until': current_time + CANCER_DURATION})
        await message.answer(f"☣️ Рак выдан")
    elif action == "remove_cancer":
        ref.update({'cancer': "No", 'cancer_until': 0})
        await message.answer(f"💊 Рак снят")
    elif action == "reset_cd":
        ref.update({'last_grow': 0})
        await message.answer(f"⏳ КД сброшен")
    elif action == "make_profi":
        size = float(user_data.get('size', 0))
        if size < PROFI_THRESHOLD:
            ref.update({'size': PROFI_THRESHOLD})
            await message.answer(f"✅ Профи")
        else:
            await message.answer(f"ℹ️ Уже профи")
    elif action == "remove_profi":
        size = float(user_data.get('size', 0))
        if size >= PROFI_THRESHOLD:
            ref.update({'size': PROFI_THRESHOLD - 1})
            await message.answer(f"✅ Профи отобран")
        else:
            await message.answer(f"ℹ️ Не профи")
    elif action == "ban":
        ref.update({'banned': True})
        await message.answer(f"🚫 Забанен")
    elif action == "unban":
        ref.update({'banned': False})
        await message.answer(f"✅ Разбанен")
    elif action == "delete_user":
        ref.delete()
        await message.answer(f"🗑️ Удалён")
    elif action == "user_info":
        size = user_data.get('size', 0)
        try:
            size = float(size)
        except:
            size = 0
        display = user_data.get('display_name', '?')
        lobok = user_data.get('lobok_name', 'не задано')
        cancer = user_data.get('cancer', 'No')
        total = user_data.get('total_uses', 0)
        today = today_str()
        daily = user_data.get('daily', {}).get(today, 0)
        streak = user_data.get('consecutive_days', 0)
        banned = user_data.get('banned', False)
        
        text = (
            f"📊 @{username}\n"
            f"Имя: {display}\n"
            f"Размер: {format_size(size)}\n"
            f"Лобок: {lobok}\n"
            f"Рак: {cancer}\n"
            f"Использований: {total} (сегодня {daily})\n"
            f"Стрик: {streak}\n"
            f"Бан: {'да' if banned else 'нет'}"
        )
        await message.answer(text)
# ========== НОВАЯ АДМИН-ПАНЕЛЬ /adminrewards (МНОГОСТРАНИЧНАЯ 3×3) ==========

# Хранилище для страниц (в памяти)
admin_rewards_pages = {}

def get_rewards_keyboard(page: int = 0):
    """Генерирует клавиатуру 3×3 для страницы page"""
    # Все действия (9 штук на страницу, всего 18 действий = 2 страницы)
    all_actions = [
        ("1️⃣ Просмотр счетчиков", "areward_view"),
        ("2️⃣ Сброс счетчиков", "areward_reset_counts"),
        ("3️⃣ Выдать награду 10", "areward_give_10"),
        ("4️⃣ Выдать награду 150", "areward_give_150"),
        ("5️⃣ Выдать награду 20/день", "areward_give_daily"),
        ("6️⃣ Выдать награду стрик 10", "areward_give_streak"),
        ("7️⃣ Сброс флагов наград", "areward_reset_flags"),
        ("8️⃣ Глобальная статистика", "areward_global_stats"),
        ("9️⃣ Выдать всё принудительно", "areward_give_all"),
        ("🔟 Снять все награды", "areward_remove_all"),
        ("1️⃣1️⃣ Установить total_uses", "areward_set_total"),
        ("1️⃣2️⃣ Установить streak", "areward_set_streak"),
        ("1️⃣3️⃣ Очистить daily", "areward_clear_daily"),
        ("1️⃣4️⃣ Показать daily", "areward_show_daily"),
        ("1️⃣5️⃣ Топ по использованиям", "areward_usage_top"),
        ("1️⃣6️⃣ Топ по стрику", "areward_streak_top"),
        ("1️⃣7️⃣ Экспорт данных", "areward_export"),
        ("1️⃣8️⃣ Импорт данных", "areward_import"),
    ]
    
    actions_per_page = 9
    start = page * actions_per_page
    end = start + actions_per_page
    page_actions = all_actions[start:end]
    
    # Строим клавиатуру 3×3
    keyboard = []
    row = []
    for i, (text, cb) in enumerate(page_actions):
        row.append(types.InlineKeyboardButton(text=text, callback_data=cb))
        if (i + 1) % 3 == 0:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    # Кнопки навигации
    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton(text="◀️", callback_data=f"areward_page_{page-1}"))
    else:
        nav.append(types.InlineKeyboardButton(text="⬜", callback_data="noop"))
    
    nav.append(types.InlineKeyboardButton(text=f"📄 {page+1}/{(len(all_actions)+8)//9}", callback_data="noop"))
    
    if end < len(all_actions):
        nav.append(types.InlineKeyboardButton(text="▶️", callback_data=f"areward_page_{page+1}"))
    else:
        nav.append(types.InlineKeyboardButton(text="⬜", callback_data="noop"))
    
    keyboard.append(nav)
    keyboard.append([types.InlineKeyboardButton(text="❌ Закрыть", callback_data="areward_cancel")])
    
    return types.InlineKeyboardMarkup(inline_keyboard=keyboard)

@dp.message(Command("adminrewards"))
async def cmd_admin_rewards(message: types.Message, state: FSMContext):
    if message.chat.type != 'private':
        await message.answer("❌ Только в личке!")
        return
    if not message.from_user.username or message.from_user.username.lower() != ADMIN_USERNAME.lower():
        await message.answer("🚫 Доступ запрещён.")
        return
    
    page = 0
    admin_rewards_pages[message.from_user.id] = page
    await message.answer(
        "🔧 **Управление наградами**\nСтраница 1/2",
        reply_markup=get_rewards_keyboard(page)
    )

@dp.callback_query(F.data.startswith(("areward_", "noop")))
async def admin_rewards_callback(callback: types.CallbackQuery, state: FSMContext):
    if not callback.from_user.username or callback.from_user.username.lower() != ADMIN_USERNAME.lower():
        await callback.answer("🚫", show_alert=True)
        return
    
    if callback.data == "noop":
        await callback.answer()
        return
    
    if callback.data.startswith("areward_page_"):
        page = int(callback.data.split("_")[2])
        admin_rewards_pages[callback.from_user.id] = page
        await callback.message.edit_text(
            f"🔧 **Управление наградами**\nСтраница {page+1}/2",
            reply_markup=get_rewards_keyboard(page)
        )
        await callback.answer()
        return
    
    if callback.data == "areward_cancel":
        await callback.message.edit_text("Закрыто.")
        await callback.answer()
        return
    
    # Обработка действий
    action = callback.data.replace("areward_", "")
    
    if action == "global_stats":
        users = db.reference('users').get() or {}
        total_uses = 0
        stats = []
        for uid, data in users.items():
            if isinstance(data, dict):
                tu = data.get('total_uses', 0)
                total_uses += tu
                stats.append((data.get('display_name', uid), tu))
        stats.sort(key=lambda x: x[1], reverse=True)
        top = "\n".join([f"{i+1}. {n} — {u}" for i, (n, u) in enumerate(stats[:10])])
        await callback.message.edit_text(f"📊 Всего использований: {total_uses}\n\nТоп-10:\n{top}")
        await callback.answer()
        return
    
    elif action == "usage_top":
        users = db.reference('users').get() or {}
        stats = []
        for uid, data in users.items():
            if isinstance(data, dict):
                stats.append((data.get('display_name', uid), data.get('total_uses', 0)))
        stats.sort(key=lambda x: x[1], reverse=True)
        top = "\n".join([f"{i+1}. {n} — {u}" for i, (n, u) in enumerate(stats[:15])])
        await callback.message.edit_text(f"🏆 **Топ по использованиям**\n\n{top}")
        await callback.answer()
        return
    
    elif action == "streak_top":
        users = db.reference('users').get() or {}
        stats = []
        for uid, data in users.items():
            if isinstance(data, dict):
                stats.append((data.get('display_name', uid), data.get('consecutive_days', 0)))
        stats.sort(key=lambda x: x[1], reverse=True)
        top = "\n".join([f"{i+1}. {n} — {u} дней" for i, (n, u) in enumerate(stats[:15])])
        await callback.message.edit_text(f"🔥 **Топ по стрику**\n\n{top}")
        await callback.answer()
        return
    
    # Действия, требующие username
    await state.update_data(admin_reward_action=action)
    await callback.message.edit_text("👤 Введи @username:")
    await state.set_state(AdminRewardsStates.waiting_for_user)
    await callback.answer()

@dp.message(AdminRewardsStates.waiting_for_user)
async def process_admin_rewards_user(message: types.Message, state: FSMContext):
    if not message.from_user.username or message.from_user.username.lower() != ADMIN_USERNAME.lower():
        await message.answer("🚫")
        await state.clear()
        return
    
    username = message.text.strip()
    res = await find_user_by_username(username)
    if not res:
        await message.answer("❌ Пользователь не найден.")
        await state.clear()
        return
    
    uid, user_data = res
    data = await state.get_data()
    action = data.get('admin_reward_action')
    ref = db.reference(f'users/{uid}')
    
    if action == "view":
        total = user_data.get('total_uses', 0)
        daily = user_data.get('daily', {})
        streak = user_data.get('consecutive_days', 0)
        rewards = user_data.get('rewards', {})
        today = today_str()
        dtoday = daily.get(today, 0)
        await message.answer(
            f"📊 @{username}\n"
            f"Всего: {total}\n"
            f"Сегодня: {dtoday}\n"
            f"Стрик: {streak}\n"
            f"Награды: {json.dumps(rewards, indent=2)}"
        )
    
    elif action == "reset_counts":
        ref.update({'total_uses': 0, 'daily': {}, 'consecutive_days': 0, 'last_use_date': ''})
        await message.answer(f"✅ Счетчики @{username} сброшены.")
    
    elif action == "give_10":
        rewards = user_data.get('rewards', {})
        if rewards.get('reward_10'):
            await message.answer("ℹ️ Уже есть.")
        else:
            size = float(user_data.get('size', 0))
            bonus = round(random.uniform(5.0, 10.0), 2)
            size += bonus
            rewards['reward_10'] = True
            ref.update({'size': size, 'rewards': rewards})
            await message.answer(f"✅ +{bonus} см. Новый размер: {format_size(size)} см.")
    
    elif action == "give_150":
        rewards = user_data.get('rewards', {})
        if rewards.get('reward_150'):
            await message.answer("ℹ️ Уже есть.")
        else:
            size = float(user_data.get('size', 0))
            bonus = round(random.uniform(100.0, 350.0), 2)
            size += bonus
            rewards['reward_150'] = True
            ref.update({'size': size, 'rewards': rewards})
            await message.answer(f"✅ +{bonus} см. Новый размер: {format_size(size)} см.")
    
    elif action == "give_daily":
        today = today_str()
        key = f"daily_20_{today}"
        rewards = user_data.get('rewards', {})
        if rewards.get(key):
            await message.answer("ℹ️ Уже сегодня получал.")
        else:
            size = float(user_data.get('size', 0))
            bonus = 10.0
            size += bonus
            rewards[key] = True
            ref.update({'size': size, 'rewards': rewards})
            await message.answer(f"✅ +{bonus} см. Новый размер: {format_size(size)} см.")
    
    elif action == "give_streak":
        rewards = user_data.get('rewards', {})
        if rewards.get('reward_streak_10'):
            await message.answer("ℹ️ Уже есть.")
        else:
            size = float(user_data.get('size', 0))
            bonus = 45.0
            size += bonus
            rewards['reward_streak_10'] = True
            ref.update({'size': size, 'rewards': rewards})
            await message.answer(f"✅ +{bonus} см. Новый размер: {format_size(size)} см.")
    
    elif action == "give_all":
        # Выдать все возможные награды принудительно
        rewards = user_data.get('rewards', {})
        size = float(user_data.get('size', 0))
        changed = False
        
        if not rewards.get('reward_10'):
            bonus = round(random.uniform(5.0, 10.0), 2)
            size += bonus
            rewards['reward_10'] = True
            changed = True
        
        if not rewards.get('reward_150'):
            bonus = round(random.uniform(100.0, 350.0), 2)
            size += bonus
            rewards['reward_150'] = True
            changed = True
        
        today = today_str()
        key = f"daily_20_{today}"
        if not rewards.get(key):
            size += 10.0
            rewards[key] = True
            changed = True
        
        if not rewards.get('reward_streak_10'):
            size += 45.0
            rewards['reward_streak_10'] = True
            changed = True
        
        if changed:
            ref.update({'size': size, 'rewards': rewards})
            await message.answer(f"✅ Все награды выданы. Новый размер: {format_size(size)} см.")
        else:
            await message.answer("ℹ️ У пользователя уже всё есть.")
    
    elif action == "reset_flags":
        ref.update({'rewards': {}})
        await message.answer(f"✅ Флаги наград @{username} сброшены.")
    
    elif action == "set_total":
        await state.update_data(target_uid=uid, target_username=username)
        await message.answer("🔢 Введи новое значение total_uses:")
        await state.set_state(AdminRewardsStates.waiting_for_number)
        return
    
    elif action == "set_streak":
        await state.update_data(target_uid=uid, target_username=username)
        await message.answer("🔢 Введи новое значение streak (дней подряд):")
        await state.set_state(AdminRewardsStates.waiting_for_number)
        return
    
    elif action == "clear_daily":
        ref.update({'daily': {}})
        await message.answer(f"✅ Daily история @{username} очищена.")
    
    elif action == "show_daily":
        daily = user_data.get('daily', {})
        if daily:
            days = "\n".join([f"{d}: {c}" for d, c in list(daily.items())[-10:]])
            await message.answer(f"📅 Последние 10 дней @{username}:\n{days}")
        else:
            await message.answer("Нет данных.")
    
    elif action == "export":
        # Простой экспорт: показать все данные пользователя
        await message.answer(f"📤 Данные @{username}:\n```\n{json.dumps(user_data, indent=2)}\n```", parse_mode="Markdown")
    
    elif action == "import":
        await state.update_data(target_uid=uid, target_username=username)
        await message.answer("📥 Отправь JSON с данными для импорта (полностью заменит текущие):")
        await state.set_state(AdminRewardsStates.waiting_for_number)  # переиспользуем состояние
        return
    
    await state.clear()

@dp.message(AdminRewardsStates.waiting_for_number)
async def admin_rewards_number_input(message: types.Message, state: FSMContext):
    if not message.from_user.username or message.from_user.username.lower() != ADMIN_USERNAME.lower():
        await message.answer("🚫")
        await state.clear()
        return
    
    data = await state.get_data()
    action = data.get('admin_reward_action')
    uid = data.get('target_uid')
    username = data.get('target_username')
    ref = db.reference(f'users/{uid}')
    
    if action in ["set_total", "set_streak"]:
        try:
            num = int(message.text.strip())
        except:
            await message.answer("❌ Введи целое число.")
            return
        
        if action == "set_total":
            ref.update({'total_uses': num})
            await message.answer(f"✅ total_uses @{username} = {num}")
        elif action == "set_streak":
            ref.update({'consecutive_days': num})
            await message.answer(f"✅ streak @{username} = {num}")
    
    elif action == "import":
        try:
            new_data = json.loads(message.text.strip())
            if isinstance(new_data, dict):
                ref.update(new_data)
                await message.answer(f"✅ Данные @{username} обновлены.")
            else:
                await message.answer("❌ Нужен JSON-объект.")
        except Exception as e:
            await message.answer(f"❌ Ошибка парсинга JSON: {e}")
    
    await state.clear()

# ========== КОМАНДА РАССЫЛКИ ==========

@dp.message(Command("adminpostru"))
async def cmd_admin_post(message: types.Message):
    if message.chat.type != 'private':
        return
    if not message.from_user.username or message.from_user.username.lower() != ADMIN_USERNAME.lower():
        await message.answer("🚫 Доступ запрещён.")
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Укажи текст рассылки. Пример:\n/adminpostru Всем привет!")
        return
    
    text = args[1]
    
    # Получаем все сохранённые чаты
    chats_ref = db.reference('chats')
    chats = chats_ref.get()
    if not chats:
        await message.answer("❌ Нет сохранённых чатов.")
        return
    
    sent = 0
    failed = 0
    for cid_str, cdata in chats.items():
        try:
            await bot.send_message(int(cid_str), f"📢 **Рассылка от админа:**\n{text}")
            sent += 1
            await asyncio.sleep(0.05)  # небольшая задержка
        except Exception as e:
            failed += 1
            print(f"Ошибка отправки в чат {cid_str}: {e}")
    
    await message.answer(f"✅ Отправлено: {sent}\n❌ Ошибок: {failed}")

# ========== ЗАПУСК ==========
async def main():
    print("✅ Бобёр с наградами, админками и рассылкой запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
