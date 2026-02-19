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
dp = Dispatcher(storage=MemoryStorage())

spam_check = {}

# ---------- Константы ----------
ADMIN_USERNAME = "trim_peek"
CD_NORMAL = 15 * 60
CD_PROFI = 10 * 60
PROFI_THRESHOLD = 1000.0
CANCER_CHANCE = 0.005
CANCER_DURATION = 5 * 60 * 60
INFINITY_VALUE = 999999999.99

# ---------- FSM ----------
class AdminStates(StatesGroup):
    waiting_for_user = State()
    waiting_for_number = State()
    action_data = State()

# ---------- Вспомогательные функции ----------
def has_cancer(user_data: dict, now: int = None) -> bool:
    if not now: now = int(time.time())
    if user_data.get('cancer') == "Yes" and user_data.get('cancer_until', 0) > now:
        return True, user_data['cancer_until'] - now
    return False, 0

async def find_user(username: str):
    username = username.lower().lstrip('@')
    users = db.reference('users').get() or {}
    for uid, data in users.items():
        if not isinstance(data, dict): continue
        if data.get('username') == username: return uid, data
        if data.get('display_name', '').lower() in (username, f'@{username}'): return uid, data
    return None

def format_size(s): return "∞" if abs(s - INFINITY_VALUE) < 0.01 else f"{s:.2f}"
def today_str(): return datetime.now().strftime("%Y-%m-%d")

async def register_chat(msg):
    if msg.chat.type != 'private':
        db.reference(f'chats/{msg.chat.id}').update({
            'id': msg.chat.id, 'type': msg.chat.type,
            'title': msg.chat.title, 'last_seen': int(time.time())
        })

async def update_stats(uid, data, ref):
    today = today_str()
    total = data.get('total_uses', 0) + 1
    daily = data.get('daily', {})
    daily[today] = daily.get(today, 0) + 1
    last = data.get('last_use_date')
    streak = data.get('consecutive_days', 1)
    if last:
        ld = datetime.strptime(last, "%Y-%m-%d").date()
        td = datetime.now().date()
        streak = streak + 1 if (td - ld).days == 1 else 1
    ref.update({
        'total_uses': total, 'daily': daily,
        'consecutive_days': streak, 'last_use_date': today
    })
    return total, daily[today], streak

async def get_available_rewards(data):
    r = data.get('rewards', {})
    t = data.get('total_uses', 0)
    today = today_str()
    d = data.get('daily', {}).get(today, 0)
    s = data.get('consecutive_days', 0)
    a = []
    if not r.get('reward_10') and t >= 10: a.append(('10', '🏅 10 использований (5-10 см)'))
    if not r.get('reward_150') and t >= 150: a.append(('150', '🏅 150 использований (100-350 см)'))
    if not r.get(f'daily_20_{today}') and d >= 20: a.append(('daily', '⚡ 20 за сегодня (10 см)'))
    if not r.get('reward_streak_10') and s >= 10: a.append(('streak', '🔥 10 дней подряд (45 см)'))
    return a

async def claim_reward(uid, rid, data, ref):
    r = data.get('rewards', {})
    size = float(data.get('size', 0))
    today = today_str()
    msg = None
    if rid == '10' and not r.get('reward_10'):
        b = round(random.uniform(5, 10), 2)
        size += b
        r['reward_10'] = True
        msg = f"🏅 +{b} см"
    elif rid == '150' and not r.get('reward_150'):
        b = round(random.uniform(100, 350), 2)
        size += b
        r['reward_150'] = True
        msg = f"🏅 +{b} см"
    elif rid == 'daily':
        k = f"daily_20_{today}"
        if not r.get(k):
            size += 10
            r[k] = True
            msg = "⚡ +10 см"
    elif rid == 'streak' and not r.get('reward_streak_10'):
        size += 45
        r['reward_streak_10'] = True
        msg = "🔥 +45 см"
    if msg: ref.update({'size': size, 'rewards': r})
    return msg

