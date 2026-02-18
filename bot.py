import os, json, asyncio, random, time
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
    cred = credentials.Certificate(json.loads(os.getenv("FIREBASE_JSON")))
    firebase_admin.initialize_app(cred, {'databaseURL': 'https://lbmetr-default-rtdb.europe-west1.firebasedatabase.app'})
except Exception as e: print(f"Firebase error: {e}")

bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher(storage=MemoryStorage())
spam_check = {}

# ---------- Константы ----------
ADMIN_USERNAME = "trim_peek"
CD_NORMAL, CD_PROFI, PROFI_THRESHOLD = 900, 600, 1000.0
CANCER_CHANCE, CANCER_DURATION, INFINITY_VALUE = 0.005, 18000, 999999999.99

# ---------- FSM ----------
class AdminStates(StatesGroup):
    waiting_for_user = State(); waiting_for_number = State(); waiting_for_text = State(); waiting_for_second_user = State()
class AdminRewardsStates(StatesGroup):
    waiting_for_user = State()

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def has_cancer(data, now=None):
    if not now: now = int(time.time())
    if data.get('cancer')=="Yes" and data.get('cancer_until',0)>now: return True, data['cancer_until']-now
    return False, 0

async def find_user(username):
    username = username.lower().lstrip('@')
    users = db.reference('users').get() or {}
    for uid, data in users.items():
        if isinstance(data,dict):
            if data.get('username')==username: return uid,data
            if data.get('display_name','').lower() in (username, f'@{username}'): return uid,data
    return None

def format_size(s): return "∞" if abs(s-INFINITY_VALUE)<0.01 else f"{s:.2f}"
def today_str(): return datetime.now().strftime("%Y-%m-%d")

async def register_chat(msg):
    if msg.chat.type!='private':
        db.reference(f'chats/{msg.chat.id}').update({'id':msg.chat.id,'type':msg.chat.type,'title':msg.chat.title,'last_seen':int(time.time())})

async def update_stats(uid, data, ref):
    today = today_str()
    total = data.get('total_uses',0)+1
    daily = data.get('daily',{})
    daily[today] = daily.get(today,0)+1
    last = data.get('last_use_date')
    streak = data.get('consecutive_days',1)
    if last:
        ld = datetime.strptime(last,"%Y-%m-%d").date()
        td = datetime.now().date()
        streak = streak+1 if (td-ld).days==1 else 1
    ref.update({'total_uses':total,'daily':daily,'consecutive_days':streak,'last_use_date':today})
    return total, daily[today], streak

async def get_available_rewards(data):
    r = data.get('rewards',{}); t=data.get('total_uses',0); today=today_str(); d=data.get('daily',{}).get(today,0); s=data.get('consecutive_days',0); a=[]
    if not r.get('reward_10') and t>=10: a.append(('10','🏅 10 использований (5-10 см)'))
    if not r.get('reward_150') and t>=150: a.append(('150','🏅 150 использований (100-350 см)'))
    if not r.get(f'daily_20_{today}') and d>=20: a.append(('daily','⚡ 20 за сегодня (10 см)'))
    if not r.get('reward_streak_10') and s>=10: a.append(('streak','🔥 10 дней подряд (45 см)'))
    return a

async def claim_reward(uid, rid, data, ref):
    r=data.get('rewards',{}); size=float(data.get('size',0)); today=today_str(); msg=None
    if rid=='10' and not r.get('reward_10'): b=round(random.uniform(5,10),2); size+=b; r['reward_10']=True; msg=f"🏅 +{b} см"
    elif rid=='150' and not r.get('reward_150'): b=round(random.uniform(100,350),2); size+=b; r['reward_150']=True; msg=f"🏅 +{b} см"
    elif rid=='daily':
        k=f"daily_20_{today}"
        if not r.get(k): size+=10; r[k]=True; msg="⚡ +10 см"
    elif rid=='streak' and not r.get('reward_streak_10'): size+=45; r['reward_streak_10']=True; msg="🔥 +45 см"
    if msg: ref.update({'size':size,'rewards':r})
    return msg

