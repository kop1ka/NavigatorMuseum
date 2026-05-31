 // Глобальные переменные
        let catalogData = null;
        let permanentItems = [];
        let availableImages = [];
        let selectedElement = null;
        let selectedImage = null;
        let filteredImages = [];
        let parserCheckTimeout = null; // Флаг для отслеживания таймера проверки парсера

        // Инициализация при загрузке
        document.addEventListener('DOMContentLoaded', async () => {
            await loadCatalog();
            await loadPermanentItems();
            await loadImages();
            await loadParserStatus();
            setupTabs();
            setupForms();
            setupSearch();
            renderParentList();
            renderImportParentList();
            
            // Слушаем события обновления из других вкладок
            window.addEventListener('storage', (e) => {
                if (e.key === 'catalogUpdated') {
                    // Обновить данные при изменении в другой вкладке
                    loadCatalog();
                    loadImages();
                    loadPermanentItems();
                    showStatus('Данные обновлены после завершения парсинга', 'success');
                }
            });
        });

        // Загрузка каталога
        async function loadCatalog() {
            try {
                const response = await fetch('/navigator/api/catalog', { credentials: 'include' });
                catalogData = await response.json();
                renderCatalogTree();
                renderParentList();
                renderImportParentList();
            } catch (error) {
                showStatus('Ошибка загрузки каталога: ' + error.message, 'error');
            }
        }

        // Загрузка постоянных элементов
        async function loadPermanentItems() {
            try {
                const response = await fetch('/navigator/api/permanent', { credentials: 'include' });
                const data = await response.json();
                permanentItems = data.permanent_items || [];
            } catch (error) {
                console.error('Ошибка загрузки постоянных элементов:', error);
            }
        }

        // Загрузка доступных изображений
        async function loadImages() {
            try {
                const response = await fetch('/navigator/api/images', { credentials: 'include' });
                availableImages = await response.json();
                filteredImages = [...availableImages];
                populateImageSelects();
                renderImagesGrids();
            } catch (error) {
                console.error('Ошибка загрузки изображений:', error);
            }
        }

        // Рендеринг дерева каталога с возможностью сворачивания/разворачивания
        function renderCatalogTree(items = catalogData.children, parentPath = '', container = null, isRoot = true) {
            if (!container) {
                container = document.getElementById('catalogTree');
                container.innerHTML = '';
            }

            items.forEach(item => {
                const currentPath = parentPath ? `${parentPath}/${item.name}` : item.name;
                const isPermanent = permanentItems.includes(currentPath);
                const hasChildren = item.children && item.children.length > 0;

                const treeItem = document.createElement('div');
                treeItem.className = `tree-item${isPermanent ? ' permanent' : ''}`;
                treeItem.dataset.path = currentPath;
                
                const toggleIcon = hasChildren ? '<span class="tree-toggle expanded"></span>' : '<span class="tree-toggle" style="visibility:hidden"></span>';
                
                // Определяем иконку для элемента
                let itemIcon = '📁';
                if (!hasChildren) {
                    if (item.icon) {
                        // Проверяем, является ли иконка URL-заглушкой
                        const placeholderUrls = [
                            'https://vm-ftp.anosov.ru/icons/folder.gif',
                            'http://vm-ftp.anosov.ru/icons/folder.gif',
                            'vm-ftp.anosov.ru/icons/folder.gif'
                        ];
                        
                        let isPlaceholder = false;
                        for (const placeholderUrl of placeholderUrls) {
                            if (item.icon.includes(placeholderUrl)) {
                                isPlaceholder = true;
                                break;
                            }
                        }
                        
                        // Если иконка не пустая и не заглушка - используем 📄
                        if (!isPlaceholder && item.icon.trim() !== '') {
                            itemIcon = '📄';
                        } else {
                            itemIcon = '📁';
                        }
                    } else {
                        itemIcon = '📁';
                    }
                }
                
                treeItem.innerHTML = `
                    ${toggleIcon}
                    <span>${itemIcon}</span>
                    <span>${item.name.toUpperCase()}</span>
                `;

                // Обработчик клика для выбора элемента
                treeItem.addEventListener('click', (e) => {
                    if (e.target.classList.contains('tree-toggle')) {
                        toggleTreeChildren(treeItem, currentPath);
                    } else {
                        selectTreeItem(treeItem, currentPath, item);
                    }
                });

                container.appendChild(treeItem);

                if (hasChildren) {
                    const childrenContainer = document.createElement('div');
                    childrenContainer.className = 'tree-children';
                    childrenContainer.dataset.parentPath = currentPath;
                    renderCatalogTree(item.children, currentPath, childrenContainer, false);
                    container.appendChild(childrenContainer);
                }
            });
        }

        // Сворачивание/разворачивание детей
        function toggleTreeChildren(treeItem, path) {
            const toggle = treeItem.querySelector('.tree-toggle');
            const childrenContainer = document.querySelector(`.tree-children[data-parent-path="${path}"]`);
            
            if (childrenContainer) {
                const isHidden = childrenContainer.classList.contains('hidden');
                if (isHidden) {
                    childrenContainer.classList.remove('hidden');
                    toggle.classList.remove('collapsed');
                    toggle.classList.add('expanded');
                } else {
                    childrenContainer.classList.add('hidden');
                    toggle.classList.remove('expanded');
                    toggle.classList.add('collapsed');
                }
            }
        }

        // Поиск по дереву
        function searchInTree(query) {
            const treeItems = document.querySelectorAll('.tree-item');
            query = query.toLowerCase().trim();
            
            treeItems.forEach(item => {
                const nameSpan = item.querySelector('span:last-child');
                const displayName = nameSpan ? nameSpan.textContent.toLowerCase() : '';
                if (query === '' || displayName.includes(query)) {
                    item.style.display = 'flex';
                } else {
                    item.style.display = 'none';
                }
            });
        }

        // Выбор элемента в дереве
        function selectTreeItem(element, path, itemData) {
            // Снять выделение со всех элементов
            document.querySelectorAll('.tree-item').forEach(el => el.classList.remove('selected'));
            element.classList.add('selected');

            selectedElement = { path, ...itemData };
            
            // Сохраняем текущую иконку в selectedImage при выборе элемента
            selectedImage = itemData.icon || '';

            // Заполнить форму редактирования
            document.getElementById('editForm').classList.remove('hidden');
            document.getElementById('editPath').value = path;
            document.getElementById('editName').value = itemData.name.toUpperCase();
            document.getElementById('editIcon').value = itemData.icon || '';
            document.getElementById('editUrl').value = itemData.url || '';
            document.getElementById('editPermanent').checked = permanentItems.includes(path);

            // Выделить текущую иконку в сетке
            highlightSelectedImage(itemData.icon, 'editImagesGrid');
            
            // Обновить отображение иконки в дереве (если это файл с изображением)
            const treeItem = document.querySelector(`.tree-item[data-path="${path}"]`);
            if (treeItem && itemData.icon) {
                const iconSpan = treeItem.querySelector('span:nth-child(2)');
                if (iconSpan) {
                    // Проверяем, является ли иконка URL-заглушкой
                    const placeholderUrls = [
                        'https://vm-ftp.anosov.ru/icons/folder.gif',
                        'http://vm-ftp.anosov.ru/icons/folder.gif',
                        'vm-ftp.anosov.ru/icons/folder.gif'
                    ];
                    
                    let isPlaceholder = false;
                    for (const placeholderUrl of placeholderUrls) {
                        if (itemData.icon.includes(placeholderUrl)) {
                            isPlaceholder = true;
                            break;
                        }
                    }
                    
                    // Если иконка не пустая и не заглушка - используем 📄, иначе 📁
                    if (!isPlaceholder && itemData.icon.trim() !== '') {
                        iconSpan.textContent = '📄';
                    } else {
                        iconSpan.textContent = '📁';
                    }
                }
            }
        }

        // Populate image selects
        function populateImageSelects() {
            const editSelect = document.getElementById('editIcon');
            const addSelect = document.getElementById('addIcon');

            [editSelect, addSelect].forEach(select => {
                select.innerHTML = '<option value="">-- Выберите иконку --</option>';
                availableImages.forEach(img => {
                    const option = document.createElement('option');
                    option.value = img.path;
                    option.textContent = img.name;
                    select.appendChild(option);
                });
            });
        }

        // Render images grids
        function renderImagesGrids() {
            renderImagesGrid('editImagesGrid', 'editIcon');
            renderImagesGrid('addImagesGrid', 'addIcon');
        }

        function renderImagesGrid(containerId, selectId, images = availableImages) {
            const container = document.getElementById(containerId);
            if (!container) return;
            container.innerHTML = '';

            images.forEach(img => {
                const imageItem = document.createElement('div');
                imageItem.className = 'image-item';
                
                // Используем прямую ссылку для всех изображений
                let imgSrc = img.path;
                
                // Если это внешний URL, используем его напрямую
                if (img.path.startsWith('http://') || img.path.startsWith('https://')) {
                    imgSrc = img.path;
                } else if (!img.path.startsWith('/')) {
                    // Для относительных путей добавляем базовый путь
                    imgSrc = '/' + img.path;
                }
                
                imageItem.innerHTML = `
                    <img src="${imgSrc}" alt="${img.name}" loading="lazy" onerror="this.style.display='none'">
                `;

                imageItem.addEventListener('click', () => {
                    // Снять выделение со всех
                    container.querySelectorAll('.image-item').forEach(el => el.classList.remove('selected'));
                    imageItem.classList.add('selected');

                    // Выбрать в селекте
                    const select = document.getElementById(selectId);
                    select.value = imgSrc;
                    selectedImage = imgSrc;
                    
                    // Обновить предпросмотр иконки у выбранного элемента в дереве
                    if (selectId === 'editIcon' && selectedElement) {
                        const treeItem = document.querySelector(`.tree-item[data-path="${selectedElement.path}"]`);
                        if (treeItem) {
                            const iconSpan = treeItem.querySelector('span:nth-child(2)');
                            if (iconSpan) {
                                // Проверяем, является ли выбранная иконка URL-заглушкой
                                const placeholderUrls = [
                                    'https://vm-ftp.anosov.ru/icons/folder.gif',
                                    'http://vm-ftp.anosov.ru/icons/folder.gif',
                                    'vm-ftp.anosov.ru/icons/folder.gif'
                                ];
                                
                                let isPlaceholder = false;
                                for (const placeholderUrl of placeholderUrls) {
                                    if (imgSrc.includes(placeholderUrl)) {
                                        isPlaceholder = true;
                                        break;
                                    }
                                }
                                
                                // Если иконка не пустая и не заглушка - используем 📄, иначе 📁
                                if (!isPlaceholder && imgSrc.trim() !== '') {
                                    iconSpan.textContent = '📄';
                                } else {
                                    iconSpan.textContent = '📁';
                                }
                            }
                        }
                    }
                });

                container.appendChild(imageItem);
            });
        }

        function highlightSelectedImage(iconPath, gridId) {
            const container = document.getElementById(gridId);
            container.querySelectorAll('.image-item').forEach(el => {
                const img = el.querySelector('img');
                const isSelected = img && img.src === iconPath;
                el.classList.toggle('selected', isSelected);
            });
        }

        // Setup tabs
        function setupTabs() {
            document.querySelectorAll('.tab').forEach(tab => {
                tab.addEventListener('click', () => {
                    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                    
                    tab.classList.add('active');
                    document.getElementById(`${tab.dataset.tab}Tab`).classList.add('active');
                });
            });
        }

        // Setup forms
        function setupForms() {
            // Edit form
            document.getElementById('editForm').addEventListener('submit', async (e) => {
                e.preventDefault();
                await updateItem();
            });

            // Add form
            document.getElementById('addForm').addEventListener('submit', async (e) => {
                e.preventDefault();
                await addItem();
            });
        }

        // Setup search handlers
        function setupSearch() {
            // Tree search
            document.getElementById('treeSearch').addEventListener('input', (e) => {
                searchInTree(e.target.value);
            });

            // Image search
            document.getElementById('imageSearch').addEventListener('input', (e) => {
                const query = e.target.value.toLowerCase().trim();
                filteredImages = availableImages.filter(img => img.name.toLowerCase().includes(query));
                renderImagesGrid('addImagesGrid', 'addIcon', filteredImages);
            });

            // Parent folder search
            document.getElementById('parentSearch').addEventListener('input', (e) => {
                const query = e.target.value.toLowerCase().trim();
                filterParentList(query);
            });
        }

        // Фильтрация списка родителей по поиску
        function filterParentList(query) {
            const parentItems = document.querySelectorAll('#parentList .parent-item');
            parentItems.forEach(item => {
                const pathSpan = item.querySelector('span:last-child');
                const pathText = pathSpan ? pathSpan.textContent.toLowerCase() : '';
                if (query === '' || pathText.includes(query)) {
                    item.style.display = 'flex';
                } else {
                    item.style.display = 'none';
                }
            });
        }

        // Render parent list for adding new items
        function renderParentList() {
            const container = document.getElementById('parentList');
            container.innerHTML = '';

            // Add root as an option
            const rootItem = document.createElement('div');
            rootItem.className = 'parent-item';
            rootItem.dataset.path = '';
            rootItem.innerHTML = `
                <span>📁</span>
                <span>Корневая папка</span>
            `;
            rootItem.addEventListener('click', () => selectParent(rootItem, ''));
            container.appendChild(rootItem);

            // Add all folders from catalog
            if (catalogData && catalogData.children) {
                renderParentListRecursive(catalogData.children, '', container);
            }
        }

        function renderParentListRecursive(items, parentPath, container) {
            items.forEach(item => {
                const currentPath = parentPath ? `${parentPath}/${item.name}` : item.name;
                
                if (item.children !== null) {  // Это папка
                    const parentItem = document.createElement('div');
                    parentItem.className = 'parent-item';
                    parentItem.dataset.path = currentPath;
                    parentItem.innerHTML = `
                        <span>📁</span>
                        <span>${currentPath}</span>
                    `;
                    parentItem.addEventListener('click', () => selectParent(parentItem, currentPath));
                    container.appendChild(parentItem);

                    if (item.children && item.children.length > 0) {
                        renderParentListRecursive(item.children, currentPath, container);
                    }
                }
            });
        }

        function selectParent(element, path) {
            document.querySelectorAll('.parent-item').forEach(el => el.classList.remove('selected'));
            element.classList.add('selected');
            document.getElementById('addParentPath').value = path;
        }

        // Update item
        async function updateItem() {
            const path = document.getElementById('editPath').value;
            
            // Используем selectedImage если он выбран, иначе берём из селекта
            let iconValue = selectedImage || document.getElementById('editIcon').value;
            
            // Проверяем, является ли иконка URL-заглушкой, и если да - заменяем на пустую строку
            const placeholderUrls = [
                'https://vm-ftp.anosov.ru/icons/folder.gif',
                'http://vm-ftp.anosov.ru/icons/folder.gif',
                'vm-ftp.anosov.ru/icons/folder.gif'
            ];
            
            let isPlaceholder = false;
            for (const placeholderUrl of placeholderUrls) {
                if (iconValue && iconValue.includes(placeholderUrl)) {
                    isPlaceholder = true;
                    break;
                }
            }
            
            if (isPlaceholder) {
                iconValue = '';
            }
            
            const updates = {
                name: document.getElementById('editName').value.toUpperCase(),
                icon: iconValue
            };

            const url = document.getElementById('editUrl').value;
            if (url) updates.url = url;

            try {
                const response = await fetch('/navigator/api/items', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path, updates }),
                    credentials: 'include'
                });

                if (response.ok) {
                    // Обновить постоянный статус
                    const isPermanent = document.getElementById('editPermanent').checked;
                    await togglePermanent(path, isPermanent);

                    showStatus('Элемент успешно обновлён', 'success');
                    selectedImage = null; // Сбросить выбранное изображение после обновления
                    await loadCatalog();
                    await loadPermanentItems();
                    
                    // Отправить событие обновления для других вкладок
                    localStorage.setItem('catalogUpdated', Date.now());
                } else {
                    const errorData = await response.json();
                    showStatus('Ошибка обновления элемента: ' + (errorData.error || 'Неизвестная ошибка'), 'error');
                }
            } catch (error) {
                showStatus('Ошибка: ' + error.message, 'error');
            }
        }

        // Add item
        async function addItem() {
            const parentPath = document.getElementById('addParentPath').value;
            const name = document.getElementById('addName').value.toUpperCase();
            
            // Используем selectedImage если он выбран, иначе берём из селекта
            let iconValue = selectedImage || document.getElementById('addIcon').value || 'folder.png';
            
            // Проверяем, является ли иконка URL-заглушкой, и если да - заменяем на пустую строку
            const placeholderUrls = [
                'https://vm-ftp.anosov.ru/icons/folder.gif',
                'http://vm-ftp.anosov.ru/icons/folder.gif',
                'vm-ftp.anosov.ru/icons/folder.gif'
            ];
            
            let isPlaceholder = false;
            for (const placeholderUrl of placeholderUrls) {
                if (iconValue && iconValue.includes(placeholderUrl)) {
                    isPlaceholder = true;
                    break;
                }
            }
            
            if (isPlaceholder) {
                iconValue = '';
            }
            
            const isPermanent = document.getElementById('addPermanent').checked;
            const url = document.getElementById('addUrl').value;

            try {
                const requestBody = { parent_path: parentPath, name, icon: iconValue };
                if (url) requestBody.url = url;

                const response = await fetch('/navigator/api/items', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(requestBody),
                    credentials: 'include'
                });

                if (response.ok) {
                    // Сделать постоянным если нужно
                    if (isPermanent) {
                        const newPath = parentPath ? `${parentPath}/${name}` : name;
                        await togglePermanent(newPath, true);
                    }

                    showStatus('Элемент успешно добавлен', 'success');
                    document.getElementById('addForm').reset();
                    document.getElementById('addParentPath').value = '';
                    selectedImage = null; // Сбросить выбранное изображение
                    await loadCatalog();
                    await loadPermanentItems();
                    
                    // Отправить событие обновления для других вкладок
                    localStorage.setItem('catalogUpdated', Date.now());
                } else {
                    const errorData = await response.json();
                    showStatus('Ошибка добавления элемента: ' + (errorData.error || 'Неизвестная ошибка'), 'error');
                }
            } catch (error) {
                showStatus('Ошибка: ' + error.message, 'error');
            }
        }

        // Delete item
        async function deleteCurrentItem() {
            if (!selectedElement) return;

            if (!confirm(`Вы уверены, что хотите удалить "${selectedElement.name}"?`)) {
                return;
            }

            try {
                const response = await fetch('/navigator/api/items', {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path: selectedElement.path }),
                    credentials: 'include'
                });

                if (response.ok) {
                    // Удалить из постоянных если был там
                    await togglePermanent(selectedElement.path, false);

                    showStatus('Элемент успешно удалён', 'success');
                    document.getElementById('editForm').classList.add('hidden');
                    selectedElement = null;
                    selectedImage = null; // Сбросить выбранное изображение при удалении
                    await loadCatalog();
                    await loadPermanentItems();
                } else {
                    const errorData = await response.json();
                    showStatus('Ошибка удаления элемента: ' + (errorData.error || 'Неизвестная ошибка'), 'error');
                }
            } catch (error) {
                showStatus('Ошибка: ' + error.message, 'error');
            }
        }

        // Toggle permanent status
        async function togglePermanent(path, makePermanent) {
            try {
                await fetch('/navigator/api/permanent', {
                    method: makePermanent ? 'POST' : 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path }),
                    credentials: 'include'
                });
            } catch (error) {
                console.error('Ошибка обновления постоянного статуса:', error);
            }
        }

        // Получить все пути элементов в каталоге (рекурсивно)
        function getAllPaths(items = null, parentPath = '') {
            let paths = [];
            // Если items не передан, используем catalogData
            if (items === null) {
                if (!catalogData || !catalogData.children) return paths;
                items = catalogData.children;
            }
            if (!items) return paths;
            
            items.forEach(item => {
                const currentPath = parentPath ? `${parentPath}/${item.name}` : item.name;
                paths.push(currentPath);
                
                if (item.children && item.children.length > 0) {
                    paths = paths.concat(getAllPaths(item.children, currentPath));
                }
            });
            return paths;
        }

        // Сделать все элементы постоянными
        async function makeAllItemsPermanent() {
            try {
                // Сначала загружаем актуальный каталог для получения всех путей
                const catalogResponse = await fetch('/navigator/api/catalog');
                const catalog = await catalogResponse.json();
                
                const allPaths = getAllPaths(catalog.children);
                for (const path of allPaths) {
                    if (!permanentItems.includes(path)) {
                        await togglePermanent(path, true);
                    }
                }
                // Обновить список постоянных элементов
                await loadPermanentItems();
            } catch (error) {
                console.error('Ошибка при установке постоянных элементов:', error);
            }
        }

        // Start parser
        async function startParser() {
            const parserBtns = document.querySelectorAll('button[onclick="startParser()"]');
            
            // Блокируем все кнопки парсера
            parserBtns.forEach(btn => {
                btn.disabled = true;
                btn.textContent = 'Парсинг...';
            });
            
            try {
                const response = await fetch('/navigator/api/parser/start', { 
                    method: 'POST',
                    credentials: 'include'
                });
                
                // Проверяем, успешен ли ответ
                if (!response.ok) {
                    if (response.status === 401) {
                        throw new Error('Требуется авторизация администратора');
                    }
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || `Ошибка сервера: ${response.status}`);
                }
                
                const data = await response.json();

                if (data.status === 'started') {
                    showStatus('Парсер запущен. Пожалуйста, дождитесь завершения...', 'success');
                    checkParserStatus();
                } else {
                    showStatus('Парсер уже запущен', 'error');
                    parserBtns.forEach(btn => {
                        btn.disabled = false;
                        btn.textContent = 'Парсер';
                    });
                }
            } catch (error) {
                showStatus('Ошибка запуска парсера: ' + error.message, 'error');
                parserBtns.forEach(btn => {
                    btn.disabled = false;
                    btn.textContent = 'Парсер';
                });
            }
        }

        // Import JSON data
        async function importJsonData() {
            const jsonData = document.getElementById('importJsonData').value;
            const parentPath = document.getElementById('importParentPath').value;

            if (!jsonData.trim()) {
                showStatus('Введите JSON данные', 'error');
                return;
            }

            try {
                const response = await fetch('/navigator/api/import/json', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ json_data: jsonData, parent_path: parentPath })
                });

                const result = await response.json();

                if (response.ok) {
                    showStatus(result.message || 'JSON успешно импортирован', 'success');
                    document.getElementById('importJsonData').value = '';
                    document.getElementById('importParentPath').value = '';
                    await loadCatalog();
                    await loadPermanentItems();
                } else {
                    showStatus('Ошибка импорта JSON: ' + (result.error || 'Неизвестная ошибка'), 'error');
                }
            } catch (error) {
                showStatus('Ошибка: ' + error.message, 'error');
            }
        }

        // Render parent list for import
        function renderImportParentList() {
            const container = document.getElementById('importParentList');
            if (!container) return;
            container.innerHTML = '';

            // Add root as an option
            const rootItem = document.createElement('div');
            rootItem.className = 'parent-item';
            rootItem.dataset.path = '';
            rootItem.innerHTML = `
                <span>📁</span>
                <span>Корневая папка</span>
            `;
            rootItem.addEventListener('click', () => selectImportParent(rootItem, ''));
            container.appendChild(rootItem);

            // Add all folders from catalog
            if (catalogData && catalogData.children) {
                renderParentListRecursive(catalogData.children, '', container);
            }
        }

        function selectImportParent(element, path) {
            document.querySelectorAll('#importParentList .parent-item').forEach(el => el.classList.remove('selected'));
            element.classList.add('selected');
            document.getElementById('importParentPath').value = path;
        }

        // Поиск папок для импорта JSON
        document.addEventListener('DOMContentLoaded', () => {
            const importParentSearchInput = document.getElementById('importParentSearch');
            if (importParentSearchInput) {
                importParentSearchInput.addEventListener('input', (e) => {
                    const query = e.target.value.toLowerCase().trim();
                    filterImportParentList(query);
                });
            }
        });

        // Фильтрация списка родителей для импорта
        function filterImportParentList(query) {
            const parentItems = document.querySelectorAll('#importParentList .parent-item');
            parentItems.forEach(item => {
                const pathSpan = item.querySelector('span:last-child');
                const pathText = pathSpan ? pathSpan.textContent.toLowerCase() : '';
                if (query === '' || pathText.includes(query)) {
                    item.style.display = 'flex';
                } else {
                    item.style.display = 'none';
                }
            });
        }

        // Check parser status
        async function checkParserStatus() {
            try {
                const response = await fetch('/navigator/api/parser/status', { credentials: 'include' });
                
                // Проверяем, успешен ли ответ
                if (!response.ok) {
                    if (response.status === 401) {
                        throw new Error('Требуется авторизация администратора');
                    }
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || `Ошибка сервера: ${response.status}`);
                }
                
                const status = await response.json();

                const statusDiv = document.getElementById('parserStatus');
                const statusText = document.getElementById('parserStatusText');
                const lastRun = document.getElementById('parserLastRun');

                statusText.textContent = status.message;
                lastRun.textContent = status.last_run || '-';

                // Выводим логи парсера в консоль браузера
                if (status.logs && status.logs.length > 0) {
                    console.groupCollapsed('[PARSER LOGS] - ' + new Date().toLocaleTimeString());
                    status.logs.forEach((logEntry, index) => {
                        // Поддерживаем старый формат (строка) и новый формат (объект)
                        let logMsg, logType = 'log', errorDetails = null;
                        
                        if (typeof logEntry === 'object' && logEntry !== null) {
                            // Новый формат: объект с полями timestamp, message, type, error_details
                            logMsg = `[${logEntry.timestamp || 'N/A'}] ${logEntry.message || ''}`;
                            logType = logEntry.type || 'log';
                            errorDetails = logEntry.error_details;
                        } else {
                            // Старый формат: просто строка
                            logMsg = String(logEntry);
                            // Определяем тип лога по содержанию
                            if (logMsg.includes('ERROR') || logMsg.includes('Ошибка') || logMsg.includes('WARNING')) {
                                logType = 'error';
                            } else if (logMsg.includes('Успешно') || logMsg.includes('завершён успешно')) {
                                logType = 'info';
                            }
                        }
                        
                        // Вывод в консоль в зависимости от типа
                        if (logType === 'error') {
                            console.error(`[${index}] ${logMsg}`);
                            // Если есть детали ошибки, выводим их отдельно
                            if (errorDetails) {
                                console.groupCollapsed(`🔴 Детали ошибки #${index}`);
                                console.log('Тип ошибки:', errorDetails.type);
                                console.log('Сообщение:', errorDetails.message);
                                console.log('URL подключения:', errorDetails.url || 'N/A');
                                console.log('Timeout:', errorDetails.timeout || 'N/A');
                                console.log('HTTP статус:', errorDetails.http_status || 'N/A');
                                console.log('Заголовки ответа:', errorDetails.response_headers || 'N/A');
                                console.log('Тело ответа:', errorDetails.response_body || 'N/A');
                                console.log('Причина ошибки:', errorDetails.reason || 'N/A');
                                console.log('Полный traceback:');
                                console.error(errorDetails.traceback || 'Traceback недоступен');
                                console.groupEnd();
                            }
                        } else if (logType === 'info') {
                            console.info(`[${index}] ${logMsg}`);
                        } else {
                            console.log(`[${index}] ${logMsg}`);
                        }
                    });
                    console.groupEnd();
                }

                statusDiv.className = 'parser-status';
                if (status.running) {
                    statusDiv.classList.add('running');
                    setTimeout(checkParserStatus, 2000);
                } else {
                    statusDiv.classList.add('completed');
                    // Re-enable parser buttons
                    document.querySelectorAll('button[onclick="startParser()"]').forEach(btn => {
                        btn.disabled = false;
                        btn.textContent = 'Парсер';
                    });
                    // Обновить изображения после завершения парсера
                    await loadImages();
                    
                    // Сначала сделать все элементы постоянными ПЕРЕД обновлением каталога
                    await makeAllItemsPermanent();
                    
                    // Обновить каталог (теперь он загрузится с учётом всех постоянных элементов)
                    await loadCatalog();
                    await loadPermanentItems();
                    
                    // Показать уведомление о завершении
                    showStatus('Парсинг завершён успешно! Все элементы сделаны постоянными.', 'success');
                    
                    // Отправить событие обновления для других вкладок
                    localStorage.setItem('catalogUpdated', Date.now());
                    
                    // Показать браузерное уведомление по окончании работы
                    showBrowserNotification('Парсер завершил работу', 'Парсинг завершён успешно! Все элементы сохранены.');
                }
            } catch (error) {
                console.error('Ошибка получения статуса парсера:', error);
                // Re-enable parser buttons on error
                document.querySelectorAll('button[onclick="startParser()"]').forEach(btn => {
                    btn.disabled = false;
                    btn.textContent = 'Парсер';
                });
            }
        }

        // Load initial parser status on page load
        async function loadParserStatus() {
            try {
                const response = await fetch('/navigator/api/parser/status', { credentials: 'include' });
                
                // Проверяем, успешен ли ответ
                if (!response.ok) {
                    if (response.status === 401) {
                        throw new Error('Требуется авторизация администратора');
                    }
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || `Ошибка сервера: ${response.status}`);
                }
                
                const status = await response.json();
                
                const statusDiv = document.getElementById('parserStatus');
                const statusText = document.getElementById('parserStatusText');
                const lastRun = document.getElementById('parserLastRun');

                statusText.textContent = status.message;
                lastRun.textContent = status.last_run || '-';

                // Выводим логи парсера в консоль браузера при загрузке
                if (status.logs && status.logs.length > 0) {
                    console.groupCollapsed('[PARSER LOGS - Initial] - ' + new Date().toLocaleTimeString());
                    status.logs.forEach((logEntry, index) => {
                        // Поддерживаем старый формат (строка) и новый формат (объект)
                        let logMsg, logType = 'log', errorDetails = null;
                        
                        if (typeof logEntry === 'object' && logEntry !== null) {
                            // Новый формат: объект с полями timestamp, message, type, error_details
                            logMsg = `[${logEntry.timestamp || 'N/A'}] ${logEntry.message || ''}`;
                            logType = logEntry.type || 'log';
                            errorDetails = logEntry.error_details;
                        } else {
                            // Старый формат: просто строка
                            logMsg = String(logEntry);
                            // Определяем тип лога по содержанию
                            if (logMsg.includes('ERROR') || logMsg.includes('Ошибка') || logMsg.includes('WARNING')) {
                                logType = 'error';
                            } else if (logMsg.includes('Успешно') || logMsg.includes('завершён успешно')) {
                                logType = 'info';
                            }
                        }
                        
                        // Вывод в консоль в зависимости от типа
                        if (logType === 'error') {
                            console.error(`[${index}] ${logMsg}`);
                            // Если есть детали ошибки, выводим их отдельно
                            if (errorDetails) {
                                console.groupCollapsed(`🔴 Детали ошибки #${index}`);
                                console.log('Тип ошибки:', errorDetails.type);
                                console.log('Сообщение:', errorDetails.message);
                                console.log('URL подключения:', errorDetails.url || 'N/A');
                                console.log('Timeout:', errorDetails.timeout || 'N/A');
                                console.log('HTTP статус:', errorDetails.http_status || 'N/A');
                                console.log('Заголовки ответа:', errorDetails.response_headers || 'N/A');
                                console.log('Тело ответа:', errorDetails.response_body || 'N/A');
                                console.log('Причина ошибки:', errorDetails.reason || 'N/A');
                                console.log('Полный traceback:');
                                console.error(errorDetails.traceback || 'Traceback недоступен');
                                console.groupEnd();
                            }
                        } else if (logType === 'info') {
                            console.info(`[${index}] ${logMsg}`);
                        } else {
                            console.log(`[${index}] ${logMsg}`);
                        }
                    });
                    console.groupEnd();
                }

                statusDiv.className = 'parser-status';
                if (status.running) {
                    statusDiv.classList.add('running');
                    setTimeout(checkParserStatus, 2000);
                } else {
                    statusDiv.classList.add('completed');
                }
            } catch (error) {
                console.error('Ошибка загрузки статуса парсера:', error);
            }
        }

        // Show status message
        function showStatus(message, type) {
            const statusDiv = document.getElementById('statusMessage');
            statusDiv.textContent = message;
            statusDiv.className = `status-message status-${type}`;
            statusDiv.classList.remove('hidden');

            setTimeout(() => {
                statusDiv.classList.add('hidden');
            }, 5000);
        }

        // Browser notification
        function showBrowserNotification(title, body) {
            // Запросить разрешение на уведомления, если ещё не получено
            if (!('Notification' in window)) {
                console.log('Браузер не поддерживает уведомления');
                return;
            }
            
            if (Notification.permission === 'granted') {
                new Notification(title, {
                    body: body,
                    icon: './page/logo.png',
                    tag: 'parser-completed',
                    requireInteraction: false
                });
            } else if (Notification.permission !== 'denied') {
                Notification.requestPermission().then(permission => {
                    if (permission === 'granted') {
                        new Notification(title, {
                            body: body,
                            icon: './page/logo.png',
                            tag: 'parser-completed',
                            requireInteraction: false
                        });
                    }
                });
            }
        }

        // Logout
        function logout() {
            window.location.href = '/navigator/logout';
        }

        // Change password
        function changePassword() {
            window.location.href = '/navigator/change-password';
        }

        // Export JSON
        function exportJson() {
            fetch('/navigator/api/catalog')
                .then(response => response.json())
                .then(data => {
                    // Функция для сбора всех элементов с указанием родительского каталога
                    function collectItems(items, parentCatalogName) {
                        let result = [];
                        
                        if (!items || !Array.isArray(items)) return result;
                        
                        for (const item of items) {
                            if (!item) continue;
                            
                            const cleaned = {
                                name: item.name,
                                icon: item.icon,
                                url: item.url || null,
                                modified: item.modified,
                                catalog: parentCatalogName
                            };
                            
                            result.push(cleaned);
                            
                            // Рекурсивно обрабатываем дочерние элементы
                            if (item.children && Array.isArray(item.children)) {
                                const childItems = collectItems(item.children, item.name);
                                result = result.concat(childItems);
                            }
                        }
                        
                        return result;
                    }
                    
                    // Собираем все элементы из всех каталогов
                    // Пропускаем главный каталог, обходим его дочерние категории
                    let allItems = [];
                    if (data.children && Array.isArray(data.children)) {
                        for (const catalog of data.children) {
                            const catalogName = catalog.name || 'Без названия';
                            // Собираем элементы внутри категории (catalog.children)
                            const items = collectItems(catalog.children, catalogName);
                            allItems = allItems.concat(items);
                        }
                    }
                    
                    const jsonStr = JSON.stringify(allItems, null, 2);
                    const blob = new Blob([jsonStr], { type: 'application/json' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = 'catalog_export_' + new Date().toISOString().slice(0, 10) + '.json';
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    URL.revokeObjectURL(url);
                    showStatus('JSON файл успешно выгружен', 'success');
                })
                .catch(error => {
                    showStatus('Ошибка выгрузки JSON: ' + error.message, 'error');
                });
        }