async def check_rewards(uid, data, ref):
    r = data.get('rewards', {})
    size = float(data.get('size', 0))
    changed = False
    msgs = []
    if not r.get('reward_10') and data.get('total_uses', 0) >= 10:
        b = round(random.uniform(5, 10), 2)
        size += b
        r['reward_10'] = True
        changed = True
        msgs.append(f"🏅 +{b}")
    if not r.get('reward_150') and data.get('total_uses', 0) >= 150:
        b = round(random.uniform(100, 350), 2)
        size += b
        r['reward_150'] = True
        changed = True
        msgs.append(f"🏅 +{b}")
    today = today_str()
    if not r.get(f'daily_20_{today}') and data.get('daily', {}).get(today, 0) >= 20:
        size += 10
        r[f'daily_20_{today}'] = True
        changed = True
        msgs.append("⚡ +10")
    if not r.get('reward_streak_10') and data.get('consecutive_days', 0) >= 10:
        size += 45
        r['reward_streak_10'] = True
        changed = True
        msgs.append("🔥 +45")
    if changed: ref.update({'size': size, 'rewards': r})
    return msgs
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
        await register_chat(message)

    users = db.reference('users').get() or {}
    if not users:
        await message.answer("📊 Топ пока пуст! Используй /lobok, чтобы попасть в рейтинг.")
        return

    top = []
    for uid, data in users.items():
        if isinstance(data, dict) and not data.get('banned') and data.get('size', 0) > 0:
            name = data.get('display_name', 'Инкогнито')
            if name.startswith('@'): name = name[1:]
            top.append({'name': name, 'size': data['size']})

    top.sort(key=lambda x: x['size'], reverse=True)
    if not top:
        await message.answer("📊 Топ пока пуст!")
        return

    text = "🏆 **ГЛОБАЛЬНЫЙ ТОП-30** 🏆\n\n"
    for i, u in enumerate(top[:30], 1):
        medal = "🥇 " if i == 1 else "🥈 " if i == 2 else "🥉 " if i == 3 else ""
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

    await register_chat(message)

    user_id = str(message.from_user.id)
    user_name = message.from_user.first_name
    username = message.from_user.username
    mention = f"[{user_name}](tg://user?id={user_id})"
    now = int(time.time())

    if user_id in spam_check and now - spam_check[user_id] < 1:
        await message.reply("⚠️ НЕ СПАМЬ!")
        return
    spam_check[user_id] = now

    ref = db.reference(f'users/{user_id}')
    data = ref.get() or {}

    if data.get('banned'):
        await message.reply("🚫 Ты забанен.")
        return

    ref.update({'display_name': user_name})
    if username: ref.update({'username': username.lower()})

    has_c, rem = has_cancer(data, now)
    if has_c:
        h, m, s = rem // 3600, (rem % 3600) // 60, rem % 60
        await message.reply(f"🚨 {mention}, у тебя рак лобка! До конца лечения: {h}ч {m}м {s}с", parse_mode="Markdown")
        return

    size = float(data.get('size', 0))
    last = data.get('last_grow', 0)
    cd = CD_PROFI if size >= PROFI_THRESHOLD else CD_NORMAL

    if now < last + cd:
        rem = (last + cd) - now
        m, s = rem // 60, rem % 60
        await message.reply(f"⏳ {mention}, подожди ещё {m}м {s}с.", parse_mode="Markdown")
        return

    if random.random() < CANCER_CHANCE:
        ref.update({'cancer': "Yes", 'cancer_until': now + CANCER_DURATION})
        await message.reply(f"☣️ {mention}, ТЫ ЗАБОЛЕЛ РАКОМ НА 5 ЧАСОВ!", parse_mode="Markdown")
        return

    growth = round(random.uniform(10, 20) if size >= PROFI_THRESHOLD else random.uniform(1, 5), 2)
    new_size = round(size + growth, 2)
    ref.update({'size': new_size, 'last_grow': now})

    total, _, _ = await update_stats(user_id, data, ref)
    reward_msgs = await check_rewards(user_id, {**data, 'size': new_size, 'total_uses': total}, ref)

    reply = f"{mention}, твой лобок вырос на {growth} см! 📏\nТекущий размер — {new_size} см. 🍈"
    if size < PROFI_THRESHOLD <= new_size:
        reply = f"🎉 {mention}, ТЫ ПРОФИ! +10-20 см за раз!\n\n{reply}"
    if reward_msgs:
        reply += "\n\n🎁 **Награды:**\n" + "\n".join(reward_msgs)

    await message.reply(reply, parse_mode="Markdown")

