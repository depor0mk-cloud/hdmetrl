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
    # Проверяем, что команда вызвана в группе
    if message.chat.type == 'private':
        await message.answer("❌ Эта команда работает только в группах!")
        return
    
    try:
        # Получаем список участников чата (админы + обычные пользователи)
        chat_members = []
        chat_user_ids = set()
        
        # Сначала получаем админов
        try:
            admins = await bot.get_chat_administrators(message.chat.id)
            for admin in admins:
                chat_members.append(admin.user)
                chat_user_ids.add(admin.user.id)
        except:
            pass
        
        # Пытаемся получить обычных участников (ограничение API)
        try:
            async for member in bot.get_chat_members(message.chat.id):
                if member.user.id not in chat_user_ids:
                    chat_members.append(member.user)
                    chat_user_ids.add(member.user.id)
        except:
            # Если не можем получить всех, используем только то, что есть
            pass
        
        # Получаем всех пользователей из Firebase
        ref = db.reference('users')
        all_users = ref.get()
        
        if not all_users:
            await message.answer("📊 Топ пока пуст! Используй /lobok, чтобы попасть в рейтинг.")
            return
        
        # Собираем только тех, кто есть в этом чате
        top_list = []
        for uid, user_data in all_users.items():
            if int(uid) in chat_user_ids:  # Проверяем, что пользователь в чате
                if isinstance(user_data, dict):
                    size = user_data.get('size', 0)
                    if size > 0:  # Показываем только тех, у кого есть размер
                        # Пытаемся получить актуальное имя
                        display_name = None
                        
                        # Ищем пользователя среди участников чата
                        for member in chat_members:
                            if member.id == int(uid):
                                if member.username:
                                    display_name = f"@{member.username}"
                                else:
                                    display_name = member.first_name
                                break
                        
                        # Если не нашли в чате, используем сохранённое имя
                        if not display_name:
                            display_name = user_data.get('display_name', f"User {uid[:6]}")
                        
                        top_list.append({
                            'name': display_name,
                            'size': size,
                            'user_id': int(uid),
                            'username': next((m.username for m in chat_members if m.id == int(uid)), None)
                        })
        
        # Сортируем по размеру (от большего к меньшему)
        top_list.sort(key=lambda x: x['size'], reverse=True)
        
        if not top_list:
            await message.answer("📊 В этом чате пока нет игроков! Напиши /lobok, чтобы начать.")
            return
        
        # Формируем красивый топ-30
        text = "🏆 **ТОП-30 ЧАТА** 🏆\n\n"
        
        for i, user in enumerate(top_list[:30], 1):
            # Определяем имя для отображения
            if user['username']:
                display_name = f"@{user['username']}"
            else:
                display_name = user['name']
            
            # Добавляем медальки для первых трёх мест
            medal = ""
            if i == 1:
                medal = "🥇 "
            elif i == 2:
                medal = "🥈 "
            elif i == 3:
                medal = "🥉 "
            
            text += f"{medal}{i}. {display_name} — {user['size']:.2f} см\n"
        
        # Добавляем статистику
        total_players = len(top_list)
        if total_players > 0:
            avg_size = sum(u['size'] for u in top_list) / total_players
            text += f"\n📊 **Всего игроков:** {total_players}"
            text += f"\n📈 **Средний размер:** {avg_size:.2f} см"
        
        await message.answer(text, parse_mode="Markdown")
        
    except Exception as e:
        print(f"Ошибка в топе: {e}")
        await message.answer("❌ Произошла ошибка при формировании топа. Попробуй позже.")

@dp.message(Command("lobok"))
async def cmd_grow(message: types.Message):
    if message.chat.type == 'private':
        await message.answer("❌ Добавь меня в группу, чтобы растить лобок!")
        return
    
    user_id = str(message.from_user.id)
    user_name = message.from_user.first_name
    display_name = f"@{message.from_user.username}" if message.from_user.username else user_name
    mention = f"@{message.from_user.username}" if message.from_user.username else f"[{user_name}](tg://user?id={user_id})"
    current_time = int(time.time())
    
    # Анти-спам проверка
    if user_id in spam_check and current_time - spam_check[user_id] < 1:
        await message.reply("⚠️ НЕ СПАМЬ!")
        return
    spam_check[user_id] = current_time
    
    # Получаем данные пользователя из Firebase
    ref = db.reference(f'users/{user_id}')
    user_data = ref.get() or {}
    
    # Проверка на рак
    cancer_until = user_data.get('cancer_until', 0)
    if current_time < cancer_until:
        rem = cancer_until - current_time
        h, m, s = rem // 3600, (rem % 3600) // 60, rem % 60
        await message.reply(f"🚨 {mention}, у тебя рак лобка! До конца лечения: {h}ч {m}м {s}с")
        return
    
    # Проверка КД
    last_grow = user_data.get('last_grow', 0)
    cd_sec = 5 * 60 
    if current_time < last_grow + cd_sec:
        rem = (last_grow + cd_sec) - current_time
        m, s = rem // 60, rem % 60
        await message.reply(f"⏳ {mention}, лобок еще не восстановился! Подожди еще {m}м {s}с.")
        return
    
    # Шанс на рак (5%)
    if random.random() < 0.05:
        five_h = 5 * 60 * 60
        ref.update({
            'cancer_until': current_time + five_h,
            'display_name': display_name,
            'last_grow': current_time  # Обновляем время последнего использования
        })
        await message.reply(f"☣️ {mention}, ПЛОХИЕ НОВОСТИ! У тебя развился рак лобка. Рост заблокирован на 5 часов.")
        return
    
    # Нормальный рост
    growth = round(random.uniform(1.0, 5.0), 2)
    current_size = user_data.get('size', 0)
    new_size = round(current_size + growth, 2)
    
    # Сохраняем в Firebase
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
        "🔹 Смотри /toplobok в своей группе\n\n"
        "Удачи с ростом! 🍈"
    )

async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
