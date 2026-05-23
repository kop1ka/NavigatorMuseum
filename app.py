"""
Flask приложение для управления мультимедийным контентом
с парсером FTP-каталога и возможностью сохранения постоянных элементов
С системой авторизации и защиты

Структура проекта:
- app.py: Основной файл приложения (маршруты, контроллеры)
- config/: Конфигурация приложения
    - settings.py: Все настройки и константы приложения
- utils/: Утилиты и вспомогательные функции
    - data_utils.py: Работа с данными (загрузка/сохранение JSON)
    - parser_utils.py: Парсинг FTP-каталога
    - auth_utils.py: Аутентификация и пользователи
    - catalog_utils.py: Работа с каталогом (поиск, обновление, удаление)
"""

import os
import json
import re
import threading
import warnings
import requests
import urllib3
from datetime import datetime, timedelta
from urllib.parse import unquote, urlparse
from flask import Flask, render_template_string, request, jsonify, send_from_directory, redirect, url_for, session, flash, Response, make_response
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Подавление SSL-предупреждений при использовании verify=False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings('ignore', category=urllib3.exceptions.InsecureRequestWarning)

# Импорт конфигурации из модуля settings
from config.settings import (
    DATA_DIR, CATALOG_FILE, PERMANENT_FILE, USERS_FILE, PARSER_IMAGES_FILE, SECRET_KEY,
    FTP_BASE_URL, PARSER_MAX_DEPTH, PARSER_TIMEOUT,
    RATELIMIT_STORAGE_URI, RATELIMIT_DEFAULT, RATELIMIT_LOGIN, RATELIMIT_ENABLED,
    LOGIN_VIEW, LOGIN_MESSAGE, SESSION_PROTECTION
)

# Директория для проектов
PROJECTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'projects')

# Словарь для хранения информации о проектах Flask
project_flask_info = {}

# Импорт утилит для работы с данными, парсингом, аутентификацией и каталогом
from utils.data_utils import (
    ensure_data_dir, load_json_file, save_json_file, get_current_timestamp, get_full_timestamp,
    load_users, save_users, load_catalog, save_catalog, load_permanent_items, save_permanent_items
)
from utils.parser_utils import extract_items_from_html, parse_folder, ERROR_LOG_FILE
from utils.auth_utils import User, hash_password, verify_password, admin_required_decorator
from utils.catalog_utils import (
    get_item_path, mark_permanent_recursive, merge_with_permanent,
    find_item_by_path, delete_item_by_path, update_item_by_path
)
from utils.audit_utils import (
    audit_error, audit_upload_success, audit_web_resource, audit_filesystem_read,
    audit_catalog_item_open, load_audit_logs, clear_audit_logs, AuditEventType
)

# Инициализация Flask приложения
# static_folder='.' указывает, что статические файлы находятся в корневой директории
# static_url_path='' позволяет обращаться к файлам напрямую по имени
app = Flask(__name__, static_folder='.', static_url_path='')
app.secret_key = SECRET_KEY  # Использование секретного ключа из конфига для сессий

# Настройка для работы за обратным прокси (nginx, Apache и т.д.)
# Позволяет приложению работать в поддиректории (например, /navigator/)
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_prefix=1)

# Middleware для обработки префикса пути (например, /navigator/)
class PathPrefixMiddleware:
    """
    Middleware для удаления префикса пути перед обработкой запроса Flask.
    Позволяет приложению работать в поддиректории без изменения маршрутов.
    Работает только если префикс ещё не был установлен nginx (SCRIPT_NAME пустой).
    
    ВАЖНО: Этот middleware удаляет префикс /navigator из PATH_INFO, поэтому
    маршруты в Flask должны быть объявлены БЕЗ префикса /navigator.
    Например: @app.route('/projects/...'), а НЕ @app.route('/navigator/projects/...')
    """
    def __init__(self, app, prefix):
        self.app = app
        self.prefix = prefix.rstrip("/")

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")
        script_name = environ.get("SCRIPT_NAME", "")

        # Применяем префикс только если SCRIPT_NAME ещё не установлен nginx
        # и путь начинается с нашего префикса
        if not script_name and path.startswith(self.prefix):
            # Удаляем префикс из PATH_INFO
            environ["PATH_INFO"] = path[len(self.prefix):] or "/"
            # Добавляем префикс к SCRIPT_NAME для правильной работы url_for
            environ["SCRIPT_NAME"] = self.prefix

        return self.app(environ, start_response)

app.wsgi_app = PathPrefixMiddleware(app.wsgi_app, '/navigator')

# Глобальная переменная для хранения префикса пути
URL_PREFIX = '/navigator'

# Настройка APPLICATION_ROOT для корректной работы url_for с префиксом
app.config['APPLICATION_ROOT'] = '/navigator'

# Настройка CORS заголовков для всех ответов (необходимо для работы на render.com и других хостингах)
@app.after_request
def add_cors_headers(response):
    """Добавляет CORS заголовки для поддержки跨源 запросов"""
    # Разрешаем запросы с любых источников (можно ограничить при необходимости)
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-CSRFToken'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    
    # Добавляем правильные MIME-типы для статических файлов
    if response.headers.get('Content-Type', '').startswith('text/plain') or not response.headers.get('Content-Type'):
        if request.path.endswith('.css'):
            response.headers['Content-Type'] = 'text/css; charset=utf-8'
        elif request.path.endswith('.js'):
            response.headers['Content-Type'] = 'application/javascript; charset=utf-8'
        elif request.path.endswith('.png'):
            response.headers['Content-Type'] = 'image/png'
        elif request.path.endswith('.jpg') or request.path.endswith('.jpeg'):
            response.headers['Content-Type'] = 'image/jpeg'
        elif request.path.endswith('.gif'):
            response.headers['Content-Type'] = 'image/gif'
        elif request.path.endswith('.webp'):
            response.headers['Content-Type'] = 'image/webp'
        elif request.path.endswith('.svg'):
            response.headers['Content-Type'] = 'image/svg+xml'
        elif request.path.endswith('.html'):
            response.headers['Content-Type'] = 'text/html; charset=utf-8'
    
    return response

# Инициализация расширений Flask
csrf = CSRFProtect(app)  # Защита от CSRF атак

# Отключаем rate limiting для статических файлов (изображения, CSS, JS) и API прокси
def limiter_enabled():
    """Проверка, включен ли rate limiting для текущего запроса"""
    # Не применяем rate limiting к статическим файлам и proxy-image endpoint
    if request.path.startswith('/page/') or request.path.startswith('/static/') or request.path.startswith('/projects/') or request.path.startswith('/css/') or request.path.startswith('/js/') or request.path == '/api/proxy-image':
        return False
    return RATELIMIT_ENABLED

limiter = Limiter(
    key_func=get_remote_address,  # Ограничение по IP адресу
    app=app,
    default_limits=RATELIMIT_DEFAULT,  # Ограничения по умолчанию из конфига
    storage_uri=RATELIMIT_STORAGE_URI,  # Хранилище счётчиков в памяти
    enabled=limiter_enabled  # Динамическое включение/отключение
)
login_manager = LoginManager()
login_manager.init_app(app)

# -------------------------------------------------------------------
# ИСПРАВЛЕНИЕ 1: Настройка login_manager для работы с префиксом
# -------------------------------------------------------------------
# Устанавливаем login_view как строку, а не функцию
# Flask-Login требует строковое значение для login_view
login_manager.login_view = 'login'
login_manager.login_message = LOGIN_MESSAGE  # Сообщение при перенаправлении
login_manager.session_protection = SESSION_PROTECTION  # Уровень защиты сессии

# Переопределяем метод login_url для корректной работы с префиксом пути
def custom_login_url(next=None):
    """Возвращает URL страницы входа с учётом префикса (SCRIPT_NAME)."""
    # Явно добавляем префикс /navigator к URL входа
    base_url = URL_PREFIX + '/login'

    if next:
        # Проверяем, содержит ли next уже префикс /navigator
        if not next.startswith(URL_PREFIX):
            # Если next начинается с / но не содержит префикс, добавляем его
            if next.startswith('/'):
                next = URL_PREFIX + next
            else:
                # Если next относительный путь, добавляем префикс и слэш
                next = URL_PREFIX + '/' + next.lstrip('/')
        return base_url + '?next=' + next
    return base_url

login_manager.login_url = custom_login_url

@login_manager.unauthorized_handler
def unauthorized():
    """Обработчик для неавторизованных пользователей с учётом префикса"""
    from flask import request, redirect
    from urllib.parse import urlparse
    # Получаем текущий URL и извлекаем только path часть
    parsed_url = urlparse(request.url)
    current_path = parsed_url.path
    
    # Убеждаемся, что next содержит префикс
    # Используем кастомный login_url для получения правильного URL
    login_url = login_manager.login_url(current_path)
    return redirect(login_url)

# Глобальная переменная для хранения статуса парсера
parser_status = {'running': False, 'last_run': None, 'message': 'Парсер не запущен', 'images': []}

# Глобальный список для хранения логов парсера (для отправки в браузер)
parser_logs = []


@login_manager.user_loader
def load_user(user_id):
    """
    Callback функция для загрузки пользователя по ID (требуется Flask-Login)
    
    Вызывается автоматически Flask-Login при работе с сессиями.
    
    Args:
        user_id (str): Идентификатор пользователя из сессии
    
    Returns:
        User or None: Объект пользователя или None если не найден
    """
    users_data = load_users(USERS_FILE, hash_password)
    for user in users_data.get('users', []):
        if str(user['id']) == str(user_id):
            return User(user['id'], user['username'], user.get('is_admin', False))
    return None


