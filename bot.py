import os
import json
import asyncio
import random
import time
from datetime import datetime, timedelta
from aiohttp import web
import firebase_admin
from firebase_admin import credentials, db
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

# ---------- Конфигурация ----------
TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_PATH = "/webhook"
BASE_URL = os.getenv("RENDER_EXTERNAL_URL")  # Render сам даёт эту переменную
if not BASE_URL:
    BASE_URL = "https://lobkomtr.onrender.com"  # твой URL
WEBHOOK_URL = BASE_URL + WEBHOOK_PATH

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

# ---------- Инициализация бота ----------
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())
spam_check = {}

# ---------- Константы ----------
ADMIN_USERNAME = "trim_peek"
LISTING_DATE = datetime(2026, 6, 1)
START_BALANCE = 100

# ---------- FSM ----------
class MinerStates(StatesGroup):
    mining_active = State()

# ---------- Вспомогательные функции ----------
def get_days_until_listing():
    delta = LISTING_DATE - datetime.now()
    return max(0, delta.days)

def get_mining_difficulty():
    days_left = get_days_until_listing()
    if days_left > 400: return 1.0
    if days_left > 300: return 1.5
    if days_left > 200: return 2.0
    if days_left > 100: return 3.0
    if days_left > 30: return 5.0
    return 10.0

async def get_user(user_id: str):
    ref = db.reference(f'users/{user_id}')
    data = ref.get() or {
        'balance': START_BALANCE,
        'energy': 1000,
        'last_energy_update': int(time.time()),
        'total_mined': 0,
        'booster': 1.0,
        'booster_until': 0
    }
    return data, ref

async def update_energy(user_id: str, data: dict, ref):
    now = int(time.time())
    last = data.get('last_energy_update', now)
    elapsed = now - last
    new_energy = min(1000, data.get('energy', 1000) + elapsed)
    data['energy'] = new_energy
    data['last_energy_update'] = now
    ref.update({'energy': new_energy, 'last_energy_update': now})
    return new_energy

# ========== КОМАНДЫ ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = str(message.from_user.id)
    data, ref = await get_user(user_id)
    
    days = get_days_until_listing()
    diff = get_mining_difficulty()
    
    text = (
        f"⛏️ **Добро пожаловать в майнинг $LBM!**\n\n"
        f"📅 До листинга: **{days} дней**\n"
        f"📈 Текущая сложность: **x{diff:.1f}**\n"
        f"💰 Твой баланс: **{data['balance']} $LBM**\n"
        f"⚡ Энергия: **{data['energy']}/1000**\n\n"
        f"🔹 /mine — начать майнинг\n"
        f"🔹 /stats — статистика\n"
        f"🔹 /top — топ майнеров\n"
        f"🔹 /boost — купить бустер"
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("mine"))
async def cmd_mine(message: types.Message):
    user_id = str(message.from_user.id)
    data, ref = await get_user(user_id)
    
    energy = await update_energy(user_id, data, ref)
    
    if energy < 10:
        await message.answer("❌ Недостаточно энергии! Подожди восстановления.")
        return
    
    cost = 10
    new_energy = energy - cost
    ref.update({'energy': new_energy})
    
    base_reward = random.randint(5, 15)
    diff_mult = get_mining_difficulty()
    booster = data.get('booster', 1.0)
    if data.get('booster_until', 0) < int(time.time()):
        booster = 1.0
    
    reward = int(base_reward * diff_mult * booster)
    
    new_balance = data['balance'] + reward
    new_total = data['total_mined'] + reward
    ref.update({
        'balance': new_balance,
        'total_mined': new_total,
        'display_name': message.from_user.first_name
    })
    
    if message.from_user.username:
        ref.update({'username': message.from_user.username.lower()})
    
    text = (
        f"⛏️ **Майнинг завершён!**\n\n"
        f"💰 Добыто: **+{reward} $LBM**\n"
        f"📊 Баланс: **{new_balance} $LBM**\n"
        f"⚡ Энергия: **{new_energy}/1000**"
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    user_id = str(message.from_user.id)
    data, _ = await get_user(user_id)
    
    text = (
        f"📊 **ТВОЯ СТАТИСТИКА**\n\n"
        f"💰 Баланс: **{data['balance']} $LBM**\n"
        f"⛏️ Всего добыто: **{data['total_mined']} $LBM**\n"
        f"⚡ Энергия: **{data['energy']}/1000**\n"
        f"🚀 Бустер: **x{data.get('booster', 1.0)}**\n"
        f"📅 До листинга: **{get_days_until_listing()} дней**"
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("top"))
async def cmd_top(message: types.Message):
    users = db.reference('users').get() or {}
    top = []
    for uid, data in users.items():
        if isinstance(data, dict):
            top.append((data.get('display_name', uid), data.get('balance', 0)))
    
    top.sort(key=lambda x: x[1], reverse=True)
    text = "🏆 **ТОП МАЙНЕРОВ** 🏆\n\n"
    for i, (name, balance) in enumerate(top[:10], 1):
        medal = "🥇 " if i == 1 else "🥈 " if i == 2 else "🥉 " if i == 3 else ""
        text += f"{medal}{i}. {name} — {balance} $LBM\n"
    
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("boost"))
async def cmd_boost(message: types.Message):
    user_id = str(message.from_user.id)
    data, ref = await get_user(user_id)
    
    if data['balance'] < 50:
        await message.answer("❌ Недостаточно $LBM! Нужно 50.")
        return
    
    new_balance = data['balance'] - 50
    booster_until = int(time.time()) + 3600
    
    ref.update({
        'balance': new_balance,
        'booster': 2.0,
        'booster_until': booster_until
    })
    
    await message.answer("🚀 **Бустер x2 активирован на 1 час!**")

# ---------- Админ-рассылка ----------
@dp.message(Command("рассылка07"))
async def cmd_broadcast(message: types.Message):
    if message.chat.type != 'private':
        return
    if not message.from_user.username or message.from_user.username.lower() != ADMIN_USERNAME:
        await message.answer("🚫 Доступ запрещён.")
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Пример: /рассылка07 Всем привет!")
        return
    
    text = args[1]
    users = db.reference('users').get() or {}
    
    sent = 0
    failed = 0
    for uid in users:
        try:
            await bot.send_message(int(uid), f"📢 **Рассылка от админа:**\n{text}")
            sent += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1
    
    await message.answer(f"✅ Отправлено: {sent}\n❌ Ошибок: {failed}")

# ========== WEBHOOK ==========
async def on_startup():
    await bot.set_webhook(WEBHOOK_URL)
    print(f"✅ Webhook установлен на {WEBHOOK_URL}")
    print(f"⛏️ Майнинг-бот $LBM запущен!")

async def on_shutdown():
    await bot.delete_webhook()
    print("❌ Webhook удалён")

# ========== Запуск сервера ==========
app = web.Application()
app.router.add_post(WEBHOOK_PATH, SimpleRequestHandler(dispatcher=dp, bot=bot))
app.router.add_get("/health", lambda r: web.Response(text="OK"))
app.router.add_get("/", lambda r: web.Response(text="Бот работает!"))
setup_application(app, dp, bot=bot)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
