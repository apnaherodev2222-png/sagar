from config import *
from core import *
from ai import *
from ai import _ai_available
from pdf_engine import *
from ui import *
from handlers import *

# -------------------- KEEP-ALIVE SERVER --------------------
def keep_alive():
    """Run a tiny Flask health server for hosting platforms such as Wispbyte."""
    try:
        from flask import Flask
        from threading import Thread
        app = Flask("pdf_mitra_keep_alive")

        @app.get("/")
        def health():
            return "PDF Mitra Pro is running", 200

        @app.get("/health")
        def health_check():
            return {"status": "ok", "bot": "PDF Mitra Pro"}, 200

        def run():
            try:
                app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
            except Exception:
                logger.exception("Keep-alive server stopped.")

        Thread(target=run, daemon=True, name="keep-alive").start()
        logger.info("Keep-alive server started on port %s", PORT)
    except Exception:
        logger.exception("Could not start keep-alive server; continuing with Telegram bot.")

# -------------------- APPLICATION ENTRYPOINT --------------------
def build_app():
    if not TOKEN or TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
        raise RuntimeError("TOKEN missing: config.py me TOKEN = \"YOUR_BOT_TOKEN\" set karo.")
    app = Application.builder().token(TOKEN).post_init(configure_commands).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("premium", premium_command))
    app.add_handler(CommandHandler("free", free_command))
    app.add_handler(CommandHandler("uploadfont", upload_font))
    app.add_handler(CommandHandler("setaikey", setaikey_command))
    app.add_handler(CommandHandler("removeaikey", removeaikey_command))
    app.add_handler(CommandHandler("aistatus", aistatus_command))
    app.add_handler(CommandHandler("setlimit", setlimit_command))
    app.add_handler(CommandHandler("genkey", genkey_command))
    app.add_handler(CommandHandler("listkeys", listkeys_command))
    app.add_handler(CommandHandler("revokekey", revokekey_command))
    app.add_handler(CommandHandler("redeem", redeem_command))
    app.add_handler(CommandHandler("setchannel", setchannel_command))
    app.add_handler(CommandHandler("channelgate", channelgate_command))
    app.add_handler(CommandHandler("setowner", setowner_command))
    app.add_handler(CallbackQueryHandler(menu_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)
    return app

def main():
    cleanup_old_files()
    logger.info("Starting PDF Bot Pro | Hindi font: %s | HarfBuzz: %s | PyMuPDF: %s | AI: %s", HINDI_FONT_AVAILABLE, HARFBUZZ_AVAILABLE, PYMUPDF_AVAILABLE, bool(_ai_available()))
    asyncio.set_event_loop(asyncio.new_event_loop())
    build_app().run_polling(drop_pending_updates=True, close_loop=False, stop_signals=None)

if __name__ == "__main__":
    keep_alive()
    while True:
        try:
            main()
            break
        except KeyboardInterrupt:
            break
        except Exception as exc:
            logger.exception("Bot crashed: %s. Restarting in 5 seconds...", exc)
            time.sleep(5)
