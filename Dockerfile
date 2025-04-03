# Используем официальный образ Python в качестве базового
FROM python:3.12.7-alpine3.20

LABEL maintainer="flatfooter633@gmail.com"
ENV ADMIN="flatfooter633"

# Обновим индекс доступных пакетов, обновим пакеты и установим bash
RUN apk update && apk upgrade && apk add bash && apk add nano

# Устанавливаем зависимости
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r /app/requirements.txt

# Копируем файлы приложения
COPY . ./app

# Устанавливаем рабочую директорию
WORKDIR /app

# Указываем команду для запуска приложения
CMD ["python", "./main.py"]
