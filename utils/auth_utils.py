"""Утилиты для аутентификации и управления пользователями"""
import bcrypt
from datetime import datetime
from flask_login import UserMixin
from functools import wraps
from flask import flash, redirect, url_for, request
from flask_login import current_user


class User(UserMixin):
    """Класс пользователя для Flask-Login"""
    def __init__(self, id, username, is_admin=False):
        self.id = id
        self.username = username
        self.is_admin = is_admin
    
    def get_id(self):
        return str(self.id)


def hash_password(password):
    """Хеширование пароля с bcrypt"""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password, password_hash):
    """Проверка пароля по хешу"""
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except Exception:
        return False


def create_user(username, password, is_admin=False):
    """Создать структуру данных пользователя"""
    return {
        "id": None,
        "username": username,
        "password_hash": hash_password(password),
        "is_admin": is_admin,
        "created_at": datetime.now().isoformat()
    }


def admin_required_decorator(f):
    """Декоратор для ограничения доступа администраторам"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, 'is_admin', False):
            # Проверяем, является ли запрос API запросом
            if request.path.startswith('/api/'):
                # Для API возвращаем JSON 401 вместо редиректа
                from flask import jsonify
                return jsonify({'error': 'Требуется авторизация администратора', 'status': 'unauthorized'}), 401
            
            flash('Требуется права администратора', 'error')
            
            # Получаем префикс из SCRIPT_NAME, который устанавливается middleware
            script_name = request.environ.get('SCRIPT_NAME', '').rstrip('/')
            
            # Если SCRIPT_NAME пустой, используем дефолтный префикс
            if not script_name:
                script_name = '/navigator'
            
            # Строим URL страницы входа с учётом префикса
            login_url = script_name + '/login'
            
            # Добавляем параметр next, чтобы после входа вернуться на запрошенную страницу
            # request.path содержит путь БЕЗ префикса (так как middleware удалил префикс)
            # но нам нужен полный путь от корня сайта для параметра next
            # Используем script_name + request.path для получения правильного пути
            full_next = script_name + request.path
            
            return redirect(login_url + '?next=' + full_next)
        return f(*args, **kwargs)
    return decorated_function
