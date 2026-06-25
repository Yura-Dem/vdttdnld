# 🎬 Telegram Video Downloader Bot

Бот скачивает видео с YouTube, TikTok, Instagram, Twitter/X и VK по ссылке.

---

## 📋 Возможности

- Скачивание видео с YouTube, TikTok, Instagram Reels, Twitter/X, VK
- Выбор качества: 360p / 720p / 1080p / Лучшее
- Скачивание только аудио в формате MP3
- Показывает название, длительность и размер файла
- Автоматически удаляет файлы после отправки

---

## 🚀 Способ 1: Запуск на локальной машине

### Шаг 1 — Создай бота в Telegram

1. Открой Telegram и найди [@BotFather](https://t.me/BotFather)
2. Отправь команду `/newbot`
3. Введи имя бота (например: `My Video Bot`)
4. Введи username (например: `my_video_dl_bot`) — должен заканчиваться на `bot`
5. Скопируй **токен** — он выглядит так: `1234567890:AABBCCDDEEFFaabbccddeeff1234567890`

### Шаг 2 — Установи зависимости

**Python 3.11+** (проверь командой `python3 --version`):

```bash
# Создай виртуальное окружение
python3 -m venv venv

# Активируй его:
# На Linux/macOS:
source venv/bin/activate
# На Windows:
venv\Scripts\activate

# Установи библиотеки
pip install -r requirements.txt
```

**FFmpeg** — нужен для конвертации аудио:

```bash
# Ubuntu / Debian:
sudo apt install ffmpeg

# macOS (через Homebrew):
brew install ffmpeg

# Windows — скачай с https://ffmpeg.org/download.html
# и добавь в PATH
```

### Шаг 3 — Вставь токен

Открой файл `bot.py` и замени строку:

```python
BOT_TOKEN = os.getenv("BOT_TOKEN", "ВСТАВЬ_ТОКЕН_СЮДА")
```

На:

```python
BOT_TOKEN = os.getenv("BOT_TOKEN", "1234567890:твой_настоящий_токен")
```

Или создай файл `.env` (скопируй из `.env.example`):

```bash
cp .env.example .env
# Открой .env и вставь свой токен
```

### Шаг 4 — Запусти бота

```bash
python bot.py
```

Ты увидишь сообщение: `Бот запущен!`

Найди своего бота в Telegram и отправь `/start` — готово! 🎉

---

## 🐳 Способ 2: Запуск через Docker (рекомендуется для сервера)

### Шаг 1 — Установи Docker

```bash
# Ubuntu / Debian:
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Перезайди в систему после этой команды
```

### Шаг 2 — Настрой токен

```bash
cp .env.example .env
nano .env  # Вставь свой токен
```

Содержимое `.env`:
```
BOT_TOKEN=1234567890:твой_настоящий_токен
```

### Шаг 3 — Запусти через Docker Compose

```bash
docker compose up -d
```

**Полезные команды:**

```bash
# Посмотреть логи:
docker compose logs -f

# Остановить бота:
docker compose down

# Перезапустить:
docker compose restart

# Обновить yt-dlp (если перестали работать ссылки):
docker compose exec bot pip install -U yt-dlp
docker compose restart
```

---

## ☁️ Способ 3: Деплой на VPS (например, Hetzner / DigitalOcean)

### Шаг 1 — Арендуй сервер

- [Hetzner](https://hetzner.com) — от €4/мес, самый дешёвый
- [DigitalOcean](https://digitalocean.com) — от $6/мес
- [Selectel](https://selectel.ru) — российский провайдер

Выбери Ubuntu 22.04 или 24.04.

### Шаг 2 — Загрузи файлы на сервер

```bash
# С локальной машины:
scp -r ./tg-video-bot root@IP_СЕРВЕРА:/root/

# Или через git:
git init && git add . && git commit -m "init"
# Залей на GitHub, затем на сервере:
git clone https://github.com/твой_юзер/tg-video-bot
```

### Шаг 3 — Запусти на сервере

```bash
ssh root@IP_СЕРВЕРА
cd tg-video-bot
cp .env.example .env && nano .env  # вставь токен
curl -fsSL https://get.docker.com | sh
docker compose up -d
```

Бот будет работать 24/7 и автоматически перезапускаться при сбоях (`restart: unless-stopped`).

---

## 🔧 Устранение проблем

| Проблема | Решение |
|---|---|
| `yt_dlp not found` | Запусти `pip install -r requirements.txt` |
| `ffmpeg not found` | Установи ffmpeg (см. выше) |
| Видео не скачивается | Обнови yt-dlp: `pip install -U yt-dlp` |
| Файл слишком большой | Выбери качество пониже (360p или аудио) |
| TikTok не работает | Обнови yt-dlp — они часто меняют защиту |
| `Token invalid` | Проверь токен в `.env` или `bot.py` |

---

## 📁 Структура проекта

```
tg-video-bot/
├── bot.py              # Основной код бота
├── requirements.txt    # Python-зависимости
├── Dockerfile          # Образ для Docker
├── docker-compose.yml  # Конфигурация Docker Compose
├── .env.example        # Пример файла с токеном
├── .env                # Твой токен (не коммить в git!)
├── downloads/          # Временные файлы (создаётся автоматически)
└── bot.log             # Логи (создаётся автоматически)
```

---

## ⚠️ Важно

- Файл `.env` **никогда не загружай в git** — добавь его в `.gitignore`
- Telegram ограничивает файлы до **50 МБ** — длинные видео в высоком качестве могут не пройти
- Для личного использования всё работает из коробки; для публичного бота с высокой нагрузкой нужна очередь задач (Celery + Redis)
