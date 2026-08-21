import asyncio
import datetime
import json
import os
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ==========================================
# 1. CẤU HÌNH CƠ BẢN (BẢN THỬ NGHIỆM)
# ==========================================
VN_TZ = datetime.timezone(datetime.timedelta(hours=7))

def get_now_vn():
    return datetime.datetime.now(VN_TZ).strftime("%H:%M:%S %d/%m/%Y")

TOKEN = "8600522241:AAGEQ6zu70HZSTJkoZpn0Ltz4CE3qx-JwHI" 
ADMIN_ID = 8925234034                                  
GROUP_ID = -1004489838407                              
GROUP_LINK = "https://t.me/Xxxhuyh"                    

# Thông tin ngân hàng thử nghiệm (Sửa lại khi chạy thật)
BANK_ID = "MB"                        # Mã ngân hàng (MB, VCB, TCB,...)
BANK_BIN = "970422"                   # Mã BIN MB Bank
ACCOUNT_NO = "00000000000"            # Số tài khoản thử nghiệm
ACCOUNT_NAME = "NGUYEN VAN A"         # Tên chủ tài khoản thử nghiệm

# API Ngân hàng tự quét (Nếu dùng bên thứ 3 cấp API MB Bank)
MB_API_URL = ""                       # Điền Link API lịch sử MB Bank vào đây nếu có

# Tập hợp lưu các mã giao dịch (RefNo) đã xử lý để CHỐNG CỘNG TRÙNG
PROCESSED_REFNO = set()

# Global Reference để gửi tin nhắn từ Background Task / Webhook
tele_app = None

