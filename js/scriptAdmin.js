
const state = {
  catalog: null,
  permanent: [],
  images: [],
  filteredImages: [],
  selected: null,
  selectedImage: null
};


// Утилиты

/**
 * парсит JSON, выбрасывает осмысленную ошибку при HTTP 4xx/5xx.
 */
const api = async (url, opts = {}) => {
  const res = await fetch(`/navigator/api/${url}`, { credentials: 'include', ...opts });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || `HTTP ${res.status}`);
  return res.json();
};

const cleanIcon = url => isPlaceholder(url) ? '' : (url ?? '');

// Показывает тост-уведомление. Автоматически скрывается через 5 сек.
const showStatus = (msg, type = 'info') => {
  const el = document.getElementById('statusMessage');
  el.textContent = msg;
  el.className = `status-message status-${type}`;
  el.classList.remove('hidden');
  setTimeout(() => el.classList.add('hidden'), 5000);
};

// Браузерное уведомление. Аккуратно обрабатывает отсутствие разрешений.
const notify = (title, body) => {
  if (!('Notification' in window)) return;
  const send = () => new Notification(title, { body, icon: './page/logo.png', tag: 'parser-done' });
  Notification.permission === 'granted' ? send() : Notification.permission !== 'denied' && Notification.requestPermission().then(p => p === 'granted' && send());
};

// Загрузка данных

// Выгружаем всё начальное состояние и сразу рендерим UI. Вызывается при старте и после любых изменений.
const loadData = async () => {
  state.catalog = await api('catalog');
  state.permanent = (await api('permanent')).permanent_items ?? [];
  state.images = await api('images');
  state.filteredImages = [...state.images];
  renderTree();
  renderParents('parentList', 'addParentPath');
  renderParents('importParentList', 'importParentPath');
  populateSelects();
  renderImageGrids();
  await updateParserStatus();
};

// Рендер дерева каталога

/**
 * Рекурсивно строит DOM-дерево. 
 * Используем data-path для привязки узлов, а не индексы массива → это спасает от багов при удалении/перемещении.
 */
const renderTree = (items = state.catalog?.children ?? [], path = '', container = document.getElementById('catalogTree'), isRoot = true) => {
  if (isRoot) container.innerHTML = '';
  items.forEach(item => {
    const cur = path ? `${path}/${item.name}` : item.name;
    const isPerm = state.permanent.includes(cur);
    const hasKids = item.children?.length > 0;
    // Иконка: если нет детей и есть валидная картинка → 📄, иначе 📁
    const icon = !hasKids ? (item.icon && !isPlaceholder(item.icon) ? '📄' : '📁') : '📁';
    
    const div = document.createElement('div');
    div.className = `tree-item${isPerm ? ' permanent' : ''}`;
    div.dataset.path = cur;
    div.innerHTML = `<span class="tree-toggle ${hasKids ? 'expanded' : ''}" style="${hasKids ? '' : 'visibility:hidden'}"></span><span>${icon}</span><span>${item.name.toUpperCase()}</span>`;
    div.onclick = e => e.target.classList.contains('tree-toggle') ? toggleTree(div, cur) : selectTree(div, cur, item);
    container.appendChild(div);
    
    if (hasKids) {
      const child = document.createElement('div');
      child.className = 'tree-children hidden';
      child.dataset.parentPath = cur;
      renderTree(item.children, cur, child, false);
      container.appendChild(child);
    }
  });
};

// Сворачивает/разворачивает вложенные узлы и крутит стрелочку.
const toggleTree = (el, path) => {
  const child = document.querySelector(`.tree-children[data-parent-path="${path}"]`);
  if (!child) return;
  const toggle = el.querySelector('.tree-toggle');
  const isHidden = child.classList.toggle('hidden');
  toggle.classList.toggle('collapsed', isHidden);
  toggle.classList.toggle('expanded', !isHidden);
};

