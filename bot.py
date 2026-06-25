import asyncio
import os
import logging
import re
from pathlib import Path

import yt_dlp
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.storage.memory import MemoryStorage

# ─── Настройки ───────────────────────────────────────────────────────────────

BOT_TOKEN = os.getenv("BOT_TOKEN", "ВСТАВЬ_ТОКЕН_СЮДА")
DOWNLOAD_DIR = Path("downloads")
MAX_FILE_SIZE_MB = 49  # Telegram лимит — 50 МБ (берём с запасом)

# ─── Логирование ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ─── Инициализация ───────────────────────────────────────────────────────────

DOWNLOAD_DIR.mkdir(exist_ok=True)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ─── Вспомогательные функции ─────────────────────────────────────────────────

SUPPORTED_DOMAINS = [
    "youtube.com", "youtu.be",
    "tiktok.com", "vm.tiktok.com",
    "instagram.com",  # Reels
    "twitter.com", "x.com",
    "vk.com",
]

def extract_url(text: str) -> str | None:
    """Извлекает первую URL из текста."""
    url_pattern = r'https?://[^\s]+'
    match = re.search(url_pattern, text)
    return match.group(0) if match else None

def is_supported_url(url: str) -> bool:
    return any(domain in url for domain in SUPPORTED_DOMAINS)

def get_platform(url: str) -> str:
    if "tiktok.com" in url:
        return "TikTok"
    if "youtube.com" in url or "youtu.be" in url:
        return "YouTube"
    if "instagram.com" in url:
        return "Instagram"
    if "twitter.com" in url or "x.com" in url:
        return "Twitter/X"
    if "vk.com" in url:
        return "VK"
    return "Видео"

def build_quality_keyboard(url: str) -> InlineKeyboardMarkup:
    """Клавиатура выбора качества."""
    buttons = [
        [
            InlineKeyboardButton(text="🎵 Только аудио (MP3)", callback_data=f"dl:audio:{url}"),
        ],
        [
            InlineKeyboardButton(text="📱 360p", callback_data=f"dl:360:{url}"),
            InlineKeyboardButton(text="💻 720p", callback_data=f"dl:720:{url}"),
        ],
        [
            InlineKeyboardButton(text="🖥 1080p", callback_data=f"dl:1080:{url}"),
            InlineKeyboardButton(text="⚡ Лучшее", callback_data=f"dl:best:{url}"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_ydl_opts(quality: str, output_path: str) -> dict:
    """Возвращает настройки yt-dlp в зависимости от выбранного качества."""
    base_opts = {
        "outtmpl": output_path,
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
    }

    if quality == "audio":
        return {
            **base_opts,
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "outtmpl": output_path.replace(".%(ext)s", ".%(ext)s"),
        }
    elif quality == "360":
        return {**base_opts, "format": f"best[height<=360][filesize<{MAX_FILE_SIZE_MB}M]/best[height<=360]/worst"}
    elif quality == "720":
        return {**base_opts, "format": f"best[height<=720][filesize<{MAX_FILE_SIZE_MB}M]/best[height<=720]/best"}
    elif quality == "1080":
        return {**base_opts, "format": f"best[height<=1080][filesize<{MAX_FILE_SIZE_MB}M]/best[height<=1080]/best"}
    else:  # best
        return {**base_opts, "format": f"best[filesize<{MAX_FILE_SIZE_MB}M]/best"}

def download_video(url: str, quality: str) -> tuple[str, dict]:
    """Скачивает видео, возвращает (путь к файлу, мета-информация)."""
    output_template = str(DOWNLOAD_DIR / "%(id)s.%(ext)s")
    ydl_opts = get_ydl_opts(quality, output_template)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)

        # Для аудио расширение меняется на .mp3
        if quality == "audio":
            filename = Path(filename).with_suffix(".mp3").as_posix()

        return filename, info

def format_size(bytes_size: int) -> str:
    if bytes_size < 1024 * 1024:
        return f"{bytes_size / 1024:.1f} КБ"
    return f"{bytes_size / (1024 * 1024):.1f} МБ"

# ─── Хендлеры ────────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я скачиваю видео по ссылке.\n\n"
        "📌 Поддерживаю:\n"
        "• YouTube\n"
        "• TikTok\n"
        "• Instagram Reels\n"
        "• Twitter / X\n"
        "• VK Видео\n\n"
        "Просто пришли мне ссылку — и выбери качество!"
    )

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "ℹ️ <b>Как пользоваться:</b>\n\n"
        "1. Скопируй ссылку на видео\n"
        "2. Отправь её мне\n"
        "3. Выбери качество\n"
        "4. Получи файл!\n\n"
        "<b>Ограничения:</b>\n"
        f"• Максимальный размер файла: {MAX_FILE_SIZE_MB} МБ\n"
        "• Если видео слишком большое — выбери качество пониже",
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
            "⚠️ Ссылка не поддерживается.\n\n"
            "Отправь ссылку на YouTube, TikTok, Instagram, Twitter или VK."
        )
        return

    platform = get_platform(url)
    await message.answer(
        f"🔗 Ссылка на <b>{platform}</b> получена!\n\nВыбери качество:",
        reply_markup=build_quality_keyboard(url),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("dl:"))
