"""Утилиты для парсинга FTP-каталога"""
import requests
import urllib3
from bs4 import BeautifulSoup
from urllib.parse import unquote, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

# Подавление SSL-предупреждений при использовании verify=False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def extract_items_from_html(html_content, base_url):
    """Извлечь элементы каталога из HTML страницы FTP"""
    print(f"[DEBUG extract_items] Начало обработки HTML для {base_url}")
    print(f"[DEBUG extract_items] Размер HTML: {len(html_content)} bytes")
    print(f"[DEBUG extract_items] Тип html_content: {type(html_content)}")
    
    soup = BeautifulSoup(html_content, 'html.parser')
    items = []
    
    print(f"[DEBUG extract_items] BeautifulSoup создан, тип soup: {type(soup)}")
    
    table = soup.find('table')
    if not table:
        print(f"[DEBUG extract_items WARNING] Таблица не найдена в HTML для {base_url}")
        # Выведем первые 1000 символов HTML для отладки
        print(f"[DEBUG extract_items] Первые 1000 символов HTML: {html_content[:1000]}")
        print(f"[DEBUG extract_items] Теги в HTML: {[tag.name for tag in soup.find_all()][:20]}")
        return items
    
    print(f"[DEBUG extract_items] Таблица найдена: {table}")
    
    rows = table.find_all('tr')
    print(f"[DEBUG extract_items] Найдено строк (tr) в таблице: {len(rows)}")
    
    for i, row in enumerate(rows):
        print(f"[DEBUG extract_items] Обработка строки {i}: {row}")
        cells = row.find_all('td')
        print(f"[DEBUG extract_items] Найдено ячеек (td): {len(cells)}")
        if len(cells) < 5:
            print(f"[DEBUG extract_items SKIP] Строка {i} пропущена: меньше 5 ячеек")
            continue
        
        link = cells[1].find('a')
        print(f"[DEBUG extract_items] Ссылка в ячейке 1: {link}")
        if not link:
            print(f"[DEBUG extract_items SKIP] Нет ссылки в строке {i}")
            continue
        
        name_text = link.get_text(strip=True)
        print(f"[DEBUG extract_items] Текст ссылки: '{name_text}'")
        if name_text == 'Parent Directory':
            print(f"[DEBUG extract_items SKIP] Пропуск Parent Directory")
            continue
        
        href = link.get('href', '')
        print(f"[DEBUG extract_items] href: '{href}'")
        modified = cells[2].get_text(strip=True) if cells[2] else None
        print(f"[DEBUG extract_items] modified: '{modified}'")
        
        img = cells[0].find('img')
        print(f"[DEBUG extract_items] img: {img}")
        is_folder = img and '[DIR]' in img.get('alt', '')
        print(f"[DEBUG extract_items] is_folder={is_folder}, alt='{img.get('alt', '') if img else 'N/A'}'")
        
        full_url = urljoin(base_url, href)
        print(f"[DEBUG extract_items] full_url: {full_url}")
        
        print(f"[DEBUG extract_items] Элемент: name='{name_text}', href='{href}', is_folder={is_folder}")
        
        if is_folder:
            items.append({
                'name': unquote(name_text.rstrip('/')),
                'icon': 'page/logo.png',
                'children': [],
                'url': full_url,
                'modified': modified
            })
            print(f"[DEBUG extract_items] Добавлена папка: {name_text}")
        else:
            name_without_ext = unquote(name_text)
            if '.' in name_without_ext:
                name_without_ext = name_without_ext.rsplit('.', 1)[0]
            items.append({
                'name': name_without_ext,
                'icon': 'page/logo.png',
                'children': None,
                'url': full_url,
                'modified': modified
            })
            print(f"[DEBUG extract_items] Добавлен файл: {name_text}")
    
    print(f"[DEBUG extract_items] Всего извлечено элементов: {len(items)}")
    return items