# ==========================================
# 2. HỆ THỐNG CƠ SỞ DỮ LIỆU SQLITE
# ==========================================
DB_FILE = "bot_data.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT,
            info TEXT,
            price INTEGER
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action_type TEXT,
            details TEXT,
            amount INTEGER,
            time_str TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS processed_refno (
            refno TEXT PRIMARY KEY
        )
    ''')
    conn.commit()

    # Load danh sách RefNo đã xử lý vào bộ nhớ tạm
    cursor.execute("SELECT refno FROM processed_refno")
    rows = cursor.fetchall()
    for row in rows:
        PROCESSED_REFNO.add(row[0])

    conn.close()

init_db()

def get_user_balance(user_id: int) -> int:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO users (user_id, balance) VALUES (?, 0)", (user_id,))
        conn.commit()
        balance = 0
    else:
        balance = row[0]
    conn.close()
    return balance

def update_user_balance(user_id: int, amount: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO users (user_id, balance) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?",
        (user_id, amount, amount)
    )
    conn.commit()
    conn.close()

def add_history(user_id: int, action_type: str, details: str, amount: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO history (user_id, action_type, details, amount, time_str) VALUES (?, ?, ?, ?, ?)",
        (user_id, action_type, details, amount, get_now_vn())
    )
    conn.commit()
    conn.close()

def save_refno(refno: str):
    PROCESSED_REFNO.add(refno)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO processed_refno (refno) VALUES (?)", (refno,))
    conn.commit()
    conn.close()

# ==========================================
# 3. LUỒNG QUÉT API NGÂN HÀNG TỰ ĐỘNG (BACKGROUND TASK)
# ==========================================
async def auto_scan_bank_history():
    """Hàm chạy ngầm quét API Ngân hàng liên tục mỗi vài giây để phát hiện biến động số dư"""
    while True:
        try:
            if MB_API_URL:
                res = requests.get(MB_API_URL, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    transactions = data.get("data", []) or data.get("transactions", [])
                    
                    for tran in transactions:
                        ref_no = str(tran.get("refNo") or tran.get("transactionID") or tran.get("id", ""))
                        amount = int(tran.get("amount", 0) or tran.get("creditAmount", 0))
                        description = str(tran.get("description", "") or tran.get("content", ""))
                        
                        # Nếu chưa xử lý RefNo này và có số tiền nạp vào
                        if ref_no and ref_no not in PROCESSED_REFNO and amount > 0:
                            if "NAP" in description.upper():
                                parts = description.upper().split("NAP")
                                if len(parts) > 1:
                                    raw_id = parts[1].strip().split()[0]
                                    if raw_id.isdigit():
                                        target_id = int(raw_id)
                                        
                                        # Lưu mã RefNo chống cộng trùng
                                        save_refno(ref_no)
                                        
                                        # Cộng tiền & Lưu lịch sử
                                        update_user_balance(target_id, amount)
                                        add_history(target_id, "💳 Nạp Tiền Tự Động", f"Auto API | RefNo: {ref_no}", amount)
                                        
                                        # Thông báo qua Telegram
                                        if tele_app:
                                            await tele_app.bot.send_message(
                                                chat_id=target_id,
                                                text=f"🎉 **NẠP TIỀN THÀNH CÔNG!**\n\n💰 Số tiền: +**{amount:,} VNĐ**\n🔖 Mã GD (RefNo): `{ref_no}`\n⏰ Thời gian: {get_now_vn()}",
                                                parse_mode='Markdown'
                                            )
                                            await tele_app.bot.send_message(
                                                chat_id=ADMIN_ID,
                                                text=f"🔔 **AUTO BANKING:** ID `{target_id}` vừa nạp thành công **{amount:,} VNĐ**! (RefNo: {ref_no})",
                                                parse_mode='Markdown'
                                            )
        except Exception as e:
            print(f"Lỗi khi quét API MB: {e}")
            
        # Nghỉ 5 giây trước khi quét lượt tiếp theo
        await asyncio.sleep(5)

# ==========================================
# 4. WEBSERVER + CỔNG WEBHOOK DỰ PHÒNG
# ==========================================
class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Shop Webhook Active!")

    def do_POST(self):
        if self.path == "/webhook":
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
                records = data.get("data", [data]) if isinstance(data.get("data"), list) else [data]
                
                for item in records:
                    content = str(item.get("description", "") or item.get("content", ""))
                    amount = int(item.get("amount", 0) or item.get("transferAmount", 0))
                    ref_no = str(item.get("refNo") or item.get("transactionID") or item.get("referenceCode", get_now_vn()))
                    
                    if ref_no not in PROCESSED_REFNO and "NAP" in content.upper() and amount > 0:
                        parts = content.upper().split("NAP")
                        if len(parts) > 1:
                            raw_id = parts[1].strip().split()[0]
                            if raw_id.isdigit():
                                target_user_id = int(raw_id)
                                
                                save_refno(ref_no)
                                update_user_balance(target_user_id, amount)
                                add_history(target_user_id, "💳 Nạp Tiền Tự Động", f"Webhook | RefNo: {ref_no}", amount)
                                
                                if tele_app:
                                    tele_app.create_task(
                                        tele_app.bot.send_message(
                                            chat_id=target_user_id,
                                            text=f"🎉 **NẠP TIỀN THÀNH CÔNG!**\n\n💰 Số tiền: +**{amount:,} VNĐ**\n⏰ Thời gian: {get_now_vn()}",
                                            parse_mode='Markdown'
                                        )
                                    )
                                    tele_app.create_task(
                                        tele_app.bot.send_message(
                                            chat_id=ADMIN_ID,
                                            text=f"🔔 **WEBHOOK BANK:** ID `{target_user_id}` vừa nạp thành công **{amount:,} VNĐ**!",
                                            parse_mode='Markdown'
                                        )
                                    )
                
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"status": "success"}')
                return
            except Exception as e:
                print(f"Lỗi xử lý Webhook: {e}")
                self.send_response(400)
                self.end_headers()
                return

        self.send_response(404)
        self.end_headers()

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), WebhookHandler)
    server.serve_forever()

# ==========================================
# 5. GIAO DIỆN CHÍNH & XỬ LÝ TELEGRAM BOT
# ==========================================
async def check_user_in_group(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if user_id == ADMIN_ID: return True
    try:
        member = await context.bot.get_chat_member(chat_id=GROUP_ID, user_id=user_id)
        return member.status in ['creator', 'administrator', 'member', 'restricted']
    except: return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    balance = get_user_balance(user_id)
    
    reply_keyboard = [
        ["🛒 Mua Acc", "💳 Nạp Tiền"],
        ["👤 Tài Khoản", "📜 Lịch Sử Giao Dịch"],
        ["📢 Nhóm Telegram", "🚀 Bắt Đầu Lại (/start)"]
    ]
    markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)

    msg = (
        f"🤖 **SHOP ACC TỰ ĐỘNG 24/7**\n\n"
        f"🆔 ID: `{user_id}`\n"
        f"💰 Số dư: **{balance:,} VNĐ**\n\n"
        f"⚡ Hệ thống nạp tiền tự động duyệt số dư 100%!"
    )
    
    if user_id == ADMIN_ID:
        msg += (
            "\n\n👑 **ADMIN:**\n"
            "• `/themacc <loại> <giá> <info>`\n"
            "• `/congtien <id> <tiền>`\n"
            "• `/kho`\n"
        )
    
    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=markup)

async def show_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await check_user_in_group(user_id, context):
        keyboard = [[InlineKeyboardButton("📢 Tham gia nhóm ngay", url=GROUP_LINK)]]
        await update.message.reply_text("⚠️ **Bạn phải vào nhóm mới mua được Acc!**", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT category FROM accounts")
    categories = cursor.fetchall()
    conn.close()

    if not categories:
        await update.message.reply_text("❌ Hết hàng!")
        return

    keyboard = [[InlineKeyboardButton(f"📂 {cat[0]}", callback_data=f"cat_{cat[0]}")] for cat in categories]
    await update.message.reply_text("🛒 **CHỌN DANH MỤC:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat_name = query.data.replace("cat_", "")
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT price, COUNT(*) FROM accounts WHERE category = ? GROUP BY price", (cat_name,))
    items = cursor.fetchall()
    conn.close()

    if not items:
        await query.message.edit_text("❌ Loại này vừa hết!")
        return

    msg = f"📂 **DANH MỤC:** {cat_name}\n\n"
    keyboard = []
    for price, count in items:
        msg += f"• Giá: **{price:,} VNĐ** (Còn {count})\n"
        keyboard.append([InlineKeyboardButton(f"💳 Mua ngay - {price:,} VNĐ", callback_data=f"buy_{cat_name}_{price}")])

    await query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, cat_name, price_str = query.data.split("_")
    price = int(price_str)
    user_id = query.from_user.id

    balance = get_user_balance(user_id)
    if balance < price:
        await query.message.reply_text(f"❌ Số dư không đủ ({balance:,}/{price:,} VNĐ). Hãy bấm 💳 Nạp Tiền!")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, info FROM accounts WHERE category = ? AND price = ? LIMIT 1", (cat_name, price))
    acc = cursor.fetchone()

    if not acc:
        conn.close()
        await query.message.reply_text("❌ Đã hết acc loại này!")
        return

    acc_id, acc_info = acc
    cursor.execute("DELETE FROM accounts WHERE id = ?", (acc_id,))
    conn.commit()
    conn.close()

    update_user_balance(user_id, -price)
    add_history(user_id, "🛒 Mua Acc", f"Loại: {cat_name} | Acc: {acc_info}", -price)

    await query.message.reply_text(f"🎉 **MUA ACC THÀNH CÔNG!**\n\n📂 Loại: {cat_name}\n💵 Giá: {price:,} VNĐ\n📦 Thông tin Acc:\n`{acc_info}`", parse_mode='Markdown')

# Giao diện nạp tiền VietQR kèm nút kiểm tra lại
async def nap_tien(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    memo = f"NAP{user_id}"
    
    # Tạo link VietQR tự động sinh ảnh
    qr_url = f"https://img.vietqr.io/image/{BANK_ID}-{ACCOUNT_NO}-compact2.png?accountName={ACCOUNT_NAME.replace(' ', '%20')}&addInfo={memo}"
    
    msg = (
        f"💳 **NẠP TIỀN TỰ ĐỘNG**\n"
        f"───────────────────\n"
        f"🏦 **STK:** `{ACCOUNT_NO}`\n"
        f"🏛 **Bank:** {BANK_ID}\n"
        f"👤 **Chủ TK:** {ACCOUNT_NAME}\n"
        f"✏️ **Nội dung chuyển khoản (BẮT BUỘC):**\n"
        f"`{memo}`\n\n"
        f"📌 **Bạn chuyển bao nhiêu tiền thì bot sẽ cộng đúng bấy nhiêu vào số dư.**\n"
        f"⚡ Không cần nhập số tiền trước, không cần tạo đơn.\n"
        f"⏱ Bot tự quét API ngân hàng mỗi vài giây, kiểm tra RefNo chống trùng.\n\n"
        f"⚠️ **Phải ghi đúng nội dung `{memo}` để bot nhận diện.**"
    )
    
    keyboard = [
        [InlineKeyboardButton("🔄 Kiểm tra lại / Làm mới", callback_data="refresh_balance")],
        [InlineKeyboardButton("🔙 Trở lại", callback_data="back_to_start")]
    ]
    
    await update.message.reply_photo(
        photo=qr_url, 
        caption=msg, 
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    balance = get_user_balance(user_id)
    
    if query.data == "refresh_balance":
        await query.message.reply_text(f"💰 Số dư hiện tại của bạn: **{balance:,} VNĐ**", parse_mode='Markdown')
    elif query.data == "back_to_start":
        await query.message.delete()

async def xem_tai_khoan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    balance = get_user_balance(user_id)
    await update.message.reply_text(f"👤 **TÀI KHOẢN**\n🆔 ID: `{user_id}`\n💰 Số dư: **{balance:,} VNĐ**", parse_mode='Markdown')

async def xem_lich_su(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT action_type, details, amount, time_str FROM history WHERE user_id = ? ORDER BY id DESC LIMIT 10", (user_id,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("📜 Chưa có giao dịch nào!")
        return

    msg = "📜 **LỊCH SỬ GIAO DỊCH:**\n\n"
    for action, details, amount, time_str in rows:
        sign = "+" if amount > 0 else ""
        msg += f"• **{action}** ({sign}{amount:,} VNĐ)\n  CT: `{details}`\n  ⏰ {time_str}\n"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🛒 Mua Acc": await show_categories(update, context)
    elif text == "💳 Nạp Tiền": await nap_tien(update, context)
    elif text == "👤 Tài Khoản": await xem_tai_khoan(update, context)
    elif text == "📜 Lịch Sử Giao Dịch": await xem_lich_su(update, context)
    elif text in ["🚀 Bắt Đầu Lại (/start)", "🚀 Bắt Đầu"]: await start(update, context)
    elif text == "📢 Nhóm Telegram":
        await update.message.reply_text("📢 **Vào nhóm:**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👉 Tham Gia", url=GROUP_LINK)]]))

async def admin_them_acc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID or len(context.args) < 3: return
    category, price_str = context.args[0], context.args[1]
    info = " ".join(context.args[2:])
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO accounts (category, info, price) VALUES (?, ?, ?)", (category, info, int(price_str)))
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ Đã thêm Acc thành công!")

async def admin_cong_tien(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID or len(context.args) < 2: return
    target_id, amount = int(context.args[0]), int(context.args[1])
    update_user_balance(target_id, amount)
    add_history(target_id, "💳 Nạp Tiền", "Admin cộng thủ công", amount)
    await update.message.reply_text(f"✅ Đã cộng {amount:,} VNĐ cho `{target_id}`!")

async def admin_xem_kho(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT category, price, COUNT(*) FROM accounts GROUP BY category, price")
    rows = cursor.fetchall()
    conn.close()
    msg = "📦 **KHO ACC:**\n\n" + "\n".join([f"• {c} | {p:,} VNĐ -> Còn {cnt}" for c, p, cnt in rows]) if rows else "Trống"
    await update.message.reply_text(msg, parse_mode='Markdown')

# Khởi chạy các tác vụ ngầm khi
