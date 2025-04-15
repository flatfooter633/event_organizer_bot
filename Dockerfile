# Используем официальный образ Python в качестве базового
FROM python:3.12.7-alpine3.20

LABEL maintainer="flatfooter633@gmail.com"
ENV ADMIN="flatfooter633"
ENV PYTHONUNBUFFERED=1

# Обновим индекс доступных пакетов, обновим пакеты и установим bash
RUN apk update && apk upgrade && apk add bash && apk add nano && apk add --no-cache tzdata
ENV TZ=Europe/Moscow


# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем файлы приложения
COPY . .

# Указываем команду для запуска приложения
CMD ["python", "-m", "src.main"]