async def check_rewards(uid, data, ref):
    r=data.get('rewards',{}); size=float(data.get('size',0)); changed=False; msgs=[]
    if not r.get('reward_10') and data.get('total_uses',0)>=10: b=round(random.uniform(5,10),2); size+=b; r['reward_10']=True; changed=True; msgs.append(f"🏅 +{b}")
    if not r.get('reward_150') and data.get('total_uses',0)>=150: b=round(random.uniform(100,350),2); size+=b; r['reward_150']=True; changed=True; msgs.append(f"🏅 +{b}")
    today=today_str(); d=data.get('daily',{}).get(today,0); k=f"daily_20_{today}"
    if not r.get(k) and d>=20: size+=10; r[k]=True; changed=True; msgs.append("⚡ +10")
    if not r.get('reward_streak_10') and data.get('consecutive_days',0)>=10: size+=45; r['reward_streak_10']=True; changed=True; msgs.append("🔥 +45")
    if changed: ref.update({'size':size,'rewards':r})
    return msgs

# ========== КОМАНДЫ ИГРОКОВ ==========
@dp.message(Command("start"))
async def start(msg: types.Message):
    await msg.answer("📏 **Лобкометр**\n/lobok — рост\n/lucky — награды\n/lobokinfo — статистика\n/toplobok — топ")

@dp.message(Command("toplobok"))
async def toplobok(msg: types.Message):
    await register_chat(msg)
    users = db.reference('users').get() or {}
    top = []
    for uid,data in users.items():
        if isinstance(data,dict) and not data.get('banned') and data.get('size',0)>0:
            name = data.get('display_name','Инкогнито')
            if name.startswith('@'): name=name[1:]
            top.append({'name':name,'size':data['size']})
    top.sort(key=lambda x:x['size'],reverse=True)
    if not top: await msg.answer("📊 Топ пуст"); return
    text = "🏆 **ТОП-30** 🏆\n"
    for i,u in enumerate(top[:30],1):
        medal = "🥇 " if i==1 else "🥈 " if i==2 else "🥉 " if i==3 else ""
        text += f"{medal}{i}. {u['name']} — {format_size(u['size'])} см\n"
    await msg.answer(text)

@dp.message(Command("lobok"))
async def lobok(msg: types.Message):
    if msg.chat.type=='private': await msg.answer("❌ Только в группе!"); return
    await register_chat(msg)
    uid = str(msg.from_user.id); now = int(time.time())
    if uid in spam_check and now-spam_check[uid]<1: await msg.reply("⚠️ Не спамь!"); return
    spam_check[uid]=now
    ref = db.reference(f'users/{uid}')
    data = ref.get() or {}
    if data.get('banned'): await msg.reply("🚫 Ты забанен"); return
    ref.update({'display_name':msg.from_user.first_name})
    if msg.from_user.username: ref.update({'username':msg.from_user.username.lower()})
    has_c,rem = has_cancer(data,now)
    if has_c: h,m,s = rem//3600, (rem%3600)//60, rem%60; await msg.reply(f"🚨 Рак! Осталось {h}ч {m}м {s}с"); return
    size = float(data.get('size',0))
    last = data.get('last_grow',0)
    cd = CD_PROFI if size>=PROFI_THRESHOLD else CD_NORMAL
    if now < last+cd:
        rem = (last+cd)-now; m,s = rem//60, rem%60; await msg.reply(f"⏳ Подожди {m}м {s}с"); return
    if random.random()<CANCER_CHANCE:
        ref.update({'cancer':"Yes",'cancer_until':now+CANCER_DURATION})
        await msg.reply("☣️ ТЫ ЗАБОЛЕЛ РАКОМ НА 5 ЧАСОВ!"); return
    growth = round(random.uniform(10,20) if size>=PROFI_THRESHOLD else random.uniform(1,5),2)
    new_size = round(size+growth,2)
    ref.update({'size':new_size,'last_grow':now})
    total,_,_ = await update_stats(uid, data, ref)
    reward_msgs = await check_rewards(uid, {**data,'size':new_size,'total_uses':total}, ref)
    reply = f"📏 +{growth} см! Теперь {new_size} см"
    if size<PROFI_THRESHOLD<=new_size: reply = f"🎉 ТЫ ПРОФИ!\n{reply}"
    if reward_msgs: reply += "\n🎁 "+", ".join(reward_msgs)
    await msg.reply(reply)

