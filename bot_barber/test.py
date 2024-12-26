# main.py

import logging
import os
from datetime import datetime, timedelta
from collections import defaultdict
import math
import aiomysql
from pefile import lang
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

# Імпортуємо функцію перекладу
from utils import tr
from translations import MESSAGES

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

# Включаємо логування
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Завантажуємо перемінні середовища з .env
load_dotenv()

# Завантажуємо конфіденційні дані з перемінних середовища
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
MYSQL_USER = os.getenv('MYSQL_USER')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD')
MYSQL_HOST = os.getenv('MYSQL_HOST', 'localhost')
MYSQL_DB = os.getenv('MYSQL_DB')
ADMIN_CHAT_ID = int(os.getenv('ADMIN_CHAT_ID'))  # ID адміністратора

if not all([TOKEN, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DB, ADMIN_CHAT_ID]):
    logger.error("Необхідно встановити всі перемінні середовища: TELEGRAM_BOT_TOKEN, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DB, ADMIN_CHAT_ID")
    exit(1)

# Створення пулу підключень до бази даних
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

# Функції для створення необхідних таблиць
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
                    user_lang VARCHAR(10) DEFAULT 'ua',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logger.info("Таблиця surveys перевірена/створена.")

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
            logger.info("Таблиця appointments перевірена/створена.")

# Повторюваний код для створення інших таблиць залишаємо без змін
# ...

# Функція ініціалізації бази даних
async def on_startup(application: Application):
    logger.info("Ініціалізація підключення до бази даних.")
    try:
        application.bot_data['db_pool'] = await create_db_pool()
        logger.info("Пул підключень до бази даних створено.")
        db_pool = application.bot_data['db_pool']

        # Створюємо необхідні таблиці
        await create_surveys_table(db_pool)
        await create_appointments_table(db_pool)
        await create_settings_table(db_pool)
        await create_price_list_table(db_pool)
        await create_media_table(db_pool)

    except Exception as e:
        logger.error(f"Помилка при створенні пулу підключень: {e}")
        raise

# Функція закриття пулу підключень при завершенні роботи бота
async def on_shutdown(application: Application):
    logger.info("Закриття пулу підключень до бази даних.")
    db_pool = application.bot_data.get('db_pool')
    if db_pool:
        db_pool.close()
        await db_pool.wait_closed()

# main.py (продовження)

