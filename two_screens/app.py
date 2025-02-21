import os
import time
import threading
import random
from datetime import datetime
import pymysql
from flask import Flask, request, jsonify, render_template, url_for, redirect, session

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # В реальном проекте используйте переменные окружения

# Конфигурация подключения к MySQL
DATABASE_CONFIG = {
    'host': 'ub469996.mysql.tools',
    'user': 'ub469996_twoscreens',
    'password': '&;NeLfg295',
    'database': 'ub469996_twoscreens',
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}

def get_db_connection():
    """Создаёт и возвращает подключение к MySQL с использованием PyMySQL."""
    try:
        connection = pymysql.connect(**DATABASE_CONFIG)
        return connection
    except Exception as e:
        print(f"Ошибка подключения к MySQL: {e}")
        return None

def init_db():
    """
    Инициализация БД:
      1. Создаём таблицу tasks (если её нет) c полями для agent_name, start_time, pnl, total_fee.
      2. Создаём таблицу trade_logs (если её нет) для хранения лога сделок.
    """
    conn = get_db_connection()
    if not conn:
        print("Не удалось подключиться к БД при инициализации.")
        return
    try:
        cursor = conn.cursor()
        # Создаём таблицу tasks
        create_tasks_query = """
        CREATE TABLE IF NOT EXISTS tasks (
            id INT AUTO_INCREMENT PRIMARY KEY,
            number INT,
            slider_value DECIMAL(10,2),
            period VARCHAR(50),
            status VARCHAR(255),
            agent_name VARCHAR(50),
            start_time DATETIME,
            pnl DECIMAL(10,2) DEFAULT 0,
            total_fee DECIMAL(10,2) DEFAULT 0
        ) ENGINE=InnoDB;
        """
        cursor.execute(create_tasks_query)

        # Создаём таблицу trade_logs
        create_trade_logs_query = """
        CREATE TABLE IF NOT EXISTS trade_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            task_id INT,
            log_time DATETIME,
            symbol VARCHAR(20),
            side VARCHAR(10),
            amount DECIMAL(10,2),
            pnl_change DECIMAL(10,2)
        ) ENGINE=InnoDB;
        """
        cursor.execute(create_trade_logs_query)

        conn.commit()
        cursor.close()
    except Exception as e:
        print("Ошибка при создании таблиц:", e)
    finally:
        conn.close()

init_db()

@app.route("/chart_data", methods=["GET"])
def chart_data():
    """
    Возвращает список всех PnL из таблицы tasks, например [12.5, -1.0, 7.2, ...].
    Или любой другой формат (например, [{x:1,y:12.5}, ...]).
    """
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "DB connection failed"}), 500
    try:
        cursor = conn.cursor()
        # Допустим, хотим получить все PnL из tasks,
        # упорядочим по id (или start_time), как вам удобнее.
        cursor.execute("SELECT pnl FROM tasks ORDER BY id ASC")
        rows = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()

    # Превратим в массив значений
    # rows будет списком словарей [{'pnl': 12.3}, ...]
    pnl_list = []
    for row in rows:
        pnl_value = float(row["pnl"]) if row["pnl"] else 0.0
        pnl_list.append(pnl_value)

    return jsonify(pnl_list)
def generate_agent_name():
    """
    Генерирует псевдослучайное имя агента, например 'Gosha#187654'.
    """
    possible_names = ["Gosha", "Slavik", "Nikolya", "Alexa", "Jenya", "Sergio", "Ivan", "Oleg", "Sasha"]
    name = random.choice(possible_names)
    number = random.randint(10000, 99999)
    return f"{name}#{number}"