@dp.message(Command("lobokinfo"))
async def info(msg: types.Message):
    if msg.chat.type=='private': await msg.answer("❌ Только в группе!"); return
    await register_chat(msg)
    uid = str(msg.from_user.id); data = db.reference(f'users/{uid}').get()
    if not data: await msg.answer("❌ Ещё не играл"); return
    size = float(data.get('size',0))
    has_c,rem = has_cancer(data,int(time.time()))
    cancer = f"☣️ Болен (осталось {rem//3600}ч {(rem%3600)//60}м)" if has_c else "✅ Здоров"
    profi = "✅ Профи" if size>=PROFI_THRESHOLD else "❌ Обычный"
    avail = await get_available_rewards(data)
    text = f"📋 **{data.get('display_name',msg.from_user.first_name)}**\n📏 {format_size(size)} см\n🏷️ {data.get('lobok_name','Безымянный')}\n⭐ {profi}\n🩺 {cancer}\n📊 Всего: {data.get('total_uses',0)} | Сегодня: {data.get('daily',{}).get(today_str(),0)} | Стрик: {data.get('consecutive_days',0)}\n🎁 Доступно: {len(avail)}"
    await msg.answer(text)

@dp.message(Command("editlobok"))
async def edit(msg: types.Message):
    if msg.chat.type=='private': await msg.answer("❌ Только в группе!"); return
    await register_chat(msg)
    args = msg.text.split(maxsplit=1)
    if len(args)<2: await msg.answer("❌ Пример: /editlobok Нагибатор"); return
    name = args[1].strip()[:50]
    db.reference(f'users/{msg.from_user.id}').update({'lobok_name':name,'display_name':msg.from_user.first_name})
    if msg.from_user.username: db.reference(f'users/{msg.from_user.id}').update({'username':msg.from_user.username.lower()})
    await msg.reply(f"✅ Имя лобка: «{name}»")