@dp.message(Command("editlobok"))
async def cmd_edit(message: types.Message):
    if message.chat.type == 'private':
        await message.answer("❌ Только в группах!")
        return

    await register_chat(message)

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Пример: /editlobok Нагибатор")
        return

    name = args[1].strip()[:50]
    uid = str(message.from_user.id)
    ref = db.reference(f'users/{uid}')
    ref.update({'lobok_name': name, 'display_name': message.from_user.first_name})
    if message.from_user.username:
        ref.update({'username': message.from_user.username.lower()})

    await message.reply(f"✅ Имя лобка: «{name}»")

@dp.message(Command("lobokinfo"))
async def cmd_info(message: types.Message):
    if message.chat.type == 'private':
        await message.answer("❌ Только в группах!")
        return

    await register_chat(message)

    uid = str(message.from_user.id)
    data = db.reference(f'users/{uid}').get()
    if not data:
        await message.answer("❌ Ты ещё не играл! Напиши /lobok")
        return

    size = float(data.get('size', 0))
    has_c, rem = has_cancer(data, int(time.time()))
    cancer = f"☣️ Болен (осталось {rem//3600}ч {(rem%3600)//60}м)" if has_c else "✅ Здоров"
    profi = "✅ Профи" if size >= PROFI_THRESHOLD else "❌ Обычный"
    avail = await get_available_rewards(data)

    text = (
        f"📋 **{data.get('display_name', message.from_user.first_name)}**\n"
        f"📏 Размер: {format_size(size)} см\n"
        f"🏷️ Имя лобка: {data.get('lobok_name', 'Безымянный')}\n"
        f"⭐ Статус: {profi}\n"
        f"🩺 Рак: {cancer}\n"
        f"📊 Всего: {data.get('total_uses', 0)} | Сегодня: {data.get('daily', {}).get(today_str(), 0)} | Стрик: {data.get('consecutive_days', 0)}\n"
        f"🎁 Доступно наград: {len(avail)}"
    )
    await message.answer(text)

