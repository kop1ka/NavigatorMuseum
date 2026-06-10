$(document).ready(function () {
    // Динамическое вычисление размеров книги
    const bookContainer = document.getElementById("demoBookExample");
    const containerWidth = bookContainer.clientWidth; // Ширина контейнера книги
    const containerHeight = bookContainer.clientHeight; // Высота контейнера книги

    // Инициализация PageFlip с динамическими размерами
    const pageFlip = new PageFlip(
        bookContainer,
        {
            width: containerWidth, // Ширина книги равна ширине контейнера
            height: containerHeight, // Высота книги равна высоте контейнера
            size: "stretch",
            minWidth: 200, // Минимальная ширина книги
            maxWidth: 600, // Максимальная ширина книги
            minHeight: 300, // Минимальная высота книги
            maxHeight: 800, // Максимальная высота книги
            maxShadowOpacity: 0.5,
            showCover: true,
            mobileScrollSupport: false
        }
    );

    // Загрузка страниц
    pageFlip.loadFromHTML(document.querySelectorAll(".page"));

    // Обработчик для кнопки поиска
    $('#searchButton').on('click', function () {
        const pageNumber = parseInt($('#searchInput').val()); // Получаем номер страницы
        const totalPages = pageFlip.getPageCount(); // Получаем общее количество страниц

        if (pageNumber >= 1 && pageNumber <= totalPages) {
            // Переход на указанную страницу (индексация с 0)
            pageFlip.flip(pageNumber - 1);
        } else {
            alert('Пожалуйста, введите действительный номер страницы (от 1 до ' + totalPages + ').');
        }
    });

    // Обработчик нажатия Enter в поле поиска
    $('#searchInput').on('keypress', function (e) {
        if (e.key === 'Enter') {
            $('#searchButton').click(); // Выполняем поиск при нажатии Enter
        }
    });

    // Обновление текущей страницы при перелистывании
    pageFlip.on('flip', function (e) {
        $('.page-current').text(e.data + 1); // Индексация с 0, поэтому +1
    });
});