@dp.message(Command("lucky"))
async def lucky(msg: types.Message):
    uid = str(msg.from_user.id); ref = db.reference(f'users/{uid}'); data = ref.get()
    if not data: await msg.answer("❌ Сначала /lobok"); return
    avail = await get_available_rewards(data)
    if not avail: await msg.answer("🎁 Нет наград"); return
    kb = [[types.InlineKeyboardButton(text=desc, callback_data=f"claim_{rid}")] for rid,desc in avail]
    kb.append([types.InlineKeyboardButton(text="🎁 Забрать всё", callback_data="claim_all")])
    kb.append([types.InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_lucky")])
    await msg.answer("🎁 **Награды:**", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith(('claim_','refresh_lucky')))
async def lucky_cb(cb: types.CallbackQuery):
    uid = str(cb.from_user.id); ref = db.reference(f'users/{uid}'); data = ref.get()
    if not data: await cb.answer("Нет данных",True); return
    if cb.data=='refresh_lucky': await cb.message.delete(); await lucky(cb.message); await cb.answer(); return
    if cb.data=='claim_all':
        avail = await get_available_rewards(data)
        if not avail: await cb.answer("Нет наград",True); return
        msgs=[]; size=float(data.get('size',0)); r=data.get('rewards',{}); today=today_str(); changed=False
        for rid,_ in avail:
            if rid=='10' and not r.get('reward_10'): size+=round(random.uniform(5,10),2); r['reward_10']=True; msgs.append("🏅 10"); changed=True
            elif rid=='150' and not r.get('reward_150'): size+=round(random.uniform(100,350),2); r['reward_150']=True; msgs.append("🏅 150"); changed=True
            elif rid=='daily' and not r.get(f'daily_20_{today}'): size+=10; r[f'daily_20_{today}']=True; msgs.append("⚡ 20"); changed=True
            elif rid=='streak' and not r.get('reward_streak_10'): size+=45; r['reward_streak_10']=True; msgs.append("🔥 стрик"); changed=True
        if changed: ref.update({'size':size,'rewards':r}); await cb.answer("Награды получены!",True); await cb.message.edit_text(f"🎁 Получено: {', '.join(msgs)}\nНовый размер: {format_size(size)}")
        else: await cb.answer("Ошибка",True)
        return
    rid = cb.data.replace('claim_','')
    msg = await claim_reward(uid, rid, data, ref)
    if msg: await cb.answer(msg,True); await lucky(cb.message)
    else: await cb.answer("Уже получено",True)

# ========== АДМИНКИ ==========
@dp.message(Command("botcodeadmin01"))
async def admin20(msg: types.Message):
    if msg.chat.type!='private' or not msg.from_user.username or msg.from_user.username.lower()!=ADMIN_USERNAME: return
    acts = ["set_size","add_size","subtract_size","set_infinity","reset_size","give_cancer","remove_cancer","set_cancer_hours","reset_cd","set_lobok_name",
            "user_info","make_profi","remove_profi","ban","unban","random_bonus","random_penalty","set_last_grow","delete_user","transfer_size"]
    kb = [[types.InlineKeyboardButton(text=f"{i+1}", callback_data=f"adm_{a}")] for i,a in enumerate(acts)]
    kb.append([types.InlineKeyboardButton(text="❌", callback_data="adm_cancel")])
    await msg.answer("🔧 Админка 20 функций", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))

@dp.message(Command("adminrewards"))
async def admin_rewards(msg: types.Message):
    if msg.chat.type!='private' or not msg.from_user.username or msg.from_user.username.lower()!=ADMIN_USERNAME: return
    acts = [("👁️ Просмотр","view"),("🔄 Сброс счетчиков","reset_counts"),("🎖️ 10","give_10"),("🎖️ 150","give_150"),("⚡ daily","give_daily"),("🔥 стрик","give_streak"),
            ("🗑️ Сброс флагов","reset_flags"),("📊 Глобал","global_stats"),("🎁 Всё","give_all"),("📈 Топ юз","usage_top"),("🔥 Топ стрик","streak_top"),("📤 Экспорт","export")]
    page=0; admin_rewards_pages={}
    admin_rewards_pages[msg.from_user.id]=page
    await msg.answer("🔧 Управление наградами", reply_markup=get_rewards_kb(page,acts))

def get_rewards_kb(page,acts):
    from math import ceil
    per_page=9; pages=ceil(len(acts)/per_page); start=page*per_page; end=start+per_page
    kb=[]; row=[]
    for i,(txt,cb) in enumerate(acts[start:end]):
        row.append(types.InlineKeyboardButton(text=txt, callback_data=f"rw_{cb}"))
        if (i+1)%3==0: kb.append(row); row=[]
    if row: kb.append(row)
    nav=[]
    if page>0: nav.append(types.InlineKeyboardButton(text="◀️", callback_data=f"rw_page_{page-1}"))
    else: nav.append(types.InlineKeyboardButton(text="⬜", callback_data="rw_noop"))
    nav.append(types.InlineKeyboardButton(text=f"📄 {page+1}/{pages}", callback_data="rw_noop"))
    if end<len(acts): nav.append(types.InlineKeyboardButton(text="▶️", callback_data=f"rw_page_{page+1}"))
    else: nav.append(types.InlineKeyboardButton(text="⬜", callback_data="rw_noop"))
    kb.append(nav); kb.append([types.InlineKeyboardButton(text="❌", callback_data="rw_cancel")])
    return types.InlineKeyboardMarkup(inline_keyboard=kb)

admin_rewards_pages = {}

@dp.callback_query(F.data.startswith('rw_'))
async def rw_cb(cb: types.CallbackQuery, state: FSMContext):
    if not cb.from_user.username or cb.from_user.username.lower()!=ADMIN_USERNAME: await cb.answer("🚫",True); return
    if cb.data=='rw_noop': await cb.answer(); return
    if cb.data.startswith('rw_page_'):
        page = int(cb.data.split('_')[2])
        admin_rewards_pages[cb.from_user.id]=page
        acts = [("👁️ Просмотр","view"),("🔄 Сброс счетчиков","reset_counts"),("🎖️ 10","give_10"),("🎖️ 150","give_150"),("⚡ daily","give_daily"),("🔥 стрик","give_streak"),
                ("🗑️ Сброс флагов","reset_flags"),("📊 Глобал","global_stats"),("🎁 Всё","give_all"),("📈 Топ юз","usage_top"),("🔥 Топ стрик","streak_top"),("📤 Экспорт","export")]
        await cb.message.edit_text("🔧 Управление наградами", reply_markup=get_rewards_kb(page,acts))
        await cb.answer(); return
    if cb.data=='rw_cancel': await cb.message.edit_text("Закрыто"); await cb.answer(); return
    action = cb.data.replace('rw_','')
    if action in ['global_stats','usage_top','streak_top']:
        users = db.reference('users').get() or {}
        if action=='global_stats':
            total = sum(data.get('total_uses',0) for data in users.values() if isinstance(data,dict))
            await cb.message.edit_text(f"📊 Всего использований: {total}")
        elif action=='usage_top':
            stats = [(data.get('display_name',uid),data.get('total_uses',0)) for uid,data in users.items() if isinstance(data,dict)]
            stats.sort(key=lambda x:x[1],reverse=True)
            top = "\n".join([f"{i+1}. {n} — {u}" for i,(n,u) in enumerate(stats[:10])])
            await cb.message.edit_text(f"🏆 Топ использований:\n{top}")
        else:
            stats = [(data.get('display_name',uid),data.get('consecutive_days',0)) for uid,data in users.items() if isinstance(data,dict)]
            stats.sort(key=lambda x:x[1],reverse=True)
            top = "\n".join([f"{i+1}. {n} — {u} дней" for i,(n,u) in enumerate(stats[:10])])
            await cb.message.edit_text(f"🔥 Топ стрик:\n{top}")
        await cb.answer(); return
    await state.update_data(admin_action=action)
    await cb.message.edit_text("👤 Введи @username:")
    await state.set_state(AdminRewardsStates.waiting_for_user)
    await cb.answer()

@dp.message(AdminRewardsStates.waiting_for_user)
async def rw_user(msg: types.Message, state: FSMContext):
    if not msg.from_user.username or msg.from_user.username.lower()!=ADMIN_USERNAME: await msg.answer("🚫"); await state.clear(); return
    res = await find_user(msg.text.strip())
    if not res: await msg.answer("❌ Не найден"); await state.clear(); return
    uid, data = res; sdata = await state.get_data(); action = sdata.get('admin_action'); ref = db.reference(f'users/{uid}')
    if action=='view':
        await msg.answer(f"📊 @{msg.text.strip()}\nВсего: {data.get('total_uses',0)}\nСегодня: {data.get('daily',{}).get(today_str(),0)}\nСтрик: {data.get('consecutive_days',0)}\nНаграды: {json.dumps(data.get('rewards',{}))}")
    elif action=='reset_counts': ref.update({'total_uses':0,'daily':{},'consecutive_days':0,'last_use_date':''}); await msg.answer("✅ Счетчики сброшены")
    elif action=='give_10' or action=='give_150' or action=='give_daily' or action=='give_streak' or action=='give_all':
        r = data.get('rewards',{}); size = float(data.get('size',0)); today=today_str(); changed=False
        if action=='give_10' and not r.get('reward_10'): size+=round(random.uniform(5,10),2); r['reward_10']=True; changed=True
        elif action=='give_150' and not r.get('reward_150'): size+=round(random.uniform(100,350),2); r['reward_150']=True; changed=True
        elif action=='give_daily' and not r.get(f'daily_20_{today}'): size+=10; r[f'daily_20_{today}']=True; changed=True
        elif action=='give_streak' and not r.get('reward_streak_10'): size+=45; r['reward_streak_10']=True; changed=True
        elif action=='give_all':
            if not r.get('reward_10'): size+=round(random.uniform(5,10),2); r['reward_10']=True; changed=True
            if not r.get('reward_150'): size+=round(random.uniform(100,350),2); r['reward_150']=True; changed=True
            if not r.get(f'daily_20_{today}'): size+=10; r[f'daily_20_{today}']=True; changed=True
            if not r.get('reward_streak_10'): size+=45; r['reward_streak_10']=True; changed=True
        if changed: ref.update({'size':size,'rewards':r}); await msg.answer(f"✅ Выдано. Новый размер: {format_size(size)}")
        else: await msg.answer("ℹ️ Уже есть")
    elif action=='reset_flags': ref.update({'rewards':{}}); await msg.answer("✅ Флаги сброшены")
    elif action=='export': await msg.answer(f"📤 {json.dumps(data, indent=2)}")
    await state.clear()

# ========== РАССЫЛКА ==========
@dp.message(Command("adminpostru"))
async def post(msg: types.Message):
    if msg.chat.type!='private' or not msg.from_user.username or msg.from_user.username.lower()!=ADMIN_USERNAME: return
    args = msg.text.split(maxsplit=1)
    if len(args)<2: await msg.answer("❌ /adminpostru Текст"); return
    chats = db.reference('chats').get() or {}
    if not chats: await msg.answer("❌ Нет чатов"); return
    s,f=0,0
    for cid in chats:
        try: await bot.send_message(int(cid), f"📢 **Рассылка:**\n{args[1]}"); s+=1; await asyncio.sleep(0.05)
        except: f+=1
    await msg.answer(f"✅ {s}, ❌ {f}")

# ========== ЗАПУСК ==========
async def main():
    print("✅ Бобёр с наградами и рассылкой запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
