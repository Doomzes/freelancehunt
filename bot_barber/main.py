import logging
import os
from datetime import datetime, timedelta
from collections import defaultdict
from translations import MESSAGES

import math
import aiomysql
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ConversationHandler,
)
from dotenv import load_dotenv

# Состояния для ConversationHandler
(
    APPOINTMENT,
    APPOINTMENT_DATE,
    APPOINTMENT_TIME,
    CONFIRM_APPOINTMENT,
    MENU_SELECTION,
    ADMIN_MENU,
    ADMIN_SCHEDULE,
    ADMIN_CLIENTS,
    SETTINGS,
    MEDIA_MANAGEMENT,
    CHANGE_THRESHOLD,
    CHANGE_PERCENTAGE,
    PRICE_EDIT_ADD,
    PRICE_EDIT_EDIT,
    PRICE_EDIT_DELETE,
    MEDIA_UPLOAD_PHOTO,
    MEDIA_UPLOAD_VIDEO,
    PRICE_EDIT_SELECTION,
    ADD_PRICE_ITEM_NAME,
    ADD_PRICE_ITEM_PRICE,
    EDIT_PRICE_ITEM_ID,
    EDIT_PRICE_ITEM_NAME,
    EDIT_PRICE_ITEM_PRICE,
    DELETE_PRICE_ITEM_ID,
    PRICE_EDIT_EDIT_ID,
    PRICE_EDIT_EDIT_NAME,
    PRICE_EDIT_EDIT_PRICE,
    PRICE_EDIT_DELETE_ID,
    SURVEY_Q1, SURVEY_Q2, SURVEY_Q3, SURVEY_Q4, SURVEY_Q5, SURVEY_Q6, SURVEY_Q7,
    CANCEL_APPOINTMENT,
    CLIENTS_LIST,
    CLIENT_DETAILS,
    PRICE_EDIT_ADD_NAME,
    PRICE_EDIT_ADD_PRICE,
    LANGUAGE_CHOICE
) = range(41)

# Список вопросов для опроса
SURVEY_QUESTIONS = [
    "1. Ім'я та прізвище?",
    "2. Номер телефону?",
    "3. Яка довжина волосся?",
    "4. Чи є борода?",
    "5. Чому обрали мене?",
    "6. Що подобається, що не подобається?",
    "7. Що потрібно зробити, щоб ви більше не зверталися до мене?",
]

TWO_WEEKS_REMINDER_TEXT = (
    "<b>Прийшов час оновити зачіску!</b> ✂️✨\n"
    "Не забудьте записатися на наступний візит, щоб підтримувати стиль та догляд за волоссям."
)
# Кількість клієнтів на сторінку
CLIENTS_PER_PAGE = 6
# Включаем логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Загружаем переменные окружения из .env
load_dotenv()

# Загружаем конфиденциальные данные из переменных окружения
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
MYSQL_USER = os.getenv('MYSQL_USER')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD')
MYSQL_HOST = os.getenv('MYSQL_HOST', 'localhost')
MYSQL_DB = os.getenv('MYSQL_DB')
ADMIN_CHAT_ID = int(os.getenv('ADMIN_CHAT_ID'))  # ID администратора

if not all([TOKEN, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DB, ADMIN_CHAT_ID]):
    logger.error("Необходимо установить все переменные окружения: TELEGRAM_BOT_TOKEN, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DB, ADMIN_CHAT_ID")
    exit(1)

# Создание пула подключений к базе данных
async def create_db_pool():
    pool = await aiomysql.create_pool(
        host=MYSQL_HOST,
        port=3306,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        db=MYSQL_DB,
        autocommit=True
    )
    return pool

# Функции для создания необходимых таблиц
async def create_surveys_table(db_pool):
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS surveys (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    chat_id BIGINT NOT NULL UNIQUE,
                    full_name VARCHAR(255),
                    phone_number VARCHAR(50),
                    hair_length VARCHAR(100),
                    has_beard BOOLEAN,
                    why_chose_us TEXT,
                    likes_dislikes TEXT,
                    suggestions TEXT,
                    visit_count INT DEFAULT 0,
                    discount_available BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logger.info("Таблица surveys проверена/создана.")

async def create_appointments_table(db_pool):
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS appointments (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    chat_id BIGINT NOT NULL,
                    full_name VARCHAR(255) NOT NULL,
                    appointment_date DATE NOT NULL,
                    appointment_time TIME NOT NULL,
                    discount DECIMAL(10,2) DEFAULT 0.00,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY unique_appointment (appointment_date, appointment_time)
                )
            """)
            logger.info("Таблица appointments проверена/создана.")


# Кількість клієнтів на сторінку
CLIENTS_PER_PAGE = 6

# Функція для відображення списку клієнтів з пагінацією
async def show_admin_clients(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    user_id = update.effective_user.id

    if query:
        await query.answer()
        chat_id = query.message.chat_id
    else:
        chat_id = user_id

    db_pool = context.application.bot_data.get('db_pool')
    if not db_pool:
        if query:
            await query.edit_message_text("Сталася помилка. Будь ласка, спробуйте пізніше.")
        else:
            await update.message.reply_text("Сталася помилка. Будь ласка, спробуйте пізніше.")
        return ConversationHandler.END

    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT chat_id, full_name, phone_number
                    FROM surveys
                    ORDER BY created_at DESC
                """)
                clients = await cur.fetchall()

        if not clients:
            if query:
                await query.edit_message_text("Немає клієнтів.")
            else:
                await update.message.reply_text("Немає клієнтів.")

            # Отправляем клавиатуру с кнопкой "Назад"
            reply_back = ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True, one_time_keyboard=True)
            await context.bot.send_message(
                chat_id=chat_id,
                text="Натисніть 'Назад', щоб повернутися до адміністративного меню.",
                reply_markup=reply_back
            )
            return CLIENTS_LIST

        total_clients = len(clients)
        total_pages = math.ceil(total_clients / CLIENTS_PER_PAGE)
        current_page = 1

        # Зберігаємо клієнтів у контексті
        context.user_data['clients'] = clients
        context.user_data['clients_page'] = current_page
        context.user_data['total_pages'] = total_pages

        # Генеруємо першу сторінку
        message_text, keyboard = generate_clients_page(clients, current_page, total_pages)

        if query:
            await query.edit_message_reply_markup(reply_markup=ReplyKeyboardRemove())
            await context.bot.send_message(
                chat_id=chat_id,
                text=message_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
        else:
            await update.message.reply_text(
                "Відображення списку клієнтів:",
                reply_markup=ReplyKeyboardRemove()
            )
            await update.message.reply_text(
                text=message_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )

        # Выводим инструкцию только если клиенты есть
        reply_back = ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True, one_time_keyboard=True)
        await context.bot.send_message(
            chat_id=chat_id,
            text="Натисніть 'Назад', щоб повернутися до адміністративного меню.",
            reply_markup=reply_back
        )

        return CLIENTS_LIST

    except Exception as e:
        logger.error(f"Ошибка при получении клиентов: {e}")
        if query:
            await query.edit_message_text("Сталася помилка при отриманні клієнтів.")
        else:
            await update.message.reply_text("Сталася помилка при отриманні клієнтів.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END


# Функція для генерації тексту та клавіатури сторінки клієнтів
def generate_clients_page(clients, page, total_pages):
    start_index = (page - 1) * CLIENTS_PER_PAGE
    end_index = start_index + CLIENTS_PER_PAGE
    page_clients = clients[start_index:end_index]

    message = f"*Мої клієнти (Сторінка {page} з {total_pages}):*\n"

    keyboard = []

    for client in page_clients:
        chat_id, full_name, phone_number = client
        button_text = f"{full_name} ({phone_number})"
        callback_data = f"client_{chat_id}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])

    # Додавання кнопок пагінації
    pagination_buttons = []
    if page > 1:
        pagination_buttons.append(InlineKeyboardButton("⬅️ Попередня", callback_data=f"clients_page_{page - 1}"))
    if page < total_pages:
        pagination_buttons.append(InlineKeyboardButton("Наступна ➡️", callback_data=f"clients_page_{page + 1}"))

    if pagination_buttons:
        keyboard.append(pagination_buttons)

    # Видалено: Додавання кнопки "Назад" до адміністративного меню

    return message, InlineKeyboardMarkup(keyboard)


# Функція для повернення до адміністративного меню
async def back_to_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    # Відправляємо нове повідомлення з адміністративним меню
    await context.bot.send_message(
        chat_id=user_id,
        text="Виберіть опцію:",
        reply_markup=get_admin_menu_keyboard()
    )

    # Видаляємо старе повідомлення зі списком клієнтів або деталями клієнта
    try:
        await query.message.delete()
    except Exception as e:
        logger.warning(f"Не вдалося видалити старе повідомлення: {e}")

    return ADMIN_MENU

# Функція для обробки показу певної сторінки клієнтів
async def show_clients_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    callback_data = query.data
    _, page_str = callback_data.split('_page_')
    page = int(page_str)

    clients = context.user_data.get('clients', [])
    total_pages = context.user_data.get('total_pages', 1)

    message_text, keyboard = generate_clients_page(clients, page, total_pages)

    await query.edit_message_text(
        text=message_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )

    # Оновлюємо поточну сторінку у контексті
    context.user_data['clients_page'] = page

    return CLIENTS_LIST

@CallbackQueryHandler
async def back_to_admin_menu_inline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    await context.bot.send_message(
        chat_id=user_id,
        text="Виберіть опцію:",
        reply_markup=get_admin_menu_keyboard()
    )
    await query.message.delete()
    return ADMIN_MENU



# Функція для показу деталей клієнта
async def show_client_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    callback_data = query.data
    _, chat_id_str = callback_data.split('_')
    chat_id = int(chat_id_str)

    clients = context.user_data.get('clients', [])
    client = next((c for c in clients if c[0] == chat_id), None)

    if not client:
        await query.edit_message_text("Клієнта не знайдено.")
        return CLIENTS_LIST

    # Отримуємо деталі клієнта з бази даних
    db_pool = context.application.bot_data.get('db_pool')
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT full_name, phone_number, hair_length, has_beard, 
                           why_chose_us, likes_dislikes, suggestions, visit_count, 
                           discount_available, created_at
                    FROM surveys
                    WHERE chat_id = %s
                """, (chat_id,))
                details = await cur.fetchone()

        if not details:
            await query.edit_message_text("Деталі клієнта не знайдено.")
            return CLIENTS_LIST

        (full_name, phone_number, hair_length, has_beard,
         why_chose_us, likes_dislikes, suggestions, visit_count,
         discount_available, created_at) = details

        message = (
            f"*Деталі клієнта:*\n"
            f"*Ім'я:* {full_name}\n"
            f"*Телефон:* {phone_number}\n"
            f"*Довжина волосся:* {hair_length}\n"
            f"*Борода:* {'Так' if has_beard else 'Ні'}\n"
            f"*Чому обрали мене:* {why_chose_us}\n"
            f"*Подобається/Не подобається:* {likes_dislikes}\n"
            f"*Пропозиції:* {suggestions}\n"
            f"*Відвідувань:* {visit_count}\n"
            f"*Знижка доступна:* {'Так' if discount_available else 'Ні'}\n"
            f"*Дата створення:* {created_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
        )

        keyboard = [
            [InlineKeyboardButton("⬅️ Назад до списку", callback_data="back_to_clients_list")],
            [InlineKeyboardButton("🏠 До Адмін-меню", callback_data="back_to_admin_menu_inline")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            text=message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )

        return CLIENT_DETAILS

    except Exception as e:
        logger.error(f"Ошибка при получении деталей клиента {chat_id}: {e}")
        await query.edit_message_text("Сталася помилка при отриманні деталей клієнта.")
        return CLIENTS_LIST



# Функція для повернення до головного меню
async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    # Відправляємо нове повідомлення з головним адміністративним меню та видаляємо поточне
    await context.bot.send_message(
        chat_id=user_id,
        text="Виберіть опцію:",
        reply_markup=get_admin_menu_keyboard()
    )

    # Видаляємо старе повідомлення з клієнтами або деталями клієнта (опціонально)
    try:
        await query.message.delete()
    except Exception as e:
        logger.warning(f"Не вдалося видалити старе повідомлення: {e}")

    return ADMIN_MENU


# Обробник для повернення до списку клієнтів
async def back_to_clients_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    clients = context.user_data.get('clients', [])
    current_page = context.user_data.get('clients_page', 1)
    total_pages = context.user_data.get('total_pages', 1)

    message_text, keyboard = generate_clients_page(clients, current_page, total_pages)

    await query.edit_message_text(
        text=message_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )

    return CLIENTS_LIST



async def create_settings_table(db_pool):
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    discount_threshold INT DEFAULT 6,
                    discount_percentage DECIMAL(5,2) DEFAULT 15.00  -- Встановлено на 15% для візитів
                )
            """)
            # Перевіряємо наявність налаштувань
            await cur.execute("SELECT COUNT(*) FROM settings")
            count = await cur.fetchone()
            if count[0] == 0:
                await cur.execute("""
                    INSERT INTO settings (discount_threshold, discount_percentage)
                    VALUES (6, 15.00)  -- Встановлено поріг на 6 візитів і знижку 15%
                """)
                logger.info("Настройки по замовчуванню додані.")
            else:
                # Опціонально: оновлюємо налаштування, якщо потрібно
                await cur.execute("""
                    UPDATE settings
                    SET discount_threshold = 6, discount_percentage = 15.00
                    WHERE id = 1
                """)
                logger.info("Настройки оновлено до порогу 6 візитів та знижки 15%.")

