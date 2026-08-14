Telegram-бот для поиска отелей via Booking API.
### К использованию планируется API apidojo-booking-v1.p.rapidapi.com

## Установка

1. Клонируйте репозиторий.
2. Создайте виртуальное окружение:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
3. Установите зависимости:  

   ```bash
   python -m pip install -r requirements.txt

4. Создайте локальный файл настроек

   ```bash
   cp .env.example .env

5. Заполните в .env значения BOT_TOKEN и RAPIDAPI_KEY.
6. Запустите бота

   ```bash
   python main.py



## Планируемые команды
/lowprice — дешевые отели
/highprice — дорогие
/bestdeal — оптимальные
/history — история
/help — справка

🛠 Этапы разработки
	• Этап 1: Базовый бот (/hello-world, Привет) +
	• Этап 2: /lowprice (Booking API)
	• Этап 3: /highprice
	• Этап 4: /bestdeal + /history
	• Финал: Inline-клавы, пагинация