// При клике на элемент: подсвечиваем его в дереве, заполняем форму редактирования, обновляем иконку.
const selectTree = (el, path, data) => {
  document.querySelectorAll('.tree-item').forEach(i => i.classList.remove('selected'));
  el.classList.add('selected');
  state.selected = { path, ...data };
  state.selectedImage = data.icon || '';
  
  document.getElementById('editPath').value = path;
  document.getElementById('editName').value = data.name.toUpperCase();
  document.getElementById('editIcon').value = cleanIcon(data.icon);
  document.getElementById('editUrl').value = data.url || '';
  document.getElementById('editPermanent').checked = state.permanent.includes(path);
  document.getElementById('editForm').classList.remove('hidden');
  
  highlightImage(data.icon, 'editImagesGrid');
  updateTreeIcon(path, data.icon);
};

// Обновляет только иконку в дереве без полного перерисовывания (оптимизация DOM-операций).
const updateTreeIcon = (path, icon) => {
  const el = document.querySelector(`.tree-item[data-path="${path}"] span:nth-child(2)`);
  if (el) el.textContent = icon && !isPlaceholder(icon) ? '📄' : '📁';
};

// Работа с изображениями

// Заполняем выпадающие списки доступными картинками.
const populateSelects = () => ['editIcon', 'addIcon'].forEach(id => {
  document.getElementById(id).innerHTML = '<option value="">-- Выберите иконку --</option>' +
    state.images.map(i => `<option value="${i.path}">${i.name}</option>`).join('');
});

// Отрисовка обеих сеток (для редактирования и добавления).
const renderImageGrids = () => {
  ['editImagesGrid', 'addImagesGrid'].forEach((id, i) => renderGrid(id, i ? 'addIcon' : 'editIcon', state.filteredImages));
};

/**
 * Рендерит кликабельную сетку изображений.
 * Поддерживает внешние URL, ленивую загрузку и скрытие битых картинок.
 */
const renderGrid = (containerId, selectId, images) => {
  const c = document.getElementById(containerId);
  if (!c) return;
  c.innerHTML = images.map(img => {
    const src = img.path.startsWith('http') ? img.path : `/${img.path}`;
    return `<div class="image-item" data-src="${src}"><img src="${src}" alt="${img.name}" loading="lazy" onerror="this.style.display='none'"></div>`;
  }).join('');
  
  c.querySelectorAll('.image-item').forEach(div => {
    div.onclick = () => {
      c.querySelectorAll('.image-item').forEach(i => i.classList.remove('selected'));
      div.classList.add('selected');
      const src = div.dataset.src;
      document.getElementById(selectId).value = src;
      state.selectedImage = src;
      // Если меняем иконку в режиме редактирования → сразу обновляем превью в дереве.
      if (selectId === 'editIcon' && state.selected) updateTreeIcon(state.selected.path, src);
    };
  });
};

// Подсвечивает выбранную картинку в сетке (сравнивает src, а не value, чтобы избежать расхождений из-за относительных путей).
const highlightImage = (icon, gridId) => {
  document.getElementById(gridId)?.querySelectorAll('.image-item').forEach(el => {
    el.classList.toggle('selected', el.querySelector('img')?.src === icon);
  });
};

// Списки родителей (для форм добавления и импорта)

// Универсальный рендер списка папок. Принимает ID контейнера и целевого инпута, чтобы не дублировать логику.
const renderParents = (containerId, targetId) => {
  const c = document.getElementById(containerId);
  if (!c) return;
  c.innerHTML = `<div class="parent-item" data-path=""><span>📁</span><span>Корневая папка</span></div>`;
  const build = (items, path) => items.forEach(item => {
    if (item.children !== null) {
      const p = path ? `${path}/${item.name}` : item.name;
      const div = document.createElement('div');
      div.className = 'parent-item';
      div.dataset.path = p;
      div.innerHTML = `<span>📁</span><span>${p}</span>`;
      div.onclick = () => {
        document.querySelectorAll(`#${containerId} .parent-item`).forEach(i => i.classList.remove('selected'));
        div.classList.add('selected');
        document.getElementById(targetId).value = p;
      };
      c.appendChild(div);
      if (item.children?.length) build(item.children, p);
    }
  });
  build(state.catalog?.children ?? [], '');
};

// Поиск

