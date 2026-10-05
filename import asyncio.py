import asyncio
import os
import sqlite3
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
from groq import Groq

# Sozlamalar
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
PRIMARY_ADMIN = int(os.getenv("ADMIN_ID"))

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher(storage=MemoryStorage())
groq_client = Groq(api_key=GROQ_API_KEY)

# ==================== DATABASE ====================
def db_init():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    # Users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY
        )
    """)
    # Channels table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            channel_id TEXT PRIMARY KEY,
            invite_link TEXT
        )
    """)
    # Admins table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            admin_id INTEGER PRIMARY KEY
        )
    """)
    cursor.execute("INSERT OR IGNORE INTO admins (admin_id) VALUES (?)", (PRIMARY_ADMIN,))
    conn.commit()
    conn.close()

def add_user(user_id):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users

def get_channels():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id, invite_link FROM channels")
    channels = cursor.fetchall()
    conn.close()
    return channels

def is_admin(user_id):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT admin_id FROM admins WHERE admin_id = ?", (user_id,))
    res = cursor.fetchone()
    conn.close()
    return res is not None

db_init()

# ==================== STATES ====================
class AdminStates(StatesGroup):
    waiting_for_channel = State()
    waiting_for_broadcast = State()
    waiting_for_new_admin = State()

# ==================== HELPER: MAJBURITY OBUNA ====================
async def check_subscriptions(user_id: int):
    channels = get_channels()
    unsubscribed = []
    
    for ch_id, invite_link in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch_id, user_id=user_id)
            if member.status in ["left", "kicked"]:
                unsubscribed.append((ch_id, invite_link))
        except Exception:
            unsubscribed.append((ch_id, invite_link))
            
    return unsubscribed

def get_sub_keyboard(unsubscribed_list):
    buttons = []
    for idx, (ch_id, link) in enumerate(unsubscribed_list, start=1):
        buttons.append([InlineKeyboardButton(text=f"📢 Kanalga obuna bo'lish #{idx}", url=link)])
    buttons.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ==================== HANDLERS ====================
SYSTEM_PROMPT = """Siz UQoder platformasining rasmiy AI Dasturchisisiz. 
Toza, xatosiz va tayyor ishlaydigan kodlarni Markdown formatida taqdim etasiz."""

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    add_user(message.from_user.id)
    unsub = await check_subscriptions(message.from_user.id)
    
    if unsub:
        await message.answer(
            "⚠️ *Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling va Tekshirish tugmasini bosing:*",
            reply_markup=get_sub_keyboard(unsub)
        )
        return

    await message.answer(
        f"👋 Salom, *{message.from_user.first_name}*!\n\n"
        f"🚀 *UQoder AI Bot*ga xush kelibsiz.\n"
        f"Menga dasturlash bo'yicha savolingizni yuboring!"
    )

@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(call: types.CallbackQuery):
    unsub = await check_subscriptions(call.from_user.id)
    if unsub:
        await call.answer("❌ Hali barcha kanallarga obuna bo'lmadingiz!", show_alert=True)
    else:
        await call.message.delete()
        await call.message.answer("✅ Rahmat! Endi botdan to'liq foydalanishingiz mumkin.\nSavolingizni yuboring:")

# ==================== ADMIN PANEL ====================
def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Statistika", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📢 Reklama yuborish", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="admin_add_channel"),
         InlineKeyboardButton(text="➖ Kanal o'chirish", callback_data="admin_del_channel")],
        [InlineKeyboardButton(text="👤 Admin qo'shish", callback_data="admin_add_admin")]
    ])

@dp.message(Command("admin"))
async def admin_cmd(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("🔑 *Admin Panelga xush kelibsiz:*", reply_markup=admin_keyboard())

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(call: types.CallbackQuery):
    if not is_admin(call.from_user.id): return
    users = get_all_users()
    channels = get_channels()
    await call.message.answer(
        f"📊 *Statistika:*\n\n"
        f"👤 Foydalanuvchilar: `{len(users)}` ta\n"
        f"📢 Ulandigan kanallar: `{len(channels)}` ta"
    )

@dp.callback_query(F.data == "admin_add_channel")
async def add_channel_start(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id): return
    await state.set_state(AdminStates.waiting_for_channel)
    await call.message.answer(
        "📌 *Kanal ID va havolasini quyidagi ko'rinishda yuboring:*\n\n"
        "`-1001234567890 https://t.me/kanal_nomi`\n\n"
        "⚠️ *Eslatma:* Botni o'sha kanalda ADMIN qilishingiz shart!"
    )

@dp.message(AdminStates.waiting_for_channel)
async def process_add_channel(message: types.Message, state: FSMContext):
    try:
        ch_id, link = message.text.split()
        conn = sqlite3.connect("bot_database.db")
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO channels (channel_id, invite_link) VALUES (?, ?)", (ch_id, link))
        conn.commit()
        conn.close()
        await message.answer("✅ Kanal muvaffaqiyatli qo'shildi!")
    except Exception as e:
        await message.answer("❌ Xatolik! Formatyga e'tibor bering: `-1001234567890 https://t.me/link`")
    await state.clear()

@dp.callback_query(F.data == "admin_broadcast")
async def broadcast_start(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id): return
    await state.set_state(AdminStates.waiting_for_broadcast)
    await call.message.answer("📢 Tarqatiladigan xabarni (Matn, Rasm yoki Video) yuboring:")

@dp.message(AdminStates.waiting_for_broadcast)
async def process_broadcast(message: types.Message, state: FSMContext):
    users = get_all_users()
    count = 0
    await message.answer("🚀 Reklama tarqatilmoqda...")
    for uid in users:
        try:
            await message.copy_to(chat_id=uid)
            count += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
    await message.answer(f"✅ Reklama `{count}` ta foydalanuvchiga muvaffaqiyatli yetkazildi!")
    await state.clear()

@dp.callback_query(F.data == "admin_add_admin")
async def add_admin_start(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id): return
    await state.set_state(AdminStates.waiting_for_new_admin)
    await call.message.answer("👤 Yangi adminning Telegram ID'sini yuboring:")

@dp.message(AdminStates.waiting_for_new_admin)
async def process_add_admin(message: types.Message, state: FSMContext):
    try:
        new_id = int(message.text)
        conn = sqlite3.connect("bot_database.db")
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO admins (admin_id) VALUES (?)", (new_id,))
        conn.commit()
        conn.close()
        await message.answer(f"✅ `{new_id}` muvaffaqiyatli admin qilindi!")
    except Exception:
        await message.answer("❌ ID faqat raqamlardan iborat bo'lishi kerak.")
    await state.clear()

# ==================== AI CHAT HANDLER ====================
@dp.message(F.text)
async def ai_handler(message: types.Message):
    add_user(message.from_user.id)
    
    # Har bir xabarda obunani tekshirish
    unsub = await check_subscriptions(message.from_user.id)
    if unsub:
        await message.answer(
            "⚠️ *Kanalga obuna bo'lmagansiz yoki chiqib ketgansiz. Davom etish uchun obuna bo'ling:*",
            reply_markup=get_sub_keyboard(unsub)
        )
        return

    status = await message.answer("⚡️ *UQoder AI o'ylamoqda...*")
    try:
        res = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message.text}
            ],
            model="llama-3.3-70b-specdec",
            temperature=0.2
        )
        await status.delete()
        text = res.choices[0].message.content
        
        if len(text) > 4000:
            for i in range(0, len(text), 4000):
                await message.answer(text[i:i+4000])
        else:
            await message.answer(text)
    except Exception as e:
        await status.edit_text(f"❌ Xatolik: {str(e)}")

async def main():
    print("🚀 UQoder AI Bot Admin & Obuna tizimi bilan ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
