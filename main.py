import datetime
import os
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Định nghĩa múi giờ Việt Nam (UTC+7)
VN_TZ = datetime.timezone(datetime.timedelta(hours=7))

def get_now_vn():
    return datetime.datetime.now(VN_TZ)

# Giữ Render sống bằng cổng PORT
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot dang chay ngon lanh!")

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    server.serve_forever()

TOKEN = "8600522241:AAGEQ6zu70HZSTJkoZpn0Ltz4CE3qx-JwHI"
ADMIN_ID = 8925234034 
GROUP_ID = -1004489838407 
GROUP_LINK = "https://t.me/Xxxhuyh"

kho_key = []

def cleanup_keys():
    now = get_now_vn()
    global kho_key
    kho_key = [k for k in kho_key if k['expiry'] > now]

async def check_user_in_group(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id=GROUP_ID, user_id=user_id)
        if member.status in ['creator', 'administrator', 'member']:
            return True
        return False
    except Exception:
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🤖 **BOT LẤY KEY TỰ ĐỘNG**\n\n"
        "• Gõ `/laykey` để nhận 1 key sử dụng.\n"
    )
    if update.effective_user.id == ADMIN_ID:
        msg += (
            "\n👑 **MENU DÀNH CHO ADMIN:**\n"
            "• `/them <key> <thời_gian>` : Thêm key (Ví dụ: `/them ABC 2h`)\n"
            "• `/soluong` : Xem tổng số key còn lại\n"
            "• `/xemkho` : Xem danh sách tất cả key\n"
            "• `/thongbao <nội_dung>` : Gửi thông báo đến người dùng\n"
        )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def lay_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    is_in_group = await check_user_in_group(user_id, context)
    
    if not is_in_group:
        keyboard = [
            [InlineKeyboardButton("📢 Tham gia nhóm ngay", url=GROUP_LINK)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "⚠️ **Bạn phải tham gia nhóm Telegram của chúng tôi mới có thể lấy key!**\n\n"
            "👉 Bấm vào nút bên dưới để vào nhóm, sau đó quay lại đây gõ lại lệnh `/laykey` nhé.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return

    cleanup_keys()
    if kho_key:
        data = kho_key.pop(0) 
        time_str = data['expiry'].strftime("%H:%M:%S %d/%m/%Y")
        await update.message.reply_text(
            f"🔑 **Key của bạn:** `{data['key']}`\n"
            f"⏰ Hạn sử dụng đến: **{time_str}**\n"
            f"*(Key đã được xuất riêng cho bạn)*",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ **Hiện tại đã hết key, vui lòng chờ Admin cấp thêm nhé!** 👀", parse_mode='Markdown')

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

if __name__ == '__main__':
    t = threading.Thread(target=run_dummy_server)
    t.daemon = True
    t.start()

    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("laykey", lay_key))
    app.add_handler(CommandHandler("them", them_key))
    app.add_handler(CommandHandler("soluong", so_luong_key))
    app.add_handler(CommandHandler("xemkho", xem_toan_bo_kho))
    app.add_handler(CommandHandler("thongbao", thong_bao))
    
    print("Bot đang chạy...")
    app.run_polling()
  
