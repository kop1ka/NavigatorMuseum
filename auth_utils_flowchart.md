# Блок-схема utils/auth_utils.py

```mermaid
flowchart TD
    subgraph "User Class - Класс пользователя"
        U1[("Начало: User.__init__")] --> U2["Установка id, username, is_admin"]
        U2 --> U3["Возврат объекта User"]
        U4[("User.get_id")] --> U5["Вернуть str(self.id)"]
        U5 --> U6[("Конец")]
    end

    subgraph "hash_password - Хеширование пароля"
        H1[("Начало: hash_password(password)")] --> H2["Закодировать пароль в bytes"]
        H2 --> H3["Сгенерировать соль bcrypt.gensalt()"]
        H3 --> H4["Создать хеш bcrypt.hashpw()"]
        H4 --> H5["Декодировать хеш в строку"]
        H5 --> H6["Вернуть хеш"]
        H6 --> H7[("Конец")]
    end

    subgraph "verify_password - Проверка пароля"
        V1[("Начало: verify_password(password, password_hash)")] --> V2{try block}
        V2 -->|success| V3["Закодировать пароль в bytes"]
        V3 --> V4["Закодировать хеш в bytes"]
        V4 --> V5["bcrypt.checkpw()"]
        V5 --> V6["Вернуть True/False"]
        V6 --> V8[("Конец")]
        V2 -->|exception| V7["Вернуть False"]
        V7 --> V8
    end

    subgraph "create_user - Создание пользователя"
        C1[("Начало: create_user(username, password, is_admin)")] --> C2["Вызвать hash_password(password)"]
        C2 --> C3["Получить текущее время datetime.now().isoformat()"]
        C3 --> C4["Создать словарь пользователя"]
        C4 --> C5["id: None<br/>username: username<br/>password_hash: хеш<br/>is_admin: is_admin<br/>created_at: timestamp"]
        C5 --> C6["Вернуть словарь"]
        C6 --> C7[("Конец")]
    end

    subgraph "admin_required_decorator - Декоратор администратора"
        A1[("Начало: admin_required_decorator(f)")] --> A2["Обернуть функцию f"]
        A2 --> A3[("decorated_function(*args, **kwargs)")]
        A3 --> A4{"current_user.is_authenticated<br/>AND<br/>current_user.is_admin?"}
        A4 -->|Да (авторизован)| A5["Вызвать f(*args, **kwargs)"]
        A5 --> A15["Вернуть результат f"]
        A15 --> A16[("Конец")]
        A4 -->|Нет (не авторизован)| A6{"request.path<br/>startswith('/api/')?"}
        A6 -->|Да (API запрос)| A7["Импортировать jsonify"]
        A7 --> A8["Вернуть JSON 401:<br/>{error: 'Требуется авторизация администратора',<br/>status: 'unauthorized'}"]
        A8 --> A16
        A6 -->|Нет (веб запрос)| A9["flash('Требуется права администратора', 'error')"]
        A9 --> A10["Получить SCRIPT_NAME из environ"]
        A10 --> A11{"SCRIPT_NAME пустой?"}
        A11 -->|Да| A12["script_name = '/navigator'"]
        A11 -->|Нет| A13["script_name = SCRIPT_NAME.rstrip('/')"]
        A12 --> A14
        A13 --> A14["login_url = script_name + '/login'"]
        A14 --> A17["full_next = script_name + request.path"]
        A17 --> A18["redirect(login_url + '?next=' + full_next)"]
        A18 --> A16
    end

    style U1 fill:#e1f5fe
    style U4 fill:#e1f5fe
    style H1 fill:#e1f5fe
    style V1 fill:#e1f5fe
    style C1 fill:#e1f5fe
    style A1 fill:#e1f5fe
    style A3 fill:#e1f5fe
    style H7 fill:#ffebee
    style V8 fill:#ffebee
    style C7 fill:#ffebee
    style A16 fill:#ffebee
    style U6 fill:#ffebee
```

## Как просмотреть

Эту блок-схему можно просмотреть:
1. В GitHub/GitLab (они поддерживают Mermaid нативно)
2. В VS Code с расширением "Markdown Preview Mermaid Support"
3. На сайте [Mermaid Live Editor](https://mermaid.live/)
4. В любом Markdown редакторе с поддержкой Mermaid