async def create_price_list_table(db_pool):
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS price_list (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    item_name VARCHAR(255) NOT NULL,
                    price DECIMAL(10,2) NOT NULL
                )
            """)
            # Проверяем наличие записей
            await cur.execute("SELECT COUNT(*) FROM price_list")
            count = await cur.fetchone()
            if count[0] == 0:
                default_prices = [
                    ("Чоловіча стрижка", 500.00),
                    ("Жіноча стрижка", 700.00),
                    ("Гоління бороди", 300.00),
                    ("Фарбування", 1000.00)
                ]
                await cur.executemany("""
                    INSERT INTO price_list (item_name, price)
                    VALUES (%s, %s)
                """, default_prices)
                logger.info("Прайс-лист по умолчанию добавлен.")

async def create_media_table(db_pool):
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS media (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    media_type ENUM('photo', 'video') NOT NULL,
                    file_id VARCHAR(255) NOT NULL,
                    file_unique_id VARCHAR(255) NOT NULL,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logger.info("Таблица media проверена/создана.")

# Функция инициализации базы данных
async def on_startup(application: Application):
    logger.info("Инициализация подключения к базе данных.")
    try:
        application.bot_data['db_pool'] = await create_db_pool()
        logger.info("Пул подключений к базе данных создан.")
        db_pool = application.bot_data['db_pool']

        # Создаем необходимые таблицы
        await create_surveys_table(db_pool)
        await create_appointments_table(db_pool)
        await create_settings_table(db_pool)
        await create_price_list_table(db_pool)
        await create_media_table(db_pool)

    except Exception as e:
        logger.error(f"Ошибка при создании пула подключений: {e}")
        raise

# Функция закрытия пула подключений при завершении работы бота
async def on_shutdown(application: Application):
    logger.info("Закрытие пула подключений к базе данных.")
    db_pool = application.bot_data.get('db_pool')
    if db_pool:
        db_pool.close()
        await db_pool.wait_closed()

def get_main_menu_keyboard(lang: str, user_id: int):
    main_menu = MESSAGES[lang]['main_menu']
    # Преобразуем список списков в список списков (как требуется для клавиатуры)
    keyboard = main_menu.copy()
    if user_id == ADMIN_CHAT_ID:
        admin_button = MESSAGES[lang].get('admin_menu_extra_button', "📋 Адмін Меню")
        keyboard.append([admin_button])
    return ReplyKeyboardMarkup(
        keyboard, resize_keyboard=True, one_time_keyboard=False
    )




# Функция для создания административного меню
def get_admin_menu_keyboard():
    keyboard = [
        ["📅 Мої заплановані сеанси", "📝 Мої клієнти"],
        ["💰 Налаштування", "📸 Управління медіа"],
        ["Назад"]
    ]
    return ReplyKeyboardMarkup(
        keyboard, resize_keyboard=True, one_time_keyboard=False
    )

# Функция для начала взаимодействия
# Функция для начала взаимодействия
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    logger.info(f"Користувач {user_id} викликав /start")

    # Проверяем, выбран ли уже язык
    user_lang = context.user_data.get('lang')
    if user_lang:
        # Если язык уже выбран, показываем главное меню на этом языке
        await update.message.reply_text(
            MESSAGES[user_lang]['welcome'],
            reply_markup=get_main_menu_keyboard(user_lang, user_id)
        )
        return MENU_SELECTION
    else:
        # Если язык не выбран, показываем варианты выбора языка
        keyboard = [
            [MESSAGES['ua']['language_option_ua'], MESSAGES['ua']['language_option_ru']],
            [MESSAGES['ua']['language_option_cz']]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(
            MESSAGES['ua']['choose_language'],
            reply_markup=reply_markup
        )
        return LANGUAGE_CHOICE

# Функция для выбора языка
async def choose_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_response = update.message.text.strip().lower()
    lang_map = {
        "українська": "ua",
        "русский": "ru",
        "česky": "cz"
    }
    chosen_lang = lang_map.get(user_response)
    if not chosen_lang:
        # Отправляем сообщение об ошибке и остаёмся в состоянии выбора языка
        await update.message.reply_text(MESSAGES['ua']['invalid_language_selection'])
        return LANGUAGE_CHOICE

    context.user_data['lang'] = chosen_lang

    # Сохраняем выбор языка в базе данных
    db_pool = context.application.bot_data.get('db_pool')
    user_id = update.effective_user.id
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                UPDATE surveys 
                SET user_lang = %s 
                WHERE chat_id = %s
            """, (chosen_lang, user_id))

            # Если записи нет, создаем
            if cur.rowcount == 0:
                await cur.execute("""
                    INSERT INTO surveys (chat_id, user_lang) 
                    VALUES (%s, %s)
                """, (user_id, chosen_lang))

    # Отправляем сообщение о выборе языка и главное меню
    await update.message.reply_text(
        MESSAGES[chosen_lang]['language_set'],
        reply_markup=get_main_menu_keyboard(chosen_lang, user_id)
    )
    return MENU_SELECTION


