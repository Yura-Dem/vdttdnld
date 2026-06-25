FROM python:3.12-slim

# ffmpeg нужен для конвертации аудио в MP3
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

# HF Spaces требует именно порт 7860
EXPOSE 7860

CMD ["python", "bot.py"]
