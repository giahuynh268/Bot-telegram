import asyncio
import logging
import os
import sqlite3
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

# ========================== CẤU HÌNH ==========================
TOKEN = "8600522241:AAGEQ6zu70HZSTJkoZpn0Ltz4CE3qx-JwHI"
ADMIN_ID = 8925234034

# ========================== WEBSERVER KEEP-ALIVE ==========================
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot dang chay ngon lanh!")

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    server.serve_forever()

threading.Thread(target=run_dummy_server, daemon=True).start()

# ========================== DATABASE ==========================
DB_NAME = "shop.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        registered_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS wallets (
        user_id INTEGER PRIMARY KEY,
        balance INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        price INTEGER,
        stock INTEGER DEFAULT 0,
        description TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        category_id INTEGER,
        quantity INTEGER,
        total_price INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        type TEXT,
        amount INTEGER,
        description TEXT,
        timestamp TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS pending_deposits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()

init_db()

# ========================== FSM STATES ==========================
class DepositStates(StatesGroup):
    waiting_amount = State()

# ========================== BOT INIT ==========================
storage = MemoryStorage()
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=storage)

# ========================== DB HELPER ==========================
def get_db():
    return sqlite3.connect(DB_NAME)

def register_user(user_id, username, full_name):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?,?,?)", (user_id, username, full_name))
    c.execute("INSERT OR IGNORE INTO wallets (user_id, balance) VALUES (?,0)", (user_id,))
    conn.commit()
    conn.close()

def get_balance(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT balance FROM wallets WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def add_balance(user_id, amount):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE wallets SET balance = balance + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()

def deduct_balance(user_id, amount):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE wallets SET balance = balance - ? WHERE user_id=? AND balance >= ?", (amount, user_id, amount))
    conn.commit()
    conn.close()

def get_categories():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, name, price, stock, description FROM categories ORDER BY id")
    rows = c.fetchall()
    conn.close()
    return rows

def get_category(category_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, name, price, stock FROM categories WHERE id=?", (category_id,))
    row = c.fetchone()
    conn.close()
    return row

def reduce_stock(category_id, quantity=1):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE categories SET stock = stock - ? WHERE id=? AND stock >= ?", (quantity, category_id, quantity))
    conn.commit()
    conn.close()

def create_order(user_id, category_id, quantity, total_price):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO orders (user_id, category_id, quantity, total_price) VALUES (?,?,?,?)",
              (user_id, category_id, quantity, total_price))
    conn.commit()
    conn.close()

def add_transaction(user_id, type, amount, description=""):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO transactions (user_id, type, amount, description) VALUES (?,?,?,?)",
              (user_id, type, amount, description))
    conn.commit()
    conn.close()

def create_pending_deposit(user_id, amount):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO pending_deposits (user_id, amount) VALUES (?,?)", (user_id, amount))
    deposit_id = c.lastrowid
    conn.commit()
    conn.close()
    return deposit_id

def get_pending_deposit(deposit_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, user_id, amount, status FROM pending_deposits WHERE id=?", (deposit_id,))
    row = c.fetchone()
    conn.close()
    return row

def update_pending_deposit(deposit_id, status):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE pending_deposits SET status=? WHERE id=?", (status, deposit_id))
    conn.commit()
    conn.close()

def get_user_transactions(user_id, limit=10):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT type, amount, description, timestamp FROM transactions WHERE user_id=? ORDER BY timestamp DESC LIMIT ?",
              (user_id, limit))
    rows = c.fetchall()
    conn.close()
    return rows

# ========================== MENU CHÍNH ==========================
def main_menu_keyboard():
    buttons = [
        [InlineKeyboardButton(text="💰 Số dư", callback_data="balance")],
        [InlineKeyboardButton(text="💳 Nạp tiền", callback_data="deposit")],
        [InlineKeyboardButton(text="🛒 Mua acc", callback_data="buy_menu")],
        [InlineKeyboardButton(text="📜 Lịch sử", callback_data="history")],
        [InlineKeyboardButton(text="📞 Liên hệ", callback_data="contact")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ========================== START ==========================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user = message.from_user
    register_user(user.id, user.username, user.full_name)
    await message.answer(
        "🤖 **CỬA HÀNG ACC CLONE FF**\n\n"
        "Chọn chức năng bên dưới:",
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown"
    )

# ========================== CALLBACKS ==========================
@dp.callback_query(lambda c: c.data == "balance")
async def show_balance(callback: CallbackQuery):
    bal = get_balance(callback.from_user.id)
    await callback.message.edit_text(
        f"💰 **Số dư của bạn:** {bal:,}đ",
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "deposit")
async def show_deposit(callback: CallbackQuery):
    user_id = callback.from_user.id
    text = (
        "💳 **NẠP TIỀN**\n\n"
        "• STK: 123456789\n"
        "• Bank: MB Bank\n"
        "• Chủ TK: NGUYEN VAN A\n"
        f"• Nội dung (BẮT BUỘC): `NAP{user_id}`\n\n"
        "Chuyển bao nhiêu thì bot sẽ cộng đúng bấy nhiêu.\n"
        "Không cần nhập số tiền trước, không cần tạo đơn.\n"
        "Bot tự quét API ngân hàng mỗi vài giây.\n\n"
        "👉 Sau khi chuyển, bấm nút bên dưới."
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("🔄 Kiểm tra lại / Làm mới", callback_data="check_deposit")],
        [InlineKeyboardButton("🔙 Trở lại", callback_data="back_main")]
    ])
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(lambda c: c.data == "check_deposit")
async def check_deposit(callback: CallbackQuery):
    await callback.message.edit_text(
        "💳 Nhập **số tiền** bạn đã chuyển (VD: 50000):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton("🔙 Trở lại", callback_data="back_main")]
        ])
    )
    await callback.answer()
    await dp.fsm.storage.set_state(chat=callback.message.chat.id, user=callback.from_user.id, state=DepositStates.waiting_amount)