# Обработка выбора в главном меню
async def handle_menu_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_selection = update.message.text
    user_id = update.effective_user.id
    lang = context.user_data.get('lang', 'ua')  # Получаем язык пользователя

    logger.info(f"Пользователь {user_id} выбрал опцию: {user_selection}")

    # Получаем переводы для меню
    main_menu = MESSAGES[lang]['main_menu']
    flat_menu = [item for sublist in main_menu for item in sublist]

    # Добавляем опцию Админ Меню, если пользователь - админ
    if user_id == ADMIN_CHAT_ID:
        admin_option = MESSAGES[lang].get('admin_menu_extra_button', "📋 Адмін Меню")
        flat_menu.append(admin_option)

    if user_selection not in flat_menu:
        logger.warning(f"Неизвестная команда от пользователя {user_id}: {user_selection}")
        await update.message.reply_text(
            MESSAGES[lang]['unknown_command']
        )
        return MENU_SELECTION

    # Обработка известных опций
    if user_selection == MESSAGES[lang]['main_menu'][0][0]:  # "✂️ Записатися на стрижку"
        # Начинаем процесс записи
        await ask_full_name(update, context)
        return APPOINTMENT
    elif user_selection == MESSAGES[lang]['main_menu'][0][1]:  # "👨‍🔧 Ознайомитися з майстром"
        await portfolio(update, context)
        return MENU_SELECTION
    elif user_selection == MESSAGES[lang]['main_menu'][1][0]:  # "💲 Прайс"
        await price(update, context, lang)
        return MENU_SELECTION
    elif user_selection == MESSAGES[lang]['main_menu'][1][1]:  # "📅 Мій запис"
        return await my_appointment(update, context)
    elif user_selection == MESSAGES[lang]['main_menu'][2][0]:  # "📝 Пройти опитування - отримати знижку"
        await survey_start(update, context)
        return SURVEY_Q1
    elif user_selection == admin_option and user_id == ADMIN_CHAT_ID:
        await show_admin_menu(update, context)
        return ADMIN_MENU
    elif user_selection == MESSAGES[lang].get('cancel_appointment_button') and context.user_data.get('has_appointment'):
        # Обработка отмены записи
        return await handle_cancellation(update, context)
    elif user_selection == MESSAGES[lang].get('back_button') and context.user_data.get('has_appointment'):
        # Возврат в главное меню из состояния с записью
        context.user_data['has_appointment'] = False
        await update.message.reply_text(
            MESSAGES[lang]['welcome'],
            reply_markup=get_main_menu_keyboard(lang, user_id)
        )
        return MENU_SELECTION
    else:
        logger.warning(f"Неизвестная команда от пользователя {user_id}: {user_selection}")
        await update.message.reply_text(
            MESSAGES[lang]['unknown_command']
        )
        return MENU_SELECTION



# Функция для запроса полного имени
async def ask_full_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        'Будь ласка, введіть ваше ім\'я та прізвище:',
        reply_markup=ReplyKeyboardRemove()
    )
    return APPOINTMENT

# Обработка ввода полного имени и запроса даты
async def appointment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    full_name = update.message.text.strip()
    user_id = update.effective_user.id
    logger.info(f"Пользователь {user_id} указал имя: {full_name}")
    context.user_data['appointment'] = {'full_name': full_name}

    # Предлагаем выбрать дату
    await ask_appointment_date(update, context)
    return APPOINTMENT_DATE

# Функция для запроса даты записи
async def ask_appointment_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    now = datetime.now()
    dates = []

    for i in range(0, 14):  # От сегодня до 13 дней вперед
        date = now + timedelta(days=i)
        date_str = date.strftime('%Y-%m-%d')
        dates.append([date_str])

    reply_markup = ReplyKeyboardMarkup(dates, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text(
        'Будь ласка, оберіть дату (сьогодні включно):',
        reply_markup=reply_markup
    )
    return APPOINTMENT_DATE

# Обработка выбранной даты и запроса времени
async def select_appointment_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    selected_date = update.message.text.strip()
    user_id = update.effective_user.id
    logger.info(f"Пользователь {user_id} выбрал дату: {selected_date}")

    # Проверка и инициализация 'appointment'
    if 'appointment' not in context.user_data:
        context.user_data['appointment'] = {}

    context.user_data['appointment']['date'] = selected_date

    # Предлагаем выбрать время
    await ask_appointment_time(update, context, selected_date)
    return APPOINTMENT_TIME


# Функция для запроса времени записи
# Функция для запроса времени записи
async def ask_appointment_time(update: Update, context: ContextTypes.DEFAULT_TYPE, selected_date: str) -> int:
    user_id = update.effective_user.id
    db_pool = context.application.bot_data.get('db_pool')
    if not db_pool:
        await update.message.reply_text("Сталася помилка. Будь ласка, спробуйте пізніше.")
        return MENU_SELECTION

    try:
        # Получаем список занятых временных слотов на выбранную дату
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT TIME_FORMAT(appointment_time, '%%H:%%i') FROM appointments
                    WHERE appointment_date = %s
                """, (selected_date,))
                taken_times = [row[0] for row in await cur.fetchall()]

        # Определяем рабочие часы (с 9:00 до 17:00, шаг 30 минут)
        time_slots = []
        start_time = datetime.strptime('09:00', '%H:%M')
        end_time = datetime.strptime('17:00', '%H:%M')
        delta = timedelta(minutes=30)
        current_time = start_time

        # Проверка, является ли выбранная дата сегодняшним днём
        selected_date_obj = datetime.strptime(selected_date, '%Y-%m-%d').date()
        today = datetime.now().date()
        is_today = selected_date_obj == today

        while current_time < end_time:
            time_str = current_time.strftime('%H:%M')

            # Если выбранная дата — сегодня, проверяем, не менее ли времени осталось 2 часа
            if is_today:
                appointment_datetime = datetime.combine(today, current_time.time())
                if appointment_datetime < datetime.now() + timedelta(hours=2):
                    current_time += delta
                    continue

            if time_str not in taken_times:
                time_slots.append([time_str])
            current_time += delta

        if not time_slots:
            await update.message.reply_text(
                "На жаль, на обрану дату немає доступного часу. Будь ласка, оберіть іншу дату.",
                reply_markup=ReplyKeyboardRemove()
            )
            await ask_appointment_date(update, context)
            return APPOINTMENT_DATE

        # Очистка предыдущих доступных времен, если были
        context.user_data.pop('available_times', None)

        reply_markup = ReplyKeyboardMarkup(time_slots, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(
            'Будь ласка, оберіть час:',
            reply_markup=reply_markup
        )
        # Сохранение доступных времен
        available_times = [slot[0] for slot in time_slots]
        context.user_data['available_times'] = available_times
        return APPOINTMENT_TIME

    except Exception as e:
        logger.error(f"Ошибка при получении доступных времен для даты {selected_date}: {e}")
        await update.message.reply_text("Сталася помилка при отриманні доступних часів. Будь ласка, спробуйте пізніше.")
        return MENU_SELECTION


# Обработка выбранного времени и подтверждение записи
# Обработка выбранного времени и подтверждение записи
async def select_appointment_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    selected_time = update.message.text.strip()
    user_id = update.effective_user.id
    logger.info(f"Пользователь {user_id} выбрал время: {selected_time}")
    available_times = context.user_data.get('available_times', [])

    if selected_time not in available_times:
        await update.message.reply_text(
            "Будь ласка, оберіть час з наявних опцій.",
            reply_markup=ReplyKeyboardMarkup([available_times], resize_keyboard=True, one_time_keyboard=True)
        )
        return APPOINTMENT_TIME

    context.user_data['appointment']['time'] = selected_time

    # Подтверждение записи
    appointment_info = context.user_data['appointment']
    await update.message.reply_text(
        f"Будь ласка, підтвердіть ваш запис:\n"
        f"Ім'я: {appointment_info['full_name']}\n"
        f"Дата: {appointment_info['date']}\n"
        f"Час: {appointment_info['time']}\n\n"
        f"Напишіть 'Так' для підтвердження або 'Скасувати' для скасування.",
        reply_markup=ReplyKeyboardMarkup([['Так', 'Скасувати']], resize_keyboard=True, one_time_keyboard=True)
    )
    return CONFIRM_APPOINTMENT


# Функция для отправки напоминания
async def send_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    chat_id = job.chat_id
    reminder_text = job.data.get('reminder_text')
    db_pool = context.application.bot_data.get('db_pool')
    if not db_pool:
        return
    # Проверяем, существует ли запись
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT 1 FROM appointments
                WHERE id = %s
            """, (job.data.get('appointment_id'),))
            result = await cur.fetchone()
            if result:
                # Запись существует, отправляем напоминание
                await context.bot.send_message(chat_id=chat_id, text=reminder_text)

# Функция для отправки напоминания через две недели
async def send_two_weeks_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    chat_id = job.chat_id
    reminder_text = job.data.get('reminder_text')

    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=reminder_text,
            parse_mode=ParseMode.HTML
        )
        logger.info(f"Напоминание через две недели отправлено пользователю {chat_id}.")
    except Exception as e:
        logger.error(f"Ошибка при отправке напоминания через две недели пользователю {chat_id}: {e}")

