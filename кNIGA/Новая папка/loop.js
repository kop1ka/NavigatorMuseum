const toggleLoopButton = document.getElementById('toggleLoop');
const image = document.getElementById('zoomableImage');
let isZoomEnabled = false;
let scale = 1;
toggleLoopButton.addEventListener('click', () => {
    isZoomEnabled = !isZoomEnabled;
    
    if (isZoomEnabled) {
        document.body.classList.add('cursor-zoom');
    } else {
        document.body.classList.remove('cursor-zoom');
        scale = 1; // Сбросить масштаб при отключении лупы
        image.style.transform = `scale(${scale})`;
    }
});
image.addEventListener('wheel', (event) => {
    if (!isZoomEnabled) return;
    event.preventDefault();
    
    if (event.deltaY < 0) {
        scale *= 1.1; // Увеличение
    } else {
        scale /= 1.1; // Уменьшение
    }
    image.style.transform = `scale(${scale})`;
});
