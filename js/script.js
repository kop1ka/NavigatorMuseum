/**
 * Навигатор по каталогу
 * Управление сайдбаром, поиск, история переходов и аудит действий
 */
document.addEventListener('DOMContentLoaded', () => {
    // ===== ЭЛЕМЕНТЫ ИНТЕРФЕЙСА =====
    // Собираем все DOM-элементы в один объект для удобного доступа
    const el = {
        sidebar: document.getElementById('sidebarLeft'),   // Левая панель навигации
        overlay: document.querySelector('.overlay'),       // Затемнение фона при открытом меню
        openBtn: document.getElementById('openCatalog'),   // Кнопка открытия каталога
        closeBtn: document.getElementById('closeSidebar'), // Кнопка закрытия меню
        backBtn: document.getElementById('backBtn'),       // Кнопка "Назад"
        title: document.getElementById('catalogTitle'),    // Заголовок текущей папки
        grid: document.getElementById('catalogGrid'),      // Сетка элементов каталога
        searchInput: document.getElementById('searchInput'),   // Поле поиска
        searchClearBtn: document.getElementById('searchClearBtn') // Кнопка очистки поиска
    };

    // ===== СОСТОЯНИЕ ПРИЛОЖЕНИЯ =====
    // Хранилище данных приложения
    let state = {
        history: [],      // Стек навигации: хранит путь от корня до текущей папки
        catalog: null,    // Полное дерево каталога, загруженное с сервера
        searchQuery: ''   // Текущий текст в поле поиска
    };

    // ===== АУДИТ: ОТПРАВКА СОБЫТИЙ =====
    /**
     * Отправляет событие аудита на сервер для логирования действий пользователя
     * @param {string} type - Тип события (например, 'link_click', 'video_player_open')
     * @param {string} id - Идентификатор объекта (имя элемента)
     * @param {string} objType - Тип объекта (например, 'catalog_item_link')
     * @param {string} desc - Описание события
     * @param {Object} data - Дополнительные данные события
     */
    function logEvent(type, id, objType, desc, data = {}) {
        fetch('/navigator/api/audit/logs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                event_type: type,
                object_id: id,
                object_type: objType,
                description: desc,
                additional_data: data
            })
        }).catch(err => console.warn('Аудит не отправлен:', err)); // Тихо игнорируем ошибки аудита
    }

    // ===== СОХРАНЕНИЕ/ВОССТАНОВЛЕНИЕ СОСТОЯНИЯ =====
    /**
     * Сохраняет текущее состояние навигации и сайдбара в sessionStorage
     * Это позволяет восстановить позицию пользователя после перезагрузки страницы
     */
    function saveState() {
        sessionStorage.setItem('catalogState', JSON.stringify({
            historyStack: state.history,           // Сохраняем стек навигации
            sidebarActive: el.sidebar.classList.contains('active') // Статус видимости меню
        }));
    }

    /**
     * Восстанавливает состояние из sessionStorage при загрузке страницы
     * Если пользователь закрыл браузер внутри папки — вернёт его туда же
     */
    function restoreState() {
        const saved = sessionStorage.getItem('catalogState');
        if (!saved) return; // Нечего восстанавливать

        try {
            const data = JSON.parse(saved);
            if (data.historyStack?.length > 0) {
                state.history = data.historyStack; // Восстанавливаем стек
                render();                          // Перерисовываем интерфейс
                if (data.sidebarActive) showSidebar(); // Открываем меню, если было открыто
            }
        } catch (e) {
            console.warn('Не удалось восстановить состояние', e);
        }
    }

    // ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
    
    /**
     * Получает путь к иконке, заменяя заглушки на логотип
     * @param {string} iconName - Имя файла или URL иконки
     * @returns {string} - Корректный путь к изображению
     */
    function getIconPath(iconName) {
        // Список заглушек, которые нужно заменить на стандартный логотип
        const placeholders = [
            'https://vm-ftp.anosov.ru/icons/folder.gif ',
            'http://vm-ftp.anosov.ru/icons/folder.gif',
            'vm-ftp.anosov.ru/icons/folder.gif'
        ];

        if (!iconName?.trim()) return 'page/logo.png';           // Пустое имя → логотип
        if (placeholders.some(p => iconName.includes(p))) return 'page/logo.png'; // Заглушка → логотип
        if (iconName.startsWith('http://') || iconName.startsWith('https://')) return iconName; // Полный URL → как есть
        return `page/${iconName}`;                               // Относительный путь → добавляем префикс
    }

    /**
     * Рекурсивный поиск элементов по названию во всём дереве каталога
     * @param {string} query - Поисковый запрос
     * @param {Array} items - Массив элементов для поиска (по умолчанию — корневые элементы)
     * @returns {Array} - Найденные элементы с полным путём
     */
    function searchCatalog(query, items = state.catalog?.children || []) {
        if (!query?.trim()) return []; // Пустой запрос → ничего не ищем

        const results = [];
        const q = query.toLowerCase();

        /**
         * Рекурсивно обходит дерево каталога
         * @param {Array} list - Текущий список элементов
         * @param {Array} path - Путь к текущему элементу (для отображения)
         */
        function searchRecursive(list, path = []) {
            for (const item of list) {
                const currentPath = [...path, item.name];
                // Если название содержит запрос — добавляем в результаты
                if (item.name.toLowerCase().includes(q)) {
                    results.push({ ...item, searchPath: currentPath.join(' / ') });
                }
                // Если есть дочерние элементы — идём глубже
                if (item.children?.length > 0) {
                    searchRecursive(item.children, currentPath);
                }
            }
        }

        searchRecursive(items);
        return results;
    }

    /**
     * Проверяет, является ли URL видеофайлом по расширению
     * @param {string} url - Ссылка для проверки
     * @returns {boolean} - true, если это видеофайл
     */
    function isVideoFile(url) {
        if (!url) return false;
        // Исправляем возможные пробелы в протоколе (http :// → http://)
        const cleanUrl = url.trim().replace(/(https?)\s*:/i, '$1:');
        try {
            // Проверяем расширение файла в конце URL
            return /\.(mp4|webm|ogg|mov|avi|mkv|flv|wmv|m4v)\s*$/i.test(
                decodeURIComponent(cleanUrl)
            );
        } catch {
            return false; // Не удалось декодировать URL → не видео
        }
    }

    // ===== ОТРИСОВКА ИНТЕРФЕЙСА =====
    
    /**
     * Отрисовывает текущий уровень каталога или результаты поиска
     * Обновляет заголовок, сетку элементов и видимость кнопки "Назад"
     */
    function render() {
        if (state.history.length === 0) return; // Нечего отображать

        const current = state.history[state.history.length - 1]; // Берём верхушку стека
        
        if (state.searchQuery) {
            // Режим поиска: показываем запрос и найденные элементы
            el.title.textContent = `Поиск: "${state.searchQuery}"`;
            renderItems(searchCatalog(state.searchQuery), true);
        } else {
            // Обычный режим: показываем содержимое текущей папки
            el.title.textContent = current.title;
            renderItems(current.items, false);
        }
        
        // Кнопка "Назад" нужна только если мы не в корневой папке
        el.backBtn.hidden = state.history.length <= 1;
        saveState(); // Сохраняем состояние после каждого рендера
    }

    /**
     * Рендерит список элементов в сетке
     * @param {Array} items - Массив элементов для отображения
     * @param {boolean} isSearch -true, если это результаты поиска
     */
    function renderItems(items, isSearch) {
        el.grid.innerHTML = ''; // Очищаем сетку перед отрисовкой

        if (items.length === 0) {
            // Показываем сообщение, если ничего нет
            const empty = document.createElement('div');
            empty.className = 'item';
            empty.style.cssText = 'justify-content:center;align-items:center;color:#999;font-size:16px';
            empty.textContent = isSearch ? 'Ничего не найдено' : 'Пусто';
            el.grid.appendChild(empty);
            return;
        }

        // Создаём DOM-элемент для каждого элемента каталога
        items.forEach(item => el.grid.appendChild(createItemElement(item, isSearch)));
    }

    /**
     * Создаёт DOM-элемент для одного элемента каталога
     * @param {Object} item - Данные элемента (name, icon, children, url)
     * @param {boolean} isSearch -true, если это результат поиска
     * @returns {HTMLElement} - Готовый div-элемент
     */
    function createItemElement(item, isSearch) {
        const div = document.createElement('div');
        div.className = 'item';
        div.setAttribute('role', 'button');  // Для доступности
        div.setAttribute('tabindex', '0');   // Можно выбрать клавиатурой
        div.dataset.name = item.name;

        // Иконка элемента
        const img = document.createElement('img');
        img.className = 'item-icon';
        img.src = getIconPath(item.icon);
        img.alt = item.name;
        img.loading = 'lazy';                // Ленивая загрузка для производительности
        img.onerror = () => { img.src = 'page/logo.png'; }; // Фолбэк при ошибке

        // Название элемента
        const nameSpan = document.createElement('span');
        nameSpan.className = 'item-name';
        nameSpan.textContent = item.name;

        // Проверяем, пустой ли элемент (нет детей и нет ссылки)
        const hasChildren = item.children?.length > 0;
        const isEmpty = !hasChildren && !item.url;
        
        if (isEmpty) {
            // Добавляем пометку "(пустой)" для неактивных элементов
            const msg = document.createElement('span');
            msg.className = 'item-empty-message';
            msg.textContent = '(пустой)';
            msg.style.cssText = 'color:#999;font-size:12px;margin-top:4px';
            nameSpan.append(document.createElement('br'), msg);
            div.style.opacity = '0.7'; // Визуально выделяем полупрозрачностью
        }

        // Для результатов поиска показываем полный путь к элементу
        if (isSearch && item.searchPath) {
            const pathSpan = document.createElement('span');
            pathSpan.className = 'item-search-path';
            pathSpan.textContent = item.searchPath;
            nameSpan.append(document.createElement('br'), pathSpan);
        }

        div.append(img, nameSpan);
        div._itemData = item; // Сохраняем данные в DOM-элементе для быстрого доступа
        return div;
    }

    // ===== НАВИГАЦИЯ =====

    /**
     * Сброс к корневому уровню каталога
     * Инициализирует историю первым элементом (корневая папка)
     */
    function resetToRoot() {
        if (!state.catalog) {
            // Если каталог ещё не загружен — ждём 100мс и пробуем снова
            setTimeout(resetToRoot, 100);
            return;
        }
        state.history = [{
            title: state.catalog.name,      // Имя корневой папки
            items: state.catalog.children   // Её содержимое
        }];
        render();
    }

    /**
     * Обработка клика по элементу каталога
     * @param {Event} e - Событие клика
     */
    function handleItemClick(e) {
        const itemDiv = e.target.closest('.item');
        if (!itemDiv?._itemData) return; // Клик не по элементу

        const item = itemDiv._itemData;
        const hasChildren = item.children?.length > 0;
        const isEmpty = !hasChildren && !item.url;

        if (isEmpty) {
            // Пустой элемент — ничего не делаем, только уведомляем
            alert(`Элемент "${item.name}" пустой.`);
            return;
        }

        if (hasChildren) {
            // Это папка — переходим внутрь
            if (state.searchQuery) clearSearch(); // Сбрасываем поиск при переходе в папку
            state.history.push({ title: item.name, items: item.children }); // Добавляем в стек
            render();
        } else if (item.url?.trim()) {
            // Это ссылка — открываем её
            saveState();
            const url = item.url.trim().replace(/(https?|ftp)\s*:/gi, '$1:'); // Исправляем пробелы в протоколе
            
            // Логируем клик по ссылке
            logEvent('link_click', item.name, 'catalog_item_link', 
                `Переход по ссылке: ${item.name}`, { url, status: 'initiated' });

            if (isVideoFile(url)) {
                // Видеофайл — открываем в специальном плеере
                const playerUrl = `/video-player?url=${encodeURIComponent(url)}&name=${encodeURIComponent(item.name)}`;
                logEvent('video_player_open', item.name, 'video_file', 
                    `Открытие видео: ${item.name}`, { url, player_url: playerUrl });
                window.location.href = playerUrl;
            } else {
                // Обычная ссылка — открываем в новой вкладке
                try {
                    const a = document.createElement('a');
                    a.href = url;
                    a.target = '_blank';
                    a.rel = 'noopener noreferrer'; // Безопасность: изолируем от opener
                    document.body.append(a);
                    a.click();
                    a.remove();
                    
                    logEvent('external_link_open', item.name, 'external_link', 
                        `Внешняя ссылка: ${item.name}`, { url, status: 'success' });
                } catch (err) {
                    // Ошибка открытия ссылки — логируем проблему
                    logEvent('external_link_error', item.name, 'external_link', 
                        `Ошибка ссылки: ${item.name}`, { url, error: err.message });
                }
            }

            if (state.searchQuery) clearSearch(); // Сбрасываем поиск после перехода
        }
    }

    /**
     * Кнопка "Назад" — возврат на уровень выше
     * Если активен поиск — сбрасывает его вместо возврата
     */
    function goBack() {
        if (state.history.length > 1) {
            state.history.pop(); // Удаляем текущую папку из стека
            render();
        } else if (state.searchQuery) {
            clearSearch(); // Если мы в корне и есть поиск — очищаем его
        }
    }

    /**
     * Очистка поиска и возврат к корневой папке
     */
    function clearSearch() {
        state.searchQuery = '';
        el.searchInput.value = '';
        el.searchClearBtn.hidden = true;
        resetToRoot();
    }

    // ===== САЙДБАР =====

    /**
     * Показать сайдбар с каталогом
     * Если данные ещё не загружены — сначала загружает их
     */
    function showSidebar() {
        if (!state.catalog) {
            loadCatalog().then(showSidebar); // Ждём загрузки, затем показываем
            return;
        }
        if (el.sidebar.classList.contains('active')) return; // Уже открыт

        resetToRoot();                // Сбрасываем на корень при каждом открытии
        el.sidebar.removeAttribute('hidden');
        el.overlay.removeAttribute('hidden');
        void el.sidebar.offsetHeight; // Принудительный reflow для анимации
        el.sidebar.classList.add('active');
        el.overlay.classList.add('active');
        el.openBtn.setAttribute('aria-expanded', 'true');
        saveState();
    }

    /**
     * Скрыть сайдбар с анимацией
     * Ждёт завершения CSS-перехода перед полным скрытием
     */
    function hideSidebar() {
        if (!el.sidebar.classList.contains('active')) return; // Уже закрыт

        el.sidebar.classList.remove('active');
        el.overlay.classList.remove('active');
        el.openBtn.setAttribute('aria-expanded', 'false');

        let done = false;
        const onEnd = () => {
            if (done) return;
            done = true;
            el.sidebar.setAttribute('hidden', '');
            el.overlay.setAttribute('hidden', '');
            clearTimeout(timer);
            saveState();
        };

        // Таймер безопасности на случай, если transitionend не сработает
        const timer = setTimeout(onEnd, 1500);
        el.sidebar.addEventListener('transitionend', onEnd);
        el.overlay.addEventListener('transitionend', onEnd);
    }

    // ===== ЗАГРУЗКА ДАННЫХ =====

    /**
     * Загружает дерево каталога с сервера через API
     * @returns {Promise<Object|null>} - Данные каталога или null при ошибке
     */
    async function loadCatalog() {
        try {
            const res = await fetch('/navigator/api/catalog');
            if (!res.ok) throw new Error('Ошибка загрузки');
            state.catalog = await res.json();
            // Если сайдбар уже открыт — перерисовываем с новыми данными
            if (el.sidebar.classList.contains('active')) resetToRoot();
            return state.catalog;
        } catch (e) {
            console.error('Не удалось загрузить каталог:', e);
            // Создаём фейковый каталог с ошибкой, чтобы интерфейс не сломался
            state.catalog = { name: 'Ошибка загрузки', children: [] };
        }
    }

    /**
     * Обновляет каталог из сервера и перерисовывает текущий вид
     * Вызывается при внешних изменениях (например, из других вкладок)
     */
    function refreshCatalog() {
        loadCatalog().then(() => {
            if (state.history.length > 0) render();
        });
    }

    // ===== ОБРАБОТЧИКИ СОБЫТИЙ =====

    // Кнопка открытия каталога
    el.openBtn.addEventListener('click', () => {
        logEvent('web_resource_view', 'main_page_catalog', 'ui_element', 'Открытие каталога');
        showSidebar();
    });

    // Кнопка закрытия и overlay (фон) закрывают меню
    el.closeBtn.addEventListener('click', hideSidebar);
    el.overlay.addEventListener('click', hideSidebar);
    
    // Кнопка "Назад" в навигации
    el.backBtn.addEventListener('click', goBack);

    // Клик по элементам сетки каталога
    el.grid.addEventListener('click', e => {
        const itemDiv = e.target.closest('.item');
        if (itemDiv?._itemData) {
            const item = itemDiv._itemData;
            // Логируем просмотр элемента
            logEvent('web_resource_view', item.name, 'catalog_item', 
                `Просмотр: ${item.name}`, { hasChildren: item.children?.length > 0 });
        }
        handleItemClick(e);
    });

    // Поддержка клавиатуры: Enter и Space для выбора элементов
    el.grid.addEventListener('keydown', e => {
        if (e.key === 'Enter' || e.key === ' ') {
            const item = e.target.closest('.item');
            if (item) {
                e.preventDefault();
                handleItemClick({ target: item });
            }
        }
    });

    // Поиск: фильтрация при вводе текста
    el.searchInput.addEventListener('input', e => {
        state.searchQuery = e.target.value.trim();
        el.searchClearBtn.hidden = state.searchQuery === '';
        render();
    });

    // Кнопка очистки поиска
    el.searchClearBtn.addEventListener('click', clearSearch);

    // Клавиша Escape: закрывает поиск или сайдбар
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape' && el.sidebar.classList.contains('active')) {
            state.searchQuery ? clearSearch() : hideSidebar();
        }
    });

    // ===== ЗАПУСК =====
    (async () => {
        await loadCatalog();   // Загружаем данные каталога
        restoreState();        // Восстанавливаем состояние из sessionStorage
        
        // Слушаем изменения в других вкладках (через storage event)
        window.addEventListener('storage', e => {
            if (e.key === 'catalogUpdated') refreshCatalog();
        });
    })();
});
