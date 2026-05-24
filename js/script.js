document.addEventListener('DOMContentLoaded', () => {
    // ----- Элементы DOM -----
    const sidebar = document.getElementById('sidebarLeft');
    const overlay = document.querySelector('.overlay');
    const openBtn = document.getElementById('openCatalog');
    const closeBtn = document.getElementById('closeSidebar');
    const backBtn = document.getElementById('backBtn');
    const catalogTitle = document.getElementById('catalogTitle');
    const catalogGrid = document.getElementById('catalogGrid');
    const searchInput = document.getElementById('searchInput');
    const searchClearBtn = document.getElementById('searchClearBtn');

    // ----- Состояние навигации (история) -----
    let historyStack = [];
    let catalogData = null; // будет загружен с сервера
    let currentSearchQuery = ''; // текущий поисковый запрос

    // ----- Функция отправки событий аудита -----
    function sendAuditEvent(eventType, objectId, objectType, description, additionalData = {}) {
        fetch('/navigator/api/audit/logs', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                event_type: eventType,
                object_id: objectId,
                object_type: objectType,
                description: description,
                additional_data: additionalData
            })
        })
        .then(response => {
            if (!response.ok) {
                console.warn('Не удалось отправить событие аудита:', response.status, response.statusText);
            }
        })
        .catch(error => {
            console.warn('Не удалось отправить событие аудита:', error);
        });
    }

    // ----- Функции для сохранения/восстановления состояния -----
    function saveState() {
        const state = {
            historyStack: historyStack,
            sidebarActive: sidebar.classList.contains('active')
        };
        sessionStorage.setItem('catalogState', JSON.stringify(state));
    }

    function restoreState() {
        const saved = sessionStorage.getItem('catalogState');
        if (!saved) return;

        try {
            const state = JSON.parse(saved);
            if (state.historyStack && Array.isArray(state.historyStack) && state.historyStack.length > 0) {
                historyStack = state.historyStack;
                renderCurrentLevel();

                if (state.sidebarActive) {
                    sidebar.removeAttribute('hidden');
                    overlay.removeAttribute('hidden');
                    sidebar.classList.add('active');
                    overlay.classList.add('active');
                    openBtn.setAttribute('aria-expanded', 'true');
                }
            }
        } catch (e) {
            console.warn('Не удалось восстановить состояние каталога', e);
        }
    }

    // ----- Вспомогательные функции -----
    function getIconPath(iconName) {
        // URLs-заглушки, которые следует заменять на logo.png (с пробелом в конце для первого URL)
        const placeholderUrls = [
            'https://vm-ftp.anosov.ru/icons/folder.gif ',
            'http://vm-ftp.anosov.ru/icons/folder.gif',
            'vm-ftp.anosov.ru/icons/folder.gif'
        ];
        
        // Если iconName пустой - возвращаем логотип по умолчанию
        if (!iconName || iconName.trim() === '') {
            return 'page/logo.png';
        }
        
        // Проверяем, является ли iconName URL-заглушкой
        for (const placeholderUrl of placeholderUrls) {
            if (iconName.includes(placeholderUrl)) {
                return 'page/logo.png';
            }
        }
        
        // Если iconName начинается с http:// или https:// – используем как есть
        if (iconName.startsWith('http://') || iconName.startsWith('https://')) {
            return iconName;
        }
        
        // Иначе используем локальный путь из папки page/
        return `page/${iconName}`;
    }

    // Функция поиска по всем элементам каталога (рекурсивно)
    function searchInCatalog(query, items = catalogData?.children || []) {
        if (!query || query.trim() === '') {
            return [];
        }
        
        const results = [];
        const lowerQuery = query.toLowerCase();
        
        function searchRecursive(itemsList, path = []) {
            for (const item of itemsList) {
                const currentPath = [...path, item.name];
                
                // Проверяем имя элемента
                if (item.name.toLowerCase().includes(lowerQuery)) {
                    results.push({
                        ...item,
                        searchPath: currentPath.join(' / ')
                    });
                }
                
                // Рекурсивно ищем в дочерних элементах
                // children может быть null или [] - оба случая означают отсутствие дочерних элементов
                const hasChildren = Boolean(item.children && Array.isArray(item.children) && item.children.length > 0);
                if (hasChildren) {
                    searchRecursive(item.children, currentPath);
                }
            }
        }
        
        searchRecursive(items);
        return results;
    }

    function renderCurrentLevel() {
        if (historyStack.length === 0) return;

        const currentLevel = historyStack[historyStack.length - 1];
        
        // Если есть активный поисковый запрос, показываем результаты поиска
        if (currentSearchQuery && currentSearchQuery.trim() !== '') {
            catalogTitle.textContent = `Поиск: "${currentSearchQuery}"`;
            const searchResults = searchInCatalog(currentSearchQuery);
            renderItems(searchResults, true, '');
        } else {
            catalogTitle.textContent = currentLevel.title;
            renderItems(currentLevel.items, false, '');
        }
        
        updateBackButton();
        saveState();
    }

    function renderItems(items, isSearchResults, parentPath = '') {
        catalogGrid.innerHTML = '';

        if (items.length === 0) {
            const noResults = document.createElement('div');
            noResults.className = 'item';
            noResults.style.justifyContent = 'center';
            noResults.style.alignItems = 'center';
            noResults.style.color = '#999';
            noResults.style.fontSize = '16px';
            noResults.textContent = isSearchResults ? 'Ничего не найдено' : 'Пусто';
            catalogGrid.appendChild(noResults);
            return;
        }

        items.forEach(item => {
            const itemDiv = document.createElement('div');
            itemDiv.className = 'item';
            itemDiv.setAttribute('role', 'button');
            itemDiv.setAttribute('tabindex', '0');
            itemDiv.dataset.name = item.name;

            const img = document.createElement('img');
            img.className = 'item-icon';
            img.src = getIconPath(item.icon);
            img.alt = item.name;
            img.loading = 'lazy';
            img.onerror = () => { img.src = 'page/logo.png'; };

            const span = document.createElement('span');
            span.className = 'item-name';
            span.textContent = item.name;

            // Динамическая проверка: элемент пустой, если нет детей И нет URL
            // children может быть null или [] - оба случая означают отсутствие дочерних элементов
            const hasChildren = Boolean(item.children && Array.isArray(item.children) && item.children.length > 0);
            const isCurrentlyEmpty = !hasChildren && !item.url;
            
            // Если элемент пустой, добавляем сообщение
            if (isCurrentlyEmpty) {
                const emptySpan = document.createElement('span');
                emptySpan.className = 'item-empty-message';
                emptySpan.textContent = '(пустой)';
                emptySpan.style.color = '#999';
                emptySpan.style.fontSize = '12px';
                emptySpan.style.marginTop = '4px';
                span.appendChild(document.createElement('br'));
                span.appendChild(emptySpan);
                
                // Делаем элемент визуально менее активным
                itemDiv.style.opacity = '0.7';
            }

            // Если это результаты поиска, добавляем путь к элементу
            if (isSearchResults && item.searchPath) {
                const pathSpan = document.createElement('span');
                pathSpan.className = 'item-search-path';
                pathSpan.textContent = item.searchPath;
                span.appendChild(document.createElement('br'));
                span.appendChild(pathSpan);
            }

            itemDiv.appendChild(img);
            itemDiv.appendChild(span);
            // Сохраняем путь к родительской папке для формирования URL проектов
            itemDiv._itemData = { ...item, parentPath: parentPath };

            catalogGrid.appendChild(itemDiv);
        });
    }

    function updateBackButton() {
        backBtn.hidden = historyStack.length <= 1;
    }

    // ----- Функция: проверка, является ли файл видео -----
    function isVideoFile(url) {
        if (!url) return false;
        try {
            // 1. Обрезаем пробелы
            let cleanUrl = url.trim();
            // 2. Исправляем возможные разрывы в протоколе (https : -> https:)
            cleanUrl = cleanUrl.replace(/(https?)\s*:/i, '$1:');
            
            // Пытаемся декодировать для проверки расширения, но игнорируем ошибки
            try {
                cleanUrl = decodeURIComponent(cleanUrl);
            } catch (e) {
                // Если декодирование не удалось, используем обрезанную версию
            }
            
            const videoExtensions = /\.(mp4|webm|ogg|mov|avi|mkv|flv|wmv|m4v)\s*$/i;
            return videoExtensions.test(cleanUrl);
        } catch (e) {
            console.warn('Ошибка при проверке видео:', e);
            return false;
        }
    }

    // Функция для получения прокси-URL для видео
    function getVideoProxyUrl(url) {
        let cleanUrl = url.trim().replace(/(https?)\s*:/i, '$1:');
        try { cleanUrl = decodeURIComponent(cleanUrl); } catch(e){}
        
        return cleanUrl;
    }

    function handleItemClick(event) {
        const itemDiv = event.target.closest('.item');
        if (!itemDiv) return;

        const itemData = itemDiv._itemData;
        if (!itemData) return;

        // Проверяем, является ли элемент пустым (динамически: нет детей И нет URL)
        // children может быть null или [] - оба случая означают отсутствие дочерних элементов
        const hasChildren = Boolean(itemData.children && Array.isArray(itemData.children) && itemData.children.length > 0);
        const isCurrentlyEmpty = !hasChildren && !itemData.url;
        
        if (isCurrentlyEmpty) {
            // Показываем сообщение о том, что элемент пустой
            alert(`Элемент "${itemData.name}" пустой: не содержит элементов и не имеет ссылки.`);
            return;
        }

        // Сначала проверяем, является ли элемент папкой (есть дети)
        // Если да - переходим в папку и прорисовываем элементы
        // Только если это не папка - переходим по ссылке
        if (hasChildren) {
            // Это папка с детьми - переходим в неё и прорисовываем элементы
            // При переходе в папку из поиска очищаем поисковый запрос
            if (currentSearchQuery && currentSearchQuery.trim() !== '') {
                clearSearch();
            }
            historyStack.push({
                title: itemData.name,
                items: itemData.children
            });
            renderCurrentLevel();
        } else if (itemData.url && itemData.url.trim() !== '') {
            // Элемент не папка, но имеет URL - переходим по нему
            saveState();

            // === КРИТИЧЕСКИ ВАЖНАЯ ОБРАБОТКА URL ===
            let targetUrl = itemData.url;
            
            // 1. Убираем пробелы по краям
            targetUrl = targetUrl.trim();
            
            // 2. Исправляем "разорванный" протокол (частая проблема при копировании)
            // Превращаем "https :" в "https:"
            targetUrl = targetUrl.replace(/(https?|ftp)\s*:/gi, '$1:');
            
            console.log('Переход по ссылке:', { original: itemData.url, processed: targetUrl });

            // Аудит: попытка перехода по ссылке
            const linkType = isVideoFile(targetUrl) ? 'video_file' : 
                             targetUrl.match(/^https?:\/\//i) ? 'external_link' : 'internal_link';
            
            sendAuditEvent('link_click', itemData.name, 'catalog_item_link', 
                `Попытка перехода по ссылке: ${itemData.name}`, {
                    url: targetUrl,
                    link_type: linkType,
                    status: 'initiated'
                });

            // Проверяем, является ли файл видео
            if (isVideoFile(targetUrl)) {
                const videoPlayerUrl = `/video-player?url=${encodeURIComponent(targetUrl)}&name=${encodeURIComponent(itemData.name)}`;
                
                // Аудит: переход к видео-плееру
                sendAuditEvent('video_player_open', itemData.name, 'video_file', 
                    `Открытие видео-плеера для: ${itemData.name}`, {
                        url: targetUrl,
                        player_url: videoPlayerUrl,
                        status: 'success'
                    });
                
                window.location.href = videoPlayerUrl;
            } else {
                // === ИСПРАВЛЕНИЕ ПРОБЛЕМЫ ===
                // Используем универсальный метод открытия ссылок
                try {
                    // Создаём временную ссылку и кликаем по ней
                    const anchor = document.createElement('a');
                    anchor.href = targetUrl;
                    anchor.target = '_blank';
                    anchor.rel = 'noopener noreferrer';
                    
                    document.body.appendChild(anchor);
                    anchor.click();
                    document.body.removeChild(anchor);
                    
                    // Аудит: результат попытки открытия ссылки
                    sendAuditEvent('external_link_open', itemData.name, 'external_link', 
                        `Внешняя ссылка открыта: ${itemData.name}`, {
                            url: targetUrl,
                            status: 'success'
                        });
                } catch (error) {
                    sendAuditEvent('external_link_error', itemData.name, 'external_link', 
                        `Ошибка при открытии внешней ссылки: ${itemData.name}`, {
                            url: targetUrl,
                            status: 'error',
                            error_message: error.message
                        });
                }
            }
            
            // После успешного перехода по URL из поиска очищаем поисковый запрос
            if (currentSearchQuery && currentSearchQuery.trim() !== '') {
                clearSearch();
            }
        } else {
            // Нет ни URL, ни детей (но это уже проверено выше как isCurrentlyEmpty)
            alert(`Вы выбрали: ${itemData.name}\n(URL не указан)`);
        }
    }

    function goBack() {
        if (historyStack.length > 1) {
            historyStack.pop();
            renderCurrentLevel();
        } else if (currentSearchQuery) {
            // Если активен поиск, очищаем его и возвращаемся к корневому уровню
            clearSearch();
        }
    }

    function clearSearch() {
        currentSearchQuery = '';
        searchInput.value = '';
        searchClearBtn.hidden = true;
        resetToRoot();
    }

    function resetToRoot() {
        if (!catalogData) {
            setTimeout(resetToRoot, 100);
            return;
        }
        historyStack = [{
            title: catalogData.name,
            items: catalogData.children
        }];
        renderCurrentLevel();
    }

    // ----- Открытие/закрытие сайдбара -----
    function openSidebar() {
        if (!catalogData) {
            loadCatalog().then(() => openSidebar());
            return;
        }
        if (sidebar.classList.contains('active')) return;

        resetToRoot();

        sidebar.removeAttribute('hidden');
        overlay.removeAttribute('hidden');

        void sidebar.offsetHeight; // reflow

        sidebar.classList.add('active');
        overlay.classList.add('active');
        openBtn.setAttribute('aria-expanded', 'true');

        saveState();
    }

    function closeSidebar() {
        if (!sidebar.classList.contains('active')) return;

        sidebar.classList.remove('active');
        overlay.classList.remove('active');
        openBtn.setAttribute('aria-expanded', 'false');

        let transitionEnded = false;
        const onTransitionEnd = () => {
            if (transitionEnded) return;
            transitionEnded = true;

            sidebar.setAttribute('hidden', '');
            overlay.setAttribute('hidden', '');
            sidebar.removeEventListener('transitionend', onTransitionEnd);
            overlay.removeEventListener('transitionend', onTransitionEnd);
            clearTimeout(fallbackTimer);

            saveState();
        };

        const fallbackTimer = setTimeout(() => {
            if (!transitionEnded) {
                sidebar.removeEventListener('transitionend', onTransitionEnd);
                overlay.removeEventListener('transitionend', onTransitionEnd);
                sidebar.setAttribute('hidden', '');
                overlay.setAttribute('hidden', '');
                transitionEnded = true;
                saveState();
            }
        }, 1500);

        sidebar.addEventListener('transitionend', onTransitionEnd);
        overlay.addEventListener('transitionend', onTransitionEnd);
    }

    // ----- Загрузка каталога с сервера -----
    async function loadCatalog() {
        try {
            const response = await fetch('/navigator/api/catalog');
            if (!response.ok) throw new Error('Ошибка загрузки');
            catalogData = await response.json();
            if (sidebar.classList.contains('active')) {
                resetToRoot();
            }
            return catalogData;
        } catch (e) {
            console.error('Не удалось загрузить каталог:', e);
            catalogData = { name: 'Ошибка загрузки', children: [] };
        }
    }

    // Функция для обновления каталога при изменениях
    function refreshCatalog() {
        loadCatalog().then(() => {
            if (historyStack.length > 0) {
                renderCurrentLevel();
            }
        });
    }

    // ----- Обработчики событий -----
    openBtn.addEventListener('click', () => {
        // Аудит: открытие каталога с главной страницы
        sendAuditEvent('web_resource_view', 'main_page_catalog', 'ui_element', 'Открытие каталога с главной страницы');
        openSidebar();
    });
    
    closeBtn.addEventListener('click', closeSidebar);
    overlay.addEventListener('click', closeSidebar);
    backBtn.addEventListener('click', goBack);

    catalogGrid.addEventListener('click', (e) => {
        // Аудит: взаимодействие с элементами каталога
        const itemDiv = e.target.closest('.item');
        if (itemDiv && itemDiv._itemData) {
            const itemData = itemDiv._itemData;
            const hasChildren = Boolean(itemData.children && Array.isArray(itemData.children) && itemData.children.length > 0);
            sendAuditEvent('web_resource_view', itemData.name, 'catalog_item', `Просмотр элемента каталога: ${itemData.name}`, {
                url: itemData.url || null,
                hasChildren: hasChildren
            });
        }
        handleItemClick(e);
    });

    catalogGrid.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
            const item = e.target.closest('.item');
            if (item) {
                e.preventDefault();
                handleItemClick({ target: item });
            }
        }
    });

    // Обработчики для поиска
    searchInput.addEventListener('input', (e) => {
        const query = e.target.value.trim();
        currentSearchQuery = query;
        
        // Показываем/скрываем кнопку очистки
        searchClearBtn.hidden = query === '';
        
        // Обновляем отображение
        renderCurrentLevel();
    });

    searchClearBtn.addEventListener('click', clearSearch);

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && sidebar.classList.contains('active')) {
            if (currentSearchQuery) {
                clearSearch();
            } else {
                closeSidebar();
            }
        }
    });

    // ----- Запуск: загружаем данные и восстанавливаем состояние -----
    (async () => {
        await loadCatalog();
        restoreState();
        
        // Слушаем события обновления из других вкладок (админ-панели)
        window.addEventListener('storage', (e) => {
            if (e.key === 'catalogUpdated') {
                refreshCatalog();
            }
        });
    })();
});
