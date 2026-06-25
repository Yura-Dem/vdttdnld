import asyncio
import os
import logging
import re
import subprocess
from pathlib import Path

import yt_dlp
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.storage.memory import MemoryStorage

# ─── Настройки ───────────────────────────────────────────────────────────────

BOT_TOKEN       = os.getenv("BOT_TOKEN", "ВСТАВЬ_ТОКЕН_СЮДА")
DOWNLOAD_DIR    = Path("downloads")
MAX_FILE_MB     = 49        # Telegram лимит — 50 МБ
MAX_DURATION    = 3 * 60    # 3 минуты в секундах

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
dp  = Dispatcher(storage=MemoryStorage())

# ─── Исключения ──────────────────────────────────────────────────────────────

class VideoTooLongError(Exception):
    def __init__(self, duration: int):
        self.duration = duration
        m, s = divmod(duration, 60)
        super().__init__(f"Too long: {m}:{s:02d}")

class FileTooLargeError(Exception):
    def __init__(self, size_mb: float):
        self.size_mb = size_mb
        super().__init__(f"Too large: {size_mb:.1f} MB")

# ─── Вспомогательные функции ─────────────────────────────────────────────────

SUPPORTED_DOMAINS = [
    "youtube.com", "youtu.be",
    "tiktok.com", "vm.tiktok.com",
    "instagram.com",
    "twitter.com", "x.com",
    "vk.com",
]

def extract_url(text: str) -> str | None:
    m = re.search(r'https?://[^\s]+', text)
    return m.group(0) if m else None

def is_supported_url(url: str) -> bool:
    return any(d in url for d in SUPPORTED_DOMAINS)

def get_platform(url: str) -> str:
    if "tiktok.com"    in url: return "TikTok"
    if "youtube.com"   in url or "youtu.be" in url: return "YouTube"
    if "instagram.com" in url: return "Instagram"
    if "twitter.com"   in url or "x.com" in url: return "Twitter/X"
    if "vk.com"        in url: return "VK"
    return "Видео"

def fmt_duration(sec: int) -> str:
    return f"{sec // 60}:{sec % 60:02d}"

def fmt_size(b: int) -> str:
    return f"{b / (1024*1024):.1f} МБ" if b >= 1024*1024 else f"{b / 1024:.1f} КБ"

def build_quality_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎵 Только аудио (MP3)", callback_data=f"dl:audio:{url}")],
        [
            InlineKeyboardButton(text="📱 360p",   callback_data=f"dl:360:{url}"),
            InlineKeyboardButton(text="💻 720p",   callback_data=f"dl:720:{url}"),
        ],
        [
            InlineKeyboardButton(text="🖥 1080p",  callback_data=f"dl:1080:{url}"),
            InlineKeyboardButton(text="⚡ Авто",   callback_data=f"dl:best:{url}"),
        ],
    ])

# ─── Загрузка и сжатие ───────────────────────────────────────────────────────

def get_video_format(quality: str) -> str:
    """Формат yt-dlp для выбранного качества (без ограничения по размеру —
    мы всё равно сожмём через ffmpeg)."""
    if quality == "audio":
        return "bestaudio/best"
    elif quality == "360":
        return "best[height<=360]/worst"
    elif quality == "720":
        return "best[height<=720]/best[height<=360]/worst"
    elif quality == "1080":
        return "best[height<=1080]/best[height<=720]/best[height<=360]/worst"
    else:  # best / auto
        return "best[height<=720]/best[height<=360]/best"

def compress_video(input_path: str, output_path: str, target_mb: float = MAX_FILE_MB) -> str:
    """Сжимает видео через ffmpeg до нужного размера.
    Вычисляет нужный битрейт исходя из длины и целевого размера файла.
    Возвращает путь к сжатому файлу.
    """
    # Получаем длину через ffprobe
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", input_path],
        capture_output=True, text=True
    )
    duration_sec = float(probe.stdout.strip() or "0")
    if duration_sec <= 0:
        return input_path  # не можем вычислить битрейт — возвращаем как есть

    # target_mb * 8 * 1024 = биты, делим на секунды = битрейт (kbps)
    # Оставляем 10% на аудио (128 kbps)
    audio_kbps  = 128
    total_kbps  = int((target_mb * 8 * 1024) / duration_sec)
    video_kbps  = max(total_kbps - audio_kbps, 200)  # минимум 200 kbps на видео

    logger.info(f"Сжатие: {duration_sec:.1f}с → видео {video_kbps}kbps + аудио {audio_kbps}kbps")

    # Двухпроходное сжатие для точного размера
    passlog = output_path + "_pass"
    for pass_num in ["1", "2"]:
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-c:v", "libx264",
            "-b:v", f"{video_kbps}k",
            "-pass", pass_num,
            "-passlogfile", passlog,
            "-c:a", "aac",
            "-b:a", f"{audio_kbps}k",
        ]
        if pass_num == "1":
            cmd += ["-f", "null", "/dev/null"]
        else:
            cmd += [output_path]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"ffmpeg pass {pass_num} error: {result.stderr[-500:]}")
            # Если сжатие не вышло — возвращаем оригинал
            return input_path

    # Удаляем временные файлы двухпроходного сжатия
    for f in Path(".").glob(Path(passlog).name + "*"):
        f.unlink(missing_ok=True)

    return output_path

