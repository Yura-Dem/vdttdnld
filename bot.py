import asyncio
import os
import logging
import re
from pathlib import Path

import yt_dlp
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

# ─── Настройки ───────────────────────────────────────────────────────────────

BOT_TOKEN   = os.environ["BOT_TOKEN"]       # Обязательно — задаётся в Secrets
SPACE_HOST  = os.environ["SPACE_HOST"]      # Например: your-name-video-bot.hf.space

WEBHOOK_PATH   = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL    = f"https://{SPACE_HOST}{WEBHOOK_PATH}"
WEBAPP_HOST    = "0.0.0.0"
WEBAPP_PORT    = 7860               # HF Spaces открывает именно этот порт

DOWNLOAD_DIR    = Path("/tmp/downloads")    # На HF писать можно только в /tmp
MAX_FILE_MB     = 49

# ─── Логирование ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Инициализация ───────────────────────────────────────────────────────────

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())

# ─── Вспомогательные функции ─────────────────────────────────────────────────

SUPPORTED_DOMAINS = [
    "youtube.com", "youtu.be",
    "tiktok.com", "vm.tiktok.com",
    "instagram.com",
    "twitter.com", "x.com",
    "vk.com",
]

def extract_url(text: str):
    m = re.search(r'https?://[^\s]+', text)
    return m.group(0) if m else None

def is_supported_url(url: str) -> bool:
    return any(d in url for d in SUPPORTED_DOMAINS)

def get_platform(url: str) -> str:
    if "tiktok.com"   in url: return "TikTok"
    if "youtube.com"  in url or "youtu.be" in url: return "YouTube"
    if "instagram.com" in url: return "Instagram"
    if "twitter.com"  in url or "x.com" in url: return "Twitter/X"
    if "vk.com"       in url: return "VK"
    return "Видео"

def build_quality_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎵 Только аудио (MP3)", callback_data=f"dl:audio:{url}")],
        [
            InlineKeyboardButton(text="📱 360p",  callback_data=f"dl:360:{url}"),
            InlineKeyboardButton(text="💻 720p",  callback_data=f"dl:720:{url}"),
        ],
        [
            InlineKeyboardButton(text="🖥 1080p",     callback_data=f"dl:1080:{url}"),
            InlineKeyboardButton(text="⚡ Лучшее",   callback_data=f"dl:best:{url}"),
        ],
    ])

def get_ydl_opts(quality: str, output_path: str) -> dict:
    base = {
        "outtmpl": output_path,
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
    }
    if quality == "audio":
        return {**base,
            "format": "bestaudio/best",
            "postprocessors": [{"key": "FFmpegExtractAudio",
                                "preferredcodec": "mp3",
                                "preferredquality": "192"}],
        }
    fmt_map = {
        "360":  f"best[height<=360][filesize<{MAX_FILE_MB}M]/best[height<=360]/worst",
        "720":  f"best[height<=720][filesize<{MAX_FILE_MB}M]/best[height<=720]/best",
        "1080": f"best[height<=1080][filesize<{MAX_FILE_MB}M]/best[height<=1080]/best",
        "best": f"best[filesize<{MAX_FILE_MB}M]/best",
    }
    return {**base, "format": fmt_map.get(quality, fmt_map["best"])}

def download_video(url: str, quality: str):
    output_template = str(DOWNLOAD_DIR / "%(id)s.%(ext)s")
    ydl_opts = get_ydl_opts(quality, output_template)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info     = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        if quality == "audio":
            filename = Path(filename).with_suffix(".mp3").as_posix()
        return filename, info

def fmt_size(b: int) -> str:
    return f"{b/(1024*1024):.1f} МБ" if b >= 1024*1024 else f"{b/1024:.1f} КБ"

# ─── Хендлеры ────────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Отправь мне ссылку на видео — скачаю и пришлю файлом.\n\n"
        "📌 Поддерживаю: YouTube · TikTok · Instagram · Twitter/X · VK"
    )

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "ℹ️ <b>Как пользоваться:</b>\n\n"
        "1. Скопируй ссылку на видео\n"
        "2. Отправь её мне\n"
        "3. Выбери качество\n"
        "4. Получи файл!\n\n"
        f"⚠️ Максимальный размер файла: {MAX_FILE_MB} МБ",
        parse_mode="HTML"
    )