async def handle_download(callback: CallbackQuery):
    await callback.answer()

    parts = callback.data.split(":", 2)
    if len(parts) != 3:
        await callback.message.edit_text("❌ Ошибка: некорректные данные.")
        return

    _, quality, url = parts
    quality_labels = {
        "audio": "🎵 Аудио MP3",
        "360": "📱 360p",
        "720": "💻 720p",
        "1080": "🖥 1080p",
        "best": "⚡ Лучшее качество",
    }
    label = quality_labels.get(quality, quality)

    status_msg = await callback.message.edit_text(
        f"⏳ Скачиваю ({label})...\nЭто может занять несколько секунд."
    )

    filepath = None
    try:
        # Скачиваем в отдельном потоке, чтобы не блокировать event loop
        filepath, info = await asyncio.to_thread(download_video, url, quality)

        if not Path(filepath).exists():
            raise FileNotFoundError(f"Файл не найден: {filepath}")

        file_size = Path(filepath).stat().st_size
        title = info.get("title", "Без названия")[:50]
        duration = info.get("duration", 0)
        duration_str = f"{duration // 60}:{duration % 60:02d}" if duration else "—"

        caption = (
            f"🎬 <b>{title}</b>\n"
            f"⏱ Длительность: {duration_str}\n"
            f"💾 Размер: {format_size(file_size)}\n"
            f"📦 Качество: {label}"
        )

        file_obj = FSInputFile(filepath)
        await status_msg.edit_text("📤 Отправляю файл...")

        if quality == "audio":
            await callback.message.answer_audio(
                file_obj,
                caption=caption,
                parse_mode="HTML",
                title=title,
            )
        else:
            await callback.message.answer_video(
                file_obj,
                caption=caption,
                parse_mode="HTML",
                width=info.get("width"),
                height=info.get("height"),
            )

        await status_msg.delete()

    except yt_dlp.utils.DownloadError as e:
        err = str(e)
        if "too large" in err.lower() or "filesize" in err.lower():
            msg = "❌ Файл слишком большой для Telegram (лимит 50 МБ).\nПопробуй выбрать качество пониже."
        elif "private" in err.lower():
            msg = "❌ Это приватное видео — скачать нельзя."
        elif "unavailable" in err.lower():
            msg = "❌ Видео недоступно или удалено."
        else:
            msg = f"❌ Ошибка загрузки:\n<code>{err[:200]}</code>"
        await status_msg.edit_text(msg, parse_mode="HTML")

    except Exception as e:
        logger.exception(f"Неожиданная ошибка при обработке {url}")
        await status_msg.edit_text(f"❌ Неожиданная ошибка: {str(e)[:150]}")

    finally:
        # Удаляем файл после отправки
        if filepath and Path(filepath).exists():
            os.remove(filepath)
            logger.info(f"Удалён файл: {filepath}")

# ─── Запуск ──────────────────────────────────────────────────────────────────

async def main():
    logger.info("Бот запущен!")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