def download_and_prepare(url: str, quality: str) -> tuple[str, dict]:
    """
    1. Получает метаданные без скачивания — проверяет длину.
    2. Скачивает видео.
    3. Если файл > лимита — сжимает через ffmpeg.
    4. Возвращает (путь к готовому файлу, info).
    """
    # ── Шаг 1: метаданные ──────────────────────────────────────────────────
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
        info = ydl.extract_info(url, download=False)

    duration = info.get("duration") or 0
    if duration and quality != "audio" and duration > MAX_DURATION:
        raise VideoTooLongError(int(duration))

    # ── Шаг 2: скачиваем ───────────────────────────────────────────────────
    output_template = str(DOWNLOAD_DIR / "%(id)s.%(ext)s")
    ydl_opts = {
        "outtmpl":             output_template,
        "quiet":               True,
        "no_warnings":         True,
        "merge_output_format": "mp4",
        "format":              get_video_format(quality),
    }
    if quality == "audio":
        ydl_opts["postprocessors"] = [{
            "key":             "FFmpegExtractAudio",
            "preferredcodec":  "mp3",
            "preferredquality": "192",
        }]

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        dl_info = ydl.extract_info(url, download=True)
        filepath = ydl.prepare_filename(dl_info)
        if quality == "audio":
            filepath = Path(filepath).with_suffix(".mp3").as_posix()

    if not Path(filepath).exists():
        raise FileNotFoundError(f"Файл не найден после скачивания: {filepath}")

    # ── Шаг 3: сжатие если нужно ───────────────────────────────────────────
    if quality != "audio":
        file_size_mb = Path(filepath).stat().st_size / (1024 * 1024)
        if file_size_mb > MAX_FILE_MB:
            logger.info(f"Файл {file_size_mb:.1f} МБ > {MAX_FILE_MB} МБ — запускаю сжатие")
            compressed_path = filepath.replace(".mp4", "_compressed.mp4")
            filepath = compress_video(filepath, compressed_path)

            # Проверяем что сжатие помогло
            final_mb = Path(filepath).stat().st_size / (1024 * 1024)
            if final_mb > MAX_FILE_MB:
                raise FileTooLargeError(final_mb)

    return filepath, dl_info

# ─── Хендлеры ────────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Отправь ссылку на видео — скачаю и пришлю файлом.\n\n"
        "📌 Поддерживаю: YouTube · TikTok · Instagram · Twitter/X · VK\n\n"
        f"⏱ Максимальная длина видео: {fmt_duration(MAX_DURATION)}\n"
        f"💾 Максимальный размер: {MAX_FILE_MB} МБ (длинные видео сжимаются автоматически)"
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
        f"• Максимальная длина: {fmt_duration(MAX_DURATION)}\n"
        f"• Максимальный размер: {MAX_FILE_MB} МБ\n"
        "• Если видео тяжёлое — сожму автоматически\n"
        "• Если после сжатия всё равно не влезает — предложу аудио",
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

    platform = get_platform(url)
    await message.answer(
        f"🔗 Ссылка на <b>{platform}</b> получена!\n\nВыбери качество:",
        reply_markup=build_quality_keyboard(url),
        parse_mode="HTML"
    )

QUALITY_LABELS = {
    "audio": "🎵 Аудио MP3",
    "360":   "📱 360p",
    "720":   "💻 720p",
    "1080":  "🖥 1080p",
    "best":  "⚡ Авто",
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
        filepath, info = await asyncio.to_thread(download_and_prepare, url, quality)

        file_size = Path(filepath).stat().st_size
        title     = info.get("title", "Без названия")[:50]
        duration  = info.get("duration", 0)
        dur_str   = fmt_duration(int(duration)) if duration else "—"

        # Показываем пометку если файл был сжат
        orig_mb = (info.get("filesize") or info.get("filesize_approx") or 0) / (1024*1024)
        compressed = quality != "audio" and orig_mb > MAX_FILE_MB
        quality_note = f"{label} (сжато 🗜)" if compressed else label

        caption = (
            f"🎬 <b>{title}</b>\n"
            f"⏱ Длительность: {dur_str}\n"
            f"💾 Размер: {fmt_size(file_size)}\n"
            f"📦 Качество: {quality_note}"
        )

        await status.edit_text("📤 Отправляю файл...")
        file_obj = FSInputFile(filepath)

        if quality == "audio":
            await callback.message.answer_audio(
                file_obj, caption=caption, parse_mode="HTML", title=title
            )
        else:
            await callback.message.answer_video(
                file_obj, caption=caption, parse_mode="HTML",
                width=info.get("width"), height=info.get("height"),
            )

        await status.delete()

    except VideoTooLongError as e:
        m, s = divmod(e.duration, 60)
        await status.edit_text(
            f"⏱ Видео слишком длинное ({m}:{s:02d}).\n"
            f"Принимаю только видео до {fmt_duration(MAX_DURATION)}."
        )

    except FileTooLargeError as e:
        await status.edit_text(
            f"❌ Не удалось сжать до нужного размера ({e.size_mb:.0f} МБ).\n"
            "Попробуй качество пониже или аудио 🎵"
        )

    except yt_dlp.utils.DownloadError as e:
        err = str(e).lower()
        if "private" in err:
            msg = "❌ Приватное видео — скачать нельзя."
        elif "unavailable" in err:
            msg = "❌ Видео недоступно или удалено."
        else:
            msg = f"❌ Ошибка загрузки:\n<code>{str(e)[:200]}</code>"
        await status.edit_text(msg, parse_mode="HTML")

    except Exception as e:
        logger.exception(f"Неожиданная ошибка при обработке {url}")
        await status.edit_text(f"❌ Неожиданная ошибка: {str(e)[:150]}")

    finally:
        # Удаляем все файлы этого видео из папки downloads
        if filepath:
            vid_id = Path(filepath).stem.replace("_compressed", "")
            for f in DOWNLOAD_DIR.glob(f"{vid_id}*"):
                try:
                    f.unlink()
                except Exception:
                    pass

# ─── Запуск ──────────────────────────────────────────────────────────────────

async def main():
    logger.info("Бот запущен!")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