def simulate_trading(task_id):
    """
    Бесконечная симуляция (каждые 5 сек), пока статус != "зупинено".
    """
    import random
    from datetime import datetime
    symbols = ["$DOGE", "$XRP", "$HAI", "$SOM", "$BTC", "$ETH"]
    sides = ["buy", "sell"]

    while True:
        # 1. Проверка статуса
        conn = get_db_connection()
        if not conn:
            break
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM tasks WHERE id=%s", (task_id,))
        row = cursor.fetchone()
        if not row or row["status"] == "зупинено":
            cursor.close()
            conn.close()
            break

        # 2. Генерируем случайную сделку
        symbol = random.choice(symbols)
        side = random.choice(sides)
        amount = round(random.uniform(10, 100), 2)
        change_pnl = round(random.uniform(-2.0, 3.0), 2)

        # 3. Запишем в trade_logs
        insert_log_query = """
            INSERT INTO trade_logs (task_id, log_time, symbol, side, amount, pnl_change)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        cursor.execute(insert_log_query, (task_id, datetime.now(), symbol, side, amount, change_pnl))

        # 4. Обновим pnl и fee
        update_tasks_query = """
            UPDATE tasks
            SET pnl = pnl + %s,
                total_fee = total_fee + 0.05
            WHERE id = %s
        """
        cursor.execute(update_tasks_query, (change_pnl, task_id))
        conn.commit()
        cursor.close()
        conn.close()

        # 5. Ждём 5 секунд
        time.sleep(5)

    # Когда цикл заканчивается (30с прошли),
    # Если задача не остановлена, меняем статус на “Результат: ...”
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM tasks WHERE id=%s", (task_id,))
            row = cursor.fetchone()
            if row and row["status"] != "зупинено":
                finish_text = "Результат: агент завершил работу"
                update_query = "UPDATE tasks SET status=%s WHERE id=%s"
                cursor.execute(update_query, (finish_text, task_id))
                conn.commit()
            cursor.close()
        finally:
            conn.close()

@app.route('/')
def home():
    """Если агент запущен, перенаправляем на страницу status, иначе – на страницу input."""
    if session.get('agent_running'):
        agent_id = session.get('agent_id')
        if agent_id:
            return redirect(url_for('status_page', task_id=agent_id))
    return redirect(url_for('input_page'))

@app.route('/input', methods=['GET'])
def input_page():
    if session.get('agent_running'):
        agent_id = session.get('agent_id')
        if agent_id:
            return redirect(url_for('status_page', task_id=agent_id))
    return render_template("input.html")

@app.route('/process', methods=['POST'])
def process_data():
    """
    Принимает JSON:
      { "number": <число>, "slider_value": <значение>, "period": <строка> }
    Записывает в БД, запускает фоновую симуляцию,
    устанавливает флаг и возвращает URL для перехода на /status/<id>.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Немає даних"}), 400

    number = data.get("number")
    slider_value = data.get("slider_value")
    period = data.get("period")
    if number is None or slider_value is None or period is None:
        return jsonify({"error": "Відсутні необхідні поля"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Проблема з підключенням до БД"}), 500

    agent_name = generate_agent_name()
    start_time = datetime.now()
    try:
        cursor = conn.cursor()
        insert_query = """
            INSERT INTO tasks (number, slider_value, period, status, agent_name, start_time)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        cursor.execute(insert_query, (number, slider_value, period, "в обробці", agent_name, start_time))
        task_id = cursor.lastrowid
        conn.commit()
        cursor.close()
    finally:
        conn.close()

    # Запоминаем в сессии
    session['agent_running'] = True
    session['agent_id'] = task_id

    # Запускаем поток симуляции
    thread = threading.Thread(target=simulate_trading, args=(task_id,))
    thread.start()

    return jsonify({"status_url": url_for('status_page', task_id=task_id, _external=True)})

@app.route('/status/<int:task_id>', methods=['GET'])
def status_page(task_id):
    """
    Страница управления. Из templates/status.html подгружается JS,
    который каждые N секунд будет дергать /status_data/<task_id> (JSON)
    для обновления логов, PnL, Uptime, графика и т.д.
    """
    return render_template("status.html", task_id=task_id)

@app.route('/stop/<int:task_id>', methods=['POST'])
def stop_task(task_id):
    """
    Маркируем статус='зупинено', убираем данные из сессии.
    Фоновый поток при следующем цикле проверки увидит “зупинено” и завершится.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            update_query = "UPDATE tasks SET status = %s WHERE id = %s"
            cursor.execute(update_query, ("зупинено", task_id))
            conn.commit()
            cursor.close()
        finally:
            conn.close()
    session.pop('agent_running', None)
    session.pop('agent_id', None)
    return jsonify({"result": "зупинено"})

@app.route('/status_data/<int:task_id>', methods=['GET'])
def status_data(task_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "DB connection failed"}), 500

    try:
        cursor = conn.cursor()
        # Смотрим данные в tasks
        cursor.execute("""
            SELECT status, agent_name, start_time, pnl, total_fee,
                   slider_value, period, number
            FROM tasks
            WHERE id = %s
        """, (task_id,))
        task_row = cursor.fetchone()
        if not task_row:
            cursor.close()
            return jsonify({"error": "Task not found"}), 404

        # Вычислим uptime
        from datetime import datetime
        start_time = task_row["start_time"]
        if start_time is None:
            uptime_str = "N/A"
        else:
            delta = datetime.now() - start_time
            hours, remainder = divmod(int(delta.total_seconds()), 3600)
            minutes, seconds = divmod(remainder, 60)
            uptime_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        # Преобразуем slider_value в текст риска
        risk_map = {
            1.0: "Low",
            2.0: "Mid",
            3.0: "High"
        }
        # slider_value мог быть Decimal или float; приводим к float для словаря
        raw_slider = float(task_row["slider_value"]) if task_row["slider_value"] else 2.0
        risk_text = risk_map.get(raw_slider, "Unknown")

        # Логи (берём последние 20)
        cursor.execute("""
            SELECT log_time, symbol, side, amount, pnl_change
            FROM trade_logs
            WHERE task_id = %s
            ORDER BY log_time DESC
            LIMIT 20
        """, (task_id,))
        logs = cursor.fetchall()

        # Логи -> список
        log_list = []
        for row in logs:
            dt_str = row["log_time"].strftime("%Y-%m-%d %H:%M:%S")
            log_list.append({
                "log_time": dt_str,
                "symbol": row["symbol"],
                "side": row["side"],
                "amount": float(row["amount"]),
                "pnl_change": float(row["pnl_change"])
            })

        # Данные для графика (кумулятивный PnL)
        cursor.execute("""
            SELECT log_time, pnl_change
            FROM trade_logs
            WHERE task_id = %s
            ORDER BY log_time ASC
        """, (task_id,))
        all_trades = cursor.fetchall()

        chart_data = []
        cumulative_pnl = 0.0
        for tr in all_trades:
            cumulative_pnl += float(tr["pnl_change"])
            t_ms = int(tr["log_time"].timestamp() * 1000)
            chart_data.append([t_ms, round(cumulative_pnl, 2)])

        status_value = task_row["status"]
        agent_name = task_row["agent_name"]
        pnl_value = float(task_row["pnl"]) if task_row["pnl"] else 0.0
        fee_value = float(task_row["total_fee"]) if task_row["total_fee"] else 0.0
        period_val = task_row["period"] or "N/A"
        operated_amount = float(task_row["number"]) if task_row["number"] else 0.0

        cursor.close()
        return jsonify({
            "status": status_value,
            "agent_name": agent_name,
            "uptime": uptime_str,
            "pnl": pnl_value,
            "total_fee": fee_value,
            "logs": log_list,
            "chart_data": chart_data,
            # Новые ключи для отображения на фронтенде
            "risk_text": risk_text,
            "period": period_val,
            "operated_amount": operated_amount
        })

    finally:
        conn.close()

if __name__ == '__main__':
    # Запускаем на порту 8080, debug=True для отладки
    app.run(debug=True, port=8080)
