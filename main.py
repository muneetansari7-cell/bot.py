import logging

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ─────────────────────────────────────────────
#  CONFIGURATION  ←  Fill these in
# ─────────────────────────────────────────────
BOT_TOKEN = "8795852939:AAESFRkA1m8jDIUKQicGQKLkCEEpecDXs4Y"   # From @BotFather
DB_CHANNEL_ID = -1003897916058                    # Your file-storage channel/group ID (negative number)
# ─────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── In-memory index: {file_name_lower: [{"name": str, "message_id": int, "type": str}]}
file_index: dict[str, list[dict]] = {}


# ═══════════════════════════════════════════════════════════════
#  INDEXING  –  scan the storage channel and build file_index
# ═══════════════════════════════════════════════════════════════

def _extract_file_info(message) -> dict | None:
    """Return file metadata dict from a Telegram Message, or None."""
    file_obj = None
    file_type = None

    if message.document:
        file_obj = message.document
        file_type = "document"
    elif message.audio:
        file_obj = message.audio
        file_type = "audio"
    elif message.video:
        file_obj = message.video
        file_type = "video"
    elif message.photo:
        # photos don't have a file_name; use caption or a placeholder
        best = message.photo[-1]
        name = (message.caption or "photo").strip()
        return {"name": name, "message_id": message.message_id, "type": "photo",
                "file_id": best.file_id}
    elif message.voice:
        file_obj = message.voice
        file_type = "voice"
    elif message.video_note:
        file_obj = message.video_note
        file_type = "video_note"

    if file_obj is None:
        return None

    name = getattr(file_obj, "file_name", None) or (message.caption or file_type or "file").strip()
    return {
        "name": name,
        "message_id": message.message_id,
        "type": file_type,
        "file_id": file_obj.file_id,
    }


async def index_channel(bot, limit: int = 200) -> int:
    """
    Walk backwards through DB_CHANNEL_ID and index every file message.
    Telegram's getChatHistory isn't directly available in Bot API, so we
    use forward-iteration via message IDs (fast heuristic scan).
    Returns the number of files indexed.
    """
    file_index.clear()
    indexed = 0
    # Try message IDs from 1 up to `limit`; gaps are silently ignored.
    for msg_id in range(1, limit + 1):
        try:
            msg = await bot.forward_message(
                chat_id=DB_CHANNEL_ID,   # forward to itself just to peek
                from_chat_id=DB_CHANNEL_ID,
                message_id=msg_id,
            )
            info = _extract_file_info(msg)
            if info:
                key = info["name"].lower()
                file_index.setdefault(key, []).append(info)
                indexed += 1
            # Delete the forwarded copy immediately to keep channel clean
            await bot.delete_message(chat_id=DB_CHANNEL_ID, message_id=msg.message_id)
        except Exception:
            pass  # message doesn't exist or isn't a file

    logger.info("Indexed %d files from channel %s", indexed, DB_CHANNEL_ID)
    return indexed


async def index_channel_via_updates(bot) -> int:
    """
    Alternative: use stored file_ids passed through bot messages.
    Call /addfile <file_name> while forwarding a file to the bot to register it.
    This is the recommended approach – see /addfile command below.
    """
    return len(file_index)


# ═══════════════════════════════════════════════════════════════
#  SEARCH HELPERS
# ═══════════════════════════════════════════════════════════════

def search_files(query: str) -> list[dict]:
    """Return all indexed files whose name contains `query` (case-insensitive)."""
    q = query.lower().strip()
    results = []
    seen_ids = set()
    for key, entries in file_index.items():
        if q in key:
            for entry in entries:
                if entry["message_id"] not in seen_ids:
                    results.append(entry)
                    seen_ids.add(entry["message_id"])
    return results


# ═══════════════════════════════════════════════════════════════
#  COMMAND HANDLERS
# ═══════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Welcome to the File Search Bot!*\n\n"
        "📁 Just type *any file name* (or part of it) and I'll find matching files from the database "
        "and show them as buttons.\n\n"
        "🔧 *Commands:*\n"
        "/start – Show this message\n"
        "/index – Re-scan the file database\n"
        "/stats – Show how many files are indexed\n"
        "/addfile – Register a file (forward a file to me then use /addfile <name>)",
        parse_mode="Markdown",
    )


