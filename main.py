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
# Server Render mặc định dùng giờ UTC (+0), phải cộng thêm 7 tiếng để đúng giờ Việt Nam
VN_TZ = datetime.timezone(datetime.timedelta(hours=7))

def get_now_vn():
    """Hàm lấy thời gian hiện tại theo giờ Việt Nam"""
    return datetime.datetime.now(VN_TZ)

# ==========================================
# 2. WEBSERVER GIỮ BOT SỐNG TRÊN RENDER (KEEP-ALIVE)
# ==========================================
# Render yêu cầu ứng dụng web phải lắng nghe một cổng PORT, nếu không sẽ bị tắt sau vài phút
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot dang chay ngon lanh!")

def run_dummy_server():
    """Khởi chạy server giả để đánh lừa Render"""
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    server.serve_forever()

# ==========================================
# 3. THÔNG TIN CẤU HÌNH BOT & NHÓM TELEGRAM
# ==========================================
TOKEN = "8600522241:AAGEQ6zu70HZSTJkoZpn0Ltz4CE3qx-JwHI" # Mã Token lấy từ BotFather
ADMIN_ID = 8925234034                                  # ID Telegram của Admin (Chủ bot)
GROUP_ID = -1004489838407                              # ID nhóm Telegram bắt buộc phải tham gia
GROUP_LINK = "https://t.me/Xxxhuyh"                    # Link nhóm Telegram

# Danh sách lưu trữ key trong bộ nhớ (Kho key tạm thời)
kho_key = []

def cleanup_keys():
    """Hàm tự động dọn dẹp, xóa bỏ những key đã hết hạn khỏi kho"""
    now = get_now_vn()
    global kho_key
    kho_key = [k for k in kho_key if k['expiry'] > now]