// Навешиваем обработчики на все поисковые поля. Фильтруем либо DOM-элементы, либо массив в состоянии.
const setupSearch = () => {
  document.getElementById('treeSearch')?.addEventListener('input', e => {
    const q = e.target.value.toLowerCase();
    document.querySelectorAll('.tree-item').forEach(i => i.style.display = !q || i.querySelector('span:last-child').textContent.toLowerCase().includes(q) ? 'flex' : 'none');
  });
  document.getElementById('imageSearch')?.addEventListener('input', e => {
    state.filteredImages = state.images.filter(i => i.name.toLowerCase().includes(e.target.value.toLowerCase()));
    renderGrid('addImagesGrid', 'addIcon', state.filteredImages);
  });
  ['parentSearch', 'importParentSearch'].forEach(id => {
    document.getElementById(id)?.addEventListener('input', e => {
      const q = e.target.value.toLowerCase();
      const target = id.includes('import') ? 'importParentList' : 'parentList';
      document.querySelectorAll(`#${target} .parent-item`).forEach(i => i.style.display = !q || i.querySelector('span:last-child').textContent.toLowerCase().includes(q) ? 'flex' : 'none');
    });
  });
};

// CRUD операции

// Обновление существующего элемента. Собирает данные формы, чистит иконку, шлёт PUT и POST/DELETE для permanent.
const updateItem = async e => {
  e.preventDefault();
  const path = document.getElementById('editPath').value;
  const icon = cleanIcon(state.selectedImage || document.getElementById('editIcon').value);
  const updates = { name: document.getElementById('editName').value.toUpperCase(), icon };
  const url = document.getElementById('editUrl').value;
  if (url) updates.url = url;
  try {
    await api('items', { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ path, updates }) });
    await api('permanent', { method: document.getElementById('editPermanent').checked ? 'POST' : 'DELETE', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ path }) });
    showStatus('Элемент обновлён', 'success');
    state.selectedImage = null;
    await loadData();
    localStorage.setItem('catalogUpdated', Date.now()); // Триггер для других вкладок
  } catch (err) { showStatus('Ошибка: ' + err.message, 'error'); }
};

// Создание нового элемента. Аналогично обновлению, но метод POST и сброс формы.
const addItem = async e => {
  e.preventDefault();
  const parent = document.getElementById('addParentPath').value;
  const name = document.getElementById('addName').value.toUpperCase();
  const icon = cleanIcon(state.selectedImage || document.getElementById('addIcon').value || 'folder.png');
  const url = document.getElementById('addUrl').value;
  const perm = document.getElementById('addPermanent').checked;
  const body = { parent_path: parent, name, icon };
  if (url) body.url = url;
  try {
    await api('items', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
    if (perm) await api('permanent', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ path: parent ? `${parent}/${name}` : name }) });
    showStatus('Элемент добавлен', 'success');
    e.target.reset();
    state.selectedImage = null;
    await loadData();
    localStorage.setItem('catalogUpdated', Date.now());
  } catch (err) { showStatus('Ошибка: ' + err.message, 'error'); }
};

// Удаление. Выносим в window.*, так как вызывается через onclick в HTML.
window.deleteCurrentItem = async () => {
  if (!state.selected || !confirm(`Удалить "${state.selected.name}"?`)) return;
  try {
    await api('items', { method: 'DELETE', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ path: state.selected.path }) });
    await api('permanent', { method: 'DELETE', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ path: state.selected.path }) });
    showStatus('Удалено', 'success');
    document.getElementById('editForm').classList.add('hidden');
    state.selected = state.selectedImage = null;
    await loadData();
  } catch (err) { showStatus('Ошибка: ' + err.message, 'error'); }
};

// Парсер

// Запуск парсера. Блокируем кнопки, шлём запрос, если ок → начинаем поллинг статуса.
window.startParser = async () => {
  const btns = document.querySelectorAll('button[onclick="startParser()"]');
  btns.forEach(b => { b.disabled = true; b.textContent = 'Парсинг...'; });
  try {
    const res = await api('parser/start', { method: 'POST' });
    if (res.status === 'started') { showStatus('Парсер запущен...', 'success'); checkParserStatus(); }
    else throw new Error('Парсер уже запущен');
  } catch (err) {
    showStatus('Ошибка: ' + err.message, 'error');
    btns.forEach(b => { b.disabled = false; b.textContent = 'Парсер'; });
  }
};

/**
 * Универсальный опрос статуса. Заменяет дублирующиеся loadParserStatus и checkParserStatus.
 * @param isInitial - если true, не выполняем логику завершения (нужно только при первой загрузке страницы)
 */
