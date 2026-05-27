# Блок-схема поиска элементов

```mermaid
flowchart TD
    Start([Начало]) --> Input[Ввод текста в #searchInput]
    Input --> UpdateQuery[Обновление currentSearchQuery]
    UpdateQuery --> CheckText{Текст есть?}
    
    CheckText -- Да --> ShowClear[Показать кнопку очистки]
    CheckText -- Нет --> HideClear[Скрыть кнопку очистки]
    
    ShowClear --> Render[Вызов renderCurrentLevel]
    HideClear --> Render
    
    Render --> CheckSearch{Есть поисковый запрос?}
    
    CheckSearch -- Нет --> GetChildren[Получить children текущей папки]
    GetChildren --> RenderItems[renderItems с isSearchResults=false]
    
    CheckSearch -- Да --> CallSearch[Вызов searchInCatalog]
    CallSearch --> SearchLoop{Перебор элементов}
    
    SearchLoop --> MatchCheck{Совпадение по name?}
    
    MatchCheck -- Да --> AddToResult[Добавить в resultsFound]
    MatchCheck -- Нет --> CheckChildren{Есть children?}
    
    CheckChildren -- Да --> Recurse[Рекурсивный вызов searchInCatalog]
    Recurse --> SearchLoop
    CheckChildren -- Нет --> SearchLoop
    
    AddToResult --> SearchLoop
    SearchLoop -- Элементы кончились --> ReturnResults[Вернуть массив результатов]
    
    ReturnResults --> RenderSearch[renderItems с isSearchResults=true]
    RenderItems --> End([Конец])
    RenderSearch --> End
    
    ClickClear[Клик на #searchClearBtn] --> ClearFunc[Вызов clearSearch]
    ClearFunc --> ResetQuery[Очистить currentSearchQuery]
    ResetQuery --> ResetInput[Очистить value у searchInput]
    ResetInput --> HideBtn[Скрыть кнопку очистки]
    HideBtn --> GoRoot[Установить currentFolder = root]
    GoRoot --> RenderRoot[renderCurrentLevel]
    RenderRoot --> End
```

## Описание блоков:

1. **Ввод данных**: Пользователь вводит текст в поле `#searchInput`
2. **Обработка ввода**: 
   - Обновляется переменная `currentSearchQuery`
   - Показывается/скрывается кнопка очистки в зависимости от наличия текста
3. **Рендеринг**: Вызывается `renderCurrentLevel()`
4. **Логика поиска**:
   - Если запрос пустой → отображаются дети текущей папки
   - Если запрос есть → запускается рекурсивный поиск `searchInCatalog()`
5. **Рекурсивный поиск**:
   - Проходит по всем элементам каталога
   - Сравнивает `name` элемента с запросом (case-insensitive)
   - При совпадении добавляет в результат
   - Если у элемента есть `children`, рекурсивно ищет внутри них
6. **Отображение результатов**: Результаты передаются в `renderItems()` с флагом `isSearchResults=true`
7. **Очистка**: Клик на кнопку очистки сбрасывает всё и возвращает к корневой папке
