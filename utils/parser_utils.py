"""Утилиты для парсинга FTP-каталога"""
import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed


def extract_items_from_html(html_content, base_url):
    """Извлечь элементы каталога из HTML страницы FTP"""
    print(f"[DEBUG extract_items] Начало обработки HTML для {base_url}")
    print(f"[DEBUG extract_items] Размер HTML: {len(html_content)} bytes")
    
    soup = BeautifulSoup(html_content, 'html.parser')
    items = []
    
    table = soup.find('table')
    if not table:
        print(f"[DEBUG extract_items WARNING] Таблица не найдена в HTML для {base_url}")
        # Выведем первые 500 символов HTML для отладки
        print(f"[DEBUG extract_items] Первые 500 символов HTML: {html_content[:500]}")
        return items
    
    rows = table.find_all('tr')
    print(f"[DEBUG extract_items] Найдено строк (tr) в таблице: {len(rows)}")
    
    for row in rows:
        cells = row.find_all('td')
        if len(cells) < 5:
            continue
        
        link = cells[1].find('a')
        if not link:
            continue
        
        name_text = link.get_text(strip=True)
        if name_text == 'Parent Directory':
            continue
        
        href = link.get('href', '')
        modified = cells[2].get_text(strip=True) if cells[2] else None
        
        img = cells[0].find('img')
        is_folder = img and '[DIR]' in img.get('alt', '')
        
        full_url = urljoin(base_url, href)
        
        print(f"[DEBUG extract_items] Элемент: name='{name_text}', href='{href}', is_folder={is_folder}")
        
        if is_folder:
            items.append({
                'name': unquote(name_text.rstrip('/')),
                'icon': 'page/logo.png',
                'children': [],
                'url': full_url,
                'modified': modified
            })
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
    
    if depth > max_depth or url in visited:
        return []
    
    visited.add(url)
    
    # ОТЛАДКА: Информация о вызове
    print(f"[DEBUG parse_folder] Вызов: url={url}, depth={depth}, max_depth={max_depth}")
    
    try:
        print(f"[DEBUG parse_folder] Запрос к {url} (timeout={timeout})...")
        response = requests.get(url, timeout=timeout, verify=False)
        response.raise_for_status()
        print(f"[DEBUG parse_folder] Получен ответ: status_code={response.status_code}, size={len(response.text)} bytes")
        
        items = extract_items_from_html(response.text, url)
        print(f"[DEBUG parse_folder] Извлечено элементов: {len(items)}")
        if items and depth == 0:
            print(f"[DEBUG parse_folder] Первые 3 элемента: {items[:3]}")
        
        folders_to_parse = [item for item in items if item['children'] is not None and item['url']]
        print(f"[DEBUG parse_folder] Найдено папок для парсинга: {len(folders_to_parse)}")
        
        if folders_to_parse and depth < max_depth:
            print(f"[DEBUG parse_folder] Запуск многопоточного парсинга {len(folders_to_parse)} папок...")
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_item = {
                    executor.submit(_parse_folder_recursive, item['url'], visited, depth + 1, max_depth, timeout): item
                    for item in folders_to_parse
                }
                
                for future in as_completed(future_to_item):
                    item = future_to_item[future]
                    try:
                        item['children'] = future.result()
                        print(f"[DEBUG parse_folder] Спарсена папка {item['url']}: найдено {len(item['children'])} элементов")
                    except Exception as e:
                        print(f"[DEBUG parse_folder] Ошибка при парсинге папки {item['url']}: {e}")
                        item['children'] = []
        
        print(f"[DEBUG parse_folder] Завершение: url={url}, возвращено {len(items)} элементов")
        return items
        
    except Exception as e:
        import traceback
        print(f"[DEBUG parse_folder ERROR] Ошибка при парсинге {url}: {e}")
        print(f"[DEBUG parse_folder ERROR] Трассировка: {traceback.format_exc()}")
        return []


def _parse_folder_recursive(url, visited, depth, max_depth, timeout):
    """Вспомогательная функция для рекурсивного парсинга"""
    return parse_folder(url, visited, depth, max_depth, timeout)