# Функція для отримання клавіатури головного меню
def get_main_menu_keyboard(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get('lang', 'ua')  # За замовчуванням українська
    menu_texts = MESSAGES.get(lang, MESSAGES['ua'])['main_menu']
    keyboard = menu_texts.copy()

    # Додаємо кнопку "Адмін Меню" для адміністратора
    if user_id == ADMIN_CHAT_ID:
        admin_menu_button = MESSAGES.get(lang, MESSAGES['ua']).get('admin_menu_extra_button', "📋 Адмін Меню")
        keyboard.append([admin_menu_button])

    return ReplyKeyboardMarkup(
        keyboard, resize_keyboard=True, one_time_keyboard=False
    )

# Функція для створення адміністративного меню
def get_admin_menu_keyboard(context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get('lang', 'ua')  # За замовчуванням українська
    admin_menu_texts = MESSAGES.get(lang, MESSAGES['ua'])['admin_menu']
    return ReplyKeyboardMarkup(
        admin_menu_texts,
        resize_keyboard=True,
        one_time_keyboard=False
    )

# main.py (продовження)

# Функція для початку взаємодії
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    logger.info(f"Користувач {user_id} викликав /start")

    # Перевіряємо, чи є у user_data вже вибрана мова
    user_lang = context.user_data.get('lang')
    if user_lang:
        # Якщо мова вже вибрана — показуємо основне меню
        await update.message.reply_text(
            tr(context, 'welcome'),
            reply_markup=get_main_menu_keyboard(user_id, context)
        )
        return MENU_SELECTION
    else:
        # Якщо мови ще немає — запитуємо вибір мови
        lang_option_ua = MESSAGES['ua']['language_option_ua']
        lang_option_ru = MESSAGES['ua']['language_option_ru']
        lang_option_cz = MESSAGES['ua']['language_option_cz']
        keyboard = [
            [lang_option_ua, lang_option_ru],
            [lang_option_cz]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(
            tr(context, 'choose_language'),
            reply_markup=reply_markup
        )
        return LANGUAGE_CHOICE

# Обробник вибору мови
async def choose_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_response = update.message.text.strip().lower()
    lang_map = {
        MESSAGES['ua']['language_option_ua'].lower(): "ua",
        MESSAGES['ua']['language_option_ru'].lower(): "ru",
        MESSAGES['ua']['language_option_cz'].lower(): "cz"
    }
    chosen_lang = lang_map.get(user_response)
    if not chosen_lang:
        lang = context.user_data.get('lang', 'ua')
        await update.message.reply_text(
            MESSAGES.get(lang, MESSAGES['ua']).get('invalid_language_selection', "Будь ласка, оберіть коректну мову.")
        )
        return LANGUAGE_CHOICE

    context.user_data['lang'] = chosen_lang

    # Зберігаємо мову у БД:
    db_pool = context.application.bot_data.get('db_pool')
    user_id = update.effective_user.id
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    UPDATE surveys 
                    SET user_lang = %s 
                    WHERE chat_id = %s
                """, (chosen_lang, user_id))

                # Якщо запису немає, створюємо новий
                if cur.rowcount == 0:
                    await cur.execute("""
                        INSERT INTO surveys (chat_id, user_lang) 
                        VALUES (%s, %s)
                    """, (user_id, chosen_lang))
    except Exception as e:
        logger.error(f"Помилка при збереженні мови для користувача {user_id}: {e}")
        await update.message.reply_text(tr(context, 'error_generic'))
        return LANGUAGE_CHOICE

    # Після вибору мови показуємо основне меню
    await update.message.reply_text(
        tr(context, 'language_set'),
        reply_markup=get_main_menu_keyboard(user_id, context)
    )
    return MENU_SELECTION


# main.py (продовження)

# Обробка вибору в головному меню
async def handle_menu_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_selection = update.message.text
    user_id = update.effective_user.id
    lang = context.user_data.get('lang', 'ua')
    logger.info(f"Користувач {user_id} вибрав опцію: {user_selection}")

    if user_selection == 'book_appointment':
        await handle_booking(update, context)
        return APPOINTMENT
    elif user_selection == 'portfolio':
        await portfolio(update, context)
        return MENU_SELECTION
    elif user_selection == 'price':
        await price(update, context)
        return MENU_SELECTION
    elif user_selection == 'my_appointment':
        return await my_appointment(update, context)
    elif user_selection == 'survey':
        await survey_start(update, context)
        return SURVEY_Q1
    elif user_selection == 'admin_menu' and user_id == ADMIN_CHAT_ID:
        await show_admin_menu(update, context)
        return ADMIN_MENU
    else:
        logger.warning(f"Неизвестная команда от пользователя {user_id}: {user_selection}")
        await update.message.reply_text(
            tr(context, 'unknown_command')
        )
        return MENU_SELECTION

# main.py (продовження)

# Функція для обробки запису на стрижку
async def handle_booking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    lang = context.user_data.get('lang', 'ua')
    db_pool = context.application.bot_data.get('db_pool')

    if not db_pool:
        await update.message.reply_text(tr(context, 'error_generic'))
        return MENU_SELECTION

    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Перевіряємо, чи є вже запис у користувача
                await cur.execute("""
                    SELECT appointment_date, TIME_FORMAT(appointment_time, '%%H:%%i')
                    FROM appointments
                    WHERE chat_id = %s AND appointment_date >= CURDATE()
                    ORDER BY appointment_date, appointment_time
                    LIMIT 1
                """, (user_id,))
                result = await cur.fetchone()

                if result:
                    appointment_date, appointment_time = result
                    # У користувача вже є запис
                    keyboard = [
                        [MESSAGES[lang]['cancel_appointment_button'], "Записати ще людину"],
                        [MESSAGES[lang]['back_button']]
                    ]
                    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                    await update.message.reply_text(
                        tr(context, 'existing_appointment').format(date=appointment_date, time=appointment_time),
                        reply_markup=reply_markup
                    )
                    # Зберігаємо флаг для розуміння дії
                    context.user_data['has_appointment'] = True
                    return MENU_SELECTION
                else:
                    # Немає активного запису, переходимо до запису
                    # Перевіряємо, чи користувач заповнив опитування
                    await cur.execute("SELECT full_name, phone_number FROM surveys WHERE chat_id = %s", (user_id,))
                    survey_data = await cur.fetchone()

                    if survey_data and survey_data[0] and survey_data[1]:
                        # Користувач заповнив опитування, пропускаємо питання про ім'я
                        context.user_data['appointment'] = {
                            'full_name': survey_data[0],
                            'is_additional_person': False
                        }
                        await ask_appointment_date(update, context)
                        return APPOINTMENT_DATE
                    else:
                        # Опрос не пройден або немає даних для запису - запитуємо ім'я
                        context.user_data['appointment'] = {'is_additional_person': False}
                        await ask_full_name(update, context)
                        return APPOINTMENT
    except Exception as e:
        logger.error(f"Помилка при перевірці записів користувача {user_id}: {e}")
        await update.message.reply_text(tr(context, 'error_generic'))
        return MENU_SELECTION

# main.py (продовження)

# Функція для запиту повного імені
async def ask_full_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = context.user_data.get('lang', 'ua')
    await update.message.reply_text(
        tr(context, 'enter_full_name'),
        reply_markup=ReplyKeyboardRemove()
    )
    return APPOINTMENT

# Обробка введеного імені та запит дати
async def appointment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    full_name = update.message.text.strip()
    user_id = update.effective_user.id
    lang = context.user_data.get('lang', 'ua')
    logger.info(f"Користувач {user_id} вказав ім'я: {full_name}")
    context.user_data['appointment'] = {'full_name': full_name}

    # Пропонуємо вибрати дату
    await ask_appointment_date(update, context)
    return APPOINTMENT_DATE

# Функція для запиту дати запису
async def ask_appointment_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = context.user_data.get('lang', 'ua')
    now = datetime.now()
    dates = []

    for i in range(0, 14):  # Від сьогодні до 13 днів вперед
        date = now + timedelta(days=i)
        date_str = date.strftime('%Y-%m-%d')
        dates.append([date_str])

    reply_markup = ReplyKeyboardMarkup(dates, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text(
        tr(context, 'choose_appointment_date'),
        reply_markup=reply_markup
    )
    return APPOINTMENT_DATE

# Обробка вибраної дати та запит часу
async def select_appointment_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    selected_date = update.message.text.strip()
    user_id = update.effective_user.id
    lang = context.user_data.get('lang', 'ua')
    logger.info(f"Користувач {user_id} вибрав дату: {selected_date}")

    # Перевіряємо та ініціалізуємо 'appointment'
    if 'appointment' not in context.user_data:
        context.user_data['appointment'] = {}

    context.user_data['appointment']['date'] = selected_date

    # Пропонуємо вибрати час
    await ask_appointment_time(update, context, selected_date)
    return APPOINTMENT_TIME

# Функція для запиту часу запису
async def ask_appointment_time(update: Update, context: ContextTypes.DEFAULT_TYPE, selected_date: str) -> int:
    user_id = update.effective_user.id
    lang = context.user_data.get('lang', 'ua')
    db_pool = context.application.bot_data.get('db_pool')
    if not db_pool:
        await update.message.reply_text(tr(context, 'error_generic'))
        return MENU_SELECTION

    try:
        # Отримуємо список зайнятих часових слотів на обрану дату
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT TIME_FORMAT(appointment_time, '%%H:%%i') FROM appointments
                    WHERE appointment_date = %s
                """, (selected_date,))
                taken_times = [row[0] for row in await cur.fetchall()]

        # Визначаємо робочі години (з 9:00 до 17:00, крок 30 хвилин)
        time_slots = []
        start_time = datetime.strptime('09:00', '%H:%M')
        end_time = datetime.strptime('17:00', '%H:%M')
        delta = timedelta(minutes=30)
        current_time = start_time

        # Перевіряємо, чи обрана дата — сьогодні
        selected_date_obj = datetime.strptime(selected_date, '%Y-%m-%d').date()
        today = datetime.now().date()
        is_today = selected_date_obj == today

        while current_time < end_time:
            time_str = current_time.strftime('%H:%M')

            # Якщо обрана дата — сьогодні, перевіряємо, чи не менше часу залишається 2 години
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
                tr(context, 'no_available_time'),
                reply_markup=ReplyKeyboardRemove()
            )
            await ask_appointment_date(update, context)
            return APPOINTMENT_DATE

        # Очищуємо попередні доступні часи, якщо були
        context.user_data.pop('available_times', None)

        reply_markup = ReplyKeyboardMarkup(time_slots, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(
            tr(context, 'choose_time'),
            reply_markup=reply_markup
        )
        # Зберігаємо доступні часи
        available_times = [slot[0] for slot in time_slots]
        context.user_data['available_times'] = available_times
        return APPOINTMENT_TIME
    except Exception as e:
        logger.error(f"Ошибка при получении доступных времен для даты {selected_date}: {e}")
        await update.message.reply_text("Сталася помилка при отриманні доступних часів. Будь ласка, спробуйте пізніше.")
        return MENU_SELECTION

# Обробка вибраного часу та підтвердження запису
async def select_appointment_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    selected_time = update.message.text.strip()
    user_id = update.effective_user.id
    lang = context.user_data.get('lang', 'ua')
    logger.info(f"Користувач {user_id} вибрав час: {selected_time}")
    available_times = context.user_data.get('available_times', [])

    if selected_time not in available_times:
        await update.message.reply_text(
            tr(context, 'invalid_time_selection'),
            reply_markup=ReplyKeyboardMarkup([available_times], resize_keyboard=True, one_time_keyboard=True)
        )
        return APPOINTMENT_TIME

    context.user_data['appointment']['time'] = selected_time

    # Підтвердження запису
    appointment_info = context.user_data['appointment']
    await update.message.reply_text(
        tr(context, 'confirm_appointment').format(
            full_name=appointment_info['full_name'],
            date=appointment_info['date'],
            time=appointment_info['time']
        ),
        reply_markup=ReplyKeyboardMarkup([['Так', 'Скасувати']], resize_keyboard=True, one_time_keyboard=True)
    )
    return CONFIRM_APPOINTMENT

# main.py (продовження)

# Функція для підтвердження запису та збереження в базі даних
async def confirm_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_response = update.message.text.strip().lower()
    user_id = update.effective_user.id
    lang = context.user_data.get('lang', 'ua')
    db_pool = context.application.bot_data.get('db_pool')

    if user_response == 'так':
        appointment_info = context.user_data['appointment']
        if not db_pool:
            await update.message.reply_text(tr(context, 'error_generic'))
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
            discount_message = tr(context, 'discount_message').format(discount=discount) if discount > 0 else ""
            await update.message.reply_text(
                tr(context, 'appointment_confirmed').format(
                    date=appointment_info['date'],
                    time=appointment_info['time'],
                    discount_message=discount_message
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=get_main_menu_keyboard(user_id, context)
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
                        'reminder_text': tr(context, 'reminder_one_day').format(date=appointment_datetime.strftime('%Y-%m-%d'), time=appointment_datetime.strftime('%H:%M')),
                        'appointment_id': appointment_id
                    }
                )
            if one_hour_before > now:
                job_queue.run_once(
                    send_reminder,
                    when=(one_hour_before - now).total_seconds(),
                    chat_id=user_id,
                    data={
                        'reminder_text': tr(context, 'reminder_one_hour').format(date=appointment_datetime.strftime('%Y-%m-%d'), time=appointment_datetime.strftime('%H:%M')),
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
            # Слот вже зайнятий
            await update.message.reply_text(
                tr(context, 'slot_taken'),
                reply_markup=ReplyKeyboardRemove()
            )
            await ask_appointment_time(update, context, appointment_info['date'])
            return APPOINTMENT_TIME
        except Exception as e:
            logger.error(f"Помилка при збереженні запису: {e}")
            await update.message.reply_text(
                tr(context, 'error_saving_appointment'),
                reply_markup=get_main_menu_keyboard(user_id, context)
            )
        finally:
            context.user_data.pop('appointment', None)
        return MENU_SELECTION

# Функція для відправки нагадувань
async def send_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    chat_id = job.chat_id
    reminder_text = job.data.get('reminder_text')
    appointment_id = job.data.get('appointment_id')
    db_pool = context.application.bot_data.get('db_pool')
    if not db_pool:
        return
    # Перевіряємо, чи існує запис
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT 1 FROM appointments
                WHERE id = %s
            """, (appointment_id,))
            result = await cur.fetchone()
            if result:
                # Запис існує, відправляємо нагадування
                await context.bot.send_message(chat_id=chat_id, text=reminder_text)

# Функція для відправки нагадування через дві тижні
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
        logger.info(f"Нагадування через дві тижні відправлено користувачу {chat_id}.")
    except Exception as e:
        logger.error(f"Помилка при відправці нагадування через дві тижні користувачу {chat_id}: {e}")

# main.py (продовження)

# Функція для відправки портфоліо користувачу
async def portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    lang = context.user_data.get('lang', 'ua')
    logger.info(f"Користувач {user_id} запросив портфоліо.")
    db_pool = context.application.bot_data.get('db_pool')

    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT media_type, file_id FROM media
                """)
                media_items = await cur.fetchall()

        if not media_items:
            await update.message.reply_text(tr(context, 'portfolio_empty'))
            return

        for media in media_items:
            media_type, file_id = media
            if media_type == 'photo':
                await update.message.reply_photo(
                    photo=file_id,
                    caption=MESSAGES.get(lang, MESSAGES['ua']).get('portfolio_caption', 'Ось деякі з моїх робіт! 🎨')
                )
            elif media_type == 'video':
                await update.message.reply_video(
                    video=file_id,
                    caption=MESSAGES.get(lang, MESSAGES['ua']).get('portfolio_video_caption', 'Перегляньте це відео про наші послуги! 📹')
                )
    except Exception as e:
        logger.error(f"Помилка при відправці медіа: {e}")
        await update.message.reply_text(tr(context, 'error_generic'))

# Функція для відправки прайс-листа користувачу
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    lang = context.user_data.get('lang', 'ua')
    logger.info(f"Користувач {user_id} запросив прайс-лист.")
    db_pool = context.application.bot_data.get('db_pool')

    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT item_name, price FROM price_list
                """)
                items = await cur.fetchall()

        if not items:
            await update.message.reply_text(tr(context, 'price_list_empty'))
            return

        price_list = tr(context, 'price_list_header') + "\n"
        for item_name, price in items:
            price_list += f"✂️ {item_name} — {price}₴\n"

        await update.message.reply_text(
            price_list, parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Помилка при отриманні прайс-листа: {e}")
        await update.message.reply_text(tr(context, 'error_generic'))

# Функція для початку опитування
async def survey_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    lang = context.user_data.get('lang', 'ua')
    logger.info(f"Користувач {user_id} розпочав опитування.")
    context.user_data['survey'] = {'current_question': 0, 'answers': []}
    # Відправляємо перше питання з кнопкою 'Повернутися'
    keyboard = [[MESSAGES[lang]['survey_return_button']]]
    reply_markup = ReplyKeyboardMarkup(
        keyboard, resize_keyboard=True, one_time_keyboard=False
    )
    await update.message.reply_text(SURVEY_QUESTIONS[0], reply_markup=reply_markup)
    return SURVEY_Q1

# Функція для обробки відповідей на опитування
async def handle_survey_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    survey = context.user_data.get('survey')
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    lang = context.user_data.get('lang', 'ua')

    if not survey:
        logger.warning(f"Користувач {user_id} спробував відповісти на опитування без його початку.")
        await update.message.reply_text(tr(context, 'start_survey_prompt'))
        return MENU_SELECTION

    user_response = update.message.text.strip()
    logger.info(f"Користувач {user_id} відповів: {user_response}")

    if user_response.lower() == MESSAGES[lang]['survey_return_button'].lower():
        await update.message.reply_text(
            tr(context, 'survey_cancelled'),
            reply_markup=get_main_menu_keyboard(user_id, context)
        )
        # Очищаємо дані опитування
        context.user_data.pop('survey', None)
        return MENU_SELECTION

    # Додаємо відповідь
    survey['answers'].append(user_response)
    current_q = survey['current_question']
    logger.info(f"Користувач {user_id} відповів на питання {current_q + 1}: {user_response}")

    survey['current_question'] += 1

    if survey['current_question'] < len(SURVEY_QUESTIONS):
        # Відправляємо наступне питання з кнопкою 'Повернутися'
        next_question = SURVEY_QUESTIONS[survey['current_question']]
        keyboard = [[MESSAGES[lang]['survey_return_button']]]
        reply_markup = ReplyKeyboardMarkup(
            keyboard, resize_keyboard=True, one_time_keyboard=False
        )
        await update.message.reply_text(next_question, reply_markup=reply_markup)
        # Визначаємо наступний стан
        next_state = SURVEY_Q1 + survey['current_question']
        return next_state
    else:
        # Всі питання задані, зберігаємо дані
        answers = survey['answers']
        logger.info(f"Користувач {user_id} завершив опитування. Зберігаємо дані.")

        # Збереження в базу даних
        try:
            db_pool = context.application.bot_data.get('db_pool')
            if not db_pool:
                raise Exception("Пул підключень до бази даних не ініціалізований.")

            async with db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    # Перевіряємо, чи є запис в surveys
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
                            answers[0],  # Ім'я та прізвище
                            answers[1],  # Номер телефону
                            answers[2],  # Довжина волосся
                            parse_yes_no(answers[3]),  # Чи є борода
                            answers[4],  # Чому обрали мене
                            answers[5],  # Що подобається/не подобається
                            answers[6],  # Пропозиції
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
                            answers[0],  # Ім'я та прізвище
                            answers[1],  # Номер телефону
                            answers[2],  # Довжина волосся
                            parse_yes_no(answers[3]),  # Чи є борода
                            answers[4],  # Чому обрали мене
                            answers[5],  # Що подобається/не подобається
                            answers[6],  # Пропозиції
                        ))
            logger.info(f"Дані опитування користувача {user_id} успішно збережено.")
            await update.message.reply_text(
                tr(context, 'survey_completed'),
                reply_markup=get_main_menu_keyboard(user_id, context)
            )
        except Exception as e:
            logger.error(f"Помилка при збереженні даних опитування для користувача {user_id}: {e}")
            await update.message.reply_text(
                tr(context, 'error_saving_survey')
            )

        # Очищаємо дані опитування
        context.user_data.pop('survey', None)
        return MENU_SELECTION

# Функція для парсингу відповіді на питання про бороду
def parse_yes_no(response: str) -> bool:
    """Парсить відповідь на питання про наявність бороди."""
    yes_responses = ['так', 'є', 'є борода', 'yes', 'y']
    no_responses = ['ні', 'немає бороди', 'no', 'n']
    response_lower = response.lower()
    if response_lower in yes_responses:
        return True
    elif response_lower in no_responses:
        return False
    else:
        return False  # За замовчуванням вважаємо, що бороди немає

# main.py (продовження)

# Функція для перегляду та скасування записів користувача
async def my_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    lang = context.user_data.get('lang', 'ua')
    db_pool = context.application.bot_data.get('db_pool')
    if not db_pool:
        await update.message.reply_text(tr(context, 'error_generic'))
        return MENU_SELECTION

    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Вибираємо всі майбутні записи користувача
                await cur.execute("""
                    SELECT appointment_date, TIME_FORMAT(appointment_time, '%%H:%%i'), id
                    FROM appointments
                    WHERE chat_id = %s AND appointment_date >= CURDATE()
                    ORDER BY appointment_date, appointment_time
                """, (user_id,))
                results = await cur.fetchall()

                if results:
                    # Показуємо всі майбутні записи
                    message = tr(context, 'your_upcoming_appointments') + "\n"
                    for (appointment_date, appointment_time, appointment_id) in results:
                        message += f"- {appointment_date} о {appointment_time} ({tr(context, 'appointment_id_label')}: {appointment_id})\n"
                    message += f"\n{tr(context, 'cancel_or_back')}"

                    # Зберігаємо ID найближчого запису
                    nearest_appointment_id = results[0][2]
                    context.user_data['appointment_id'] = nearest_appointment_id

                    await update.message.reply_text(
                        message,
                        reply_markup=ReplyKeyboardMarkup([[
                            tr(context, 'cancel_appointment_button'),
                            tr(context, 'back_button')
                        ]], resize_keyboard=True)
                    )
                    return CANCEL_APPOINTMENT
                else:
                    await update.message.reply_text(
                        tr(context, 'no_active_appointments'),
                        reply_markup=get_main_menu_keyboard(user_id, context)
                    )
                    return MENU_SELECTION
    except Exception as e:
        logger.error(f"Помилка при отриманні записів користувача {user_id}: {e}")
        await update.message.reply_text(tr(context, 'error_fetching_appointments'))
        return MENU_SELECTION

# Функція для скасування запису
async def handle_cancellation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_response = update.message.text.strip().lower()
    user_id = update.effective_user.id
    lang = context.user_data.get('lang', 'ua')

    if user_response == tr(context, 'cancel_appointment_button').lower():
        # Скасовуємо запис
        db_pool = context.application.bot_data.get('db_pool')
        if not db_pool:
            await update.message.reply_text(tr(context, 'error_generic'))
            return MENU_SELECTION
        try:
            appointment_id = context.user_data.get('appointment_id')
            if not appointment_id:
                await update.message.reply_text(tr(context, 'error_generic'))
                return MENU_SELECTION

            async with db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    # Видаляємо запис
                    await cur.execute("""
                        DELETE FROM appointments
                        WHERE id = %s
                    """, (appointment_id,))
            await update.message.reply_text(
                tr(context, 'appointment_cancelled'),
                reply_markup=get_main_menu_keyboard(user_id, context)
            )
            return MENU_SELECTION
        except Exception as e:
            logger.error(f"Помилка при скасуванні запису користувача {user_id}: {e}")
            await update.message.reply_text(tr(context, 'error_canceling_appointment'))
            return MENU_SELECTION
    elif user_response == tr(context, 'back_button').lower():
        # Повертаємося до меню
        await update.message.reply_text(
            tr(context, 'welcome'),
            reply_markup=get_main_menu_keyboard(user_id, context)
        )
        return MENU_SELECTION
    else:
        # Невідома команда
        await update.message.reply_text(tr(context, 'unknown_command'))
        return MENU_SELECTION

# main.py (продовження)

# Функція для показу адміністративного меню
async def show_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = context.user_data.get('lang', 'ua')
    await update.message.reply_text(
        tr(context, 'admin_menu_welcome'),
        reply_markup=get_admin_menu_keyboard(context)
    )

# Функція для показу розкладу адміністратора
async def show_admin_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = context.user_data.get('lang', 'ua')
    db_pool = context.application.bot_data.get('db_pool')
    if not db_pool:
        await update.message.reply_text(tr(context, 'error_generic'))
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
            await update.message.reply_text(tr(context, 'no_scheduled_sessions'))
            return

        schedule = {}
        for full_name, appointment_date, appointment_time, phone_number, discount in appointments:
            if appointment_date not in schedule:
                schedule[appointment_date] = []
            phone_number = phone_number if phone_number else "N/A"
            schedule[appointment_date].append((full_name, appointment_time, phone_number, discount))

        message = tr(context, 'scheduled_sessions') + "\n"
        for date, sessions in schedule.items():
            message += f"\n*{date}*\n"
            for name, time, phone, disc in sessions:
                message += f"• {time} - {name} (тел: {phone}), Знижка: {disc}%\n"

        await update.message.reply_text(
            message, parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Помилка при отриманні розкладу: {e}")
        await update.message.reply_text(tr(context, 'error_generic'))

# Функція для показу клієнтів адміністратора з пагінацією
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
            await query.edit_message_text(tr(context, 'error_generic'))
        else:
            await update.message.reply_text(tr(context, 'error_generic'))
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
                await query.edit_message_text(tr(context, 'no_clients'))
            else:
                await update.message.reply_text(tr(context, 'no_clients'))

            # Відправляємо клавіатуру з кнопкою "Назад"
            reply_back = ReplyKeyboardMarkup([['Назад']], resize_keyboard=True, one_time_keyboard=True)
            await context.bot.send_message(
                chat_id=chat_id,
                text=tr(context, 'press_back_to_admin_menu'),
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
        message_text, keyboard = generate_clients_page(clients, current_page, total_pages, lang)

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
                tr(context, 'displaying_clients'),
                reply_markup=ReplyKeyboardRemove()
            )
            await update.message.reply_text(
                text=message_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )

        # Виводимо інструкцію тільки якщо клієнти є
        reply_back = ReplyKeyboardMarkup([['Назад']], resize_keyboard=True, one_time_keyboard=True)
        await context.bot.send_message(
            chat_id=chat_id,
            text=tr(context, 'press_back_to_admin_menu'),
            reply_markup=reply_back
        )

        return CLIENTS_LIST

    except Exception as e:
        logger.error(f"Помилка при отриманні клієнтів: {e}")
        if query:
            await query.edit_message_text(tr(context, 'error_fetching_clients'))
        else:
            await update.message.reply_text(tr(context, 'error_fetching_clients'))
        return ConversationHandler.END

# Функція для генерації тексту та клавіатури сторінки клієнтів
def generate_clients_page(clients, page, total_pages, lang):
    start_index = (page - 1) * CLIENTS_PER_PAGE
    end_index = start_index + CLIENTS_PER_PAGE
    page_clients = clients[start_index:end_index]

    message = f"*{tr_by_lang(lang, 'my_clients')} (Сторінка {page} з {total_pages}):*\n"

    keyboard = []

    for client in page_clients:
        chat_id, full_name, phone_number = client
        button_text = f"{full_name} ({phone_number})"
        callback_data = f"client_{chat_id}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])

    # Додавання кнопок пагінації
    pagination_buttons = []
    if page > 1:
        pagination_buttons.append(InlineKeyboardButton(tr_by_lang(lang, 'previous'), callback_data=f"clients_page_{page - 1}"))
    if page < total_pages:
        pagination_buttons.append(InlineKeyboardButton(tr_by_lang(lang, 'next'), callback_data=f"clients_page_{page + 1}"))

    if pagination_buttons:
        keyboard.append(pagination_buttons)

    return message, InlineKeyboardMarkup(keyboard)

# Допоміжна функція для перекладу кнопок пагінації
def tr_by_lang(lang, key):
    return MESSAGES.get(lang, MESSAGES['ua']).get(key, key)

# main.py (продовження)

# Функція для повернення до адміністративного меню
async def back_to_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    lang = context.user_data.get('lang', 'ua')
    await query.answer()
    user_id = query.from_user.id

    # Відправляємо нове повідомлення з адміністративним меню
    await context.bot.send_message(
        chat_id=user_id,
        text=tr(context, 'admin_menu_welcome'),
        reply_markup=get_admin_menu_keyboard(context)
    )

    # Видаляємо старе повідомлення зі списком клієнтів або деталями клієнта
    try:
        await query.message.delete()
    except Exception as e:
        logger.warning(f"Не вдалося видалити старе повідомлення: {e}")

    return ADMIN_MENU

# Функція для показу деталей клієнта
async def show_client_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    lang = context.user_data.get('lang', 'ua')
    await query.answer()

    callback_data = query.data
    _, chat_id_str = callback_data.split('_')
    chat_id = int(chat_id_str)

    clients = context.user_data.get('clients', [])
    client = next((c for c in clients if c[0] == chat_id), None)

    if not client:
        await query.edit_message_text(tr(context, 'client_not_found'))
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
            await query.edit_message_text(tr(context, 'client_details_not_found'))
            return CLIENTS_LIST

        (full_name, phone_number, hair_length, has_beard,
         why_chose_us, likes_dislikes, suggestions, visit_count,
         discount_available, created_at) = details

        message = (
            f"*{tr(context, 'client_details')}*\n"
            f"*{tr(context, 'name')}:* {full_name}\n"
            f"*{tr(context, 'phone')}:* {phone_number}\n"
            f"*{tr(context, 'hair_length')}:* {hair_length}\n"
            f"*{tr(context, 'has_beard')}:* {'Так' if has_beard else 'Ні'}\n"
            f"*{tr(context, 'why_chose_us')}:* {why_chose_us}\n"
            f"*{tr(context, 'likes_dislikes')}:* {likes_dislikes}\n"
            f"*{tr(context, 'suggestions')}:* {suggestions}\n"
            f"*{tr(context, 'visit_count')}:* {visit_count}\n"
            f"*{tr(context, 'discount_available')}:* {'Так' if discount_available else 'Ні'}\n"
            f"*{tr(context, 'created_at')}:* {created_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
        )

        keyboard = [
            [InlineKeyboardButton(tr(context, 'back_to_clients_list'), callback_data="back_to_clients_list")],
            [InlineKeyboardButton(tr(context, 'back_to_admin_menu'), callback_data="back_to_admin_menu_inline")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            text=message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )

        return CLIENT_DETAILS

    except Exception as e:
        logger.error(f"Помилка при отриманні деталей клієнта {chat_id}: {e}")
        await query.edit_message_text(tr(context, 'error_generic'))
        return CLIENTS_LIST

# Функція для повернення до списку клієнтів
async def back_to_clients_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    lang = context.user_data.get('lang', 'ua')
    await query.answer()

    clients = context.user_data.get('clients', [])
    current_page = context.user_data.get('clients_page', 1)
    total_pages = context.user_data.get('total_pages', 1)

    message_text, keyboard = generate_clients_page(clients, current_page, total_pages, lang)

    await query.edit_message_text(
        text=message_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )

    return CLIENTS_LIST

# main.py (продовження)

# Функція для повернення до головного меню
async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    lang = context.user_data.get('lang', 'ua')
    await query.answer()
    user_id = query.from_user.id

    # Відправляємо нове повідомлення з головним меню та видаляємо поточне
    await context.bot.send_message(
        chat_id=user_id,
        text=tr(context, 'welcome'),
        reply_markup=get_main_menu_keyboard(user_id, context)
    )

    # Видаляємо старе повідомлення з клієнтами або деталями клієнта (опціонально)
    try:
        await query.message.delete()
    except Exception as e:
        logger.warning(f"Не вдалося видалити старе повідомлення: {e}")

    return ADMIN_MENU

# Функція для обробки показу певної сторінки клієнтів
async def show_clients_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    lang = context.user_data.get('lang', 'ua')
    await query.answer()

    callback_data = query.data
    _, page_str = callback_data.split('_page_')
    page = int(page_str)

    clients = context.user_data.get('clients', [])
    total_pages = context.user_data.get('total_pages', 1)

    message_text, keyboard = generate_clients_page(clients, page, total_pages, lang)

    await query.edit_message_text(
        text=message_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )

    # Оновлюємо поточну сторінку у контексті
    context.user_data['clients_page'] = page

    return CLIENTS_LIST

# Обробник для повернення до адміністративного меню через Inline кнопки
async def back_to_admin_menu_inline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    lang = context.user_data.get('lang', 'ua')
    await query.answer()
    user_id = query.from_user.id
    await context.bot.send_message(
        chat_id=user_id,
        text=tr(context, 'admin_menu_welcome'),
        reply_markup=get_admin_menu_keyboard(context)
    )
    await query.message.delete()
    return ADMIN_MENU

# Функція для обробки невідомих команд
async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    lang = context.user_data.get('lang', 'ua')
    logger.warning(f"Користувач {user_id} надіслав невідоме повідомлення: {update.message.text}")
    await update.message.reply_text(
        tr(context, 'unknown_command')
    )

# main.py (продовження)

# Функція для створення таблиці налаштувань
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
                logger.info("Налаштування за замовчуванням додано.")
            else:
                # Опціонально: оновлюємо налаштування, якщо потрібно
                await cur.execute("""
                    UPDATE settings
                    SET discount_threshold = 6, discount_percentage = 15.00
                    WHERE id = 1
                """)
                logger.info("Налаштування оновлено до порогу 6 візитів та знижки 15%.")

# Функція для створення таблиці прайс-листа
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
            # Перевіряємо наявність записів
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
                logger.info("Прайс-лист за замовчуванням додано.")

# Функція для створення таблиці медіа
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
            logger.info("Таблиця media перевірена/створена.")

# main.py (продовження)

# Функція для показу меню налаштувань адміністратора
async def show_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = context.user_data.get('lang', 'ua')
    db_pool = context.application.bot_data.get('db_pool')
    if not db_pool:
        await update.message.reply_text(tr(context, 'error_generic'))
        return

    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT discount_threshold, discount_percentage FROM settings WHERE id = 1")
                settings = await cur.fetchone()
                if settings:
                    threshold, percentage = settings
                    message = (
                        f"*{tr(context, 'discount_settings')}*\n"
                        f"• {tr(context, 'discount_threshold')}: {threshold}\n"
                        f"• {tr(context, 'discount_percentage')}: {percentage}%\n\n"
                        f"{tr(context, 'choose_action')}"
                    )
                    keyboard = [
                        [tr(context, 'change_threshold'), tr(context, 'change_percentage')],
                        [tr(context, 'manage_price_list'), tr(context, 'back_button')]
                    ]
                    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
                    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
                else:
                    await update.message.reply_text(tr(context, 'settings_not_found'))
    except Exception as e:
        logger.error(f"Помилка при отриманні налаштувань: {e}")
        await update.message.reply_text(tr(context, 'error_generic'))

# main.py (продовження)

# Функція для обробки вибору дій у налаштуваннях
async def handle_settings_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    selection = update.message.text
    lang = context.user_data.get('lang', 'ua')
    logger.info(f"Адмін вибрав налаштування: {selection}")

    if selection == tr(context, 'change_threshold'):
        await update.message.reply_text(
            tr(context, 'enter_new_threshold'),
            reply_markup=ReplyKeyboardRemove()
        )
        return CHANGE_THRESHOLD
    elif selection == tr(context, 'change_percentage'):
        await update.message.reply_text(
            tr(context, 'enter_new_percentage'),
            reply_markup=ReplyKeyboardRemove()
        )
        return CHANGE_PERCENTAGE
    elif selection == tr(context, 'manage_price_list'):
        await show_price_edit_menu(update, context)
        return PRICE_EDIT_SELECTION
    elif selection == tr(context, 'back_button'):
        await show_admin_menu(update, context)
        return ADMIN_MENU
    else:
        await update.message.reply_text(tr(context, 'unknown_command'))
        return SETTINGS

# Функція для зміни порогу відвідувань для знижки
async def change_threshold(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    new_threshold = update.message.text.strip()
    lang = context.user_data.get('lang', 'ua')

    if not new_threshold.isdigit():
        await update.message.reply_text(
            tr(context, 'invalid_number'),
            reply_markup=ReplyKeyboardMarkup([['Скасувати']], resize_keyboard=True, one_time_keyboard=True)
        )
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
        await update.message.reply_text(
            tr(context, 'threshold_updated').format(threshold=new_threshold),
            reply_markup=get_admin_menu_keyboard(context)
        )
    except Exception as e:
        logger.error(f"Помилка при зміні порогу відвідувань: {e}")
        await update.message.reply_text(tr(context, 'error_generic'))

    return ADMIN_MENU

# Функція для зміни відсотка знижки
async def change_percentage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    new_percentage = update.message.text.strip()
    lang = context.user_data.get('lang', 'ua')

    try:
        new_percentage = float(new_percentage)
        if new_percentage < 0:
            raise ValueError("Відсоток знижки не може бути від'ємним.")
    except ValueError:
        await update.message.reply_text(
            tr(context, 'invalid_percentage'),
            reply_markup=ReplyKeyboardMarkup([['Скасувати']], resize_keyboard=True, one_time_keyboard=True)
        )
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
        await update.message.reply_text(
            tr(context, 'percentage_updated').format(percentage=new_percentage),
            reply_markup=get_admin_menu_keyboard(context)
        )
    except Exception as e:
        logger.error(f"Помилка при зміні відсотка знижки: {e}")
        await update.message.reply_text(tr(context, 'error_generic'))

    return ADMIN_MENU

# Функція для показу меню редагування прайс-листа
async def show_price_edit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = context.user_data.get('lang', 'ua')
    keyboard = [
        [tr(context, 'add_item'), tr(context, 'edit_item')],
        [tr(context, 'delete_item'), tr(context, 'back_button')]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text(
        tr(context, 'price_list_management'),
        reply_markup=reply_markup
    )

# Функція для обробки вибору дій у прайс-листі
async def handle_price_edit_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    selection = update.message.text
    lang = context.user_data.get('lang', 'ua')
    logger.info(f"Адмін вибрав дію прайс-листа: {selection}")

    if selection == tr(context, 'add_item'):
        await update.message.reply_text(
            tr(context, 'enter_new_item_name'),
            reply_markup=ReplyKeyboardRemove()
        )
        return PRICE_EDIT_ADD_NAME
    elif selection == tr(context, 'edit_item'):
        await list_price_items(update, context, action="edit")
        return PRICE_EDIT_EDIT_ID
    elif selection == tr(context, 'delete_item'):
        await list_price_items(update, context, action="delete")
        return PRICE_EDIT_DELETE_ID
    elif selection == tr(context, 'back_button'):
        await show_settings_menu(update, context)
        return SETTINGS
    else:
        await update.message.reply_text(tr(context, 'unknown_command'))
        return PRICE_EDIT_SELECTION

# Функція для списку прайс-листа
async def list_price_items(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str) -> None:
    lang = context.user_data.get('lang', 'ua')
    db_pool = context.application.bot_data.get('db_pool')

    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id, item_name, price FROM price_list")
                items = await cur.fetchall()

        if not items:
            await update.message.reply_text(tr(context, 'price_list_empty'))
            await show_price_edit_menu(update, context)
            return

        message = f"*{tr(context, 'price_list')}*\n"
        for item_id, item_name, price in items:
            message += f"{item_id}. {item_name} — {price}₴\n"

        action_text = tr(context, f'action_{action}')
        await update.message.reply_text(
            f"{message}\n{tr(context, 'enter_item_id_for_action').format(action=action_text)}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=ReplyKeyboardMarkup([['Скасувати']], resize_keyboard=True, one_time_keyboard=True)
        )
        context.user_data['price_action'] = action
    except Exception as e:
        logger.error(f"Помилка при отриманні прайс-листа: {e}")
        await update.message.reply_text(tr(context, 'error_generic'))

# main.py (продовження)

# Функція для додавання нової позиції в прайс-лист
async def add_price_item_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    item_name = update.message.text.strip()
    lang = context.user_data.get('lang', 'ua')

    if item_name.lower() == tr(context, 'cancel').lower():
        return await cancel_price_edit(update, context)

    if not item_name:
        await update.message.reply_text(
            tr(context, 'empty_item_name'),
            reply_markup=ReplyKeyboardMarkup([['Скасувати']], resize_keyboard=True, one_time_keyboard=True)
        )
        return PRICE_EDIT_ADD_NAME

    context.user_data['new_item_name'] = item_name
    await update.message.reply_text(
        tr(context, 'enter_item_price'),
        reply_markup=ReplyKeyboardMarkup([['Скасувати']], resize_keyboard=True, one_time_keyboard=True)
    )
    return PRICE_EDIT_ADD_PRICE

# Функція для обробки ціни нової позиції
async def add_price_item_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    price_text = update.message.text.strip()
    lang = context.user_data.get('lang', 'ua')

    if price_text.lower() == tr(context, 'cancel').lower():
        return await cancel_price_edit(update, context)

    try:
        price = float(price_text)
        if price < 0:
            raise ValueError("Ціна не може бути від'ємною.")
    except ValueError:
        await update.message.reply_text(
            tr(context, 'invalid_price'),
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
            tr(context, 'item_added_successfully').format(item_name=item_name, price=price),
            reply_markup=get_admin_menu_keyboard(context)
        )
    except Exception as e:
        logger.error(f"Помилка при додаванні позиції: {e}")
        await update.message.reply_text(tr(context, 'error_generic'))

    context.user_data.pop('new_item_name', None)
    return ADMIN_MENU

# Функція для скасування операції редагування прайс-листа
async def cancel_price_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = context.user_data.get('lang', 'ua')
    await update.message.reply_text(
        tr(context, 'operation_cancelled'),
        reply_markup=get_admin_menu_keyboard(context)
    )
    # Очищаємо всі пов'язані дані
    keys_to_remove = [
        'new_item_name', 'edit_item_id', 'current_name', 'current_price',
        'delete_item_id', 'delete_item_name'
    ]
    for key in keys_to_remove:
        context.user_data.pop(key, None)
    return PRICE_EDIT_SELECTION

# Функція для обробки ID для редагування позиції
async def edit_price_item_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    item_id = update.message.text.strip()
    lang = context.user_data.get('lang', 'ua')

    if item_id.lower() == tr(context, 'cancel').lower():
        return await cancel_price_edit(update, context)

    if not item_id.isdigit():
        await update.message.reply_text(
            tr(context, 'invalid_item_id'),
            reply_markup=ReplyKeyboardMarkup([['Скасувати']], resize_keyboard=True, one_time_keyboard=True)
        )
        return PRICE_EDIT_EDIT_ID

    item_id = int(item_id)
    context.user_data['edit_item_id'] = item_id

    db_pool = context.application.bot_data.get('db_pool')
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT item_name, price FROM price_list WHERE id = %s", (item_id,))
                result = await cur.fetchone()
                if not result:
                    await update.message.reply_text(
                        tr(context, 'item_not_found'),
                        reply_markup=ReplyKeyboardMarkup([['Скасувати']], resize_keyboard=True, one_time_keyboard=True)
                    )
                    return PRICE_EDIT_EDIT_ID

                current_name, current_price = result
                context.user_data['current_name'] = current_name
                context.user_data['current_price'] = current_price

    except Exception as e:
        logger.error(f"Помилка при перевірці позиції ID {item_id}: {e}")
        await update.message.reply_text(tr(context, 'error_generic'))
        return PRICE_EDIT_SELECTION

    await update.message.reply_text(
        tr(context, 'enter_new_item_name').format(current_name=current_name),
        reply_markup=ReplyKeyboardRemove()
    )
    return PRICE_EDIT_EDIT_NAME

# Функція для обробки нового імені позиції
async def edit_price_item_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    new_name = update.message.text.strip()
    lang = context.user_data.get('lang', 'ua')

    if new_name.lower() == tr(context, 'cancel').lower():
        return await cancel_price_edit(update, context)

    if not new_name:
        await update.message.reply_text(
            tr(context, 'empty_item_name'),
            reply_markup=ReplyKeyboardMarkup([['Скасувати']], resize_keyboard=True, one_time_keyboard=True)
        )
        return PRICE_EDIT_EDIT_NAME

    context.user_data['new_item_name'] = new_name
    await update.message.reply_text(
        tr(context, 'enter_new_item_price'),
        reply_markup=ReplyKeyboardMarkup([['Скасувати']], resize_keyboard=True, one_time_keyboard=True)
    )
    return PRICE_EDIT_EDIT_PRICE

# Функція для обробки нової ціни позиції
async def edit_price_item_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    price_text = update.message.text.strip()
    lang = context.user_data.get('lang', 'ua')

    if price_text.lower() == tr(context, 'cancel').lower():
        return await cancel_price_edit(update, context)

    try:
        new_price = float(price_text)
        if new_price < 0:
            raise ValueError("Ціна не може бути від'ємною.")
    except ValueError:
        await update.message.reply_text(
            tr(context, 'invalid_price'),
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
            tr(context, 'item_updated_successfully').format(item_id=item_id),
            reply_markup=get_admin_menu_keyboard(context)
        )
    except Exception as e:
        logger.error(f"Помилка при оновленні позиції ID {item_id}: {e}")
        await update.message.reply_text(tr(context, 'error_generic'))

    # Очищаємо дані
    context.user_data.pop('edit_item_id', None)
    context.user_data.pop('new_item_name', None)
    context.user_data.pop('current_name', None)
    context.user_data.pop('current_price', None)

    return ADMIN_MENU

# Функція для видалення позиції прайс-листа
async def delete_price_item_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    item_id = update.message.text.strip()
    lang = context.user_data.get('lang', 'ua')

    if item_id.lower() == tr(context, 'cancel').lower():
        return await cancel_price_edit(update, context)

    if not item_id.isdigit():
        await update.message.reply_text(
            tr(context, 'invalid_item_id'),
            reply_markup=ReplyKeyboardMarkup([['Скасувати']], resize_keyboard=True, one_time_keyboard=True)
        )
        return PRICE_EDIT_DELETE_ID

    item_id = int(item_id)
    context.user_data['delete_item_id'] = item_id

    db_pool = context.application.bot_data.get('db_pool')
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT item_name FROM price_list WHERE id = %s", (item_id,))
                result = await cur.fetchone()
                if not result:
                    await update.message.reply_text(
                        tr(context, 'item_not_found'),
                        reply_markup=ReplyKeyboardMarkup([['Скасувати']], resize_keyboard=True, one_time_keyboard=True)
                    )
                    return PRICE_EDIT_DELETE_ID

                item_name = result[0]
                context.user_data['delete_item_name'] = item_name

    except Exception as e:
        logger.error(f"Помилка при перевірці позиції ID {item_id}: {e}")
        await update.message.reply_text(tr(context, 'error_generic'))
        return PRICE_EDIT_SELECTION

    await update.message.reply_text(
        tr(context, 'confirm_delete_item').format(item_name=item_name),
        reply_markup=ReplyKeyboardMarkup([['Так', 'Скасувати']], resize_keyboard=True, one_time_keyboard=True)
    )
    return PRICE_EDIT_DELETE_ID

# Функція для підтвердження видалення позиції
async def confirm_delete_price_item(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_response = update.message.text.strip().lower()
    user_id = update.effective_user.id
    lang = context.user_data.get('lang', 'ua')

    if user_response == tr(context, 'confirm_yes').lower():
        item_id = context.user_data.get('delete_item_id')
        item_name = context.user_data.get('delete_item_name')
        db_pool = context.application.bot_data.get('db_pool')

        try:
            async with db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("DELETE FROM price_list WHERE id = %s", (item_id,))
            await update.message.reply_text(
                tr(context, 'item_deleted_successfully').format(item_name=item_name),
                reply_markup=get_admin_menu_keyboard(context)
            )
        except Exception as e:
            logger.error(f"Помилка при видаленні позиції ID {item_id}: {e}")
            await update.message.reply_text(tr(context, 'error_generic'))

        # Очищаємо дані
        context.user_data.pop('delete_item_id', None)
        context.user_data.pop('delete_item_name', None)
        return ADMIN_MENU

    elif user_response == tr(context, 'confirm_cancel').lower():
        await update.message.reply_text(
            tr(context, 'delete_operation_cancelled'),
            reply_markup=get_price_edit_menu_keyboard(lang)
        )
        # Очищаємо дані
        context.user_data.pop('delete_item_id', None)
        context.user_data.pop('delete_item_name', None)
        return PRICE_EDIT_SELECTION
    else:
        await update.message.reply_text(
            tr(context, 'invalid_confirmation_response'),
            reply_markup=ReplyKeyboardMarkup([['Так', 'Скасувати']], resize_keyboard=True, one_time_keyboard=True)
        )
        return PRICE_EDIT_DELETE_ID

def get_price_edit_menu_keyboard(lang):
    keyboard = [
        [MESSAGES[lang]['add_item'], MESSAGES[lang]['edit_item']],
        [MESSAGES[lang]['delete_item'], MESSAGES[lang]['back_button']]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

# Функція для управління медіа
async def show_media_management_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = context.user_data.get('lang', 'ua')
    keyboard = [
        [tr(context, 'add_photo'), tr(context, 'add_video')],
        [tr(context, 'delete_media'), tr(context, 'back_button')]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text(
        tr(context, 'media_management'),
        reply_markup=reply_markup
    )

# Функція для обробки вибору дій у медіа
async def handle_media_management_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    selection = update.message.text
    lang = context.user_data.get('lang', 'ua')
    logger.info(f"Адмін вибрав дію медіа: {selection}")

    if selection == tr(context, 'add_photo'):
        keyboard = [['Скасувати']]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(
            tr(context, 'send_photo_to_add'),
            reply_markup=reply_markup
        )
        return MEDIA_UPLOAD_PHOTO
    elif selection == tr(context, 'add_video'):
        keyboard = [['Скасувати']]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(
            tr(context, 'send_video_to_add'),
            reply_markup=reply_markup
        )
        return MEDIA_UPLOAD_VIDEO
    elif selection == tr(context, 'delete_media'):
        await list_media_items(update, context, action="delete")
        return MEDIA_MANAGEMENT
    elif selection == tr(context, 'back_button'):
        await show_admin_menu(update, context)
        return ADMIN_MENU
    else:
        await update.message.reply_text(tr(context, 'unknown_command'))
        return MEDIA_MANAGEMENT

# Функція для додавання фото
async def add_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message.photo:
        await update.message.reply_text(tr(context, 'invalid_photo'))
        return MEDIA_UPLOAD_PHOTO

    photo = update.message.photo[-1]  # Отримуємо найкращу якість
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
        await update.message.reply_text(
            tr(context, 'photo_added_successfully'),
            reply_markup=get_admin_menu_keyboard(context)
        )

        # Відправляємо повідомлення адміністратору з Inline кнопкою для видалення
        keyboard = [
            [InlineKeyboardButton(tr(context, 'delete'), callback_data=f"delete_media_{media_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"{tr(context, 'new_photo_added')} ID: {media_id}",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Помилка при додаванні фото: {e}")
        await update.message.reply_text(tr(context, 'error_generic'))

    return ADMIN_MENU

# Функція для додавання відео
async def add_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message.video:
        await update.message.reply_text(tr(context, 'invalid_video'))
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
        await update.message.reply_text(
            tr(context, 'video_added_successfully'),
            reply_markup=get_admin_menu_keyboard(context)
        )

        # Відправляємо повідомлення адміністратору з Inline кнопкою для видалення
        keyboard = [
            [InlineKeyboardButton(tr(context, 'delete'), callback_data=f"delete_media_{media_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"{tr(context, 'new_video_added')} ID: {media_id}",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Помилка при додаванні відео: {e}")
        await update.message.reply_text(tr(context, 'error_generic'))

    return ADMIN_MENU

# Функція для списку медіа
async def list_media_items(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str) -> None:
    lang = context.user_data.get('lang', 'ua')
    db_pool = context.application.bot_data.get('db_pool')

    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT id, media_type, file_id FROM media
                """)
                media_items = await cur.fetchall()

        if not media_items:
            await update.message.reply_text(tr(context, 'media_library_empty'))
            await show_media_management_menu(update, context)
            return

        message = f"*{tr(context, 'media_library')}*\n"
        for media in media_items:
            media_id, media_type, file_id = media
            message += f"{media_id}. Тип: {media_type}, File ID: {file_id}\n"

        action_text = tr(context, f'action_{action}')
        await update.message.reply_text(
            f"{message}\n{tr(context, 'enter_media_id_for_action').format(action=action_text)}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=ReplyKeyboardMarkup([['Скасувати']], resize_keyboard=True, one_time_keyboard=True)
        )
        context.user_data['media_action'] = action
    except Exception as e:
        logger.error(f"Помилка при отриманні медіа: {e}")
        await update.message.reply_text(tr(context, 'error_generic'))

# Функція для видалення медіа
async def delete_media_item(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = context.user_data.get('lang', 'ua')
    action = context.user_data.get('media_action')

    if action != 'delete':
        await update.message.reply_text(tr(context, 'unknown_command'))
        return MEDIA_MANAGEMENT

    media_id_str = update.message.text.strip()
    if not media_id_str.isdigit():
        await update.message.reply_text(
            tr(context, 'invalid_media_id'),
            reply_markup=ReplyKeyboardMarkup([['Скасувати']], resize_keyboard=True, one_time_keyboard=True)
        )
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
                    await update.message.reply_text(tr(context, 'media_not_found'))
                    return MEDIA_MANAGEMENT

                # Видаляємо медіа
                await cur.execute("DELETE FROM media WHERE id = %s", (media_id,))
        await update.message.reply_text(
            tr(context, 'media_deleted_successfully').format(media_id=media_id),
            reply_markup=get_admin_menu_keyboard(context)
        )
    except Exception as e:
        logger.error(f"Помилка при видаленні медіа: {e}")
        await update.message.reply_text(tr(context, 'error_generic'))

    return ADMIN_MENU

# main.py (продовження)

# Обробник колбеків для видалення медіа через Inline кнопки
async def delete_media_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    lang = context.user_data.get('lang', 'ua')
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
                        await query.edit_message_text(tr(context, 'media_already_deleted'))
                        return

                    media_type, file_id = result
                    await cur.execute("DELETE FROM media WHERE id = %s", (media_id,))
            await query.edit_message_text(tr(context, 'media_deleted_successfully').format(media_id=media_id))
        except Exception as e:
            logger.error(f"Помилка при видаленні медіа через callback: {e}")
            await query.edit_message_text(tr(context, 'error_generic'))
# Функція для обробки вибору в адміністративному меню
async def handle_admin_menu_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    admin_selection = update.message.text
    lang = context.user_data.get('lang', 'ua')
    logger.info(f"Адмін вибрав опцію: {admin_selection}")

    if admin_selection == tr(context, 'show_schedule'):
        await show_admin_schedule(update, context)
        return ADMIN_MENU
    elif admin_selection == tr(context, 'show_clients'):
        await show_admin_clients(update, context)
        return CLIENTS_LIST
    elif admin_selection == tr(context, 'settings'):
        await show_settings_menu(update, context)
        return SETTINGS
    elif admin_selection == tr(context, 'media_management'):
        await show_media_management_menu(update, context)
        return MEDIA_MANAGEMENT
    elif admin_selection == tr(context, 'back_button'):
        await show_admin_menu(update, context)
        return ADMIN_MENU
    else:
        await update.message.reply_text(tr(context, 'unknown_command'))
        return ADMIN_MENU

# main.py (продовження)

# Основна функція для запуску бота
def main():
    application = ApplicationBuilder().token(TOKEN).post_init(on_startup).post_shutdown(on_shutdown).build()

    # Додавання обробника помилок
    application.add_error_handler(error_handler)

    # Conversation handler для різних функцій
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            LANGUAGE_CHOICE: [
                MessageHandler(filters.Regex(r'^(Українська|Русский|Česky)$'), choose_language),
                # Якщо користувач вводить щось інше:
                MessageHandler(filters.TEXT & ~filters.COMMAND, choose_language)
            ],
            MENU_SELECTION: [
                MessageHandler(filters.Regex(
                    r'^(' + '|'.join([
                        MESSAGES['ua']['main_menu'][0][0],  # "✂️ Записатися на стрижку"
                        MESSAGES['ua']['main_menu'][0][1],  # "👨‍🔧 Ознайомитися з майстром"
                        MESSAGES['ua']['main_menu'][1][0],  # "💲 Прайс"
                        MESSAGES['ua']['main_menu'][1][1],  # "📅 Мій запис"
                        MESSAGES['ua']['main_menu'][2][0],  # "📝 Пройти опитування - отримати знижку"
                        MESSAGES['ua'].get('admin_menu_extra_button', "📋 Адмін Меню")  # "📋 Адмін Меню"
                    ]) + r')$'
                ), handle_menu_selection)
            ],
            APPOINTMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, appointment)
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
            # Додайте обробники для SURVEY_Q2 - SURVEY_Q7 аналогічно
            ADMIN_MENU: [
                MessageHandler(filters.Regex(
                    r'^(' + '|'.join([item for sublist in MESSAGES['ua']['admin_menu'] for item in sublist]) + r')$'
                ), handle_admin_menu_selection)
            ],
            SETTINGS: [
                MessageHandler(filters.Regex(
                    r'^(change_threshold|change_percentage|manage_price_list|back)$'
                ), handle_settings_selection)
            ],
            PRICE_EDIT_SELECTION: [
                MessageHandler(filters.Regex(
                    r'^(add_item|edit_item|delete_item|back)$'
                ), handle_price_edit_selection)
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
                MessageHandler(filters.Regex('^(так|скасувати)$'), confirm_delete_price_item),
                MessageHandler(filters.TEXT & ~filters.COMMAND, delete_price_item_id)
            ],
            MEDIA_MANAGEMENT: [
                MessageHandler(filters.Regex(
                    r'^(add_photo|add_video|delete_media|back)$'
                ), handle_media_management_selection),
                # Обробник для скасування при видаленні медіа
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

    # CallbackQueryHandler для видалення медіа через Inline кнопки
    application.add_handler(CallbackQueryHandler(delete_media_callback, pattern=r'^delete_media_\d+$'))

    # Обробник невідомих команд
    application.add_handler(MessageHandler(filters.COMMAND, unknown))

    # Запуск бота з polling
    logger.info("Запуск бота.")
    application.run_polling()

async def cancel_media_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    await update.message.reply_text(
        tr(context, 'operation_cancelled'),
        reply_markup=get_admin_menu_keyboard(context)
    )
    # Очищення пов'язаних даних, якщо необхідно
    context.user_data.pop('media_upload', None)
    return MEDIA_MANAGEMENT

async def back_to_admin_menu_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    await update.message.reply_text(
        tr(context, 'admin_menu_welcome'),
        reply_markup=get_admin_menu_keyboard(context)
    )
    return ADMIN_MENU

# Обробник помилок
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.message:
        try:
            await update.message.reply_text(tr(context, 'error_generic'))
        except Exception as e:
            logger.error(f"Помилка при відправці повідомлення про помилку: {e}")

# Функція для обробки невідомих повідомлен
# Функція для обробки вибору в адміністративному меню
async def handle_admin_menu_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    admin_selection = update.message.text
    lang = context.user_data.get('lang', 'ua')
    logger.info(f"Адмін вибрав опцію: {admin_selection}")

    if admin_selection == tr(context, 'show_schedule'):
        await show_admin_schedule(update, context)
        return ADMIN_MENU
    elif admin_selection == tr(context, 'show_clients'):
        await show_admin_clients(update, context)
        return CLIENTS_LIST
    elif admin_selection == tr(context, 'settings'):
        await show_settings_menu(update, context)
        return SETTINGS
    elif admin_selection == tr(context, 'media_management'):
        await show_media_management_menu(update, context)
        return MEDIA_MANAGEMENT
    elif admin_selection == tr(context, 'back_button'):
        await show_admin_menu(update, context)
        return ADMIN_MENU
    else:
        await update.message.reply_text(tr(context, 'unknown_command'))
        return ADMIN_MENU

# Запуск основної функції
if __name__ == '__main__':
    main()