# Функция для подтверждения записи и сохранения в базе данных
# Функция для подтверждения записи и сохранения в базе данных
# Функция для подтверждения записи и сохранения в базе данных
async def confirm_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_response = update.message.text.strip().lower()
    user_id = update.effective_user.id
    db_pool = context.application.bot_data.get('db_pool')

    if user_response == 'так':
        appointment_info = context.user_data['appointment']
        if not db_pool:
            await update.message.reply_text("Сталася помилка. Будь ласка, спробуйте пізніше.")
            return MENU_SELECTION

        try:
            async with db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    # Отримуємо дані про знижку для користувача
                    await cur.execute("SELECT discount_available, visit_count FROM surveys WHERE chat_id = %s", (user_id,))
                    survey_data = await cur.fetchone()

                    await cur.execute("SELECT discount_threshold, discount_percentage FROM settings WHERE id = 1")
                    settings_data = await cur.fetchone()

                    discount = 0.0
                    survey_discount_percentage = 10.0  # Встановіть бажаний відсоток знижки від опитування

                    discount_available = False
                    discount_threshold = 6  # Встановлено на 6 візитів
                    visit_discount_percentage = 15.0  # Встановлено на 15% знижку

                    current_visit_count = 0

                    if survey_data:
                        discount_available = survey_data[0]
                        current_visit_count = survey_data[1]
                    if settings_data:
                        discount_threshold = int(settings_data[0])
                        visit_discount_percentage = float(settings_data[1])

                    # Обчислюємо загальну знижку
                    if discount_available:
                        discount += survey_discount_percentage  # Додаємо знижку від опитування

                    # Перевіряємо, чи це кратне 6-е відвідування
                    if (current_visit_count + 1) % discount_threshold == 0:
                        discount += visit_discount_percentage  # Додаємо знижку від кількості відвідувань

                    # Вставляємо запис з урахуванням знижки
                    await cur.execute("""
                        INSERT INTO appointments (
                            chat_id,
                            full_name,
                            appointment_date,
                            appointment_time,
                            discount
                        ) VALUES (%s, %s, %s, %s, %s)
                    """, (
                        user_id,
                        appointment_info['full_name'],
                        appointment_info['date'],
                        appointment_info['time'],
                        discount
                    ))
                    appointment_id = cur.lastrowid

                    # Оновлюємо кількість відвідувань
                    await cur.execute("""
                        UPDATE surveys
                        SET visit_count = visit_count + 1
                        WHERE chat_id = %s
                    """, (user_id,))

            # Формуємо повідомлення для користувача
            discount_message = f"Ви отримали знижку {discount}%!" if discount > 0 else ""
            await update.message.reply_text(
                f"Дякую! Ваш запис підтверджено на <b>{appointment_info['date']}</b> о <b>{appointment_info['time']}</b>.\n{discount_message}",
                parse_mode=ParseMode.HTML,
                reply_markup=get_main_menu_keyboard(user_id)
            )

            # Плануємо нагадування за день і за годину до запису
            appointment_datetime_str = f"{appointment_info['date']} {appointment_info['time']}"
            appointment_datetime = datetime.strptime(appointment_datetime_str, '%Y-%m-%d %H:%M')
            now = datetime.now()
            one_day_before = appointment_datetime - timedelta(days=1)
            one_hour_before = appointment_datetime - timedelta(hours=1)
            two_weeks_after = appointment_datetime + timedelta(weeks=2)
            job_queue = context.application.job_queue

            if one_day_before > now:
                job_queue.run_once(
                    send_reminder,
                    when=(one_day_before - now).total_seconds(),
                    chat_id=user_id,
                    data={
                        'reminder_text': f"Нагадування: завтра у вас запис на {appointment_datetime.strftime('%Y-%m-%d %H:%M')}.",
                        'appointment_id': appointment_id
                    }
                )
            if one_hour_before > now:
                job_queue.run_once(
                    send_reminder,
                    when=(one_hour_before - now).total_seconds(),
                    chat_id=user_id,
                    data={
                        'reminder_text': f"Нагадування: через годину у вас запис на {appointment_datetime.strftime('%Y-%m-%d %H:%M')}.",
                        'appointment_id': appointment_id
                    }
                )

            if two_weeks_after > now:
                job_queue.run_once(
                    send_two_weeks_reminder,
                    when=(two_weeks_after - now).total_seconds(),
                    chat_id=user_id,
                    data={
                        'reminder_text': TWO_WEEKS_REMINDER_TEXT
                    }
                )

        except aiomysql.IntegrityError:
            # Слот уже занят
            await update.message.reply_text(
                "На жаль, обране час вже зайнято. Будь ласка, оберіть інший час.",
                reply_markup=ReplyKeyboardRemove()
            )
            await ask_appointment_time(update, context, appointment_info['date'])
            return APPOINTMENT_TIME
        except Exception as e:
            logger.error(f"Помилка при збереженні запису: {e}")
            await update.message.reply_text(
                "Сталася помилка при збереженні вашого запису. Будь ласка, спробуйте пізніше.",
                reply_markup=get_main_menu_keyboard(user_id)
            )
        finally:
            context.user_data.pop('appointment', None)
        return MENU_SELECTION

    elif user_response == 'скасувати':
        await update.message.reply_text(
            "Запис скасовано.",
            reply_markup=get_main_menu_keyboard(user_id)
        )
        context.user_data.pop('appointment', None)
        return MENU_SELECTION

    else:
        await update.message.reply_text(
            "Операція скасування відмінена.",
            reply_markup=get_main_menu_keyboard(user_id)
        )
        context.user_data.pop('appointment', None)
        return MENU_SELECTION