@dp.message(F.text)
async def handle_link(message: Message):
    url = extract_url(message.text)
    if not url:
        await message.answer("❓ Не вижу ссылки. Отправь URL на видео.")
        return
    if not is_supported_url(url):
        await message.answer(
            "⚠️ Ссылка не поддерживается.\n"
            "Отправь ссылку на YouTube, TikTok, Instagram, Twitter или VK."
        )
        return
    await message.answer(
        f"🔗 Ссылка на <b>{get_platform(url)}</b> получена!\n\nВыбери качество:",
        reply_markup=build_quality_keyboard(url),
        parse_mode="HTML"
    )

QUALITY_LABELS = {
    "audio": "🎵 Аудио MP3",
    "360":   "📱 360p",
    "720":   "💻 720p",
    "1080":  "🖥 1080p",
    "best":  "⚡ Лучшее качество",
}

@dp.callback_query(F.data.startswith("dl:"))
async def handle_download(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":", 2)
    if len(parts) != 3:
        await callback.message.edit_text("❌ Ошибка: некорректные данные.")
        return

    _, quality, url = parts
    label = QUALITY_LABELS.get(quality, quality)
    status = await callback.message.edit_text(
        f"⏳ Скачиваю ({label})...\nЭто может занять несколько секунд."
    )

    filepath = None
    try:
        filepath, info = await asyncio.to_thread(download_video, url, quality)
        if not Path(filepath).exists():
            raise FileNotFoundError(f"Файл не найден: {filepath}")

        size      = Path(filepath).stat().st_size
        title     = info.get("title", "Без названия")[:50]
        duration  = info.get("duration", 0)
        dur_str   = f"{duration//60}:{duration%60:02d}" if duration else "—"
        caption   = (
            f"🎬 <b>{title}</b>\n"
            f"⏱ Длительность: {dur_str}\n"
            f"💾 Размер: {fmt_size(size)}\n"
            f"📦 Качество: {label}"
        )

        file_obj = FSInputFile(filepath)
        await status.edit_text("📤 Отправляю файл...")

        if quality == "audio":
            await callback.message.answer_audio(file_obj, caption=caption,
                                                parse_mode="HTML", title=title)
        else:
            await callback.message.answer_video(
                file_obj, caption=caption, parse_mode="HTML",
                width=info.get("width"), height=info.get("height"),
            )
        await status.delete()

    except yt_dlp.utils.DownloadError as e:
        err = str(e).lower()
        if "too large" in err or "filesize" in err:
            msg = "❌ Файл слишком большой (лимит 50 МБ). Попробуй качество пониже."
        elif "private" in err:
            msg = "❌ Приватное видео — скачать нельзя."
        elif "unavailable" in err:
            msg = "❌ Видео недоступно или удалено."
        else:
            msg = f"❌ Ошибка загрузки:\n<code>{str(e)[:200]}</code>"
        await status.edit_text(msg, parse_mode="HTML")

    except Exception as e:
        logger.exception("Неожиданная ошибка")
        await status.edit_text(f"❌ Ошибка: {str(e)[:150]}")

    finally:
        if filepath and Path(filepath).exists():
            os.remove(filepath)

# ─── Healthcheck для UptimeRobot ─────────────────────────────────────────────

async def healthcheck(request):
    return web.Response(text="OK")

# ─── Запуск ──────────────────────────────────────────────────────────────────

async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    logger.info(f"Webhook установлен: {WEBHOOK_URL}")

async def on_shutdown(app):
    await bot.delete_webhook()
    logger.info("Webhook удалён")

def main():
    app = web.Application()
    app.router.add_get("/", healthcheck)          # для UptimeRobot

    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    web.run_app(app, host=WEBAPP_HOST, port=WEBAPP_PORT)

if __name__ == "__main__":
    main()
