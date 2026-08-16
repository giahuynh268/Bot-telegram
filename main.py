import datetime
import os
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# ==========================================
# 1. CẤU HÌNH MÚI GIỜ VIỆT NAM (UTC+7)
# ==========================================
VN_TZ = datetime.timezone(datetime.timedelta(hours=7))

def get_now_vn():
    return datetime.datetime.now(VN_TZ)

# ==========================================
# 2. WEBSERVER GIỮ BOT SỐNG TRÊN RENDER (KEEP-ALIVE)
# ==========================================
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot dang chay ngon lanh!")

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    server.serve_forever()

# ==========================================
# 3. THÔNG TIN CẤU HÌNH BOT & KÊNH/NHÓM
# ==========================================
TOKEN = "8600522241:AAGEQ6zu70HZSTJkoZpn0Ltz4CE3qx-JwHI" # Token Bot
ADMIN_ID = 8925234034                                  # ID Telegram Admin
GROUP_ID = -1004489838407                              # ID Kênh hoặc Nhóm
GROUP_LINK = "https://t.me/Xxxhuyh"                    # Link Kênh hoặc Nhóm

kho_key = []

def cleanup_keys():
    now = get_now_vn()
    global kho_key
    kho_key = [k for k in kho_key if k['expiry'] > now]