async def cmd_index(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔄 Scanning database channel, please wait…")
    count = await index_channel(context.bot)
    await msg.edit_text(f"✅ Done! Indexed *{count}* files.", parse_mode="Markdown")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total = sum(len(v) for v in file_index.values())
    await update.message.reply_text(
        f"📊 *Database Stats*\n\nUnique names: *{len(file_index)}*\nTotal files: *{total}*",
        parse_mode="Markdown",
    )


# ─── /addfile – lets you manually register a file by forwarding it to the bot
# Usage: forward a file to the bot, then reply to it with /addfile <optional name>
async def cmd_addfile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Register a file the user forwards/sends to the bot into the in-memory index."""
    target_msg = update.message.reply_to_message or update.message

    info = _extract_file_info(target_msg)
    if info is None:
        await update.message.reply_text(
            "⚠️ Please forward a file to the bot and then reply to it with /addfile, "
            "or send a file directly and use /addfile in the caption."
        )
        return

    # Override name if user supplied one
    if context.args:
        info["name"] = " ".join(context.args)

    key = info["name"].lower()
    file_index.setdefault(key, []).append(info)
    await update.message.reply_text(
        f"✅ Registered *{info['name']}* (type: {info['type']})", parse_mode="Markdown"
    )


# ═══════════════════════════════════════════════════════════════
#  MESSAGE HANDLER  –  search when user types a file name
# ═══════════════════════════════════════════════════════════════

RESULTS_PER_PAGE = 10   # max buttons per message


async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    if not query:
        return

    results = search_files(query)

    if not results:
        await update.message.reply_text(
            f"❌ No files found matching *{query}*.\n\n"
            "Try a shorter or different keyword.",
            parse_mode="Markdown",
        )
        return

    # Build inline keyboard – each button = one file
    keyboard = []
    for r in results[:RESULTS_PER_PAGE]:
        label = f"📄 {r['name']}"
        if len(label) > 60:
            label = label[:57] + "…"
        # callback_data: "send|<message_id>"  (message_id in DB channel)
        keyboard.append([InlineKeyboardButton(label, callback_data=f"send|{r['message_id']}")])

    if len(results) > RESULTS_PER_PAGE:
        keyboard.append([
            InlineKeyboardButton(
                f"… and {len(results) - RESULTS_PER_PAGE} more results",
                callback_data="noop"
            )
        ])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
        f"🔍 Found *{len(results)}* file(s) matching *{query}*.\nTap a button to receive the file:",
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )


# ═══════════════════════════════════════════════════════════════
#  CALLBACK HANDLER  –  send selected file to user
# ═══════════════════════════════════════════════════════════════

async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == "noop":
        return

    if not data.startswith("send|"):
        return

    _, msg_id_str = data.split("|", 1)
    msg_id = int(msg_id_str)

    # Find file_id in index
    file_info = None
    for entries in file_index.values():
        for e in entries:
            if e["message_id"] == msg_id:
                file_info = e
                break
        if file_info:
            break

    if file_info is None:
        await query.message.reply_text("⚠️ File not found in index. Try /index to refresh.")
        return

    try:
        chat_id = query.message.chat_id
        ftype = file_info["type"]
        fid = file_info["file_id"]
        caption = f"📄 *{file_info['name']}*"

        if ftype == "document":
            await context.bot.send_document(chat_id, fid, caption=caption, parse_mode="Markdown")
        elif ftype == "audio":
            await context.bot.send_audio(chat_id, fid, caption=caption, parse_mode="Markdown")
        elif ftype == "video":
            await context.bot.send_video(chat_id, fid, caption=caption, parse_mode="Markdown")
        elif ftype == "photo":
            await context.bot.send_photo(chat_id, fid, caption=caption, parse_mode="Markdown")
        elif ftype == "voice":
            await context.bot.send_voice(chat_id, fid, caption=caption, parse_mode="Markdown")
        elif ftype == "video_note":
            await context.bot.send_video_note(chat_id, fid)
        else:
            await context.bot.send_document(chat_id, fid, caption=caption, parse_mode="Markdown")

    except Exception as e:
        logger.error("Failed to send file: %s", e)
        await query.message.reply_text(
            "❌ Could not send the file. It may have been deleted from the database channel."
        )


# ═══════════════════════════════════════════════════════════════
#  POST-INIT  –  auto-index on startup
# ═══════════════════════════════════════════════════════════════

async def post_init(application: Application):
    logger.info("Bot started. Skipping auto-index (use /index or /addfile to populate).")
    # Uncomment the line below to auto-scan on startup (slow for large channels):
    # await index_channel(application.bot)


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Please set BOT_TOKEN in the script before running.")
        return

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("index", cmd_index))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("addfile", cmd_addfile))
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search))

    logger.info("Bot is running…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
