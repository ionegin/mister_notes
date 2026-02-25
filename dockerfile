FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Папка data/ должна быть подключена как Volume в Railway
# (Settings → Volumes → Mount Path: /app/data)
# Это сохранит users.json и temp_audio между деплоями

CMD ["python", "bot.py"]