# Функция для отправки портфолио пользователю
async def portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    logger.info(f"Пользователь {user_id} запросил портфолио.")
    db_pool = context.application.bot_data.get('db_pool')

    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT media_type, file_id FROM media
                """)
                media_items = await cur.fetchall()

        if not media_items:
            await update.message.reply_text("Портфоліо порожнє.")
            return

        for media in media_items:
            media_type, file_id = media
            if media_type == 'photo':
                await update.message.reply_photo(
                    photo=file_id,
                    caption='Ось деякі з моїх робіт! 🎨'
                )
            elif media_type == 'video':
                await update.message.reply_video(
                    video=file_id,
                    caption='Перегляньте це відео про наші послуги! 📹'
                )
    except Exception as e:
        logger.error(f"Ошибка при отправке медиа: {e}")
        await update.message.reply_text("Сталася помилка при відправці медіа.")

# Функция для отправки прайс-листа пользователям
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    logger.info(f"Пользователь {user_id} запросил прайс-лист.")
    db_pool = context.application.bot_data.get('db_pool')

    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT item_name, price FROM price_list
                """)
                items = await cur.fetchall()

        if not items:
            await update.message.reply_text("Прайс-лист пустий.")
            return

        price_list = "*Прайс-лист:*\n"
        for item_name, price in items:
            price_list += f"✂️ {item_name} — {price}₴\n"

        await update.message.reply_text(
            price_list, parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Ошибка при получении прайс-листа: {e}")
        await update.message.reply_text("Сталася помилка при отриманні прайс-листа.")


async def edit_price_item_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    item_id = update.message.text.strip()
    if item_id.lower() == 'скасувати':
        return await cancel_price_edit(update, context)

    if not item_id.isdigit():
        await update.message.reply_text(
            "Будь ласка, введіть коректний ID позиції або натисніть 'Скасувати'.",
            reply_markup=ReplyKeyboardMarkup([['Скасувати']], resize_keyboard=True, one_time_keyboard=True)
        )
        return PRICE_EDIT_EDIT_ID

    item_id = int(item_id)
    context.user_data['edit_item_id'] = item_id

    # Перевіряємо, чи існує позиція з таким ID
    db_pool = context.application.bot_data.get('db_pool')
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT item_name, price FROM price_list WHERE id = %s", (item_id,))
                result = await cur.fetchone()
                if not result:
                    await update.message.reply_text(
                        "Позиція з таким ID не існує. Будь ласка, введіть інший ID або натисніть 'Скасувати'.",
                        reply_markup=ReplyKeyboardMarkup([['Скасувати']], resize_keyboard=True, one_time_keyboard=True)
                    )
                    return PRICE_EDIT_EDIT_ID

                current_name, current_price = result
                context.user_data['current_name'] = current_name
                context.user_data['current_price'] = current_price

    except Exception as e:
        logger.error(f"Ошибка при перевірці позиції ID {item_id}: {e}")
        await update.message.reply_text("Сталася помилка при перевірці позиції. Спробуйте пізніше.")
        return PRICE_EDIT_SELECTION

    await update.message.reply_text(
        f"Введіть нову назву для позиції (поточна: {current_name}):",
        reply_markup=ReplyKeyboardMarkup([['Скасувати']], resize_keyboard=True, one_time_keyboard=True)
    )
    return PRICE_EDIT_EDIT_NAME

# Функция для начала опроса
async def survey_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    logger.info(f"Пользователь {user_id} начал опрос.")
    context.user_data['survey'] = {'current_question': 0, 'answers': []}
    # Отправляем первое вопрос с кнопкой 'Повернутися'
    keyboard = [['Повернутися']]
    reply_markup = ReplyKeyboardMarkup(
        keyboard, resize_keyboard=True, one_time_keyboard=False
    )
    await update.message.reply_text(
        SURVEY_QUESTIONS[0], reply_markup=reply_markup
    )
    return SURVEY_Q1

# Функция для обработки ответов на опрос
async def handle_survey_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    survey = context.user_data.get('survey')
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if not survey:
        logger.warning(f"Пользователь {user_id} попытался ответить на опрос без его начала.")
        await update.message.reply_text("Будь ласка, розпочніть опитування через меню.")
        return MENU_SELECTION

    user_response = update.message.text.strip()
    logger.info(f"Пользователь {user_id} ответил: {user_response}")

    if user_response.lower() == 'повернутися':
        await update.message.reply_text(
            "Ви вийшли з опитування.",
            reply_markup=get_main_menu_keyboard(user_id)
        )
        # Очищаем данные опроса
        context.user_data.pop('survey', None)
        return MENU_SELECTION

    # Добавляем ответ
    survey['answers'].append(user_response)
    current_q = survey['current_question']
    logger.info(f"Пользователь {user_id} ответил на вопрос {current_q + 1}: {user_response}")

    survey['current_question'] += 1

    if survey['current_question'] < len(SURVEY_QUESTIONS):
        # Отправляем следующий вопрос с кнопкой 'Повернутися'
        next_question = SURVEY_QUESTIONS[survey['current_question']]
        keyboard = [['Повернутися']]
        reply_markup = ReplyKeyboardMarkup(
            keyboard, resize_keyboard=True, one_time_keyboard=False
        )
        await update.message.reply_text(next_question, reply_markup=reply_markup)
        # Определяем следующий состояние
        next_state = SURVEY_Q1 + survey['current_question']
        return next_state
    else:
        # Все вопросы заданы, сохраняем данные
        answers = survey['answers']
        logger.info(f"Пользователь {user_id} завершил опрос. Сохраняем данные.")

        # Сохранение в базу данных
        try:
            db_pool = context.application.bot_data.get('db_pool')
            if not db_pool:
                raise Exception("Пул подключений к базе данных не инициализирован.")

            async with db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    # Проверяем, есть ли запись в surveys
                    await cur.execute("SELECT id FROM surveys WHERE chat_id = %s", (chat_id,))
                    existing = await cur.fetchone()
                    if existing:
                        await cur.execute("""
                            UPDATE surveys
                            SET full_name = %s,
                                phone_number = %s,
                                hair_length = %s,
                                has_beard = %s,
                                why_chose_us = %s,
                                likes_dislikes = %s,
                                suggestions = %s,
                                discount_available = TRUE
                            WHERE chat_id = %s
                        """, (
                            answers[0],  # Имя и фамилия
                            answers[1],  # Номер телефона
                            answers[2],  # Длина волос
                            parse_yes_no(answers[3]),  # Есть ли борода
                            answers[4],  # Почему выбрали меня
                            answers[5],  # Что нравится/не нравится
                            answers[6],  # Предложения
                            chat_id
                        ))
                    else:
                        await cur.execute("""
                            INSERT INTO surveys (
                                chat_id,
                                full_name,
                                phone_number,
                                hair_length,
                                has_beard,
                                why_chose_us,
                                likes_dislikes,
                                suggestions,
                                discount_available
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE)
                        """, (
                            chat_id,
                            answers[0],  # Имя и фамилия
                            answers[1],  # Номер телефона
                            answers[2],  # Длина волос
                            parse_yes_no(answers[3]),  # Есть ли борода
                            answers[4],  # Почему выбрали меня
                            answers[5],  # Что нравится/не нравится
                            answers[6],  # Предложения
                        ))
            logger.info(f"Данные опроса пользователя {user_id} успешно сохранены.")
            await update.message.reply_text(
                "Дякую за участь! Ваша знижка буде застосована при наступному записі. 🎉",
                reply_markup=get_main_menu_keyboard(user_id)
            )
        except Exception as e:
            logger.error(f"Ошибка при сохранении данных опроса для пользователя {user_id}: {e}")
            await update.message.reply_text(
                "Сталася помилка при збереженні ваших відповідей. Будь ласка, спробуйте пізніше."
            )

        # Очищаем данные опроса
        context.user_data.pop('survey', None)
        return MENU_SELECTION

# Функция для парсинга ответа на вопрос о бороде
def parse_yes_no(response: str) -> bool:
    """Парсит ответ на вопрос о наличии бороды."""
    yes_responses = ['так', 'є', 'є борода', 'yes', 'y']
    no_responses = ['ні', 'немає бороди', 'no', 'n']
    response_lower = response.lower()
    if response_lower in yes_responses:
        return True
    elif response_lower in no_responses:
        return False
    else:
        return False  # По умолчанию считаем, что бороды нет

# Функция для просмотра и отмены записи
async def my_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    db_pool = context.application.bot_data.get('db_pool')
    if not db_pool:
        await update.message.reply_text("Сталася помилка. Будь ласка, спробуйте пізніше.")
        return MENU_SELECTION

    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Выбираем все будущие записи пользователя
                await cur.execute("""
                    SELECT appointment_date, TIME_FORMAT(appointment_time, '%%H:%%i'), id
                    FROM appointments
                    WHERE chat_id = %s AND appointment_date >= CURDATE()
                    ORDER BY appointment_date, appointment_time
                """, (user_id,))
                results = await cur.fetchall()

                if results:
                    # Показываем все будущие записи
                    message = "Ваші майбутні записи:\n"
                    for (appointment_date, appointment_time, appointment_id) in results:
                        message += f"- {appointment_date} о {appointment_time} (ID: {appointment_id})\n"
                    message += "\nНапишіть 'Скасувати', щоб скасувати ваш найближчий запис, або 'Назад' для повернення до меню."

                    # Сохраняем ID ближайшей записи (первая в списке)
                    nearest_appointment_id = results[0][2]
                    context.user_data['appointment_id'] = nearest_appointment_id

                    await update.message.reply_text(
                        message,
                        reply_markup=ReplyKeyboardMarkup([['Скасувати', 'Назад']], resize_keyboard=True)
                    )
                    return CANCEL_APPOINTMENT
                else:
                    await update.message.reply_text(
                        "У вас немає активних записів.",
                        reply_markup=get_main_menu_keyboard(user_id)
                    )
                    return MENU_SELECTION
    except Exception as e:
        logger.error(f"Ошибка при отриманні записів користувача {user_id}: {e}")
        await update.message.reply_text("Сталася помилка при отриманні ваших записів. Будь ласка, спробуйте пізніше.")
        return MENU_SELECTION

async def cleanup_old_appointments(context: ContextTypes.DEFAULT_TYPE) -> None:
    db_pool = context.application.bot_data.get('db_pool')
    if not db_pool:
        return
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                DELETE FROM appointments
                WHERE appointment_date < CURDATE()
                   OR (appointment_date = CURDATE() AND appointment_time < CURTIME())
            """)
# Обработка отмены записи
async def handle_cancellation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_response = update.message.text.strip().lower()
    user_id = update.effective_user.id
    if user_response == 'скасувати':
        # Отменяем запись
        db_pool = context.application.bot_data.get('db_pool')
        if not db_pool:
            await update.message.reply_text("Сталася помилка. Будь ласка, спробуйте пізніше.")
            return MENU_SELECTION
        try:
            appointment_id = context.user_data.get('appointment_id')
            if not appointment_id:
                await update.message.reply_text("Сталася помилка. Спробуйте знову.")
                return MENU_SELECTION

            async with db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    # Удаляем запись
                    await cur.execute("""
                        DELETE FROM appointments
                        WHERE id = %s
                    """, (appointment_id,))
            await update.message.reply_text(
                "Ваш запис був успішно скасований.",
                reply_markup=get_main_menu_keyboard(user_id)
            )
            return MENU_SELECTION
        except Exception as e:
            logger.error(f"Ошибка при отмене записи пользователя {user_id}: {e}")
            await update.message.reply_text("Сталася помилка при скасуванні вашого запису. Будь ласка, спробуйте пізніше.")
            return MENU_SELECTION
    else:
        # Пользователь решил не отменять запись
        await update.message.reply_text(
            "Операція скасування відмінена.",
            reply_markup=get_main_menu_keyboard(user_id)
        )
        return MENU_SELECTION

# Функция для отображения административного меню
async def show_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        'Вітаю, Адмін! Оберіть опцію:',
        reply_markup=get_admin_menu_keyboard()
    )

# Функция для показа запланированных сеансов администратору
async def show_admin_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db_pool = context.application.bot_data.get('db_pool')
    if not db_pool:
        await update.message.reply_text("Сталася помилка. Будь ласка, спробуйте пізніше.")
        return

    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT a.full_name, a.appointment_date, a.appointment_time, s.phone_number, a.discount
                    FROM appointments a
                    LEFT JOIN surveys s ON a.chat_id = s.chat_id
                    ORDER BY a.appointment_date, a.appointment_time
                """)
                appointments = await cur.fetchall()

        if not appointments:
            await update.message.reply_text("Немає запланованих сеансів.")
            return

        schedule = {}
        for full_name, appointment_date, appointment_time, phone_number, discount in appointments:
            if appointment_date not in schedule:
                schedule[appointment_date] = []
            # Если phone_number отсутствует, подставим "N/A" или другое обозначение
            phone_number = phone_number if phone_number else "N/A"
            schedule[appointment_date].append((full_name, appointment_time, phone_number, discount))

        message = "*Мої заплановані сеанси:*\n"
        for date, sessions in schedule.items():
            message += f"\n*{date}*\n"
            for name, time, phone, disc in sessions:
                message += f"• {time} - {name} (тел: {phone}), Знижка: {disc}%\n"

        await update.message.reply_text(
            message, parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Ошибка при отриманні розкладу: {e}")
        await update.message.reply_text("Сталася помилка при отриманні розкладу.")




# Функция для показа меню настроек администратору
async def show_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db_pool = context.application.bot_data.get('db_pool')
    if not db_pool:
        await update.message.reply_text("Сталася помилка. Спробуйте пізніше.")
        return

    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT discount_threshold, discount_percentage FROM settings WHERE id = 1")
                settings = await cur.fetchone()
                if settings:
                    threshold, percentage = settings
                    message = (
                        f"*Налаштування Скидок:*\n"
                        f"• Кількість відвідувань для знижки: {threshold}\n"
                        f"• Відсоток знижки: {percentage}%\n\n"
                        f"Оберіть дію:"
                    )
                    keyboard = [
                        ["Змінити кількість відвідувань", "Змінити відсоток знижки"],
                        ["Управління прайс-листом", "Назад"]
                    ]
                    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
                    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
                else:
                    await update.message.reply_text("Налаштування не знайдено.")
    except Exception as e:
        logger.error(f"Ошибка при получении настроек: {e}")
        await update.message.reply_text("Сталася помилка при отриманні налаштувань.")

# Функция для обработки выбора настроек
async def handle_settings_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    selection = update.message.text
    logger.info(f"Адмін вибрав настройку: {selection}")

    if selection == "Змінити кількість відвідувань":
        await update.message.reply_text("Введіть нову кількість відвідувань для знижки:", reply_markup=ReplyKeyboardRemove())
        return CHANGE_THRESHOLD

    elif selection == "Змінити відсоток знижки":
        await update.message.reply_text("Введіть новий відсоток знижки (число без %):", reply_markup=ReplyKeyboardRemove())
        return CHANGE_PERCENTAGE

    elif selection == "Управління прайс-листом":
        await show_price_edit_menu(update, context)
        return PRICE_EDIT_SELECTION

    elif selection == "Назад":
        await show_admin_menu(update, context)
        return ADMIN_MENU

    else:
        await update.message.reply_text("Невідома опція. Будь ласка, оберіть ще раз.")
        return SETTINGS

# Функция для изменения порога посещений для скидки
async def change_threshold(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    new_threshold = update.message.text.strip()
    if not new_threshold.isdigit():
        await update.message.reply_text("Будь ласка, введіть коректне число.")
        return CHANGE_THRESHOLD

    new_threshold = int(new_threshold)
    db_pool = context.application.bot_data.get('db_pool')

    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    UPDATE settings
                    SET discount_threshold = %s
                    WHERE id = 1
                """, (new_threshold,))
        await update.message.reply_text(f"Кількість відвідувань для знижки змінено на {new_threshold}.", reply_markup=get_admin_menu_keyboard())
    except Exception as e:
        logger.error(f"Ошибка при изменении порога посещений: {e}")
        await update.message.reply_text("Сталася помилка при зміні налаштувань.")

    return ADMIN_MENU

# Функция для изменения процента скидки
async def change_percentage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    new_percentage = update.message.text.strip()
    try:
        new_percentage = float(new_percentage)
    except ValueError:
        await update.message.reply_text("Будь ласка, введіть коректне число.")
        return CHANGE_PERCENTAGE

    db_pool = context.application.bot_data.get('db_pool')

    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    UPDATE settings
                    SET discount_percentage = %s
                    WHERE id = 1
                """, (new_percentage,))
        await update.message.reply_text(f"Відсоток знижки змінено на {new_percentage}%.", reply_markup=get_admin_menu_keyboard())
    except Exception as e:
        logger.error(f"Ошибка при изменении процента скидки: {e}")
        await update.message.reply_text("Сталася помилка при зміні налаштувань.")

    return ADMIN_MENU

# Функция для показа меню редактирования прайс-листа
async def show_price_edit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        ["Додати позицію", "Змінити позицію"],
        ["Видалити позицію", "Назад"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text(
        "Оберіть дію для прайс-листа:",
        reply_markup=reply_markup
    )

# Функция для обработки выбора действия в прайс-листе
async def handle_price_edit_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    selection = update.message.text
    logger.info(f"Адмін вибрав дію прайс-листа: {selection}")

    if selection == "Додати позицію":
        await update.message.reply_text(
            "Введіть назву позиції:",
            reply_markup=ReplyKeyboardMarkup([['Скасувати']], resize_keyboard=True, one_time_keyboard=True)
        )
        return PRICE_EDIT_ADD_NAME

    elif selection == "Змінити позицію":
        await list_price_items(update, context, action="edit")
        return PRICE_EDIT_EDIT_ID  # Перейти до стану введення ID для редагування

    elif selection == "Видалити позицію":
        await list_price_items(update, context, action="delete")
        return PRICE_EDIT_DELETE_ID  # Перейти до стану введення ID для видалення

    elif selection == "Назад":
        await show_settings_menu(update, context)
        return SETTINGS

    else:
        await update.message.reply_text("Невідома опція. Будь ласка, оберіть ще раз.")
        return PRICE_EDIT_SELECTION



# Функция для списка прайс-листа
async def list_price_items(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str) -> None:
    db_pool = context.application.bot_data.get('db_pool')

    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id, item_name, price FROM price_list")
                items = await cur.fetchall()

        if not items:
            await update.message.reply_text("Прайс-лист пустий.")
            await show_price_edit_menu(update, context)
            return

        message = "*Прайс-лист:*\n"
        for item_id, item_name, price in items:
            message += f"{item_id}. {item_name} — {price}₴\n"

        if action == "edit":
            action_text = "змінити"
        elif action == "delete":
            action_text = "видалити"
        else:
            action_text = ""

        await update.message.reply_text(
            f"{message}\nВведіть ID позиції, яку бажаєте {action_text}, або натисніть 'Скасувати':",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=ReplyKeyboardMarkup([['Скасувати']], resize_keyboard=True, one_time_keyboard=True)
        )
        context.user_data['price_action'] = action
    except Exception as e:
        logger.error(f"Ошибка при получении прайс-листа: {e}")
        await update.message.reply_text("Сталася помилка при отриманні прайс-листа.")


# Функция для добавления новой позиции в прайс-лист
async def add_price_item(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    item_name = update.message.text.strip()
    context.user_data['new_item_name'] = item_name
    await update.message.reply_text("Введіть ціну для цієї позиції:")
    return PRICE_EDIT_ADD

# handler для ADD_PRICE_ITEM_NAME:
async def add_price_item_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    item_name = update.message.text.strip()
    if item_name.lower() == 'скасувати':
        return await cancel_price_edit(update, context)

    if not item_name:
        await update.message.reply_text(
            "Назва позиції не може бути порожньою. Будь ласка, введіть коректну назву або натисніть 'Скасувати'.",
            reply_markup=ReplyKeyboardMarkup([['Скасувати']], resize_keyboard=True, one_time_keyboard=True)
        )
        return PRICE_EDIT_ADD_NAME

    context.user_data['new_item_name'] = item_name
    await update.message.reply_text(
        "Введіть ціну для цієї позиції (наприклад, 100 або 100.00):",
        reply_markup=ReplyKeyboardMarkup([['Скасувати']], resize_keyboard=True, one_time_keyboard=True)
    )
    return PRICE_EDIT_ADD_PRICE


# handler для ADD_PRICE_ITEM_PRICE:
async def add_price_item_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    price_text = update.message.text.strip()
    if price_text.lower() == 'скасувати':
        return await cancel_price_edit(update, context)

    try:
        price = float(price_text)
        if price < 0:
            raise ValueError("Ціна не може бути від'ємною.")
    except ValueError:
        await update.message.reply_text(
            "Будь ласка, введіть коректну ціну (наприклад, 100 або 100.00) або натисніть 'Скасувати'.",
            reply_markup=ReplyKeyboardMarkup([['Скасувати']], resize_keyboard=True, one_time_keyboard=True)
        )
        return PRICE_EDIT_ADD_PRICE

    item_name = context.user_data.get('new_item_name')
    db_pool = context.application.bot_data.get('db_pool')

    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    INSERT INTO price_list (item_name, price)
                    VALUES (%s, %s)
                """, (item_name, price))
        await update.message.reply_text(
            f"Позицію '{item_name}' з ціною {price:.2f}₴ додано успішно.",
            reply_markup=get_admin_menu_keyboard()
        )
    except Exception as e:
        logger.error(f"Помилка при додаванні позиції: {e}")
        await update.message.reply_text("Сталася помилка при додаванні позиції. Спробуйте ще раз.",
                                        reply_markup=get_admin_menu_keyboard())

    context.user_data.pop('new_item_name', None)
    return ADMIN_MENU

async def cancel_price_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Операція скасована.",
        reply_markup=get_price_edit_menu_keyboard()
    )
    # Очищуємо всі пов'язані дані
    keys_to_remove = [
        'new_item_name', 'edit_item_id', 'current_name', 'current_price',
        'delete_item_id', 'delete_item_name'
    ]
    for key in keys_to_remove:
        context.user_data.pop(key, None)
    return PRICE_EDIT_SELECTION


def get_price_edit_menu_keyboard():
    keyboard = [
        ["Додати позицію", "Змінити позицію"],
        ["Видалити позицію", "Назад"]
    ]
    return ReplyKeyboardMarkup(
        keyboard, resize_keyboard=True, one_time_keyboard=True
    )

# Функция для изменения существующей позиции в прайс-листе
async def edit_price_item(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    item_id = update.message.text.strip()
    if not item_id.isdigit():
        await update.message.reply_text("Будь ласка, введіть коректний ID:")
        return PRICE_EDIT_EDIT

    item_id = int(item_id)
    context.user_data['edit_item_id'] = item_id
    await update.message.reply_text("Введіть нову назву для цієї позиції:")
    return PRICE_EDIT_EDIT

async def edit_price_item_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    new_name = update.message.text.strip()
    if new_name.lower() == 'скасувати':
        return await cancel_price_edit(update, context)

    if not new_name:
        await update.message.reply_text(
            "Назва не може бути порожньою. Будь ласка, введіть коректну назву або натисніть 'Скасувати'.",
            reply_markup=ReplyKeyboardMarkup([['Скасувати']], resize_keyboard=True, one_time_keyboard=True)
        )
        return PRICE_EDIT_EDIT_NAME

    context.user_data['new_item_name'] = new_name
    await update.message.reply_text(
        "Введіть нову ціну для цієї позиції (наприклад, 100 або 100.00):",
        reply_markup=ReplyKeyboardMarkup([['Скасувати']], resize_keyboard=True, one_time_keyboard=True)
    )
    return PRICE_EDIT_EDIT_PRICE


async def edit_price_item_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    price_text = update.message.text.strip()
    if price_text.lower() == 'скасувати':
        return await cancel_price_edit(update, context)

    try:
        new_price = float(price_text)
        if new_price < 0:
            raise ValueError("Ціна не може бути від'ємною.")
    except ValueError:
        await update.message.reply_text(
            "Будь ласка, введіть коректну ціну (наприклад, 100 або 100.00) або натисніть 'Скасувати'.",
            reply_markup=ReplyKeyboardMarkup([['Скасувати']], resize_keyboard=True, one_time_keyboard=True)
        )
        return PRICE_EDIT_EDIT_PRICE

    item_id = context.user_data.get('edit_item_id')
    new_name = context.user_data.get('new_item_name')
    db_pool = context.application.bot_data.get('db_pool')

    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    UPDATE price_list
                    SET item_name = %s, price = %s
                    WHERE id = %s
                """, (new_name, new_price, item_id))
        await update.message.reply_text(
            f"Позицію ID {item_id} оновлено успішно.",
            reply_markup=get_admin_menu_keyboard()
        )
    except Exception as e:
        logger.error(f"Ошибка при обновлении позиції ID {item_id}: {e}")
        await update.message.reply_text(
            "Сталася помилка при оновленні позиції. Спробуйте ще раз.",
            reply_markup=get_admin_menu_keyboard()
        )

    # Очищуємо дані
    context.user_data.pop('edit_item_id', None)
    context.user_data.pop('new_item_name', None)
    context.user_data.pop('current_name', None)
    context.user_data.pop('current_price', None)

    return ADMIN_MENU


# Функция для удаления позиции из прайс-листа
async def delete_price_item(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    media_id = update.message.text.strip()
    if not media_id.isdigit():
        await update.message.reply_text("Будь ласка, введіть коректний ID:")
        return PRICE_EDIT_DELETE

    media_id = int(media_id)
    db_pool = context.application.bot_data.get('db_pool')

    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Проверяем, существует ли позиция
                await cur.execute("""
                    SELECT item_name FROM price_list WHERE id = %s
                """, (media_id,))
                result = await cur.fetchone()
                if not result:
                    await update.message.reply_text("Позиція з таким ID не існує.")
                    return ADMIN_MENU

                item_name = result[0]
                # Удаляем позицию
                await cur.execute("""
                    DELETE FROM price_list WHERE id = %s
                """, (media_id,))
        await update.message.reply_text(f"Позицію '{item_name}' видалено успішно.", reply_markup=get_admin_menu_keyboard())
    except Exception as e:
        logger.error(f"Ошибка при удалении позиции: {e}")
        await update.message.reply_text("Сталася помилка при видаленні позиції.")

    return ADMIN_MENU

# Функция для показа списка прайс-листа (может быть объединена с list_price_items)
# Уже реализовано выше

# Функция для управления медиаматериалами
async def show_media_management_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        ["Додати фото", "Додати відео"],
        ["Видалити медіа", "Назад"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text(
        "Управління медіа:",
        reply_markup=reply_markup
    )

# Функция для обработки выбора действия в управлении медиа
async def handle_media_management_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    selection = update.message.text
    logger.info(f"Адмін вибрав дію медіа: {selection}")

    if selection == "Додати фото":
        keyboard = [['Скасувати']]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(
            "Відправте фото для додавання або натисніть 'Скасувати' для скасування.",
            reply_markup=reply_markup
        )
        return MEDIA_UPLOAD_PHOTO

    elif selection == "Додати відео":
        keyboard = [['Скасувати']]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(
            "Відправте відео для додавання або натисніть 'Скасувати' для скасування.",
            reply_markup=reply_markup
        )
        return MEDIA_UPLOAD_VIDEO

    elif selection == "Видалити медіа":
        await list_media_items(update, context, action="delete")
        return MEDIA_MANAGEMENT

    elif selection == "Назад":
        await show_admin_menu(update, context)
        return ADMIN_MENU

    else:
        await update.message.reply_text("Невідома опція. Будь ласка, оберіть ще раз.")
        return MEDIA_MANAGEMENT


# Додаємо новий стан для скасування
CANCEL_MEDIA_UPLOAD = 35  # Переконайтеся, що цей номер не конфліктує з іншими станами

async def cancel_media_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    await update.message.reply_text(
        "Операція скасована.",
        reply_markup=get_admin_menu_keyboard()
    )
    return ADMIN_MENU


# Функция для добавления фото
async def add_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message.photo:
        await update.message.reply_text("Будь ласка, відправте коректне фото.")
        return MEDIA_UPLOAD_PHOTO

    photo = update.message.photo[-1]  # Получаем наилучшее качество
    file_id = photo.file_id
    file_unique_id = photo.file_unique_id
    db_pool = context.application.bot_data.get('db_pool')

    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    INSERT INTO media (media_type, file_id, file_unique_id)
                    VALUES ('photo', %s, %s)
                """, (file_id, file_unique_id))
                media_id = cur.lastrowid
        await update.message.reply_text("Фото додано успішно.", reply_markup=get_admin_menu_keyboard())

        # Отправляем уведомление администратору
        keyboard = [
            [InlineKeyboardButton("Видалити", callback_data=f"delete_media_{media_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"Новe фото додано. ID: {media_id}",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Ошибка при добавлении фото: {e}")
        await update.message.reply_text("Сталася помилка при додаванні фото.")

    return ADMIN_MENU

# Функция для добавления видео
async def add_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message.video:
        await update.message.reply_text("Будь ласка, відправте коректне відео.")
        return MEDIA_UPLOAD_VIDEO

    video = update.message.video
    file_id = video.file_id
    file_unique_id = video.file_unique_id
    db_pool = context.application.bot_data.get('db_pool')

    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    INSERT INTO media (media_type, file_id, file_unique_id)
                    VALUES ('video', %s, %s)
                """, (file_id, file_unique_id))
                media_id = cur.lastrowid
        await update.message.reply_text("Відео додано успішно.", reply_markup=get_admin_menu_keyboard())

        # Отправляем уведомление администратору
        keyboard = [
            [InlineKeyboardButton("Видалити", callback_data=f"delete_media_{media_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"Новe відео додано. ID: {media_id}",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Ошибка при добавлении видео: {e}")
        await update.message.reply_text("Сталася помилка при додаванні відео.")

    return ADMIN_MENU

# Функция для отображения списка медиа администратору
async def list_media_items(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str) -> None:
    db_pool = context.application.bot_data.get('db_pool')

    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT id, media_type, file_id FROM media
                """)
                media_items = await cur.fetchall()

        if not media_items:
            await update.message.reply_text("Медіа бібліотека порожня.")
            await show_media_management_menu(update, context)
            return

        message = "*Медіа бібліотека:*\n"
        for media in media_items:
            media_id, media_type, file_id = media
            message += f"{media_id}. Тип: {media_type}, File ID: {file_id}\n"

        action_text = "видаліть"
        await update.message.reply_text(
            f"{message}\nВведіть ID медіа, яке бажаєте {action_text}:",
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data['media_action'] = action
    except Exception as e:
        logger.error(f"Ошибка при получении медиа: {e}")
        await update.message.reply_text("Сталася помилка при отриманні медіа.")

# Функция для удаления медиа
async def delete_media_item(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    action = context.user_data.get('media_action')
    if action != 'delete':
        # Если пользователь ввёл что-то иное или мы не в процессе удаления, игнорируем
        await update.message.reply_text("Невідома команда. Будь ласка, оберіть опцію з меню.")
        return MEDIA_MANAGEMENT

    media_id_str = update.message.text.strip()
    if not media_id_str.isdigit():
        await update.message.reply_text("Будь ласка, введіть коректний ID медіа для видалення:")
        return MEDIA_MANAGEMENT

    media_id = int(media_id_str)
    db_pool = context.application.bot_data.get('db_pool')

    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT media_type, file_id FROM media WHERE id = %s
                """, (media_id,))
                result = await cur.fetchone()
                if not result:
                    await update.message.reply_text("Медіа з таким ID не існує.")
                    return MEDIA_MANAGEMENT

                # Удаляем медиа
                await cur.execute("""DELETE FROM media WHERE id = %s""", (media_id,))
        await update.message.reply_text(
            f"Медіа ID {media_id} видалено успішно.",
            reply_markup=get_admin_menu_keyboard()
        )
        # Сбрасываем действие, чтобы не повторять удаление
        context.user_data.pop('media_action', None)
    except Exception as e:
        logger.error(f"Ошибка при удалении медиа: {e}")
        await update.message.reply_text("Сталася помилка при видаленні медіа.")

    return ADMIN_MENU

# Функция для обработки колбэков удаления медиа через Inline кнопки
async def delete_media_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data
    if data.startswith("delete_media_"):
        media_id = int(data.split("_")[2])
        db_pool = context.application.bot_data.get('db_pool')

        try:
            async with db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("""
                        SELECT media_type, file_id FROM media WHERE id = %s
                    """, (media_id,))
                    result = await cur.fetchone()
                    if not result:
                        await query.edit_message_text("Медіа вже видалено або не існує.")
                        return

                    media_type, file_id = result
                    await cur.execute("""
                        DELETE FROM media WHERE id = %s
                    """, (media_id,))
            await query.edit_message_text("Медіа успішно видалено.")
        except Exception as e:
            logger.error(f"Ошибка при удалении медиа через callback: {e}")
            await query.edit_message_text("Сталася помилка при видаленні медіа.")


async def delete_price_item_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    item_id = update.message.text.strip()
    if item_id.lower() == 'скасувати':
        return await cancel_price_edit(update, context)

    if not item_id.isdigit():
        await update.message.reply_text(
            "Будь ласка, введіть коректний ID позиції або натисніть 'Скасувати'.",
            reply_markup=ReplyKeyboardMarkup([['Скасувати']], resize_keyboard=True, one_time_keyboard=True)
        )
        return PRICE_EDIT_DELETE_ID

    item_id = int(item_id)
    context.user_data['delete_item_id'] = item_id

    # Перевіряємо, чи існує позиція з таким ID
    db_pool = context.application.bot_data.get('db_pool')
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT item_name FROM price_list WHERE id = %s", (item_id,))
                result = await cur.fetchone()
                if not result:
                    await update.message.reply_text(
                        "Позиція з таким ID не існує. Будь ласка, введіть інший ID або натисніть 'Скасувати'.",
                        reply_markup=ReplyKeyboardMarkup([['Скасувати']], resize_keyboard=True, one_time_keyboard=True)
                    )
                    return PRICE_EDIT_DELETE_ID

                item_name = result[0]
                context.user_data['delete_item_name'] = item_name

    except Exception as e:
        logger.error(f"Ошибка при перевірці позиції ID {item_id}: {e}")
        await update.message.reply_text("Сталася помилка при перевірці позиції. Спробуйте пізніше.")
        return PRICE_EDIT_SELECTION

    await update.message.reply_text(
        f"Ви впевнені, що хочете видалити позицію '{item_name}'? Введіть 'Так' для підтвердження або 'Скасувати' для скасування.",
        reply_markup=ReplyKeyboardMarkup([['Так', 'Скасувати']], resize_keyboard=True, one_time_keyboard=True)
    )
    return PRICE_EDIT_DELETE_ID


async def confirm_delete_price_item(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_response = update.message.text.strip().lower()
    user_id = update.effective_user.id

    if user_response == 'так':
        item_id = context.user_data.get('delete_item_id')
        item_name = context.user_data.get('delete_item_name')
        db_pool = context.application.bot_data.get('db_pool')

        try:
            async with db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("DELETE FROM price_list WHERE id = %s", (item_id,))
            await update.message.reply_text(
                f"Позицію '{item_name}' видалено успішно.",
                reply_markup=get_admin_menu_keyboard()
            )
        except Exception as e:
            logger.error(f"Ошибка при видаленні позиції ID {item_id}: {e}")
            await update.message.reply_text(
                "Сталася помилка при видаленні позиції. Спробуйте ще раз.",
                reply_markup=get_admin_menu_keyboard()
            )

        # Очищуємо дані
        context.user_data.pop('delete_item_id', None)
        context.user_data.pop('delete_item_name', None)
        return ADMIN_MENU

    elif user_response == 'скасувати':
        await update.message.reply_text(
            "Операція видалення позиції скасована.",
            reply_markup=get_price_edit_menu_keyboard()
        )
        # Очищуємо дані
        context.user_data.pop('delete_item_id', None)
        context.user_data.pop('delete_item_name', None)
        return PRICE_EDIT_SELECTION

    else:
        await update.message.reply_text(
            "Невідома команда. Введіть 'Так' для підтвердження або 'Скасувати' для скасування.",
            reply_markup=ReplyKeyboardMarkup([['Так', 'Скасувати']], resize_keyboard=True, one_time_keyboard=True)
        )
        return PRICE_EDIT_DELETE_ID

async def back_to_admin_menu_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    logger.info(f"Адмін вибрав 'Назад' від клієнтів.")
    await update.message.reply_text(
        "Виберіть опцію:",
        reply_markup=get_admin_menu_keyboard()
    )
    return ADMIN_MENU

# Основная функция для запуска бота
def main():
    application = ApplicationBuilder().token(TOKEN).post_init(on_startup).post_shutdown(on_shutdown).build()

    # Добавление обработчика ошибок
    application.add_error_handler(error_handler)

    # Conversation handler для різних функцій
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            MENU_SELECTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_selection)
            ],
            APPOINTMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, appointment)
            ],
            LANGUAGE_CHOICE: [
                MessageHandler(filters.Regex(r'^(Українська|Русский|Česky)$'), choose_language),
                # Если пользователь вводит что-то другое:
                MessageHandler(filters.TEXT & ~filters.COMMAND, choose_language)
            ],
            APPOINTMENT_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, select_appointment_date)
            ],
            APPOINTMENT_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, select_appointment_time)
            ],
            CONFIRM_APPOINTMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_appointment)
            ],
            CANCEL_APPOINTMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_cancellation)
            ],
            SURVEY_Q1: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_survey_response)
            ],
            SURVEY_Q2: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_survey_response)
            ],
            SURVEY_Q3: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_survey_response)
            ],
            SURVEY_Q4: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_survey_response)
            ],
            SURVEY_Q5: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_survey_response)
            ],
            SURVEY_Q6: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_survey_response)
            ],
            SURVEY_Q7: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_survey_response)
            ],
            ADMIN_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_menu_selection)
            ],
            SETTINGS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_settings_selection)
            ],
            CHANGE_THRESHOLD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, change_threshold)
            ],
            CHANGE_PERCENTAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, change_percentage)
            ],
            PRICE_EDIT_SELECTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_price_edit_selection)
            ],
            PRICE_EDIT_ADD_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_price_item_name),
                MessageHandler(filters.Regex('^Скасувати$'), cancel_price_edit)
            ],
            PRICE_EDIT_ADD_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_price_item_price),
                MessageHandler(filters.Regex('^Скасувати$'), cancel_price_edit)
            ],
            PRICE_EDIT_EDIT_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_price_item_id),
                MessageHandler(filters.Regex('^Скасувати$'), cancel_price_edit)
            ],
            PRICE_EDIT_EDIT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_price_item_name),
                MessageHandler(filters.Regex('^Скасувати$'), cancel_price_edit)
            ],
            PRICE_EDIT_EDIT_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_price_item_price),
                MessageHandler(filters.Regex('^Скасувати$'), cancel_price_edit)
            ],
            PRICE_EDIT_DELETE_ID: [
                MessageHandler(filters.Regex('^Так$'), confirm_delete_price_item),
                MessageHandler(filters.TEXT & ~filters.COMMAND, delete_price_item_id),
                MessageHandler(filters.Regex('^Скасувати$'), cancel_price_edit)
            ],
            MEDIA_MANAGEMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_media_management_selection),
                # Обработчик для скасування при видаленні медіа
                MessageHandler(filters.Regex('^Скасувати$'), cancel_media_upload),
            ],
            MEDIA_UPLOAD_PHOTO: [
                MessageHandler(filters.PHOTO, add_photo),
                MessageHandler(filters.Regex('^Скасувати$'), cancel_media_upload),
            ],
            MEDIA_UPLOAD_VIDEO: [
                MessageHandler(filters.VIDEO, add_video),
                MessageHandler(filters.Regex('^Скасувати$'), cancel_media_upload),
            ],
            CLIENTS_LIST: [
                CallbackQueryHandler(show_clients_page, pattern=r'^clients_page_\d+$'),
                CallbackQueryHandler(show_client_details, pattern=r'^client_\d+$'),
                MessageHandler(filters.Regex('^Назад$'), back_to_admin_menu_reply),
            ],
            CLIENT_DETAILS: [
                CallbackQueryHandler(back_to_clients_list, pattern=r'^back_to_clients_list$'),
            ],
        },
        fallbacks=[CommandHandler('start', start)],
        allow_reentry=False
    )

    application.add_handler(conv_handler)

    # CallbackQueryHandler для видалення медіа через inline кнопки
    application.add_handler(CallbackQueryHandler(delete_media_callback, pattern=r'^delete_media_\d+$'))

    # Обработчик неизвестных команд
    application.add_handler(MessageHandler(filters.COMMAND, unknown))

    # Здесь вы запускаете периодическое задание на очистку старых записей
    application.job_queue.run_repeating(cleanup_old_appointments, interval=86400, first=0)
    # Запуск бота с polling
    logger.info("Запуск бота.")
    application.run_polling()