const updateParserStatus = async (isInitial = false) => {
  try {
    const s = await api('parser/status');
    document.getElementById('parserStatusText').textContent = s.message;
    document.getElementById('parserLastRun').textContent = s.last_run || '-';
    document.getElementById('parserStatus').className = `parser-status ${s.running ? 'running' : 'completed'}`;
    
    if (s.running) {
      setTimeout(checkParserStatus, 2000); // Продолжаем опрос
    } else if (!isInitial) {
      // Парсер закончил работу: разблокируем кнопки, помечаем всё как permanent, обновляем UI.
      document.querySelectorAll('button[onclick="startParser()"]').forEach(b => { b.disabled = false; b.textContent = 'Парсер'; });
      await makeAllPermanent();
      await loadData();
      showStatus('Парсинг завершён!', 'success');
      localStorage.setItem('catalogUpdated', Date.now());
      notify('Парсер завершил работу', 'Все элементы сохранены.');
    }
  } catch (err) {
    console.error(err);
    document.querySelectorAll('button[onclick="startParser()"]').forEach(b => { b.disabled = false; b.textContent = 'Парсер'; });
  }
};

const checkParserStatus = () => updateParserStatus(false);

/**
 * После работы парсера сервер может создать новые узлы без флага permanent.
 * Эта функция проходит по всему дереву и ставит флаг, чтобы при обновлении страницы ничего не потерялось.
 */
const makeAllPermanent = async () => {
  const getPaths = (items = state.catalog?.children ?? [], path = '') =>
    items.flatMap(item => [path ? `${path}/${item.name}` : item.name, ...(item.children?.length ? getPaths(item.children, path ? `${path}/${item.name}` : item.name) : [])]);
  const newPaths = getPaths().filter(p => !state.permanent.includes(p));
  for (const p of newPaths) await api('permanent', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ path: p }) });
  state.permanent = (await api('permanent')).permanent_items ?? [];
};

// Импорт/Экспорт

// Импорт JSON из textarea. Валидирует ввод, шлёт на сервер, перезагружает данные.
const importJson = async e => {
  e.preventDefault();
  const data = document.getElementById('importJsonData').value.trim();
  if (!data) return showStatus('Введите JSON', 'error');
  try {
    const res = await api('import/json', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ json_data: data, parent_path: document.getElementById('importParentPath').value }) });
    showStatus(res.message || 'Импорт успешен', 'success');
    e.target.reset();
    await loadData();
  } catch (err) { showStatus('Ошибка: ' + err.message, 'error'); }
};

// Экспорт каталога в плоский JSON-файл для бэкапа или миграции.
window.exportJson = async () => {
  try {
    const data = await api('catalog');
    const collect = (items, cat) => items.flatMap(i => [{ name: i.name, icon: i.icon, url: i.url || null, modified: i.modified, catalog: cat }, ...(i.children?.length ? collect(i.children, i.name) : [])]);
    const all = data.children.flatMap(c => collect(c.children || [], c.name));
    const blob = new Blob([JSON.stringify(all, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `catalog_export_${new Date().toISOString().slice(0,10)}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
    showStatus('JSON выгружен', 'success');
  } catch (err) { showStatus('Ошибка: ' + err.message, 'error'); }
};

// Инициализация

document.addEventListener('DOMContentLoaded', () => {
  loadData();
  // Переключение вкладок
  document.querySelectorAll('.tab').forEach(tab => tab.onclick = () => {
    document.querySelectorAll('.tab, .tab-content').forEach(el => el.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(`${tab.dataset.tab}Tab`).classList.add('active');
  });
  setupSearch();
  document.getElementById('editForm').addEventListener('submit', updateItem);
  document.getElementById('addForm').addEventListener('submit', addItem);
  document.getElementById('importForm')?.addEventListener('submit', importJson);
  
  // Кросс-таб синхронизация: если в другой вкладке завершился парсер → обновляем данные здесь.
  window.addEventListener('storage', e => e.key === 'catalogUpdated' && loadData().then(() => showStatus('Данные обновлены', 'success')));
});

// Глобальные хелперы для вызова из HTML-атрибутов onclick
window.logout = () => location.href = '/navigator/logout';
window.changePassword = () => location.href = '/navigator/change-password';