@dp.message(Command("lucky"))
async def cmd_lucky(message: types.Message):
    uid = str(message.from_user.id)
    ref = db.reference(f'users/{uid}')
    data = ref.get()
    if not data:
        await message.answer("❌ Сначала /lobok")
        return

    avail = await get_available_rewards(data)
    if not avail:
        await message.answer("🎁 Нет доступных наград")
        return

    kb = []
    for rid, desc in avail:
        kb.append([types.InlineKeyboardButton(text=desc, callback_data=f"claim_{rid}")])
    kb.append([types.InlineKeyboardButton(text="🎁 Забрать всё", callback_data="claim_all")])
    kb.append([types.InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_lucky")])

    await message.answer("🎁 **Доступные награды:**", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith(('claim_', 'refresh_lucky')))
async def lucky_callback(cb: types.CallbackQuery):
    uid = str(cb.from_user.id)
    ref = db.reference(f'users/{uid}')
    data = ref.get()
    if not data:
        await cb.answer("Нет данных", show_alert=True)
        return

    if cb.data == 'refresh_lucky':
        await cb.message.delete()
        await cmd_lucky(cb.message)
        await cb.answer()
        return

    if cb.data == 'claim_all':
        avail = await get_available_rewards(data)
        if not avail:
            await cb.answer("Нет наград", show_alert=True)
            return

        msgs = []
        size = float(data.get('size', 0))
        r = data.get('rewards', {})
        today = today_str()
        changed = False

        for rid, _ in avail:
            if rid == '10' and not r.get('reward_10'):
                size += round(random.uniform(5, 10), 2)
                r['reward_10'] = True
                msgs.append("🏅 10")
                changed = True
            elif rid == '150' and not r.get('reward_150'):
                size += round(random.uniform(100, 350), 2)
                r['reward_150'] = True
                msgs.append("🏅 150")
                changed = True
            elif rid == 'daily' and not r.get(f'daily_20_{today}'):
                size += 10
                r[f'daily_20_{today}'] = True
                msgs.append("⚡ 20")
                changed = True
            elif rid == 'streak' and not r.get('reward_streak_10'):
                size += 45
                r['reward_streak_10'] = True
                msgs.append("🔥 стрик")
                changed = True

        if changed:
            ref.update({'size': size, 'rewards': r})
            await cb.answer("Награды получены!", show_alert=True)
            await cb.message.edit_text(f"🎁 Получено: {', '.join(msgs)}\nНовый размер: {format_size(size)}")
        else:
            await cb.answer("Ошибка", show_alert=True)
        return

    rid = cb.data.replace('claim_', '')
    msg = await claim_reward(uid, rid, data, ref)
    if msg:
        await cb.answer(msg, show_alert=True)
        await cmd_lucky(cb.message)
    else:
        await cb.answer("Уже получено", show_alert=True)

# ========== АДМИНКА (ТОЛЬКО ВАЖНОЕ) ==========

@dp.message(Command("botcodeadmin01"))
async def admin_panel(message: types.Message, state: FSMContext):
    if message.chat.type != 'private':
        return
    if not message.from_user.username or message.from_user.username.lower() != ADMIN_USERNAME:
        await message.answer("🚫 Доступ запрещён.")
        return

    kb = [
        [types.InlineKeyboardButton(text="1️⃣ Изменить размер", callback_data="admin_set_size")],
        [types.InlineKeyboardButton(text="2️⃣ Выдать рак", callback_data="admin_give_cancer")],
        [types.InlineKeyboardButton(text="3️⃣ Снять рак", callback_data="admin_remove_cancer")],
        [types.InlineKeyboardButton(text="4️⃣ Сбросить КД", callback_data="admin_reset_cd")],
        [types.InlineKeyboardButton(text="5️⃣ Забанить", callback_data="admin_ban")],
        [types.InlineKeyboardButton(text="6️⃣ Разбанить", callback_data="admin_unban")],
        [types.InlineKeyboardButton(text="7️⃣ Инфо о юзере", callback_data="admin_info")],
        [types.InlineKeyboardButton(text="8️⃣ Сделать профи", callback_data="admin_make_profi")],
        [types.InlineKeyboardButton(text="9️⃣ Сбросить всё", callback_data="admin_reset_all")],
        [types.InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_post")],
        [types.InlineKeyboardButton(text="❌ Закрыть", callback_data="admin_cancel")]
    ]
    await message.answer("🔧 **Админ-панель**", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("admin_"))
async def admin_callback(cb: types.CallbackQuery, state: FSMContext):
    if not cb.from_user.username or cb.from_user.username.lower() != ADMIN_USERNAME:
        await cb.answer("🚫", show_alert=True)
        return

    action = cb.data.replace("admin_", "")
    if action == "cancel":
        await cb.message.edit_text("Закрыто.")
        await state.clear()
        await cb.answer()
        return

    if action == "post":
        await state.set_state(AdminStates.waiting_for_text)
        await cb.message.edit_text("📝 Введи текст рассылки:")
        await cb.answer()
        return

    await state.update_data(admin_action=action)
    await cb.message.edit_text("👤 Введи @username:")
    await state.set_state(AdminStates.waiting_for_user)
    await cb.answer()

@dp.message(AdminStates.waiting_for_user)
async def admin_user_input(message: types.Message, state: FSMContext):
    if not message.from_user.username or message.from_user.username.lower() != ADMIN_USERNAME:
        await message.answer("🚫")
        await state.clear()
        return

    username = message.text.strip()
    res = await find_user(username)
    if not res:
        await message.answer("❌ Пользователь не найден")
        await state.clear()
        return

    uid, data = res
    sdata = await state.get_data()
    action = sdata.get('admin_action')
    ref = db.reference(f'users/{uid}')

    if action in ["set_size", "give_cancer"]:
        await state.update_data(target_uid=uid, target_username=username)
        await message.answer("🔢 Введи число (см или часы):")
        await state.set_state(AdminStates.waiting_for_number)
        return

    now = int(time.time())

    if action == "remove_cancer":
        ref.update({'cancer': "No", 'cancer_until': 0})
        await message.answer(f"✅ Рак снят у @{username}")

    elif action == "reset_cd":
        ref.update({'last_grow': 0})
        await message.answer(f"⏳ КД сброшен для @{username}")

    elif action == "ban":
        ref.update({'banned': True})
        await message.answer(f"🚫 @{username} забанен")

    elif action == "unban":
        ref.update({'banned': False})
        await message.answer(f"✅ @{username} разбанен")

    elif action == "info":
        size = float(data.get('size', 0))
        total = data.get('total_uses', 0)
        today = data.get('daily', {}).get(today_str(), 0)
        streak = data.get('consecutive_days', 0)
        has_c, rem = has_cancer(data, now)
        cancer = f"☣️ {rem//3600}ч {(rem%3600)//60}м" if has_c else "✅ Нет"
        await message.answer(
            f"📊 @{username}\n"
            f"Размер: {format_size(size)}\n"
            f"Рак: {cancer}\n"
            f"Всего: {total} | Сегодня: {today} | Стрик: {streak}\n"
            f"Бан: {'да' if data.get('banned') else 'нет'}"
        )

    elif action == "make_profi":
        size = float(data.get('size', 0))
        if size < PROFI_THRESHOLD:
            ref.update({'size': PROFI_THRESHOLD})
            await message.answer(f"✅ @{username} теперь профи (1000 см)")
        else:
            await message.answer(f"ℹ️ Уже профи")

    elif action == "reset_all":
        ref.update({'total_uses': 0, 'daily': {}, 'consecutive_days': 0, 'last_use_date': '', 'rewards': {}})
        await message.answer(f"✅ Счетчики @{username} сброшены")

    await state.clear()

@dp.message(AdminStates.waiting_for_number)
async def admin_number_input(message: types.Message, state: FSMContext):
    if not message.from_user.username or message.from_user.username.lower() != ADMIN_USERNAME:
        await message.answer("🚫")
        await state.clear()
        return

    try:
        num = float(message.text.strip())
    except:
        await message.answer("❌ Введи число")
        return

    data = await state.get_data()
    action = data.get('admin_action')
    uid = data.get('target_uid')
    username = data.get('target_username')
    ref = db.reference(f'users/{uid}')
    user_data = ref.get() or {}

    if action == "set_size":
        ref.update({'size': num})
        await message.answer(f"✅ Размер @{username} = {format_size(num)} см")
    elif action == "give_cancer":
        now = int(time.time())
        ref.update({'cancer': "Yes", 'cancer_until': now + int(num * 3600)})
        await message.answer(f"☣️ Рак на {num} ч выдан @{username}")

    await state.clear()

@dp.message(AdminStates.waiting_for_text)
async def admin_post_input(message: types.Message, state: FSMContext):
    if not message.from_user.username or message.from_user.username.lower() != ADMIN_USERNAME:
        await message.answer("🚫")
        await state.clear()
        return

    text = message.text.strip()
    chats = db.reference('chats').get() or {}
    if not chats:
        await message.answer("❌ Нет чатов")
        await state.clear()
        return

    sent, failed = 0, 0
    for cid in chats:
        try:
            await bot.send_message(int(cid), f"📢 **Рассылка:**\n{text}")
            sent += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1

    await message.answer(f"✅ Отправлено: {sent}\n❌ Ошибок: {failed}")
    await state.clear()

# ========== ЗАПУСК ==========
async def main():
    print("✅ Бобёр с админкой запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