@dp.callback_query(lambda c: c.data == "buy_menu")
async def show_buy_menu(callback: CallbackQuery):
    categories = get_categories()
    if not categories:
        await callback.message.edit_text("❌ Chưa có loại acc nào.", reply_markup=main_menu_keyboard())
        await callback.answer()
        return

    text = "🛒 **KHU VỰC MUA ACC**\n\n"
    buttons = []
    for cat in categories:
        stock = cat[3]
        price = cat[2]
        name = cat[1]
        text += f"• **{name}**\n  Giá: {price:,}đ | Tồn: {stock}\n\n"
        if stock > 0:
            buttons.append([InlineKeyboardButton(f"Mua {name} ({price:,}đ)", callback_data=f"buy_{cat[0]}")])
    if not buttons:
        text += "❌ Tất cả acc đã hết hàng."
    buttons.append([InlineKeyboardButton("🔙 Trở lại menu", callback_data="back_main")])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith("buy_"))
async def process_buy(callback: CallbackQuery):
    category_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id

    cat = get_category(category_id)
    if not cat or cat[3] <= 0:
        await callback.answer("Loại acc này đã hết!", show_alert=True)
        return

    price = cat[2]
    balance = get_balance(user_id)
    if balance < price:
        await callback.answer(f"❌ Không đủ tiền! Cần {price:,}đ, bạn có {balance:,}đ.", show_alert=True)
        return

    deduct_balance(user_id, price)
    reduce_stock(category_id, 1)
    create_order(user_id, category_id, 1, price)
    add_transaction(user_id, "purchase", -price, f"Mua {cat[1]}")

    await callback.message.edit_text(
        f"✅ **Mua thành công!**\n"
        f"Bạn đã mua 1 {cat[1]} với giá {price:,}đ.\n"
        f"Số dư còn lại: {get_balance(user_id):,}đ.\n\n"
        f"Vui lòng kiểm tra inbox để nhận acc (nếu có).",
        reply_markup=main_menu_keyboard()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "history")
async def show_history(callback: CallbackQuery):
    user_id = callback.from_user.id
    transactions = get_user_transactions(user_id, limit=10)
    if not transactions:
        text = "📜 Chưa có giao dịch nào."
    else:
        text = "📜 **Lịch sử (10 gần nhất):**\n\n"
        for t in transactions:
            typ = "➕ Nạp" if t[0] == 'deposit' else "➖ Mua"
            text += f"{typ} {t[1]:,}đ - {t[2]} - {t[3]}\n"
    await callback.message.edit_text(text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(lambda c: c.data == "contact")
async def show_contact(callback: CallbackQuery):
    text = "📞 **LIÊN HỆ**\n\n• Chat admin để xử lý nhanh\n• Vào nhóm chat để hỏi thêm\n• Theo dõi kênh để cập nhật"
    buttons = [
        [InlineKeyboardButton("👤 Chat Admin", url="https://t.me/huyh_ff")],
        [InlineKeyboardButton("📢 Kênh", url="https://t.me/Xxxhuyh")],
        [InlineKeyboardButton("👥 Nhóm chat", url="https://t.me/your_group_chat")],
        [InlineKeyboardButton("🔙 Trở lại", callback_data="back_main")]
    ]
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_main")
async def back_to_main(callback: CallbackQuery):
    await callback.message.edit_text("🏠 **Menu chính**", reply_markup=main_menu_keyboard())
    await callback.answer()

# ========================== NHẬP SỐ TIỀN NẠP ==========================
@dp.message(StateFilter(DepositStates.waiting_amount))
async def deposit_amount(message: Message, state: FSMContext):
    try:
        amount = int(message.text.strip().replace(',', ''))
        if amount <= 0:
            raise ValueError
    except:
        await message.answer("❌ Số tiền không hợp lệ. Nhập lại:")
        return

    user_id = message.from_user.id
    deposit_id = create_pending_deposit(user_id, amount)

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("✅ Xác nhận", callback_data=f"confirm_deposit_{deposit_id}")],
        [InlineKeyboardButton("❌ Từ chối", callback_data=f"reject_deposit_{deposit_id}")]
    ])
    await bot.send_message(
        ADMIN_ID,
        f"💳 **YÊU CẦU NẠP TIỀN**\nUser: {user_id}\nSố tiền: {amount:,}đ\nMã yêu cầu: #{deposit_id}",
        reply_markup=admin_kb
    )

    await message.answer(
        f"✅ Đã ghi nhận yêu cầu nạp {amount:,}đ.\n"
        f"Vui lòng chờ admin xác nhận.",
        reply_markup=main_menu_keyboard()
    )
    await state.clear()