async def check_user_in_group(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Hàm kiểm tra xem người dùng đã vào nhóm Telegram hay chưa"""
    # Nếu là Admin thì luôn cho qua, không cần kiểm tra nhóm
    if user_id == ADMIN_ID:
        return True
    try:
        member = await context.bot.get_chat_member(chat_id=GROUP_ID, user_id=user_id)
        # Các trạng thái được tính là đã vào nhóm: Chủ nhóm, Admin, Thành viên, Hoặc bị hạn chế
        if member.status in ['creator', 'administrator', 'member', 'restricted']:
            return True
        return False
    except Exception as e:
        print(f"Lỗi kiểm tra thành viên: {e}")
        return False

# ==========================================
# 4. LỆNH /start (GIAO DIỆN CHÍNH & BÀN PHÍM BẤM NHANH)
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Bàn phím nút bấm to cố định ở dưới khung chat (Reply Keyboard)
    reply_keyboard = [
        ["🔑 Lấy Key Ngay"],
        ["🚀 Bắt Đầu Lại (/start)", "📢 Nhóm Telegram"],
        ["ℹ️ Trợ Giúp"]
    ]
    markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)

    # Tin nhắn chào mừng gửi đến tất cả người dùng
    msg = (
        "🤖 **XIN CHÀO MỌI NGHƯỜI ĐẾN VỚI BOT LẤY KEY TỰ ĐỘNG!**\n\n"
        "👇 *Bấm nút '🔑 Lấy Key Ngay' ở bàn phím bên dưới để nhận key nhanh nhé!*\n"
    )
    
    # Nếu người gõ /start đúng là ADMIN_ID thì bổ sung thêm Menu quản lý
    if user_id == ADMIN_ID:
        msg += (
            "\n👑 **MENU DÀNH CHO ADMIN:**\n"
            "• `/them <key> <thời_gian>` : Thêm key (Ví dụ: `/them ABC 2h`)\n"
            "• `/soluong` : Xem tổng số key còn lại\n"
            "• `/xemkho` : Xem danh sách tất cả key\n"
            "• `/thongbao <nội_dung>` : Gửi thông báo đến người dùng\n"
        )
    
    # Gửi tin nhắn kèm bàn phím bấm nhanh
    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=markup)

# ==========================================
# 5. XỬ LÝ LẤY KEY TỰ ĐỘNG
# ==========================================
async def process_lay_key(user_id, send_func, context):
    """Hàm lõi xử lý việc cấp key cho người dùng"""
    # 1. Kiểm tra xem người dùng đã vào nhóm chưa
    is_in_group = await check_user_in_group(user_id, context)
    
    # Nếu chưa vào nhóm -> Báo lỗi và hiện nút vào nhóm
    if not is_in_group:
        keyboard = [
            [InlineKeyboardButton("📢 Tham gia nhóm ngay", url=GROUP_LINK)],
            [InlineKeyboardButton("🔄 Bấm vào đây sau khi đã vào nhóm", callback_data="check_and_get_key")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await send_func(
            "⚠️ **Bạn phải tham gia nhóm Telegram mới có thể lấy key!**\n\n"
            "👉 Bấm nút bên dưới để tham gia nhóm, sau đó quay lại chọn **🔑 Lấy Key Ngay**.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return

    # 2. Xóa các key hết hạn trước khi xuất key
    cleanup_keys()
    
    # 3. Nếu còn key trong kho -> Lấy 1 key ra gửi cho khách
    if kho_key:
        data = kho_key.pop(0) # Lấy ra và xóa key đó khỏi kho (đảm bảo mỗi người 1 key)
        time_str = data['expiry'].strftime("%H:%M:%S %d/%m/%Y")
        
        # Tạo nút bấm inline dính dưới tin nhắn key
        keyboard = [[InlineKeyboardButton("🔑 Bấm để Lấy Key Tiếp", callback_data="check_and_get_key")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await send_func(
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔑 **KEY CỦA BẠN:** `{data['key']}`\n"
            f"⏰ **Hạn sử dụng:** {time_str}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"*(Sao chép key bằng cách ấn trực tiếp vào mã key)*",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    else:
        # Nếu kho trống -> Báo hết key
        await send_func("❌ **Hiện tại đã hết key trong kho, vui lòng chờ Admin cấp thêm nhé!** 👀", parse_mode='Markdown')

async def lay_key_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý khi người dùng gõ lệnh /laykey bằng tay"""
    await process_lay_key(update.effective_user.id, update.message.reply_text, context)

# ==========================================
# 6. LẮNG NGHE & XỬ LÝ KHI NGƯỜI DÙNG BẤM NÚT
# ==========================================
async def handle_text_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bắt các sự kiện khi người dùng bấm nút trên bàn phím to dưới khung chat"""
    text = update.message.text
    user_id = update.effective_user.id

    if text == "🔑 Lấy Key Ngay":
        await process_lay_key(user_id, update.message.reply_text, context)
    elif text in ["🚀 Bắt Đầu Lại (/start)", "🚀 Bắt Đầu"]:
        await start(update, context)
    elif text == "📢 Nhóm Telegram":
        keyboard = [[InlineKeyboardButton("👉 Vào Nhóm Ngay", url=GROUP_LINK)]]
        await update.message.reply_text("📢 **Bấm vào nút bên dưới để truy cập nhóm:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    elif text == "ℹ️ Trợ Giúp":
        await update.message.reply_text("💡 **HƯỚNG DẪN:**\n- Bấm nút `🔑 Lấy Key Ngay` để nhận key dùng thử.\n- Nếu gặp sự cố, liên hệ Admin nhóm.", parse_mode='Markdown')

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý khi người dùng bấm các nút Inline (Nút gắn trực tiếp dưới tin nhắn)"""
    query = update.callback_query
    await query.answer() # Phản hồi lại Telegram để tắt hiệu ứng xoay tròn trên nút bấm
    
    if query.data == "check_and_get_key":
        async def send_msg(text, parse_mode=None, reply_markup=None):
            await query.message.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
            
        await process_lay_key(query.from_user.id, send_msg, context)

# ==========================================
# 7. CÁC LỆNH QUẢN LÝ DÀNH RIÊNG CHO ADMIN
# ==========================================
async def them_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /them <key> <thời_gian> để thêm key vào kho"""
    if update.effective_user.id != ADMIN_ID:
        return

    if len(context.args) < 2:
        await update.message.reply_text("❌ Ví dụ: `/them KEY123 2h` hoặc `/them KEY123 30m`", parse_mode='Markdown')
        return

    new_key = context.args[0]
    time_arg = context.args[1].lower()

    # Kiểm tra định dạng thời gian truyền vào (ví dụ: 2h hoặc 30m)
    match = re.match(r"^(\d+)([hm])$", time_arg)
    if not match:
        await update.message.reply_text("❌ Dùng `h` cho giờ hoặc `m` cho phút.", parse_mode='Markdown')
        return

    val, unit = int(match.group(1)), match.group(2)
    now = get_now_vn()

    # Tính mốc thời gian hết hạn theo giờ Việt Nam
    if unit == 'h':
        expiry = now + datetime.timedelta(hours=val)
        time_desc = f"{val} giờ"
    else:
        expiry = now + datetime.timedelta(minutes=val)
        time_desc = f"{val} phút"

    # Thêm key vào danh sách
    kho_key.append({'key': new_key, 'expiry': expiry})
    time_str = expiry.strftime("%H:%M:%S %d/%m/%Y")
    
    await update.message.reply_text(
        f"✅ **Đã thêm key:** `{new_key}`\n"
        f"⏳ Hạn dùng: **{time_desc}** (Hết hạn lúc {time_str})",
        parse_mode='Markdown'
    )

async def so_luong_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /soluong để xem tổng số key còn khả dụng"""
    if update.effective_user.id != ADMIN_ID:
        return
    cleanup_keys()
    await update.message.reply_text(f"📊 Trong kho hiện còn: **{len(kho_key)}** key hợp lệ.", parse_mode='Markdown')

async def xem_toan_bo_kho(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /xemkho để xem chi tiết tất cả các key đang có trong kho"""
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
    """Lệnh /thongbao <nội_dung> để Admin gửi thông báo"""
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text("❌ **Cú pháp sai!**\nVí dụ: `/thongbao Kho key vừa được cập nhật thêm 50 key mới!`", parse_mode='Markdown')
        return

    noi_dung = " ".join(context.args)
    msg = f"📢 **THÔNG BÁO TỪ ADMIN:**\n\n{noi_dung}"
    
    await update.message.reply_text(msg, parse_mode='Markdown')

# ==========================================
# 8. KHỞI CHẠY BOT (MAIN RUNNER)
# ==========================================
if __name__ == '__main__':
    # Chạy server giả trong 1 luồng phụ (Thread)
    t = threading.Thread(target=run_dummy_server)
    t.daemon = True
    t.start()

    # Khởi tạo ứng dụng Bot
    app = ApplicationBuilder().token(TOKEN).build()
    
    # 1. Đăng ký các Handler cho các câu lệnh (/start, /laykey, /them,...)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("laykey", lay_key_cmd))
    app.add_handler(CommandHandler("them", them_key))
    app.add_handler(CommandHandler("soluong", so_luong_key))
    app.add_handler(CommandHandler("xemkho", xem_toan_bo_kho))
    app.add_handler(CommandHandler("thongbao", thong_bao))
    
    # 2. Đăng ký các Handler cho nút bấm
    app.add_handler(CallbackQueryHandler(button_callback))                                # Nút inline dưới tin nhắn
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_buttons)) # Nút bấm bàn phím to
    
    # Bắt đầu nhận và xử lý tin nhắn từ Telegram
    print("Bot đang chạy...")
    app.run_polling()
    
