# Блок-схема авторизации в app.py

## Общая схема процесса авторизации

```mermaid
flowchart TD
    A[Начало] --> B{Запрос к /login}
    B -->|GET| C[Отображение формы входа]
    B -->|POST| D[Получение данных из формы]
    
    C --> E[Конец - ожидание ввода]
    D --> F{Пользователь уже<br/>авторизован?}
    F -->|Да| G[Редирект на /navigator/]
    F -->|Нет| H{username и password<br/>заполнены?}
    
    H -->|Нет| I[Установить error message]
    H -->|Да| J[Загрузка пользователей из JSON]
    
    I --> C
    J --> K{Пользователь найден?}
    K -->|Нет| L[Установить error:<br/>'Неверное имя пользователя или пароль']
    K -->|Да| M{Пароль верный?}
    
    L --> C
    M -->|Нет| L
    M -->|Да| N[Создание объекта User]
    
    N --> O[login_user - создание сессии]
    O --> P[Flash сообщение об успехе]
    P --> Q{Есть next параметр?}
    
    Q -->|Нет| R[Редирект на /navigator/admin]
    Q -->|Да| S[Добавление префикса URL_PREFIX<br/>к next если нужно]
    
    S --> T[Редирект на next страницу]
    R --> U[Конец]
    T --> U
    G --> U
```

## Детальная схема проверки учётных данных

```mermaid
flowchart TD
    A[POST /login] --> B[username = request.form.get('username')]
    B --> C[password = request.form.get('password')]
    C --> D[remember = request.form.get('remember')]
    
    D --> E{Поля заполнены?}
    E -->|Нет| F[error = 'Введите имя пользователя и пароль']
    E -->|Да| G[users_data = load_users USERS_FILE]
    
    F --> H[Рендер login.html с error]
    G --> I[Цикл по всем пользователям]
    
    I --> J{username совпадает?}
    J -->|Нет| K{Есть ещё пользователи?}
    J -->|Да| L[user_found = текущий пользователь]
    
    K -->|Да| I
    K -->|Нет| M[error = 'Неверное имя пользователя или пароль']
    M --> H
    
    L --> N[verify_password password, user_found.password_hash]
    N --> O{Пароль верный?}
    O -->|Нет| M
    O -->|Да| P[User object = User id, username, is_admin]
    
    P --> Q[login_user user_obj, remember=remember]
    Q --> R[flash 'Вы успешно вошли в систему']
    
    R --> S{next параметр существует?}
    S -->|Нет| T[redirect URL_PREFIX + '/admin']
    S -->|Да| U{URL_PREFIX в next?}
    
    U -->|Нет| V[Добавить URL_PREFIX к next]
    U -->|Да| W[Использовать next как есть]
    
    V --> X[redirect next_page]
    W --> X
    T --> Y[Конец]
    X --> Y
```

## Схема работы Flask-Login middleware

```mermaid
flowchart TD
    A[Входящий запрос] --> B{Пользователь<br/>авторизован?}
    B -->|Да| C[Обработка запроса]
    B -->|Нет| D{Защищённый маршрут?<br/>@login_required}
    
    D -->|Нет| C
    D -->|Да| E[unauthorized_handler]
    
    E --> F[Получить текущий путь]
    F --> G[redirect login_url с next параметром]
    
    G --> H[Страница /login]
    H --> I[Успешная авторизация]
    I --> J[redirect на next или /admin]
    
    J --> K[Запрос повторён]
    K --> C
```

## Схема загрузки пользователя из сессии

```mermaid
flowchart TD
    A[Новый запрос с сессией] --> B[Flask-Login вызывает load_user]
    B --> C[load_user user_id из сессии]
    
    C --> D[load_users USERS_FILE]
    D --> E[Цикл по users в файле]
    
    E --> F{user.id == user_id?}
    F -->|Нет| G{Есть ещё пользователи?}
    F -->|Да| H[Вернуть User object]
    
    G -->|Да| E
    G -->|Нет| I[Вернуть None]
    
    H --> J[current_user установлен]
    I --> K[current_user = AnonymousUser]
    
    J --> L[Продолжить обработку запроса]
    K --> L
```

## Схема выхода из системы (logout)

```mermaid
flowchart TD
    A[GET /logout] --> B{@login_required проверка}
    B --> C{Пользователь<br/>авторизован?}
    
    C -->|Нет| D[redirect на login]
    C -->|Да| E[logout_user]
    
    E --> F[Удаление сессии пользователя]
    F --> G[flash 'Вы вышли из системы']
    
    G --> H[redirect URL_PREFIX + '/']
    H --> I[Конец - главная страница]
    
    D --> I
```

## Последовательность событий при авторизации

```mermaid
sequenceDiagram
    participant Browser
    participant Flask
    participant LoginManager
    participant AuthUtils
    participant JSONFile
    
    Browser->>Flask: GET /login
    Flask->>Browser: render_template login.html
    
    Browser->>Flask: POST /login<br/>(username, password)
    Flask->>Flask: Проверка current_user.is_authenticated
    
    Flask->>JSONFile: load_users USERS_FILE
    JSONFile-->>Flask: Список пользователей
    
    Flask->>AuthUtils: verify_password password, hash
    AuthUtils-->>Flask: True/False
    
    alt Пароль верный
        Flask->>AuthUtils: Создать User object
        Flask->>LoginManager: login_user user_obj
        
        LoginManager->>JSONFile: Сохранить session cookie
        JSONFile-->>Browser: Set-Cookie: session=...
        
        Flask->>Browser: redirect /navigator/admin
    else Пароль неверный
        Flask->>Browser: render_template с error
    end
```

## Ключевые компоненты системы авторизации

### 1. Инициализация (в начале app.py)
```python
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = LOGIN_MESSAGE
login_manager.session_protection = SESSION_PROTECTION
```

### 2. Callback функция load_user
```python
@login_manager.user_loader
def load_user(user_id):
    users_data = load_users(USERS_FILE, hash_password)
    for user in users_data.get('users', []):
        if str(user['id']) == str(user_id):
            return User(user['id'], user['username'], user.get('is_admin', False))
    return None
```

### 3. Декораторы защиты маршрутов
```python
@app.route('/logout')
@login_required  # Требует авторизации
def logout():
    ...

@app.route('/admin')
@admin_required  # Требует прав администратора
def admin_panel():
    ...
```

### 4. Обработчик неавторизованного доступа
```python
@login_manager.unauthorized_handler
def unauthorized():
    current_path = urlparse(request.url).path
    return redirect(login_manager.login_url(current_path))
```

## Точки расширения безопасности

1. **Rate Limiting**: `@limiter.limit(RATELIMIT_LOGIN)` - защита от брутфорса
2. **CSRF Protection**: `csrf_token()` в форме - защита от CSRF атак
3. **Password Hashing**: `hash_password()` / `verify_password()` - хеширование паролей
4. **Session Protection**: `login_manager.session_protection` - защита сессии
5. **Remember Me**: Опция запоминания пользователя через cookie