# ========================== ADMIN XỬ LÝ NẠP ==========================
@dp.callback_query(lambda c: c.data and c.data.startswith("confirm_deposit_"))
async def confirm_deposit(callback: CallbackQuery):
    deposit_id = int(callback.data.split("_")[2])
    deposit = get_pending_deposit(deposit_id)
    if not deposit or deposit[3] != 'pending':
        await callback.answer("Yêu cầu không hợp lệ hoặc đã xử lý.", show_alert=True)
        return
    user_id, amount = deposit[1], deposit[2]
    add_balance(user_id, amount)
    add_transaction(user_id, "deposit", amount, f"Nạp qua admin (mã #{deposit_id})")
    update_pending_deposit(deposit_id, "confirmed")
    try:
        await bot.send_message(user_id, f"💰 **Nạp tiền thành công!**\nSố tiền {amount:,}đ đã được cộng vào ví.")
    except:
        pass
    await callback.message.edit_text(f"✅ Đã xác nhận nạp #{deposit_id} ({amount:,}đ) cho user {user_id}.")
    await callback.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith("reject_deposit_"))
async def reject_deposit(callback: CallbackQuery):
    deposit_id = int(callback.data.split("_")[2])
    deposit = get_pending_deposit(deposit_id)
    if not deposit or deposit[3] != 'pending':
        await callback.answer("Yêu cầu không hợp lệ hoặc đã xử lý.", show_alert=True)
        return
    update_pending_deposit(deposit_id, "cancelled")
    try:
        await bot.send_message(deposit[1], "❌ Yêu cầu nạp tiền của bạn đã bị từ chối.")
    except:
        pass
    await callback.message.edit_text(f"❌ Đã từ chối nạp #{deposit_id}.")
    await callback.answer()

# ========================== ADMIN LỆNH ==========================
@dp.message(Command("addcat"))
async def add_category(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split(maxsplit=3)
    if len(parts) < 4:
        await message.answer("Sai cú pháp: /addcat <tên> <giá> <số_lượng>")
        return
    name, price, stock = parts[1], int(parts[2]), int(parts[3])
    desc = parts[4] if len(parts) > 4 else ""
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO categories (name, price, stock, description) VALUES (?,?,?,?)", (name, price, stock, desc))
        conn.commit()
        await message.answer(f"✅ Đã thêm {name} - {price:,}đ - tồn {stock}")
    except sqlite3.IntegrityError:
        await message.answer("❌ Tên đã tồn tại.")
    conn.close()

@dp.message(Command("delcat"))
async def delete_category(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Sai cú pháp: /delcat <tên>")
        return
    name = parts[1]
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM categories WHERE name=?", (name,))
    if c.rowcount > 0:
        conn.commit()
        await message.answer(f"✅ Đã xóa {name}")
    else:
        await message.answer("❌ Không tìm thấy.")
    conn.close()

@dp.message(Command("pending"))
async def list_pending(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, user_id, amount, created_at FROM pending_deposits WHERE status='pending'")
    rows = c.fetchall()
    conn.close()
    if not rows:
        await message.answer("Không có yêu cầu nạp nào.")
        return
    text = "📋 Yêu cầu nạp chờ:\n"
    for r in rows:
        text += f"#{r[0]} | User {r[1]} | {r[2]:,}đ | {r[3]}\n"
    await message.answer(text)

@dp.message(Command("addmoney"))
async def add_money(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("Sai cú pháp: /addmoney <user_id> <số_tiền>")
        return
    uid, amt = int(parts[1]), int(parts[2])
    add_balance(uid, amt)
    add_transaction(uid, "deposit", amt, "Admin cộng trực tiếp")
    await message.answer(f"✅ Đã cộng {amt:,}đ cho {uid}")
    try:
        await bot.send_message(uid, f"💰 Admin đã cộng {amt:,}đ vào ví của bạn.")
    except:
        pass

# ========================== RUN ==========================
async def main():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM categories")
    if c.fetchone()[0] == 0:
        sample = [
            ("ACC LV5", 1700, 143, "Acc level 5"),
            ("ACC Rank KC", 35000, 0, "Rank Kim Cương"),
            ("ACC Rank Huyền Thoại", 50000, 0, "Rank Huyền Thoại"),
        ]
        c.executemany("INSERT INTO categories (name, price, stock, description) VALUES (?,?,?,?)", sample)
        conn.commit()
    conn.close()

    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