async def check_user_in_group(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Hàm kiểm tra xem người dùng đã tham gia Kênh / Nhóm chưa"""
    if user_id == ADMIN_ID:
        return True
    try:
        member = await context.bot.get_chat_member(chat_id=GROUP_ID, user_id=user_id)
        if member.status in ['creator', 'administrator', 'member', 'restricted']:
            return True
        return False
    except Exception as e:
        print(f"Lỗi kiểm tra thành viên: {e}")
        return False

# ==========================================
# 4. LỆNH /start (GIAO DIỆN CHÍNH)
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    reply_keyboard = [
        ["🔑 Lấy Key Ngay"],
        ["🚀 Bắt Đầu Lại (/start)", "📢 Nhóm Telegram"],
        ["ℹ️ Trợ Giúp"]
    ]
    markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)

    msg = (
        "🤖 **XIN CHÀO MỌI NGHƯỜI ĐẾN VỚI BOT LẤY KEY TỰ ĐỘNG!**\n\n"
        "👇 *Bấm nút '🔑 Lấy Key Ngay' ở bàn phím bên dưới để nhận key nhanh nhé!*\n"
    )
    
    if user_id == ADMIN_ID:
        msg += (
            "\n👑 **MENU DÀNH CHO ADMIN:**\n"
            "• `/them <key> <thời_gian>` : Thêm key (Ví dụ: `/them ABC 2h`)\n"
            "• `/soluong` : Xem tổng số key còn lại\n"
            "• `/xemkho` : Xem danh sách tất cả key\n"
            "• `/thongbao <nội_dung>` : Gửi thông báo đến người dùng\n"
        )
    
    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=markup)

# ==========================================
# 5. XỬ LÝ LẤY KEY TỰ ĐỘNG & BÁO VỀ ADMIN
# ==========================================
async def process_lay_key(user, send_func, context):
    user_id = user.id
    first_name = user.first_name or "Không tên"
    username = f"@{user.username}" if user.username else "Không có"

    # 1. Kiểm tra tham gia Kênh/Nhóm
    is_in_group = await check_user_in_group(user_id, context)
    
    if not is_in_group:
        keyboard = [
            [InlineKeyboardButton("📢 Tham gia nhóm ngay", url=GROUP_LINK)],
            [InlineKeyboardButton("🔄 Bấm vào đây sau khi đã vào nhóm", callback_data="check_and_get_key")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await send_func(
            "⚠️ **Bạn phải tham gia nhóm/kênh Telegram mới có thể lấy key!**\n\n"
            "👉 Bấm nút bên dưới để tham gia, sau đó quay lại chọn **🔑 Lấy Key Ngay**.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return

    # 2. Xóa các key hết hạn
    cleanup_keys()
    
    # 3. Xuất key nếu còn
    if kho_key:
        data = kho_key.pop(0) 
        time_str = data['expiry'].strftime("%H:%M:%S %d/%m/%Y")
        
        keyboard = [[InlineKeyboardButton("🔑 Bấm để Lấy Key Tiếp", callback_data="check_and_get_key")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Gửi key cho Khách
        await send_func(
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔑 **KEY CỦA BẠN:** `{data['key']}`\n"
            f"⏰ **Hạn sử dụng:** {time_str}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"*(Sao chép key bằng cách ấn trực tiếp vào mã key)*",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

        # 🔔 GỬI THÔNG BÁO VỀ CHO ADMIN (Nếu người lấy không phải Admin)
        if user_id != ADMIN_ID:
            try:
                admin_msg = (
                    "🔔 **CÓ KHÁCH VỪA LẤY KEY!**\n\n"
                    f"👤 **Tên:** {first_name}\n"
                    f"🆔 **ID:** `{user_id}`\n"
                    f"🌐 **Username:** {username}\n"
                    f"🔑 **Key đã cấp:** `{data['key']}`\n"
                    f"⏳ **Hạn dùng:** {time_str}"
                )
                await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode='Markdown')
            except Exception as e:
                print(f"Lỗi gửi thông báo cho Admin: {e}")

    else:
        await send_func("❌ **Hiện tại đã hết key trong kho, vui lòng chờ Admin cấp thêm nhé!** 👀", parse_mode='Markdown')

async def lay_key_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_lay_key(update.effective_user, update.message.reply_text, context)

# ==========================================
# 6. LẮNG NGHE & XỬ LÝ NÚT BẤM
# ==========================================
async def handle_text_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "🔑 Lấy Key Ngay":
        await process_lay_key(update.effective_user, update.message.reply_text, context)
    elif text in ["🚀 Bắt Đầu Lại (/start)", "🚀 Bắt Đầu"]:
        await start(update, context)
    elif text == "📢 Nhóm Telegram":
        keyboard = [[InlineKeyboardButton("👉 Vào Nhóm/Kênh Ngay", url=GROUP_LINK)]]
        await update.message.reply_text("📢 **Bấm vào nút bên dưới để truy cập:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    elif text == "ℹ️ Trợ Giúp":
        await update.message.reply_text("💡 **HƯỚNG DẪN:**\n- Bấm nút `🔑 Lấy Key Ngay` để nhận key dùng thử.\n- Nếu gặp sự cố, liên hệ Admin.", parse_mode='Markdown')

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "check_and_get_key":
        async def send_msg(text, parse_mode=None, reply_markup=None):
            await query.message.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
            
        await process_lay_key(query.from_user, send_msg, context)

# ==========================================
# 7. CÁC LỆNH QUẢN LÝ CỦA ADMIN
# ==========================================
async def them_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if len(context.args) < 2:
        await update.message.reply_text("❌ Ví dụ: `/them KEY123 2h` hoặc `/them KEY123 30m`", parse_mode='Markdown')
        return

    new_key = context.args[0]
    time_arg = context.args[1].lower()

    match = re.match(r"^(\d+)([hm])$", time_arg)
    if not match:
        await update.message.reply_text("❌ Dùng `h` cho giờ hoặc `m` cho phút.", parse_mode='Markdown')
        return

    val, unit = int(match.group(1)), match.group(2)
    now = get_now_vn()

    if unit == 'h':
        expiry = now + datetime.timedelta(hours=val)
        time_desc = f"{val} giờ"
    else:
        expiry = now + datetime.timedelta(minutes=val)
        time_desc = f"{val} phút"

    kho_key.append({'key': new_key, 'expiry': expiry})
    time_str = expiry.strftime("%H:%M:%S %d/%m/%Y")
    
    await update.message.reply_text(
        f"✅ **Đã thêm key:** `{new_key}`\n"
        f"⏳ Hạn dùng: **{time_desc}** (Hết hạn lúc {time_str})",
        parse_mode='Markdown'
    )

async def so_luong_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    cleanup_keys()
    await update.message.reply_text(f"📊 Trong kho hiện còn: **{len(kho_key)}** key hợp lệ.", parse_mode='Markdown')

async def xem_toan_bo_kho(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    cleanup_keys()
    
    if not kho_key:
        await update.message.reply_text("📦 Kho key hiện đang trống!", parse_mode='Markdown')
        return

    msg = f"📦 **DANH SÁCH KEY TRONG KHO ({len(kho_key)} key):**\n\n"
    for i, item in enumerate(kho_key, 1):
        time_str = item['expiry'].strftime("%H:%M:%S %d/%m/%Y")
        msg += f"{i}. Key: `{item['key']}`\n   ⏳ Hết hạn: {time_str}\n"

    await update.message.reply_text(msg, parse_mode='Markdown')

async def thong_bao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text("❌ **Cú pháp sai!**\nVí dụ: `/thongbao Kho key vừa được cập nhật thêm 50 key mới!`", parse_mode='Markdown')
        return

    noi_dung = " ".join(context.args)
    msg = f"📢 **THÔNG BÁO TỪ ADMIN:**\n\n{noi_dung}"
    
    await update.message.reply_text(msg, parse_mode='Markdown')

# ==========================================
# 8. KHỞI CHẠY BOT
# ==========================================
if __name__ == '__main__':
    t = threading.Thread(target=run_dummy_server)
    t.daemon = True
    t.start()

    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("laykey", lay_key_cmd))
    app.add_handler(CommandHandler("them", them_key))
    app.add_handler(CommandHandler("soluong", so_luong_key))
    app.add_handler(CommandHandler("xemkho", xem_toan_bo_kho))
    app.add_handler(CommandHandler("thongbao", thong_bao))
    
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_buttons))
    
    print("Bot đang chạy...")
    app.run_polling()
                