def run_parser_task():
    """
    Фоновая задача парсинга FTP-каталога
    
    Выполняется в отдельном потоке для неблокирующей работы.
    Обновляет глобальную переменную parser_status для отображения прогресса.
    Сохраняет найденные изображения в файл для постоянного доступа.
    НЕ сбрасывает уже сохранённые изображения - добавляет только новые.
    """
    import logging
    import traceback as tb_module
    global parser_status, parser_logs
    try:
        # Очищаем логи перед новым запуском
        parser_logs.clear()
        
        def log(message, log_type='info', error_details=None):
            """Добавляет сообщение в лог с временной меткой и дополнительной информацией"""
            timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
            log_entry = {
                'timestamp': timestamp,
                'message': message,
                'type': log_type,
                'error_details': error_details
            }
            parser_logs.append(log_entry)
            # Также выводим в консоль сервера
            print(f"[{timestamp}] {message}")
            if error_details:
                print(f"[{timestamp}] DETAILS: {error_details}")
        
        # Не меняем статус здесь, так как он уже установлен в start_parser()
        # parser_status['running'] = True
        # parser_status['message'] = 'Парсинг запущен...'
        
        # ОТЛАДКА: Начало парсинга
        log("Запуск run_parser_task()")
        log(f"FTP_BASE_URL: {FTP_BASE_URL}")
        log(f"PARSER_MAX_DEPTH: {PARSER_MAX_DEPTH}")
        log(f"PARSER_TIMEOUT: {PARSER_TIMEOUT}")
        
        # Загрузить уже сохранённые изображения, чтобы не потерять их
        existing_images_data = load_json_file(PARSER_IMAGES_FILE, {'images': []})
        existing_images = set(existing_images_data.get('images', []))
        log(f"Существующих изображений в файле: {len(existing_images)}")
        
        # Запустить парсинг FTP-каталога
        log("Вызов parse_folder()...")
        items = parse_folder(FTP_BASE_URL, max_depth=PARSER_MAX_DEPTH, timeout=PARSER_TIMEOUT)
        log(f"parse_folder() вернул элементов: {len(items)}")
        if items:
            log(f"Первые 5 элементов: {items[:5]}")
        else:
            log("WARNING: parse_folder() вернул пустой список!")
        
        # Собрать все найденные изображения из парсера
        new_parser_images = []
        def collect_images(items_list):
            for item in items_list:
                # Проверяем, является ли элемент файлом изображения (у файлов children=None)
                if item.get('children') is None:
                    # Это файл - проверяем расширение
                    url = item.get('url', '')
                    if url and (url.lower().endswith('.png') or url.lower().endswith('.jpg') or 
                                url.lower().endswith('.jpeg') or url.lower().endswith('.gif') or 
                                url.lower().endswith('.webp')):
                        if url not in new_parser_images:
                            new_parser_images.append(url)
                else:
                    # Это папка - рекурсивно обрабатываем детей
                    if item.get('children'):
                        collect_images(item['children'])
        
        log("Сбор изображений из элементов...")
        collect_images(items)
        log(f"Найдено новых изображений: {len(new_parser_images)}")
        if new_parser_images:
            log(f"Первые 5 изображений: {new_parser_images[:5]}")
        
        # Заменить все ссылки с 192.168.3.78:8085 на vm-ftp.anosov.ru
        def replace_url_domain(url):
            """Заменить домен в URL с 192.168.3.78:8085 на vm-ftp.anosov.ru"""
            return url.replace('192.168.3.78:8085', 'vm-ftp.anosov.ru')
        
        # Применяем замену ко всем новым изображениям
        new_parser_images = [replace_url_domain(img) for img in new_parser_images]
        
        # Объединить с существующими изображениями (сохраняем старые + добавляем новые)
        all_images = list(existing_images)
        for img_url in new_parser_images:
            if img_url not in existing_images:
                all_images.append(img_url)
        
        log(f"Всего изображений после объединения: {len(all_images)}")
        
        # Сохранить все изображения в файл для постоянного доступа
        save_json_file(PARSER_IMAGES_FILE, {'images': all_images})
        log(f"Изображения сохранены в {PARSER_IMAGES_FILE}")
        
        # Обновить статус парсера с новыми изображениями
        parser_status['images'] = all_images
        
        # Заменить все ссылки с 192.168.3.78:8085 на vm-ftp.anosov.ru в элементах каталога
        def replace_url_domain_recursive(items_list):
            """Рекурсивно заменить домен в URL всех элементов"""
            for item in items_list:
                # Заменяем URL в текущем элементе
                if 'url' in item and item['url']:
                    item['url'] = item['url'].replace('192.168.3.78:8085', 'vm-ftp.anosov.ru')
                # Рекурсивно обрабатываем дочерние элементы
                if item.get('children') and isinstance(item['children'], list):
                    replace_url_domain_recursive(item['children'])
        
        # Применяем замену ко всем элементам каталога
        replace_url_domain_recursive(items)
        
        permanent_items = load_permanent_items(PERMANENT_FILE)
        permanent_paths = set(permanent_items.get('permanent_items', []))
        
        # Загрузить существующий каталог
        existing_catalog = load_catalog(CATALOG_FILE)
        existing_children = existing_catalog.get('children', [])
        
        # Объединить новые данные с существующими, сохраняя постоянные элементы
        merged_children = merge_with_permanent(items, existing_children, permanent_paths)
        
        # Сохранить обновлённый каталог
        existing_catalog['children'] = merged_children
        existing_catalog['modified'] = get_current_timestamp()
        save_catalog(CATALOG_FILE, existing_catalog)
        log(f"Каталог сохранён в {CATALOG_FILE}")
        
        # Аудит: успешная загрузка элементов парсером
        audit_upload_success('ftp_parser', object_type='catalog', 
                           description=f'Успешный парсинг FTP: найдено {len(items)} элементов',
                           additional_data={'items_count': len(items), 'images_count': len(all_images)})
        
        # Обновить статус парсера
        parser_status['last_run'] = get_full_timestamp()
        parser_status['message'] = f'Парсинг завершён успешно. Найдено элементов: {len(items)}. Всего изображений: {len(all_images)}'
        log(f"Итоговый статус: {parser_status['message']}")
        
    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        parser_status['message'] = f'Ошибка парсинга: {str(e)}'
        
        # Формируем детальную информацию об ошибке
        error_details = {
            'type': type(e).__name__,
            'message': str(e),
            'url': None,
            'timeout': PARSER_TIMEOUT,
            'http_status': None,
            'response_headers': None,
            'response_body': None,
            'reason': None,
            'traceback': error_traceback
        }
        
        # Детализация ошибок подключения
        if hasattr(e, 'request') and e.request is not None:
            error_details['url'] = e.request.url
            error_details['method'] = e.request.method
        if hasattr(e, 'response') and e.response is not None:
            error_details['http_status'] = e.response.status_code
            error_details['response_headers'] = dict(e.response.headers)
            error_details['response_body'] = str(e.response.text[:500])
        if hasattr(e, 'reason'):
            error_details['reason'] = str(e.reason)
        
        # Логируем ошибку с деталями
        log(f"ОШИБКА в run_parser_task(): {str(e)}", log_type='error', error_details=error_details)
        log(f"Тип ошибки: {type(e).__name__}", log_type='error')
        if error_details['url']:
            log(f"URL запроса: {error_details['url']}", log_type='error')
        if error_details.get('method'):
            log(f"Метод запроса: {error_details['method']}", log_type='error')
        if error_details['http_status']:
            log(f"Статус ответа: {error_details['http_status']}", log_type='error')
        if error_details['response_headers']:
            log(f"Заголовки ответа: {error_details['response_headers']}", log_type='error')
        if error_details['response_body']:
            log(f"Тело ответа (первые 500 символов): {error_details['response_body']}", log_type='error')
        if error_details['reason']:
            log(f"Причина ошибки: {error_details['reason']}", log_type='error')
        log(f"Полный traceback: {error_traceback}", log_type='error')
        
        # Аудит: ошибка парсинга
        audit_error('parser_error', 'ftp_parser', 
                   description=f'Ошибка парсинга FTP: {str(e)}',
                   exception=e,
                   additional_data=error_details)
    finally:
        parser_status['running'] = False
        log(f"Завершение run_parser_task(). Статус: running={parser_status['running']}")


@app.route('/login', methods=['GET', 'POST'])
@limiter.limit(RATELIMIT_LOGIN)  # Ограничение частоты запросов для защиты от брутфорса
def login():
    """
    Страница входа в систему
    
    Обрабатывает GET (отображение формы) и POST (аутентификация) запросы.
    
    Returns:
        Response: HTML страница входа или редирект на главную
    """
    if current_user.is_authenticated:
        return redirect(URL_PREFIX + '/')
    
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember', False)
        
        if not username or not password:
            error = 'Введите имя пользователя и пароль'
        else:
            users_data = load_users(USERS_FILE, hash_password)
            user_found = None
            for user in users_data.get('users', []):
                if user['username'] == username:
                    user_found = user
                    break
            
            if user_found and verify_password(password, user_found['password_hash']):
                user_obj = User(user_found['id'], user_found['username'], user_found.get('is_admin', False))
                login_user(user_obj, remember=remember)
                next_page = request.args.get('next')
                flash('Вы успешно вошли в систему', 'success')
                
                # Если next_page не указан, перенаправляем на /navigator/admin
                if not next_page:
                    return redirect(URL_PREFIX + '/admin')
                
                # Проверяем, если next_page содержит '/admin' но не содержит префикс
                # Добавляем префикс к next_page
                if URL_PREFIX not in next_page and next_page.startswith('/'):
                    next_page = URL_PREFIX + next_page
                elif URL_PREFIX not in next_page:
                    # Если next_page относительный (например, 'admin'), добавляем префикс
                    next_page = URL_PREFIX + '/' + next_page.lstrip('/')
                    
                return redirect(next_page)
            else:
                error = 'Неверное имя пользователя или пароль'
    
    # Получаем параметр next из query string для формы
    next_page = request.args.get('next')
    
    # -------------------------------------------------------------------
    # ИСПРАВЛЕНИЕ 2: Создаём функцию для получения URL входа с префиксом
    # и передаём её в шаблон для использования в action формы.
    # -------------------------------------------------------------------
    def get_prefixed_login_url():
        """Возвращает URL страницы входа с учётом префикса (SCRIPT_NAME)."""
        return URL_PREFIX + '/login'
    
    return render_template_string('''
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Вход в систему</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        .login-container {
            background: white;
            padding: 40px;
            border-radius: 10px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            width: 100%;
            max-width: 400px;
        }
        h1 {
            text-align: center;
            color: #333;
            margin-bottom: 30px;
            font-size: 24px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            color: #555;
            font-weight: bold;
        }
        input[type="text"],
        input[type="password"] {
            width: 100%;
            padding: 12px 15px;
            border: 2px solid #e0e0e0;
            border-radius: 5px;
            font-size: 16px;
            transition: border-color 0.3s;
        }
        input[type="text"]:focus,
        input[type="password"]:focus {
            outline: none;
            border-color: #667eea;
        }
        .checkbox-group {
            display: flex;
            align-items: center;
            margin-bottom: 20px;
        }
        .checkbox-group input {
            margin-right: 10px;
        }
        .checkbox-group label {
            margin: 0;
            font-weight: normal;
            cursor: pointer;
        }
        .btn-submit {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 5px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .btn-submit:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 20px rgba(102, 126, 234, 0.4);
        }
        .error-message {
            background: #fee;
            color: #c00;
            padding: 12px;
            border-radius: 5px;
            margin-bottom: 20px;
            text-align: center;
            border: 1px solid #fcc;
        }
        .flash-messages {
            margin-bottom: 20px;
        }
        .flash-message {
            padding: 12px;
            border-radius: 5px;
            margin-bottom: 10px;
            text-align: center;
        }
        .flash-success {
            background: #efe;
            color: #0a0;
            border: 1px solid #cfc;
        }
        .flash-error {
            background: #fee;
            color: #c00;
            border: 1px solid #fcc;
        }
        .flash-info {
            background: #eef;
            color: #00a;
            border: 1px solid #ccf;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <h1>Вход в систему</h1>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                <div class="flash-messages">
                    {% for category, message in messages %}
                        <div class="flash-message flash-{{ category }}">{{ message }}</div>
                    {% endfor %}
                </div>
            {% endif %}
        {% endwith %}
        
        {% if error %}
            <div class="error-message">{{ error }}</div>
        {% endif %}
        
        <!-- ИСПРАВЛЕНИЕ 3: action формы теперь использует функцию с префиксом -->
        <form method="POST" action="{{ get_prefixed_login_url() }}">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            
            <div class="form-group">
                <label for="username">Имя пользователя</label>
                <input type="text" id="username" name="username" required autofocus>
            </div>
            
            <div class="form-group">
                <label for="password">Пароль</label>
                <input type="password" id="password" name="password" required>
            </div>
            
            <div class="checkbox-group">
                <input type="checkbox" id="remember" name="remember">
                <label for="remember">Запомнить меня</label>
            </div>
            
            <button type="submit" class="btn-submit">Войти</button>
        </form>
    </div>
</body>
</html>
''', error=error, get_prefixed_login_url=get_prefixed_login_url)  # Передаём функцию в контекст


