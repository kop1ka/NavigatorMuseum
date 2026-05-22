"""Утилиты для парсинга FTP-каталога"""
import requests
import urllib3
import json
import os
import time
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import unquote, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

# Подавление SSL-предупреждений при использовании verify=False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Путь к файлу логов ошибок
ERROR_LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'error_log.json')

# Путь к файлу детальных логов парсера (для отладки ответов сервера)
PARSER_DEBUG_LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'parser_debug_log.json')

# Задержка между запросами к FTP-серверу (в секундах) для избежания 429 ошибки
REQUEST_DELAY = 2.0  # 2 секунды между запросами


def log_parser_response(url, response, depth=0):
    """
    Сохранить детальную информацию об ответе сервера в JSON файл для отладки
    
    Args:
        url: URL запроса
        response: объект ответа requests
        depth: глубина рекурсии
    """
    # Форматируем время в читаемом формате: ДД.ММ.ГГГГ ЧЧ:ММ:СС
    now = datetime.now()
    formatted_timestamp = now.strftime('%d.%m.%Y %H:%M:%S')
    
    log_entry = {
        'timestamp': formatted_timestamp,
        'url': url,
        'depth': depth,
        'response': {
            'status_code': response.status_code,
            'headers': dict(response.headers),
            'content_length': len(response.text),
            'encoding': response.encoding,
            'apparent_encoding': response.apparent_encoding,
            'full_content': response.text,
            'content_preview': response.text[:5000] if len(response.text) > 5000 else response.text
        }
    }
    
    # Читаем существующие логи или создаём новую структуру
    if os.path.exists(PARSER_DEBUG_LOG_FILE):
        try:
            with open(PARSER_DEBUG_LOG_FILE, 'r', encoding='utf-8') as f:
                logs = json.load(f)
        except (json.JSONDecodeError, IOError):
            logs = {'responses': []}
    else:
        logs = {'responses': []}
    
    # Добавляем новую запись
    logs['responses'].append(log_entry)
    
    # Сохраняем обратно в файл
    with open(PARSER_DEBUG_LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(logs, f, indent=2, ensure_ascii=False)
    
    print(f"[LOG] Ответ сервера записан в {PARSER_DEBUG_LOG_FILE}: {url} (status={response.status_code}, size={len(response.text)} bytes)")


def log_error_to_json(error_type, url, response=None, exception=None, depth=None, timeout=None):
    """
    Сохранить информацию об ошибке в JSON файл
    
    Args:
        error_type: тип ошибки (timeout, connection, http_error, parse_error, etc.)
        url: URL, при запросе к которому произошла ошибка
        response: объект ответа requests (опционально)
        exception: объект исключения (опционально)
        depth: глубина рекурсии (опционально)
        timeout: таймаут запроса (опционально)
    """
    log_entry = {
        'timestamp': datetime.now().isoformat(),
        'error_type': error_type,
        'url': url,
        'depth': depth,
        'timeout': timeout,
        'response': {
            'status_code': response.status_code if response else None,
            'headers': dict(response.headers) if response else None,
            'content_length': len(response.text) if response else None,
            'content_preview': response.text[:2000] if response else None,
            'encoding': response.encoding if response else None
        } if response else None,
        'exception': {
            'type': type(exception).__name__ if exception else None,
            'message': str(exception) if exception else None,
            'has_response': hasattr(exception, 'response') and exception.response is not None,
            'response_status': exception.response.status_code if hasattr(exception, 'response') and exception.response is not None else None
        } if exception else None
    }
    
    # Читаем существующие логи или создаём новую структуру
    if os.path.exists(ERROR_LOG_FILE):
        try:
            with open(ERROR_LOG_FILE, 'r', encoding='utf-8') as f:
                logs = json.load(f)
        except (json.JSONDecodeError, IOError):
            logs = {'errors': []}
    else:
        logs = {'errors': []}
    
    # Добавляем новую запись
    logs['errors'].append(log_entry)
    
    # Сохраняем обратно в файл
    with open(ERROR_LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(logs, f, indent=2, ensure_ascii=False)
    
    print(f"[LOG] Ошибка записана в {ERROR_LOG_FILE}: {error_type} для {url}")


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
        # Заменить домен с 192.168.3.78:8085 на vm-ftp.anosov.ru
        full_url = full_url.replace('192.168.3.78:8085', 'vm-ftp.anosov.ru')
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


def parse_folder(url, visited=None, depth=0, max_depth=10, timeout=10, max_workers=5):
    """
    Парсинг FTP-каталога с многопоточностью
    
    Args:
        url: URL для парсинга
        visited: множество посещённых URL
        depth: текущая глубина рекурсии
        max_depth: максимальная глубина парсинга
        timeout: таймаут запроса в секундах
        max_workers: количество потоков для параллельного парсинга
    
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
        print(f"[DEBUG parse_folder] Запрос к {url} (timeout={timeout})...")
        log_detail = f"URL: {url}, timeout: {timeout}s, depth: {depth}, max_depth: {max_depth}"
        
        # Добавляем задержку перед запросом для избежания 429 ошибки
        time.sleep(REQUEST_DELAY)
        
        try:
            print(f"[DEBUG parse_folder] Выполнение requests.get(url='{url}', timeout={timeout}, verify=False)")
            response = requests.get(url, timeout=timeout, verify=False)
            print(f"[DEBUG parse_folder] Получен ответ: status_code={response.status_code}, size={len(response.text)} bytes")
            print(f"[DEBUG parse_folder] Заголовки ответа: {dict(response.headers)}")
            
            # Логирование полного ответа сервера для отладки
            log_parser_response(url, response, depth)
            
            # Проверка статуса ответа
            if response.status_code != 200:
                print(f"[ERROR parse_folder] Неожиданный HTTP статус: {response.status_code}")
                print(f"[ERROR parse_folder] Заголовки ответа: {dict(response.headers)}")
                print(f"[ERROR parse_folder] Тело ответа (первые 1000 символов): {response.text[:1000]}")
                log_error_to_json('http_error', url, response=response, depth=depth, timeout=timeout)
            
            response.raise_for_status()
            print(f"[DEBUG parse_folder] response.raise_for_status() выполнен успешно")
            
        except requests.exceptions.Timeout as e:
            print(f"[ERROR parse_folder] Таймаут подключения к {url}")
            print(f"[ERROR parse_folder] Детали таймаута: {e}")
            print(f"[ERROR parse_folder] Конфигурация: timeout={timeout}s, url={url}")
            log_error_to_json('timeout', url, exception=e, depth=depth, timeout=timeout)
            raise
        except requests.exceptions.ConnectionError as e:
            print(f"[ERROR parse_folder] Ошибка подключения к {url}")
            print(f"[ERROR parse_folder] Детали ошибки подключения: {e}")
            if hasattr(e, 'reason'):
                print(f"[ERROR parse_folder] Причина: {e.reason}")
            if hasattr(e, 'request'):
                print(f"[ERROR parse_folder] Запрос: {e.request}")
            print(f"[ERROR parse_folder] Конфигурация: timeout={timeout}s, url={url}")
            log_error_to_json('connection_error', url, exception=e, depth=depth, timeout=timeout)
            raise
        except requests.exceptions.RequestException as e:
            print(f"[ERROR parse_folder] Общая ошибка запроса к {url}")
            print(f"[ERROR parse_folder] Тип ошибки: {type(e).__name__}")
            print(f"[ERROR parse_folder] Детали: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"[ERROR parse_folder] Статус ответа: {e.response.status_code}")
                print(f"[ERROR parse_folder] Тело ответа (первые 1000 символов): {str(e.response.text[:1000])}")
                log_error_to_json('request_exception', url, response=e.response, exception=e, depth=depth, timeout=timeout)
            else:
                log_error_to_json('request_exception', url, exception=e, depth=depth, timeout=timeout)
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
            print(f"[DEBUG parse_folder] Запуск многопоточного парсинга {len(folders_to_parse)} папок...")
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_item = {
                    executor.submit(_parse_folder_recursive, item['url'], visited, depth + 1, max_depth, timeout): item
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
        log_error_to_json('parse_error', url, exception=e, depth=depth, timeout=timeout)
        return []


def _parse_folder_recursive(url, visited, depth, max_depth, timeout):
    """Вспомогательная функция для рекурсивного парсинга"""
    return parse_folder(url, visited, depth, max_depth, timeout)