# Обработчик ошибок
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.message:
        try:
            await update.message.reply_text("Сталася помилка. Будь ласка, спробуйте пізніше.")
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения об ошибке: {e}")

# Обработчик неизвестных команд
async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    logger.warning(f"Пользователь {user_id} отправил неизвестное сообщение: {update.message.text}")
    await update.message.reply_text(
        "Вибачте, я не розумію цю команду. Будь ласка, використовуйте меню."
    )

# Обработчик выбора в административном меню
# Обработчик выбора в административном меню
# Обробник вибору в адміністративному меню
async def handle_admin_menu_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    admin_selection = update.message.text
    logger.info(f"Адмін вибрав опцію: {admin_selection}")

    lang = context.user_data.get('lang', 'ua')  # Получаем язык пользователя

    if admin_selection == MESSAGES[lang]['admin_menu'][0][0]:  # "📅 Мої заплановані сеанси"
        await show_admin_schedule(update, context)
        return ADMIN_MENU

    elif admin_selection == MESSAGES[lang]['admin_menu'][0][1]:  # "📝 Мої клієнти"
        await show_admin_clients(update, context)
        return CLIENTS_LIST  # Перехід до нового стану

    elif admin_selection == MESSAGES[lang]['admin_menu'][1][0]:  # "💰 Налаштування"
        await show_settings_menu(update, context)
        return SETTINGS

    elif admin_selection == MESSAGES[lang]['admin_menu'][1][1]:  # "📸 Управління медіа"
        await show_media_management_menu(update, context)
        return MEDIA_MANAGEMENT

    elif admin_selection == MESSAGES[lang]['admin_menu'][2][0]:  # "Назад"
        user_id = update.effective_user.id

        await update.message.reply_text(
            "Виберіть опцію:",
            reply_markup=get_main_menu_keyboard(lang, user_id)
        )
        return MENU_SELECTION

    else:
        await update.message.reply_text("Невідома опція. Будь ласка, оберіть ще раз.")
        return ADMIN_MENU





# Функции для опроса, подтверждения записей и т.д. остаются без изменений

# Запуск основной функции
if __name__ == '__main__':
    main()