@app.route('/logout')
@login_required
def logout():
    """
    Выход из системы
    
    Завершает сессию пользователя и перенаправляет на главную страницу /navigator/.
    
    Returns:
        Response: Редирект на главную страницу
    """
    logout_user()
    flash('Вы вышли из системы', 'info')
    return redirect(URL_PREFIX + '/')


@app.route(URL_PREFIX + '/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """
    Страница изменения пароля пользователя
    
    Обрабатывает GET (отображение формы) и POST (смена пароля) запросы.
    
    Returns:
        Response: HTML страница смены пароля или редирект
    """
    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        if not current_password or not new_password or not confirm_password:
            flash('Заполните все поля', 'error')
            return redirect(URL_PREFIX + '/change-password')
        
        if new_password != confirm_password:
            flash('Новые пароли не совпадают', 'error')
            return redirect(URL_PREFIX + '/change-password')
        
        if len(new_password) < 6:
            flash('Пароль должен быть не менее 6 символов', 'error')
            return redirect(URL_PREFIX + '/change-password')
        
        # Проверяем текущий пароль
        users_data = load_users(USERS_FILE, hash_password)
        user_found = None
        user_index = None
        for idx, user in enumerate(users_data.get('users', [])):
            if user['username'] == current_user.username:
                user_found = user
                user_index = idx
                break
        
        if not user_found or not verify_password(current_password, user_found['password_hash']):
            flash('Текущий пароль неверен', 'error')
            return redirect(URL_PREFIX + '/change-password')
        
        # Обновляем пароль
        users_data['users'][user_index]['password_hash'] = hash_password(new_password)
        save_users(USERS_FILE, users_data)
        
        flash('Пароль успешно изменён', 'success')
        return redirect(URL_PREFIX + '/admin')
    
    return render_template_string('''
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Изменение пароля</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        .container {
            background: white;
            padding: 40px;
            border-radius: 10px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            width: 100%;
            max-width: 450px;
        }
        h1 {
            text-align: center;
            color: #333;
            margin-bottom: 30px;
            font-size: 24px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            color: #555;
            font-weight: bold;
        }
        input[type="password"] {
            width: 100%;
            padding: 12px 15px;
            border: 2px solid #e0e0e0;
            border-radius: 5px;
            font-size: 16px;
            transition: border-color 0.3s;
        }
        input[type="password"]:focus {
            outline: none;
            border-color: #667eea;
        }
        .btn-submit {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 5px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .btn-submit:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 20px rgba(102, 126, 234, 0.4);
        }
        .btn-secondary {
            display: block;
            width: 100%;
            padding: 14px;
            background: #f0f0f0;
            color: #333;
            border: none;
            border-radius: 5px;
            font-size: 16px;
            cursor: pointer;
            margin-top: 10px;
            text-align: center;
            text-decoration: none;
        }
        .btn-secondary:hover {
            background: #e0e0e0;
        }
        .flash-messages {
            margin-bottom: 20px;
        }
        .flash-message {
            padding: 12px;
            border-radius: 5px;
            margin-bottom: 10px;
            text-align: center;
        }
        .flash-success {
            background: #efe;
            color: #0a0;
            border: 1px solid #cfc;
        }
        .flash-error {
            background: #fee;
            color: #c00;
            border: 1px solid #fcc;
        }
        .password-requirements {
            background: #f8f9fa;
            padding: 12px;
            border-radius: 5px;
            margin-bottom: 20px;
            font-size: 14px;
            color: #666;
        }
        .password-requirements ul {
            margin-left: 20px;
            margin-top: 8px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Изменение пароля</h1>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                <div class="flash-messages">
                    {% for category, message in messages %}
                        <div class="flash-message flash-{{ category }}">{{ message }}</div>
                    {% endfor %}
                </div>
            {% endif %}
        {% endwith %}
        
        <div class="password-requirements">
            <strong>Требования к паролю:</strong>
            <ul>
                <li>Минимум 6 символов</li>
                <li>Подтверждение пароля должно совпадать</li>
            </ul>
        </div>
        
        <form method="POST" action="{{ url_for('change_password') }}">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            
            <div class="form-group">
                <label for="current_password">Текущий пароль</label>
                <input type="password" id="current_password" name="current_password" required autofocus>
            </div>
            
            <div class="form-group">
                <label for="new_password">Новый пароль</label>
                <input type="password" id="new_password" name="new_password" required>
            </div>
            
            <div class="form-group">
                <label for="confirm_password">Подтверждение нового пароля</label>
                <input type="password" id="confirm_password" name="confirm_password" required>
            </div>
            
            <button type="submit" class="btn-submit">Изменить пароль</button>
            <a href="{{ url_for('admin') }}" class="btn-secondary">Отмена</a>
        </form>
    </div>
</body>
</html>
''')


@app.route('/')
def index():
    """
    Главная страница приложения
    
    Отдаёт клиентский HTML файл интерфейса пользователя.
    
    Returns:
        Response: HTML файл index.html
    """
    # Фиксируем открытие главной страницы (каталог)
    try:
        audit_catalog_item_open(
            item_path='/',
            item_name='Главная страница',
            status_code=200,
            item_type='index',
            description='Открытие главной страницы каталога'
        )
    except Exception as e:
        # Если аудит не удался, просто логируем ошибку, но не прерываем работу
        app.logger.error(f"Ошибка аудита главной страницы: {e}")
    
    response = send_from_directory('.', 'index.html')
    # Добавляем заголовки для предотвращения кэширования HTML страниц
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/admin')
@login_required
@admin_required_decorator  # Только для администраторов
def admin():
    """
    Панель администратора
    
    Доступна только авторизованным пользователям с правами администратора.
    
    Returns:
        Response: HTML файл admin.html
    """
    # Фиксируем открытие панели администратора
    try:
        ip_address = request.remote_addr or '127.0.0.1'
        user_id = getattr(g, 'user_id', None)
        username = getattr(g, 'username', 'anonymous')
        
        audit_catalog_item_open(
            item_path='/admin',
            item_name='Панель администратора',
            status_code=200,
            item_type='admin_page',
            description='Открытие панели администратора',
            ip_address=ip_address,
            user_id=user_id,
            username=username
        )
    except Exception as e:
        # Если аудит не удался, просто логируем ошибку, но не прерываем работу
        app.logger.error(f"Ошибка аудита панели администратора: {e}")
    
    response = send_from_directory('.', 'admin.html')
    # Добавляем заголовки для предотвращения кэширования HTML страниц
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/video-player')
def video_player():
    """
    Страница просмотра видео
    
    Открывает HTML страницу видеоплеера для воспроизведения видеофайлов.
    
    Returns:
        Response: HTML файл video-player.html
    """
    # Фиксируем открытие страницы видеоплеера
    try:
        ip_address = request.remote_addr or '127.0.0.1'
        user_id = getattr(g, 'user_id', None)
        username = getattr(g, 'username', 'anonymous')
        
        audit_catalog_item_open(
            item_path='/video-player',
            item_name='Видеоплеер',
            status_code=200,
            item_type='video_player_page',
            description='Открытие страницы видеоплеера',
            ip_address=ip_address,
            user_id=user_id,
            username=username
        )
    except Exception as e:
        # Если аудит не удался, просто логируем ошибку, но не прерываем работу
        app.logger.error(f"Ошибка аудита видеоплеера: {e}")
    
    response = send_from_directory('.', 'video-player.html')
    # Добавляем заголовки для предотвращения кэширования HTML страниц
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/parser-logs')
@login_required
@admin_required_decorator  # Только для администраторов
def parser_logs_page():
    """
    Страница просмотра логов парсера
    
    Доступна только авторизованным пользователям с правами администратора.
    
    Returns:
        Response: HTML страница с логами парсера
    """
    # Фиксируем открытие страницы логов парсера
    try:
        ip_address = request.remote_addr or '127.0.0.1'
        user_id = getattr(g, 'user_id', None)
        username = getattr(g, 'username', 'anonymous')
        
        audit_catalog_item_open(
            item_path='/parser-logs',
            item_name='Логи парсера',
            status_code=200,
            item_type='parser_logs_page',
            description='Открытие страницы логов парсера',
            ip_address=ip_address,
            user_id=user_id,
            username=username
        )
    except Exception as e:
        # Если аудит не удался, просто логируем ошибку, но не прерываем работу
        app.logger.error(f"Ошибка аудита страницы логов парсера: {e}")
    
    html_template = '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <base href="/navigator/">
    <title>Логи парсера</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: Arial, sans-serif;
            background: #f5f5f5;
            min-height: 100vh;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .header h1 {
            font-size: 24px;
        }
        .header-actions {
            display: flex;
            gap: 10px;
        }
        .btn {
            padding: 10px 20px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.3s;
        }
        .btn-primary {
            background: white;
            color: #667eea;
        }
        .btn-primary:hover {
            background: #f0f0f0;
        }
        .btn-success {
            background: #28a745;
            color: white;
        }
        .btn-success:hover {
            background: #218838;
        }
        .container {
            max-width: 1400px;
            margin: 20px auto;
            padding: 20px;
        }
        .logs-container {
            background: white;
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .log-entry {
            padding: 10px;
            border-bottom: 1px solid #e0e0e0;
            font-family: monospace;
            font-size: 13px;
        }
        .log-entry:last-child {
            border-bottom: none;
        }
        .log-entry.info {
            background: #f8f9fa;
        }
        .log-entry.success {
            background: #d4edda;
            color: #155724;
        }
        .log-entry.warning {
            background: #fff3cd;
            color: #856404;
        }
        .log-entry.error {
            background: #f8d7da;
            color: #721c24;
        }
        .log-timestamp {
            color: #666;
            font-weight: bold;
            margin-right: 10px;
        }
        .log-type {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 3px;
            font-size: 11px;
            font-weight: bold;
            text-transform: uppercase;
            margin-right: 10px;
        }
        .log-type.info {
            background: #17a2b8;
            color: white;
        }
        .log-type.success {
            background: #28a745;
            color: white;
        }
        .log-type.warning {
            background: #ffc107;
            color: #000;
        }
        .log-type.error {
            background: #dc3545;
            color: white;
        }
        .logs-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 2px solid #e0e0e0;
        }
        .logs-actions {
            display: flex;
            gap: 10px;
        }
        .btn-danger {
            background: #dc3545;
            color: white;
        }
        .btn-danger:hover {
            background: #c82333;
        }
        .auto-refresh {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 15px;
        }
        .auto-refresh input {
            width: 20px;
            height: 20px;
        }
        .empty-logs {
            text-align: center;
            color: #666;
            padding: 40px;
            font-style: italic;
        }
        .log-error-details {
            margin-top: 10px;
            padding: 10px;
            background: #f8f9fa;
            border-left: 3px solid #dc3545;
            font-size: 12px;
            white-space: pre-wrap;
            word-break: break-all;
        }
        
        @media (max-width: 768px) {
            .header {
                flex-direction: column;
                padding: 15px;
            }
            .header h1 {
                font-size: 20px;
                margin-bottom: 10px;
                text-align: center;
            }
            .header-actions {
                flex-wrap: wrap;
                justify-content: center;
                gap: 8px;
            }
            .btn {
                padding: 8px 15px;
                font-size: 13px;
            }
            .container {
                padding: 15px;
            }
            .logs-header {
                flex-direction: column;
                gap: 15px;
            }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>Логи парсера</h1>
        <div class="header-actions">
            <button class="btn btn-primary" onclick="window.location.href='/navigator/admin'">Назад в админку</button>
            <button class="btn btn-primary" onclick="window.location.href='/navigator/'">На сайт</button>
        </div>
    </div>

    <div class="container">
        <div class="logs-container">
            <div class="logs-header">
                <h2>Журнал работы парсера</h2>
                <div class="logs-actions">
                    <button class="btn btn-success" onclick="loadLogs()">Обновить</button>
                    <button class="btn btn-danger" onclick="clearLogs()">Очистить логи</button>
                </div>
            </div>
            
            <div class="auto-refresh">
                <input type="checkbox" id="autoRefresh" checked onchange="toggleAutoRefresh()">
                <label for="autoRefresh">Автоматическое обновление каждые 5 секунд</label>
            </div>
            
            <div id="logsContent"></div>
        </div>
    </div>

    <script>
        let autoRefreshInterval = null;
        
        async function loadLogs() {
            try {
                const response = await fetch('/navigator/api/parser/status', { credentials: 'include' });
                if (!response.ok) {
                    throw new Error('Ошибка загрузки логов');
                }
                const data = await response.json();
                renderLogs(data.logs || []);
            } catch (error) {
                document.getElementById('logsContent').innerHTML = 
                    '<div class="empty-logs">Ошибка загрузки логов: ' + error.message + '</div>';
            }
        }
        
        function renderLogs(logs) {
            const container = document.getElementById('logsContent');
            
            if (!logs || logs.length === 0) {
                container.innerHTML = '<div class="empty-logs">Логи отсутствуют. Запустите парсер для записи логов.</div>';
                return;
            }
            
            // Отображаем логи в обратном порядке (новые сверху)
            const reversedLogs = [...logs].reverse();
            
            container.innerHTML = reversedLogs.map(log => {
                const typeClass = log.type || 'info';
                const typeLabel = {
                    'info': 'INFO',
                    'success': 'SUCCESS',
                    'warning': 'WARNING',
                    'error': 'ERROR'
                }[typeClass] || 'INFO';
                
                let detailsHtml = '';
                if (log.error_details) {
                    detailsHtml = '<div class="log-error-details">' + 
                        escapeHtml(JSON.stringify(log.error_details, null, 2)) + 
                        '</div>';
                }
                
                return '<div class="log-entry ' + typeClass + '">' +
                    '<span class="log-timestamp">[' + escapeHtml(log.timestamp || '') + ']</span>' +
                    '<span class="log-type ' + typeClass + '">' + escapeHtml(typeLabel) + '</span>' +
                    escapeHtml(log.message || '') +
                    detailsHtml +
                    '</div>';
            }).join('');
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        function toggleAutoRefresh() {
            const checkbox = document.getElementById('autoRefresh');
            if (checkbox.checked) {
                startAutoRefresh();
            } else {
                stopAutoRefresh();
            }
        }
        
        function startAutoRefresh() {
            if (autoRefreshInterval) {
                clearInterval(autoRefreshInterval);
            }
            autoRefreshInterval = setInterval(loadLogs, 5000);
        }
        
        function stopAutoRefresh() {
            if (autoRefreshInterval) {
                clearInterval(autoRefreshInterval);
                autoRefreshInterval = null;
            }
        }
        
        async function clearLogs() {
            if (!confirm('Вы уверены, что хотите очистить логи?')) {
                return;
            }
            
            try {
                const response = await fetch('/navigator/api/parser/reset', {
                    method: 'POST',
                    credentials: 'include',
                    headers: {
                        'X-CSRFToken': getCsrfToken()
                    }
                });
                
                if (response.ok) {
                    loadLogs();
                    showMessage('Логи очищены', 'success');
                } else {
                    showMessage('Ошибка при очистке логов', 'error');
                }
            } catch (error) {
                showMessage('Ошибка: ' + error.message, 'error');
            }
        }
        
        function getCsrfToken() {
            const cookies = document.cookie.split(';');
            for (let cookie of cookies) {
                const [name, value] = cookie.trim().split('=');
                if (name === 'csrf_token') {
                    return decodeURIComponent(value);
                }
            }
            return '';
        }
        
        function showMessage(message, type) {
            // Простое уведомление через alert для simplicity
            alert(message);
        }
        
        // Загрузка логов при открытии страницы
        document.addEventListener('DOMContentLoaded', function() {
            loadLogs();
            startAutoRefresh();
        });
    </script>
</body>
</html>'''
    
    response = app.response_class(response=html_template, status=200, mimetype='text/html')
    # Добавляем заголовки для предотвращения кэширования HTML страниц
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/parser-debug-log')
@login_required
@admin_required_decorator
def parser_debug_log_page():
    """
    Страница просмотра детальных отладочных логов парсера
    
    Доступна только авторизованным пользователям с правами администратора.
    
    Returns:
        Response: HTML страница с отладочными логами
    """
    # Фиксируем открытие страницы отладочных логов парсера
    try:
        ip_address = request.remote_addr or '127.0.0.1'
        user_id = getattr(g, 'user_id', None)
        username = getattr(g, 'username', 'anonymous')
        
        audit_catalog_item_open(
            item_path='/parser-debug-log',
            item_name='Отладочные логи парсера',
            status_code=200,
            item_type='parser_debug_log_page',
            description='Открытие страницы отладочных логов парсера',
            ip_address=ip_address,
            user_id=user_id,
            username=username
        )
    except Exception as e:
        # Если аудит не удался, просто логируем ошибку, но не прерываем работу
        app.logger.error(f"Ошибка аудита страницы отладочных логов: {e}")
    
    html_template = '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <base href="/navigator/">
    <title>Отладочные логи парсера</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: Arial, sans-serif;
            background: #f5f5f5;
            min-height: 100vh;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .header h1 {
            font-size: 24px;
        }
        .header-actions {
            display: flex;
            gap: 10px;
        }
        .btn {
            padding: 10px 20px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 14px;
            text-decoration: none;
            display: inline-block;
        }
        .btn-primary {
            background: #007bff;
            color: white;
        }
        .btn-primary:hover {
            background: #0056b3;
        }
        .btn-success {
            background: #28a745;
            color: white;
        }
        .btn-success:hover {
            background: #218838;
        }
        .btn-danger {
            background: #dc3545;
            color: white;
        }
        .btn-danger:hover {
            background: #c82333;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }
        .logs-container {
            background: white;
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .logs-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 2px solid #e0e0e0;
        }
        .log-entry {
            margin-bottom: 20px;
            padding: 15px;
            border: 1px solid #ddd;
            border-radius: 5px;
            background: #f9f9f9;
        }
        .log-info {
            border-left: 4px solid #17a2b8;
        }
        .log-url {
            font-weight: bold;
            color: #007bff;
            margin-bottom: 10px;
            word-break: break-all;
        }
        .log-timestamp {
            color: #666;
            font-size: 12px;
            margin-bottom: 10px;
        }
        .log-section {
            margin-top: 10px;
        }
        .log-section-title {
            font-weight: bold;
            color: #333;
            margin-bottom: 5px;
        }
        .log-details {
            background: #fff;
            padding: 10px;
            border: 1px solid #eee;
            border-radius: 3px;
            font-family: monospace;
            font-size: 12px;
            white-space: pre-wrap;
            word-break: break-all;
            max-height: 300px;
            overflow-y: auto;
        }
        .status-code {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 3px;
            font-weight: bold;
            font-size: 12px;
        }
        .status-success {
            background: #28a745;
            color: white;
        }
        .status-error {
            background: #dc3545;
            color: white;
        }
        .empty-logs {
            text-align: center;
            color: #666;
            padding: 40px;
            font-style: italic;
        }
        
        @media (max-width: 768px) {
            .header {
                flex-direction: column;
                padding: 15px;
            }
            .header h1 {
                font-size: 20px;
                margin-bottom: 10px;
                text-align: center;
            }
            .header-actions {
                flex-wrap: wrap;
                justify-content: center;
                gap: 8px;
            }
            .btn {
                padding: 8px 15px;
                font-size: 13px;
            }
            .container {
                padding: 15px;
            }
            .logs-header {
                flex-direction: column;
                gap: 15px;
            }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>Отладочные логи парсера</h1>
        <div class="header-actions">
            <button class="btn btn-primary" onclick="window.location.href='/navigator/admin'">Назад в админку</button>
            <button class="btn btn-primary" onclick="window.location.href='/navigator/parser-logs'">Обычные логи</button>
            <button class="btn btn-success" onclick="loadLogs()">Обновить</button>
            <button class="btn btn-danger" onclick="deleteLogs()">Удалить логи</button>
        </div>
    </div>

    <div class="container">
        <div class="logs-container">
            <div class="logs-header">
                <h2>Детальные ответы сервера</h2>
                <button class="btn btn-success" onclick="loadLogs()">Обновить</button>
            </div>
            
            <div id="logsContent"></div>
        </div>
    </div>

    <script>
        async function loadLogs() {
            try {
                const response = await fetch('/navigator/api/parser/debug-log', { credentials: 'include' });
                if (!response.ok) {
                    throw new Error('Ошибка загрузки логов');
                }
                const data = await response.json();
                renderLogs(data.responses || []);
            } catch (error) {
                document.getElementById('logsContent').innerHTML = 
                    '<div class="empty-logs">Ошибка загрузки логов: ' + error.message + '</div>';
            }
        }
        
        function renderLogs(responses) {
            const container = document.getElementById('logsContent');
            
            if (!responses || responses.length === 0) {
                container.innerHTML = '<div class="empty-logs">Отладочные логи отсутствуют. Запустите парсер для записи логов.</div>';
                return;
            }
            
            // Отображаем логи в обратном порядке (новые сверху)
            const reversedLogs = [...responses].reverse();
            
            container.innerHTML = reversedLogs.map(log => {
                const resp = log.response || {};
                const statusCode = resp.status_code || 'N/A';
                const statusClass = (statusCode >= 200 && statusCode < 300) ? 'status-success' : 'status-error';
                
                let headersHtml = '';
                if (resp.headers) {
                    headersHtml = '<div class="log-section">' +
                        '<div class="log-section-title">Заголовки:</div>' +
                        '<div class="log-details">' + escapeHtml(JSON.stringify(resp.headers, null, 2)) + '</div>' +
                        '</div>';
                }
                
                let contentPreview = '';
                if (resp.content_preview) {
                    contentPreview = '<div class="log-section">' +
                        '<div class="log-section-title">Предпросмотр контента:</div>' +
                        '<div class="log-details">' + escapeHtml(resp.content_preview.substring(0, 2000)) + '</div>' +
                        '</div>';
                }
                
                let fullContent = '';
                if (resp.full_content) {
                    fullContent = '<div class="log-section">' +
                        '<div class="log-section-title">Полный контент:</div>' +
                        '<div class="log-details">' + escapeHtml(resp.full_content) + '</div>' +
                        '</div>';
                }
                
                return '<div class="log-entry log-info">' +
                    '<div class="log-url">URL: ' + escapeHtml(log.url || 'N/A') + '</div>' +
                    '<div class="log-timestamp">Время: ' + escapeHtml(log.timestamp || 'N/A') + ' | Глубина: ' + (log.depth || 0) + '</div>' +
                    '<div><span class="status-code ' + statusClass + '">Status: ' + statusCode + '</span>' +
                    ' | Длина контента: ' + (resp.content_length || 'N/A') + ' bytes' +
                    ' | Кодировка: ' + (resp.encoding || 'N/A') + '</div>' +
                    headersHtml +
                    contentPreview +
                    fullContent +
                    '</div>';
            }).join('');
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        // Функция для удаления логов
        async function deleteLogs() {
            if (!confirm('Вы уверены, что хотите удалить все отладочные логи?')) {
                return;
            }
            
            try {
                const response = await fetch('/navigator/api/parser/debug-log', { 
                    method: 'DELETE',
                    credentials: 'include' 
                });
                
                if (!response.ok) {
                    throw new Error('Ошибка удаления логов');
                }
                
                const data = await response.json();
                alert(data.message || 'Логи успешно удалены');
                loadLogs(); // Обновить список логов
            } catch (error) {
                alert('Ошибка удаления логов: ' + error.message);
            }
        }
        
        // Загрузка логов при открытии страницы
        document.addEventListener('DOMContentLoaded', function() {
            loadLogs();
        });
    </script>
</body>
</html>'''
    
    response = app.response_class(response=html_template, status=200, mimetype='text/html')
    # Добавляем заголовки для предотвращения кэширования HTML страниц
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/api/catalog')
def get_catalog():
    """
    API endpoint для получения каталога
    
    Возвращает каталог с отмеченными постоянными элементами.
    
    Returns:
        Response: JSON объект каталога
    """
    # Аудит: просмотр каталога
    audit_web_resource('view', 'catalog', description='Просмотр каталога веб-ресурсов')
    
    catalog = load_catalog(CATALOG_FILE)
    permanent_items = load_permanent_items(PERMANENT_FILE)
    permanent_paths = set(permanent_items.get('permanent_items', []))
    mark_permanent_recursive(catalog.get('children', []), permanent_paths)
    
    # Добавляем проекты из папки projects напрямую в каталог (без создания папки projects)
    if os.path.exists(PROJECTS_DIR):
        # Собираем все проекты из файловой системы
        project_items = []
        for project_name in os.listdir(PROJECTS_DIR):
            project_path = os.path.join(PROJECTS_DIR, project_name)
            if os.path.isdir(project_path):
                # Ищем index.html в нескольких возможных местах
                possible_index_paths = [
                    os.path.join(project_path, 'index.html'),
                    os.path.join(project_path, 'templates', 'index.html'),
                    os.path.join(project_path, 'app', 'index.html')
                ]
                
                index_html_path = None
                for possible_path in possible_index_paths:
                    if os.path.exists(possible_path):
                        index_html_path = possible_path
                        break
                
                if index_html_path is None:
                    # Если нет index.html, но есть app.py (Flask проект), всё равно добавляем проект
                    flask_app_path = os.path.join(project_path, 'app.py')
                    if not os.path.exists(flask_app_path):
                        continue
                    # Используем app.py для определения времени модификации
                    index_html_path = flask_app_path
                
                # Проверяем, есть ли Flask приложение в проекте
                flask_app_path = os.path.join(project_path, 'app.py')
                has_flask = os.path.exists(flask_app_path)
                
                # Если это Flask приложение, сохраняем информацию о нём
                if has_flask:
                    project_flask_info[project_name] = {
                        'app_path': flask_app_path,
                        'loaded': False,
                        'error': None,
                        'is_blueprint': True  # Флаг для Blueprint проектов
                    }
                
                project_items.append({
                    'name': project_name,
                    'path': project_path,
                    'index_html_path': index_html_path,
                    'has_flask': has_flask
                })
        
        # Создаём словарь существующих проектов для быстрого поиска
        existing_project_indices = {}
        children = catalog.get('children') or []
        for idx, item in enumerate(children):
            if item and isinstance(item, dict):
                url_val = item.get('url')
                if url_val and str(url_val).startswith('/projects/'):
                    project_name_from_url = url_val.split('/')[2]
                    existing_project_indices[project_name_from_url.lower()] = idx
        
        # Сначала удаляем все существующие проекты из каталога (сохраняя их настройки)
        saved_project_settings = {}
        for proj_info in project_items:
            project_name = proj_info['name']
            existing_idx = existing_project_indices.get(project_name.lower())
            if existing_idx is not None:
                existing_project = children[existing_idx]
                # Сохраняем пользовательские настройки (иконку, имя)
                icon_to_use = "page/logo.png"
                if existing_project.get('icon'):
                    existing_icon = existing_project.get('icon', '')
                    if existing_icon and existing_icon.strip() != '' and existing_icon != 'page/logo.png':
                        icon_to_use = existing_icon
                
                saved_project_settings[project_name.lower()] = {
                    'icon': icon_to_use,
                    'name': existing_project.get('name', project_name)
                }
        
        # Удаляем старые записи проектов из каталога (начиная с конца, чтобы индексы не сдвигались)
        for project_name in sorted(existing_project_indices.keys(), key=lambda k: existing_project_indices[k], reverse=True):
            idx = existing_project_indices[project_name]
            children.pop(idx)
        
        # Добавляем все проекты в начало каталога в алфавитном порядке
        # Получаем префикс пути из SCRIPT_NAME для корректной работы в подкаталоге (например, /navigator)
        path_prefix = request.environ.get('SCRIPT_NAME', '').rstrip('/')
        # Если path_prefix пустой, используем глобальный URL_PREFIX
        if not path_prefix:
            path_prefix = URL_PREFIX
        for proj_info in sorted(project_items, key=lambda x: x['name']):
            project_name = proj_info['name']
            settings = saved_project_settings.get(project_name.lower(), {})
            
            project_item = {
                "name": settings.get('name', project_name),
                "icon": settings.get('icon', "page/logo.png"),
                "children": None,
                "url": f"{path_prefix}/projects/{project_name}/index.html",
                "modified": datetime.fromtimestamp(os.path.getmtime(proj_info['index_html_path'])).strftime('%Y-%m-%d %H:%M'),
                "permanent": True,
                "has_flask": proj_info['has_flask']
            }
            catalog["children"].insert(0, project_item)
    
    response = jsonify(catalog)
    # Добавляем заголовки для предотвращения кэширования API ответов
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/api/parser/status')
@login_required
@admin_required_decorator
def get_parser_status():
    """
    API endpoint для получения статуса парсера
    
    Returns:
        Response: JSON объект со статусом парсера и логами
    """
    return jsonify({
        'status': parser_status.get('running', False),
        'running': parser_status.get('running', False),
        'last_run': parser_status.get('last_run'),
        'message': parser_status.get('message', 'Нет данных'),
        'images': parser_status.get('images', []),
        'logs': parser_logs[-50:],  # Возвращаем последние 50 записей лога
        'error_logs_available': os.path.exists(ERROR_LOG_FILE)  # Флаг наличия файла ошибок
    })


@app.route('/api/parser/start', methods=['POST'])
@login_required
@admin_required_decorator
@csrf.exempt  # Освободить от CSRF защиты
def start_parser():
    """
    API endpoint для запуска парсера
    
    Запускает парсинг в фоновом потоке если он ещё не запущен.
    
    Returns:
        Response: JSON объект со статусом операции
    """
    if not parser_status['running']:
        # Сразу обновляем статус перед запуском потока
        parser_status['running'] = True
        parser_status['message'] = 'Парсинг запущен...'
        
        thread = threading.Thread(target=run_parser_task)
        thread.daemon = True
        thread.start()
        return jsonify({'status': 'started'})
    return jsonify({'status': 'already_running'})


@app.route('/api/parser/stop', methods=['POST'])
@login_required
@admin_required_decorator
@csrf.exempt  # Освободить от CSRF защиты
def stop_parser():
    """
    API endpoint для остановки парсера
    
    Останавливает парсинг (устанавливает флаг running в False).
    
    Returns:
        Response: JSON объект со статусом операции
    """
    if parser_status['running']:
        parser_status['running'] = False
        parser_status['message'] = 'Парсинг остановлен пользователем'
        return jsonify({'status': 'stopped'})
    return jsonify({'status': 'not_running'})


@app.route('/api/parser/reset', methods=['POST'])
@login_required
@admin_required_decorator
@csrf.exempt  # Освободить от CSRF защиты
def reset_parser():
    """
    API endpoint для сброса статуса парсера
    
    Сбрасывает статус парсера в начальное состояние.
    
    Returns:
        Response: JSON объект со статусом операции
    """
    global parser_status
    parser_status = {'running': False, 'last_run': None, 'message': 'Парсер не запущен', 'images': parser_status.get('images', [])}
    return jsonify({'status': 'reset'})


@app.route('/api/parser/error-logs')
@login_required
@admin_required_decorator
def get_error_logs():
    """
    API endpoint для получения логов ошибок парсера
    
    Возвращает логи ошибок из JSON файла, который сохраняется при ошибках парсинга.
    
    Returns:
        Response: JSON объект с логами ошибок
    """
    # Аудит: просмотр логов ошибок
    audit_web_resource('view', 'error_logs', description='Просмотр логов ошибок парсера')
    
    try:
        if os.path.exists(ERROR_LOG_FILE):
            with open(ERROR_LOG_FILE, 'r', encoding='utf-8') as f:
                logs = json.load(f)
            return jsonify(logs)
        else:
            return jsonify({'errors': [], 'message': 'Файл логов ещё не создан'})
    except json.JSONDecodeError as e:
        return jsonify({'error': f'Ошибка чтения JSON: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': f'Ошибка: {str(e)}'}), 500


@app.route('/api/parser/debug-log', methods=['GET', 'DELETE'])
@login_required
@admin_required_decorator
def get_parser_debug_log():
    """
    API endpoint для получения/удаления детальных логов отладки парсера
    
    GET: Возвращает полные ответы сервера с заголовками и контентом для отладки.
    DELETE: Удаляет файл отладочных логов.
    
    Returns:
        Response: JSON объект с детальными логами или статусом удаления
    """
    try:
        debug_log_file = os.path.join(os.path.dirname(__file__), 'parser_debug_log.json')
        
        # Обработка DELETE запроса - удаление логов
        if request.method == 'DELETE':
            if os.path.exists(debug_log_file):
                os.remove(debug_log_file)
                return jsonify({'success': True, 'message': 'Отладочные логи успешно удалены'})
            else:
                return jsonify({'success': True, 'message': 'Файл отладочных логов не существует'})
        
        # Обработка GET запроса - получение логов
        if os.path.exists(debug_log_file):
            with open(debug_log_file, 'r', encoding='utf-8') as f:
                logs = json.load(f)
            return jsonify(logs)
        else:
            return jsonify({'responses': [], 'message': 'Файл отладочных логов ещё не создан'})
    except json.JSONDecodeError as e:
        return jsonify({'error': f'Ошибка чтения JSON: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': f'Ошибка: {str(e)}'}), 500


@app.route('/api/audit/logs', methods=['GET', 'POST', 'OPTIONS'])
@csrf.exempt  # Отключаем CSRF для POST запросов от фронтенда
def handle_audit_logs():
    """
    API endpoint для работы с журналом аудита
    
    GET: Возвращает записи журнала аудита с фильтрацией и пагинацией.
         Требуется авторизация администратора.
    
    POST: Добавляет новую запись в журнал аудита.
          Доступно без авторизации для фронтенд-событий.
    
    OPTIONS: Обработка preflight запросов для CORS.
    
    Query Parameters (для GET):
        date (str, optional): Дата в формате YYYY-MM-DD
        limit (int, optional): Максимальное количество записей (по умолчанию 100)
        offset (int, optional): Смещение для пагинации (по умолчанию 0)
        event_type (str, optional): Фильтр по типу события
        object_id (str, optional): Фильтр по ID объекта
    
    Request Body (для POST):
        event_type (str): Тип события
        object_id (str): Идентификатор объекта
        object_type (str, optional): Тип объекта
        description (str, optional): Описание
        additional_data (dict, optional): Дополнительные данные
    
    Returns:
        Response: JSON объект с записями аудита (GET) или подтверждением создания (POST)
    """
    from flask_login import current_user
    
    # Обработка OPTIONS запроса для CORS preflight
    if request.method == 'OPTIONS':
        response = make_response('')
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-CSRFToken'
        return response
    
    if request.method == 'POST':
        # Обработка POST запроса - добавление записи аудита от фронтенда
        try:
            data = request.get_json()
            
            if not data or 'event_type' not in data or 'object_id' not in data:
                return jsonify({'error': 'Требуемые поля: event_type и object_id'}), 400
            
            event_type = data.get('event_type')
            object_id = data.get('object_id')
            object_type = data.get('object_type', 'web_event')
            description = data.get('description', '')
            additional_data = data.get('additional_data', {})
            
            # Получаем имя пользователя если доступна авторизация
            username = current_user.username if hasattr(current_user, 'username') and current_user.is_authenticated else None
            
            # Создаем запись аудита через log_audit_event
            from utils.audit_utils import log_audit_event
            audit_entry = log_audit_event(
                event_type=event_type,
                object_id=object_id,
                object_type=object_type,
                description=description,
                additional_data=additional_data,
                username=username
            )
            
            return jsonify({
                'success': True,
                'message': 'Событие аудита сохранено',
                'audit_id': audit_entry.get('id')
            }), 201
            
        except Exception as e:
            app.logger.error(f"Ошибка при сохранении события аудита: {e}")
            return jsonify({'error': f'Ошибка: {str(e)}'}), 500
    
    else:  # GET запрос
        # Требуется авторизация администратора для просмотра логов
        if not current_user.is_authenticated or not getattr(current_user, 'is_admin', False):
            return jsonify({'error': 'Требуется авторизация администратора'}), 403
        
        # Аудит: просмотр журнала аудита
        audit_web_resource('view', 'audit_logs', description='Просмотр журнала аудита')
        
        try:
            date = request.args.get('date')
            limit = int(request.args.get('limit', 100))
            offset = int(request.args.get('offset', 0))
            event_type = request.args.get('event_type')
            object_id = request.args.get('object_id')
            
            result = load_audit_logs(
                date=date,
                limit=limit,
                offset=offset,
                event_type=event_type,
                object_id=object_id
            )
            
            return jsonify(result)
        except ValueError as e:
            return jsonify({'error': f'Неверный формат параметров: {str(e)}'}), 400
        except Exception as e:
            audit_error('audit_logs_error', 'audit_logs', 
                       description=f'Ошибка получения журнала аудита: {str(e)}',
                       exception=e)
            return jsonify({'error': f'Ошибка: {str(e)}'}), 500


@app.route('/navigator/api/audit/clear', methods=['POST'])
@login_required
@admin_required_decorator
@csrf.exempt
def clear_audit_logs_route():
    """
    API endpoint для очистки журнала аудита
    
    Request Body:
        date (str, optional): Дата для очистки. Если не указана, очищается текущий день.
    
    Returns:
        Response: JSON объект со статусом операции
    """
    # Аудит: очистка журнала аудита
    audit_web_resource('change', 'audit_logs', description='Очистка журнала аудита')
    
    try:
        data = request.json or {}
        date = data.get('date')
        
        success = clear_audit_logs(date=date)
        
        if success:
            return jsonify({'status': 'success', 'message': 'Журнал аудита очищен'})
        else:
            return jsonify({'status': 'error', 'message': 'Ошибка при очистке журнала'}), 500
    except Exception as e:
        audit_error('audit_clear_error', 'audit_logs',
                   description=f'Ошибка очистки журнала аудита: {str(e)}',
                   exception=e)
        return jsonify({'error': f'Ошибка: {str(e)}'}), 500


@app.route('/api/import/json', methods=['POST'])
@login_required
@admin_required_decorator
@csrf.exempt  # Освободить от CSRF защиты
def import_json():
    """
    API endpoint для импорта JSON данных
    
    Принимает JSON файл или данные и добавляет их в каталог.
    
    Request Body:
        json_data: JSON строка с данными для импорта
        parent_path: Путь родительской папки (опционально)
    
    Returns:
        Response: JSON объект со статусом операции
    """
    try:
        data = request.json
        json_data = data.get('json_data')
        parent_path = data.get('parent_path', '')
        
        if not json_data:
            return jsonify({'error': 'JSON данные не предоставлены'}), 400
        
        # Парсинг JSON данных
        imported_items = json.loads(json_data)
        
        # Загрузка каталога
        catalog = load_catalog(CATALOG_FILE)
        
        # Определение целевого списка для добавления
        if not parent_path:
            target_list = catalog['children']
        else:
            parent_item = find_item_by_path(catalog['children'], parent_path)
            if parent_item and 'children' in parent_item:
                target_list = parent_item['children']
            else:
                return jsonify({'error': 'Родительская папка не найдена'}), 404
        
        # Функция для рекурсивного добавления элементов
        def add_imported_items(items, target):
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        target.append(item)
                    elif isinstance(item, list):
                        add_imported_items(item, target)
            elif isinstance(items, dict):
                target.append(items)
        
        add_imported_items(imported_items, target_list)
        save_catalog(CATALOG_FILE, catalog)
        
        # Аудит: добавление ресурса через импорт
        audit_web_resource('add', 'import_json', description=f'Импорт JSON данных: {len(target_list)} элементов')
        
        return jsonify({'status': 'success', 'message': f'Импортировано элементов: {len(target_list)}'})
    
    except json.JSONDecodeError as e:
        return jsonify({'error': f'Ошибка парсинга JSON: {str(e)}'}), 400
    except Exception as e:
        return jsonify({'error': f'Ошибка импорта: {str(e)}'}), 500


@app.route('/api/permanent', methods=['GET', 'POST', 'DELETE'])
@login_required
@admin_required_decorator
@csrf.exempt  # Освободить от CSRF защиты
def permanent_api():
    """
    API endpoint для управления постоянными элементами
    
    Методы:
        GET: Получить список всех постоянных элементов
        POST: Добавить новый постоянный элемент
        DELETE: Удалить элемент из списка постоянных
    
    Returns:
        Response: JSON объект со статусом операции или списком элементов
    """
    permanent_data = load_permanent_items(PERMANENT_FILE)
    
    if request.method == 'POST':
        path = request.json.get('path')
        if path and path not in permanent_data['permanent_items']:
            permanent_data['permanent_items'].append(path)
            save_permanent_items(PERMANENT_FILE, permanent_data)
        return jsonify({'status': 'success'})
    
    elif request.method == 'DELETE':
        path = request.json.get('path')
        if path in permanent_data['permanent_items']:
            permanent_data['permanent_items'].remove(path)
            save_permanent_items(PERMANENT_FILE, permanent_data)
        return jsonify({'status': 'success'})
    
    return jsonify(permanent_data)


@app.route('/api/items', methods=['POST', 'PUT', 'DELETE'])
@login_required
@admin_required_decorator
@csrf.exempt  # Освободить от CSRF защиты
def items_api():
    """
    API endpoint для CRUD операций с элементами каталога
    
    Методы:
        POST: Создать новую папку
        PUT: Обновить существующий элемент
        DELETE: Удалить элемент
    
    Request Body:
        path: Путь элемента
        name: Имя элемента (для POST)
        parent_path: Путь родительской папки (для POST)
        updates: Словарь обновлений (для PUT)
    
    Returns:
        Response: JSON объект со статусом операции
    """
    catalog = load_catalog(CATALOG_FILE)
    data = request.json
    path = data.get('path', '')
    
    if request.method == 'POST':
        name = data.get('name')
        parent_path = data.get('parent_path', '')
        icon = data.get('icon', 'folder.png')
        url = data.get('url')
        
        # Определить целевой список для добавления
        if not parent_path:
            target_list = catalog['children']
        else:
            parent_item = find_item_by_path(catalog['children'], parent_path)
            if parent_item and 'children' in parent_item:
                target_list = parent_item['children']
            else:
                return jsonify({'error': 'Parent not found'}), 404
        
        # Создать новый элемент
        new_item = {'name': name, 'icon': icon, 'children': []}
        if url:
            new_item['url'] = url
        target_list.append(new_item)
        save_catalog(CATALOG_FILE, catalog)
        
        # Аудит: добавление ресурса
        audit_web_resource('add', path or name, description=f'Добавлен новый элемент: {name}')
        
        response = jsonify({'status': 'success'})
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return response
    
    elif request.method == 'DELETE':
        if delete_item_by_path(catalog['children'], path):
            save_catalog(CATALOG_FILE, catalog)
            
            # Аудит: удаление ресурса
            audit_web_resource('delete', path, description=f'Удален элемент: {path}')
            
            response = jsonify({'status': 'success'})
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            return response
        return jsonify({'error': 'Not found'}), 404
    
    elif request.method == 'PUT':
        updates = data.get('updates', {})
        
        # Если в обновлениях есть icon, нужно также установить permanent=True
        if 'icon' in updates and updates['icon']:
            updates['permanent'] = True
        
        # Попытаться обновить существующий элемент
        if update_item_by_path(catalog['children'], path, updates):
            save_catalog(CATALOG_FILE, catalog)
            
            # Аудит: изменение ресурса
            audit_web_resource('change', path, description=f'Обновлен элемент: {path}')
            
            response = jsonify({'status': 'success'})
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            return response
        
        # Элемент не найден - создать его автоматически
        # Разбить путь на части для определения родительской папки
        path_parts = path.split('/')
        if len(path_parts) > 1:
            parent_path = '/'.join(path_parts[:-1])
            item_name = path_parts[-1]
        else:
            parent_path = ''
            item_name = path
        
        # Определить целевой список для добавления
        if not parent_path:
            target_list = catalog['children']
        else:
            parent_item = find_item_by_path(catalog['children'], parent_path)
            if parent_item and 'children' in parent_item:
                target_list = parent_item['children']
            else:
                # Родительская папка не найдена - создать её рекурсивно
                # Для простоты создаём в корне
                target_list = catalog['children']
                parent_path = ''
        
        # Создать новый элемент с данными из updates
        new_item = {
            'name': updates.get('name', item_name.upper()),
            'icon': updates.get('icon', 'folder.png'),
            'children': []
        }
        if 'url' in updates:
            new_item['url'] = updates['url']
        if updates.get('permanent'):
            new_item['permanent'] = True
        
        target_list.append(new_item)
        save_catalog(CATALOG_FILE, catalog)
        response = jsonify({'status': 'created'})
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return response
    
    return jsonify({'error': 'Invalid method'}), 400


@app.route('/api/images')
def get_images():
    """
    API endpoint для получения списка всех доступных изображений
    
    Возвращает изображения, найденные парсером (из файла parser_images.json).
    НЕ сканирует папки page/ и projects/ - используем только изображения от парсера.
    
    Returns:
        Response: JSON массив объектов с информацией об изображениях в UTF-8
    """
    images = []
    seen_paths = set()  # Для предотвращения дубликатов
    
    # Загрузить изображения из парсера (сохранённые в файле)
    parser_images_data = load_json_file(PARSER_IMAGES_FILE, default={'images': []})
    parser_images = parser_images_data.get('images', [])
    
    # Добавить изображения из парсера
    for icon_url in parser_images:
        if icon_url and icon_url not in seen_paths:
            # Извлечь имя файла из URL и декодировать URL-кодирование для корректного отображения кириллицы
            try:
                # Сначала декодируем весь URL, затем извлекаем имя файла
                decoded_url = unquote(icon_url)
                filename = decoded_url.split('/')[-1]
            except:
                filename = os.path.basename(icon_url)
            images.append({'name': filename, 'path': icon_url})
            seen_paths.add(icon_url)
    
    # Также добавить изображения из текущего статуса парсера (если он активен)
    if parser_status.get('images'):
        for icon_url in parser_status['images']:
            if icon_url and icon_url not in seen_paths:
                try:
                    decoded_url = unquote(icon_url)
                    filename = decoded_url.split('/')[-1]
                except:
                    filename = os.path.basename(icon_url)
                images.append({'name': filename, 'path': icon_url})
                seen_paths.add(icon_url)
    
    # Создаем response с явным указанием кодировки UTF-8
    response = Response(
        json.dumps(images, ensure_ascii=False),
        mimetype='application/json; charset=utf-8'
    )
    # Добавляем заголовки для предотвращения кэширования API ответов
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/page/<path:filename>')
def serve_page_image(filename):
    """
    API endpoint для раздачи изображений из папки page/
    
    Args:
        filename: Путь к файлу относительно папки page/
    
    Returns:
        Response: Файл изображения
    """
    # Аудит: чтение файла из файловой системы
    audit_filesystem_read(f'page/{filename}', description=f'Чтение файла из page/: {filename}')
    
    page_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'page')
    return send_from_directory(page_dir, filename, max_age=86400)  # Кэширование на 24 часа


@app.route('/css/<path:filename>')
def serve_css(filename):
    """
    API endpoint для раздачи CSS файлов из папки css/
    
    Args:
        filename: Путь к файлу относительно папки css/
    
    Returns:
        Response: CSS файл
    """
    # Аудит: чтение файла из файловой системы
    audit_filesystem_read(f'css/{filename}', description=f'Чтение CSS файла: {filename}')
    
    css_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'css')
    response = send_from_directory(css_dir, filename, max_age=86400)
    response.headers['Content-Type'] = 'text/css; charset=utf-8'
    return response


@app.route('/js/<path:filename>')
def serve_js(filename):
    """
    API endpoint для раздачи JS файлов из папки js/
    
    Args:
        filename: Путь к файлу относительно папки js/
    
    Returns:
        Response: JS файл
    """
    # Аудит: чтение файла из файловой системы
    audit_filesystem_read(f'js/{filename}', description=f'Чтение JS файла: {filename}')
    
    js_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'js')
    response = send_from_directory(js_dir, filename, max_age=86400)
    response.headers['Content-Type'] = 'application/javascript; charset=utf-8'
    return response



# -------------------------------------------------------------------
# Маршруты для проектов (с учётом префикса /navigator)
# -------------------------------------------------------------------
# Примечание: Middleware PathPrefixMiddleware автоматически удаляет префикс
# /navigator из PATH_INFO, поэтому маршруты объявляются БЕЗ префикса.
# Пользователь обращается по адресу /navigator/projects/..., но Flask
# получает запрос как /projects/...

@app.route('/projects/<project_name>/static/<path:filename>')
def serve_project_static(project_name, filename):
    """
    API endpoint для раздачи статических файлов проектов из папки projects/<project>/static/
    
    Этот маршрут должен быть объявлен ДО общего маршрута /projects/<path:filename>,
    чтобы перехватывать запросы к статике до того, как они попадут в общий обработчик.
    Поддерживает оба варианта: с префиксом /navigator и без него.

    Args:
        project_name: Имя проекта
        filename: Путь к файлу относительно папки static проекта

    Returns:
        Response: Статический файл проекта (css, js, images, etc.)
    """
    project_path = os.path.join(PROJECTS_DIR, project_name)
    static_folder = os.path.join(project_path, 'static')
    
    # Проверяем существование проекта и папки static
    if not os.path.exists(static_folder) or not os.path.isdir(static_folder):
        return jsonify({'error': f'Статика не найдена для проекта: {project_name}'}), 404
    
    return send_from_directory(static_folder, filename, max_age=86400)


@app.route('/projects/<path:remaining_path>', methods=['GET', 'HEAD', 'OPTIONS'])
def serve_project_file_with_path(remaining_path):
    """
    API endpoint для раздачи файлов проектов с явным указанием пути
    Обработчик для запросов вида /projects/<project_name>/<остальной_путь>
    
    Args:
        remaining_path: Полный путь включая имя проекта и остальной путь
    
    Returns:
        Response: Файл проекта или ответ от Flask приложения проекта
    """
    # Декодируем URL на случай кириллических символов
    remaining_path = unquote(remaining_path)
    
    # Разделяем путь на имя проекта и остальной путь
    parts = remaining_path.split('/', 1)
    if len(parts) < 1 or not parts[0]:
        return jsonify({'error': 'Некорректный путь к проекту'}), 400
    
    project_name = parts[0]
    file_path_suffix = parts[1] if len(parts) > 1 else ''
    
    project_path = os.path.join(PROJECTS_DIR, project_name)
    
    # Аудит: открытие элемента каталога (проекта)
    audit_catalog_item_open(
        item_path=f'/projects/{project_name}/{file_path_suffix}' if file_path_suffix else f'/projects/{project_name}',
        item_name=project_name,
        status_code=200,  # Будет обновлен ниже при ошибках
        item_type='project'
    )
    
    # Проверяем существование проекта
    if not os.path.exists(project_path) or not os.path.isdir(project_path):
        # Обновляем аудит с ошибкой 404
        audit_catalog_item_open(
            item_path=f'/projects/{project_name}',
            item_name=project_name,
            status_code=404,
            item_type='project',
            description=f'Проект не найден: {project_name}'
        )
        return jsonify({'error': f'Проект не найден: {project_name}'}), 404
    
    # Проверяем, есть ли у этого проекта Flask приложение
    if project_name in project_flask_info:
        flask_info = project_flask_info[project_name]
        
        # Загружаем Flask приложение при первом запросе, если ещё не загружено
        if not flask_info.get('loaded') and flask_info.get('app_path'):
            try:
                import importlib.util
                import sys
                
                # Добавляем директорию проекта в sys.path для корректных импортов
                project_dir = os.path.dirname(flask_info['app_path'])
                if project_dir not in sys.path:
                    sys.path.insert(0, project_dir)
                
                spec = importlib.util.spec_from_file_location(f"{project_name}_app", flask_info['app_path'])
                if spec and spec.loader:
                    project_module = importlib.util.module_from_spec(spec)
                    # Добавляем проект в sys.modules для корректной работы импортов
                    sys.modules[f"{project_name}_app"] = project_module
                    spec.loader.exec_module(project_module)
                    
                    # Проверяем, является ли проект Blueprint
                    if flask_info.get('is_blueprint') and hasattr(project_module, 'parad_zvezd_bp'):
                        # Это Blueprint - сохраняем его для последующей регистрации
                        blueprint = project_module.parad_zvezd_bp
                        project_flask_info[project_name]['blueprint'] = blueprint
                        project_flask_info[project_name]['loaded'] = True
                        print(f"Blueprint '{project_name}' загружен (статика: {blueprint.static_url_path})")
                    elif hasattr(project_module, 'app'):
                        # Это обычное Flask приложение
                        flask_app = project_module.app
                        project_flask_info[project_name]['app'] = flask_app
                        project_flask_info[project_name]['loaded'] = True
                        print(f"Flask приложение '{project_name}' успешно загружено")
            except Exception as e:
                error_msg = f"Ошибка загрузки Flask приложения '{project_name}': {e}"
                print(error_msg)
                import traceback
                traceback.print_exc()
                project_flask_info[project_name]['error'] = error_msg
                pass
        
        # Если Flask приложение загружено, пробуем обработать запрос через него
        if flask_info.get('loaded') and 'app' in flask_info and not flask_info.get('is_blueprint'):
            flask_app = flask_info['app']
            try:
                environ = request.environ.copy()
                environ['PATH_INFO'] = '/' + file_path_suffix
                environ['SCRIPT_NAME'] = f'/projects/{project_name}'
                
                response_iter = flask_app(environ, lambda status, headers: None)
                
                if response_iter:
                    from flask import Response
                    if isinstance(response_iter, Response):
                        return response_iter
                    body = b''.join(response_iter)
                    return Response(body, status='200 OK', content_type='text/html; charset=utf-8')
            except Exception as e:
                print(f"Ошибка обработки запроса Flask приложением '{project_name}': {e}")
                import traceback
                traceback.print_exc()
    
    # Стандартная обработка - пробуем найти файл
    if file_path_suffix:
        file_path = os.path.join(project_path, file_path_suffix)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            # Аудит: успешное открытие файла проекта
            audit_catalog_item_open(
                item_path=f'/projects/{project_name}/{file_path_suffix}',
                item_name=file_path_suffix,
                status_code=200,
                item_type='file'
            )
            return send_from_directory(project_path, file_path_suffix, max_age=86400)
        
        # Для проектов с шаблонами в templates/
        templates_path = os.path.join(project_path, 'templates', file_path_suffix)
        if os.path.exists(templates_path) and os.path.isfile(templates_path):
            # Аудит: успешное открытие файла из templates
            audit_catalog_item_open(
                item_path=f'/projects/{project_name}/templates/{file_path_suffix}',
                item_name=file_path_suffix,
                status_code=200,
                item_type='template'
            )
            return send_from_directory(os.path.join(project_path, 'templates'), file_path_suffix, max_age=86400)
        
        # Для статических файлов в static/
        static_path = os.path.join(project_path, 'static', file_path_suffix)
        if os.path.exists(static_path) and os.path.isfile(static_path):
            # Аудит: успешное открытие файла из static
            audit_catalog_item_open(
                item_path=f'/projects/{project_name}/static/{file_path_suffix}',
                item_name=file_path_suffix,
                status_code=200,
                item_type='static'
            )
            return send_from_directory(os.path.join(project_path, 'static'), file_path_suffix, max_age=86400)
    else:
        # Если file_path_suffix пустой, отдаём index.html
        index_path = os.path.join(project_path, 'index.html')
        if os.path.exists(index_path) and os.path.isfile(index_path):
            # Аудит: успешное открытие index.html проекта
            audit_catalog_item_open(
                item_path=f'/projects/{project_name}/index.html',
                item_name='index.html',
                status_code=200,
                item_type='index'
            )
            return send_from_directory(project_path, 'index.html', max_age=86400)
    
    # Аудит: файл не найден (404)
    audit_catalog_item_open(
        item_path=f'/projects/{project_name}/{file_path_suffix}' if file_path_suffix else f'/projects/{project_name}',
        item_name=file_path_suffix or 'index.html',
        status_code=404,
        item_type='file',
        description=f'Файл не найден: {file_path_suffix}'
    )
    return jsonify({'error': f'Файл не найден: {file_path_suffix}'}), 404


@app.route('/api/proxy-image')
def proxy_image():
    """
    API endpoint для проксирования изображений с внешних URL
    
    Используется для обхода CORS и rate limiting при загрузке изображений
    с FTP-сервера vm-ftp.anosov.ru
    
    Query params:
        url: Полный URL изображения
    
    Returns:
        Response: Изображение с appropriate Content-Type
    """
    image_url = request.args.get('url', '')
    
    if not image_url:
        return jsonify({'error': 'URL не указан'}), 400
    
    # Проверка, что URL принадлежит нашему доверенному домену
    parsed = urlparse(image_url)
    if parsed.netloc != 'vm-ftp.anosov.ru':
        return jsonify({'error': 'Недоверенный домен'}), 403
    
    try:
        # Загружаем изображение с внешнего сервера
        # Используем verify=False для самоподписанных сертификатов
        response = requests.get(image_url, timeout=10)
        response.raise_for_status()
        
        # Определяем Content-Type
        content_type = response.headers.get('Content-Type', 'image/jpeg')
        
        # Создаём ответ с правильными заголовками
        proxy_response = Response(
            response.content,
            status=200,
            content_type=content_type
        )
        
        # Добавляем заголовки для кэширования
        proxy_response.headers['Cache-Control'] = 'public, max-age=86400'
        
        return proxy_response
        
    except requests.exceptions.RequestException as e:
        return jsonify({'error': f'Ошибка загрузки: {str(e)}'}), 500


@app.route('/api/video-proxy')
def proxy_video():
    """
    API endpoint для проксирования видеофайлов с внешних URL
    
    Используется для открытия видео в браузере вместо скачивания.
    Устанавливает правильный Content-Type и убирает Content-Disposition: attachment.
    Поддерживает Range requests для потоковой передачи.
    
    Query params:
        url: Полный URL видеофайла
    
    Returns:
        Response: Видеофайл с правильным Content-Type для воспроизведения в браузере
    """
    video_url = request.args.get('url', '')
    
    if not video_url:
        return jsonify({'error': 'URL не указан'}), 400
    
    # Проверка, что URL принадлежит нашему доверенному домену
    parsed = urlparse(video_url)
    allowed_domains = ['vm-ftp.anosov.ru', 'testnavi.onrender.com']
    if parsed.netloc not in allowed_domains:
        return jsonify({'error': 'Недоверенный домен'}), 403
    
    try:
        # Определяем Content-Type по расширению файла
        video_content_types = {
            '.mp4': 'video/mp4',
            '.webm': 'video/webm',
            '.ogg': 'video/ogg',
            '.mov': 'video/quicktime',
            '.avi': 'video/x-msvideo',
            '.mkv': 'video/x-matroska',
            '.flv': 'video/x-flv',
            '.wmv': 'video/x-ms-wmv',
            '.m4v': 'video/x-m4v'
        }

        # Получаем расширение из URL (декодируем проценты и убираем пробелы)
        from urllib.parse import unquote
        decoded_url = unquote(video_url).strip()
        ext = os.path.splitext(decoded_url)[1].lower()
        content_type = video_content_types.get(ext, 'video/mp4')

        # Сначала получаем информацию о файле (размер) с правильным User-Agent
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive'
        }
        
        head_response = requests.head(video_url, headers=headers, timeout=30, allow_redirects=True, verify=False)
        head_response.raise_for_status()
        file_size = int(head_response.headers.get('Content-Length', 0))
        
        # Проверяем поддержку Range запросов на удалённом сервере
        supports_ranges = head_response.headers.get('Accept-Ranges', '').lower() == 'bytes'
        
        # Обрабатываем Range запрос от браузера
        range_header = request.headers.get('Range', '')
        
        if range_header and supports_ranges and file_size > 0:
            # Браузер запрашивает часть файла (для перемотки)
            range_match = re.match(r'bytes=(\d+)-(\d*)', range_header)
            if range_match:
                start = int(range_match.group(1))
                end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
                end = min(end, file_size - 1)
                
                # Запрашиваем диапазон с удалённого сервера
                headers['Range'] = f'bytes={start}-{end}'
                response = requests.get(video_url, headers=headers, timeout=60, stream=True, verify=False)
                response.raise_for_status()
                
                # Возвращаем частичный контент
                proxy_response = Response(
                    response.iter_content(chunk_size=8192),
                    status=206,  # Partial Content
                    mimetype=content_type
                )
                proxy_response.headers['Content-Length'] = str(end - start + 1)
                proxy_response.headers['Content-Range'] = f'bytes {start}-{end}/{file_size}'
                proxy_response.headers['Accept-Ranges'] = 'bytes'
                # КРИТИЧЕСКИ ВАЖНО: Устанавливаем inline и убираем любые следы attachment
                proxy_response.headers['Content-Disposition'] = f'inline; filename*=UTF-8\'\'{os.path.basename(decoded_url)}'
                # Убираем заголовки, которые могут вызвать скачивание в Edge
                proxy_response.headers.pop('X-Download-Options', None)
                return proxy_response
        
        # Если нет Range запроса или сервер не поддерживает ranges - отдаём всё видео
        response = requests.get(video_url, headers=headers, timeout=60, stream=True, verify=False)
        response.raise_for_status()
        
        # Создаём ответ для клиента
        proxy_response = Response(
            response.iter_content(chunk_size=8192),
            status=response.status_code,
            mimetype=content_type
        )

        # Копируем важные заголовки от оригинального ответа
        if file_size > 0:
            proxy_response.headers['Content-Length'] = str(file_size)

        # Критически важные заголовки для воспроизведения вместо скачивания:
        # 1. Content-Disposition: inline - говорит браузеру отображать файл
        # Используем filename* для лучшей совместимости с UTF-8 именами
        proxy_response.headers['Content-Disposition'] = f'inline; filename*=UTF-8\'\'{os.path.basename(decoded_url)}'
        # 2. Accept-Ranges: bytes - поддержка перемотки
        proxy_response.headers['Accept-Ranges'] = 'bytes'
        # 3. Cache-Control - кэширование для лучшей производительности
        proxy_response.headers['Cache-Control'] = 'public, max-age=3600'
        # 4. Убираем заголовки, которые могут вызвать скачивание в Edge
        proxy_response.headers.pop('X-Download-Options', None)
        proxy_response.headers.pop('Content-Transfer-Encoding', None)

        return proxy_response

    except requests.exceptions.RequestException as e:
        return jsonify({'error': f'Ошибка загрузки видео: {str(e)}'}), 500


if __name__ == '__main__':
    # Убедиться, что директория данных существует
    ensure_data_dir(DATA_DIR)
    
    # Инициализировать файл пользователей если не существует
    load_users(USERS_FILE, hash_password)
    
    print("🚀 Запуск сервера...")
    app.run(debug=True, host='0.0.0.0', port=5000)