def parse_folder(url, visited=None, depth=0, max_depth=10, timeout=10, max_workers=5, delay=2):
    """
    Парсинг FTP-каталога с многопоточностью и задержками для избежания 429 ошибок
    
    Args:
        url: URL для парсинга
        visited: множество посещённых URL
        depth: текущая глубина рекурсии
        max_depth: максимальная глубина парсинга
        timeout: таймаут запроса в секундах
        max_workers: количество потоков для параллельного парсинга
        delay: задержка между запросами в секундах
    
    Returns:
        list: список элементов каталога
    """
    if visited is None:
        visited = set()
    
    print(f"[DEBUG parse_folder START] Вызов: url={url}, depth={depth}, max_depth={max_depth}, timeout={timeout}")
    print(f"[DEBUG parse_folder START] visited содержит {len(visited)} URL'ов")
    
    if depth > max_depth:
        print(f"[DEBUG parse_folder SKIP] Превышена максимальная глубина: depth={depth} > max_depth={max_depth}")
        return []
    
    if url in visited:
        print(f"[DEBUG parse_folder SKIP] URL уже посещён: {url}")
        return []
    
    visited.add(url)
    print(f"[DEBUG parse_folder] URL добавлен в visited, теперь {len(visited)} URL'ов")
    
    # ОТЛАДКА: Информация о вызове
    print(f"[DEBUG parse_folder] Вызов: url={url}, depth={depth}, max_depth={max_depth}")
    
    try:
        # Добавляем задержку перед запросом для избежания 429 ошибок
        import time
        if depth > 0:  # Не задерживаем первый запрос
            print(f"[DEBUG parse_folder] Задержка {delay}s перед запросом к {url}...")
            time.sleep(delay)
        
        print(f"[DEBUG parse_folder] Запрос к {url} (timeout={timeout})...")
        log_detail = f"URL: {url}, timeout: {timeout}s, depth: {depth}, max_depth: {max_depth}"
        
        try:
            print(f"[DEBUG parse_folder] Выполнение requests.get(url='{url}', timeout={timeout}, verify=False)")
            response = requests.get(url, timeout=timeout, verify=False)
            print(f"[DEBUG parse_folder] Получен ответ: status_code={response.status_code}, size={len(response.text)} bytes")
            print(f"[DEBUG parse_folder] Заголовки ответа: {dict(response.headers)}")
            
            # Проверка на 429 ошибку с автоматической обработкой
            if response.status_code == 429:
                print(f"[WARNING parse_folder] Получена 429 ошибка (Too Many Requests) от {url}")
                
                # Пытаемся получить время ожидания из заголовка Retry-After
                retry_after = response.headers.get('Retry-After')
                if retry_after:
                    wait_time = int(retry_after)
                    print(f"[WARNING parse_folder] Сервер запросил ожидание {wait_time}s (из заголовка Retry-After)")
                else:
                    # Экспоненциальная задержка: delay * 2, delay * 4, delay * 8
                    wait_time = delay * (2 ** 1)  # Первая повторная попытка
                    print(f"[WARNING parse_folder] Используем экспоненциальную задержку {wait_time}s")
                
                print(f"[WARNING parse_folder] Ожидание {wait_time}s перед повторной попыткой...")
                time.sleep(wait_time)
                
                # Повторная попытка с увеличенным таймаутом
                response = requests.get(url, timeout=timeout * 2, verify=False)
                print(f"[DEBUG parse_folder] Повторный ответ: status_code={response.status_code}")
                
                # Если снова 429, пробуем ещё раз с большей задержкой
                if response.status_code == 429:
                    retry_after = response.headers.get('Retry-After')
                    if retry_after:
                        wait_time = int(retry_after)
                    else:
                        wait_time = delay * (2 ** 2)  # Вторая повторная попытка
                    
                    print(f"[WARNING parse_folder] Снова 429 ошибка. Ожидание {wait_time}s...")
                    time.sleep(wait_time)
                    response = requests.get(url, timeout=timeout * 3, verify=False)
                    print(f"[DEBUG parse_folder] Третий ответ: status_code={response.status_code}")
            
            # Проверка статуса ответа
            if response.status_code != 200:
                print(f"[ERROR parse_folder] Неожиданный HTTP статус: {response.status_code}")
                print(f"[ERROR parse_folder] Заголовки ответа: {dict(response.headers)}")
                print(f"[ERROR parse_folder] Тело ответа (первые 1000 символов): {response.text[:1000]}")
            
            response.raise_for_status()
            print(f"[DEBUG parse_folder] response.raise_for_status() выполнен успешно")
            
        except requests.exceptions.Timeout as e:
            print(f"[ERROR parse_folder] Таймаут подключения к {url}")
            print(f"[ERROR parse_folder] Детали таймаута: {e}")
            print(f"[ERROR parse_folder] Конфигурация: timeout={timeout}s, url={url}")
            raise
        except requests.exceptions.ConnectionError as e:
            print(f"[ERROR parse_folder] Ошибка подключения к {url}")
            print(f"[ERROR parse_folder] Детали ошибки подключения: {e}")
            if hasattr(e, 'reason'):
                print(f"[ERROR parse_folder] Причина: {e.reason}")
            if hasattr(e, 'request'):
                print(f"[ERROR parse_folder] Запрос: {e.request}")
            print(f"[ERROR parse_folder] Конфигурация: timeout={timeout}s, url={url}")
            raise
        except requests.exceptions.RequestException as e:
            print(f"[ERROR parse_folder] Общая ошибка запроса к {url}")
            print(f"[ERROR parse_folder] Тип ошибки: {type(e).__name__}")
            print(f"[ERROR parse_folder] Детали: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"[ERROR parse_folder] Статус ответа: {e.response.status_code}")
                print(f"[ERROR parse_folder] Тело ответа (первые 1000 символов): {str(e.response.text[:1000])}")
            raise
        
        print(f"[DEBUG parse_folder] Начало обработки HTML контента...")
        items = extract_items_from_html(response.text, url)
        print(f"[DEBUG parse_folder] Извлечено элементов: {len(items)}")
        if items and depth == 0:
            print(f"[DEBUG parse_folder] Первые 3 элемента: {items[:3]}")
        elif items:
            print(f"[DEBUG parse_folder] Пример элемента: {items[0]}")
        
        folders_to_parse = [item for item in items if item['children'] is not None and item['url']]
        print(f"[DEBUG parse_folder] Найдено папок для парсинга: {len(folders_to_parse)}")
        if folders_to_parse:
            print(f"[DEBUG parse_folder] Папки для парсинга: {[f['url'] for f in folders_to_parse]}")
        
        if folders_to_parse and depth < max_depth:
            print(f"[DEBUG parse_folder] Запуск многопоточного парсинга {len(folders_to_parse)} папок с max_workers={max_workers}...")
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_item = {
                    executor.submit(_parse_folder_recursive, item['url'], visited, depth + 1, max_depth, timeout, delay): item
                    for item in folders_to_parse
                }
                
                print(f"[DEBUG parse_folder] Создано {len(future_to_item)} задач для выполнения")
                
                for future in as_completed(future_to_item):
                    item = future_to_item[future]
                    try:
                        result = future.result()
                        item['children'] = result
                        print(f"[DEBUG parse_folder] Спарсена папка {item['url']}: найдено {len(result)} элементов")
                    except Exception as e:
                        import traceback
                        print(f"[DEBUG parse_folder] Ошибка при парсинге папки {item['url']}: {e}")
                        print(f"[DEBUG parse_folder] Трассировка: {traceback.format_exc()}")
                        item['children'] = []
        else:
            if depth >= max_depth:
                print(f"[DEBUG parse_folder] Пропуск рекурсивного парсинга: достигнута максимальная глубина depth={depth}")
            else:
                print(f"[DEBUG parse_folder] Пропуск рекурсивного парсинга: нет папок для обработки")
        
        print(f"[DEBUG parse_folder] Завершение: url={url}, возвращено {len(items)} элементов")
        return items
        
    except Exception as e:
        import traceback
        print(f"[DEBUG parse_folder ERROR] Ошибка при парсинге {url}: {e}")
        print(f"[DEBUG parse_folder ERROR] Тип ошибки: {type(e).__name__}")
        print(f"[DEBUG parse_folder ERROR] Трассировка: {traceback.format_exc()}")
        return []


def _parse_folder_recursive(url, visited, depth, max_depth, timeout, delay=2):
    """Вспомогательная функция для рекурсивного парсинга"""
    return parse_folder(url, visited, depth, max_depth, timeout, delay=delay)
