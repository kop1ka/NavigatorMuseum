"""
Тесты для proxy endpoints (proxy-image и video-proxy)
"""
import pytest
from app import app
from unittest.mock import patch, MagicMock
import requests


@pytest.fixture
def client():
    """Создание тестового клиента Flask"""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


class TestProxyImage:
    """Тесты endpoint проксирования изображений"""
    
    def test_proxy_image_no_url(self, client):
        """Проверка ошибки при отсутствии URL"""
        response = client.get('/api/proxy-image')
        assert response.status_code == 400
        data = response.get_json()
        assert 'error' in data
    
    def test_proxy_image_untrusted_domain(self, client):
        """Проверка ошибки для недоверенного домена"""
        response = client.get('/api/proxy-image?url=http://evil.com/image.png')
        assert response.status_code == 403
        data = response.get_json()
        assert 'error' in data
    
    @patch('app.requests.get')
    def test_proxy_image_success(self, mock_get, client):
        """Успешное проксирование изображения"""
        # Настройка мок-объекта
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'fake_image_data'
        mock_response.headers = {'Content-Type': 'image/png'}
        mock_get.return_value = mock_response
        
        response = client.get('/api/proxy-image?url=https://vm-ftp.anosov.ru/test/image.png')
        
        assert response.status_code == 200
        assert response.content_type.startswith('image/')
        assert 'Cache-Control' in response.headers
        assert 'ETag' in response.headers
        mock_get.assert_called_once()
    
    @patch('app.requests.get')
    def test_proxy_image_retry_on_429(self, mock_get, client):
        """Повторная попытка при получении 429 ошибки"""
        # Первая попытка - 429, вторая - успех
        mock_response_429 = MagicMock()
        mock_response_429.status_code = 429
        mock_response_429.headers = {}
        
        mock_response_success = MagicMock()
        mock_response_success.status_code = 200
        mock_response_success.content = b'fake_image_data'
        mock_response_success.headers = {'Content-Type': 'image/png'}
        
        mock_get.side_effect = [mock_response_429, mock_response_success]
        
        response = client.get('/api/proxy-image?url=https://vm-ftp.anosov.ru/test/image.png')
        
        assert response.status_code == 200
        assert mock_get.call_count == 2
    
    @patch('app.requests.get')
    def test_proxy_image_retry_on_timeout(self, mock_get, client):
        """Повторная попытка при таймауте"""
        import requests
        
        # Первая попытка - timeout, вторая - успех
        mock_get.side_effect = [
            requests.exceptions.Timeout("Connection timed out"),
            MagicMock(status_code=200, content=b'fake_image_data', headers={'Content-Type': 'image/png'})
        ]
        
        response = client.get('/api/proxy-image?url=https://vm-ftp.anosov.ru/test/image.png')
        
        assert response.status_code == 200
        assert mock_get.call_count == 2
    
    @patch('app.requests.get')
    def test_proxy_image_max_retries_exceeded(self, mock_get, client):
        """Ошибка после превышения количества попыток"""
        import requests
        
        # Все попытки возвращают timeout
        mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")
        
        response = client.get('/api/proxy-image?url=https://vm-ftp.anosov.ru/test/image.png')
        
        assert response.status_code == 500
        data = response.get_json()
        assert 'error' in data


class TestVideoProxy:
    """Тесты endpoint проксирования видео"""
    
    def test_video_proxy_no_url(self, client):
        """Проверка ошибки при отсутствии URL"""
        response = client.get('/api/video-proxy')
        assert response.status_code == 400
        data = response.get_json()
        assert 'error' in data
    
    def test_video_proxy_untrusted_domain(self, client):
        """Проверка ошибки для недоверенного домена"""
        response = client.get('/api/video-proxy?url=http://evil.com/video.mp4')
        assert response.status_code == 403
        data = response.get_json()
        assert 'error' in data
    
    @patch('app.requests.head')
    @patch('app.requests.get')
    def test_video_proxy_success(self, mock_get, mock_head, client):
        """Успешное проксирование видео"""
        # Настройка мок-объектов
        mock_head_response = MagicMock()
        mock_head_response.status_code = 200
        mock_head_response.headers = {
            'Content-Length': '1000000',
            'Accept-Ranges': 'bytes'
        }
        mock_head.return_value = mock_head_response
        
        mock_get_response = MagicMock()
        mock_get_response.status_code = 200
        mock_get_response.iter_content.return_value = [b'fake_video_data']
        mock_get.return_value = mock_get_response
        
        response = client.get('/api/video-proxy?url=https://vm-ftp.anosov.ru/test/video.mp4')
        
        assert response.status_code == 200
        assert response.content_type.startswith('video/')
        assert 'Content-Disposition' in response.headers
        assert 'inline' in response.headers['Content-Disposition']
    
    @patch('app.requests.head')
    @patch('app.requests.get')
    def test_video_proxy_range_request(self, mock_get, mock_head, client):
        """Проксирование видео с Range запросом"""
        # HEAD запрос
        mock_head_response = MagicMock()
        mock_head_response.status_code = 200
        mock_head_response.headers = {
            'Content-Length': '1000000',
            'Accept-Ranges': 'bytes'
        }
        mock_head.return_value = mock_head_response
        
        # GET запрос с Range
        mock_get_response = MagicMock()
        mock_get_response.status_code = 206
        mock_get_response.iter_content.return_value = [b'partial_video_data']
        mock_get.return_value = mock_get_response
        
        response = client.get(
            '/api/video-proxy?url=https://vm-ftp.anosov.ru/test/video.mp4',
            headers={'Range': 'bytes=0-1023'}
        )
        
        assert response.status_code == 206
        assert 'Content-Range' in response.headers
    
    @patch('app.requests.head')
    @patch('app.requests.get')
    def test_video_proxy_retry_on_429(self, mock_get, mock_head, client):
        """Повторная попытка при получении 429 ошибки"""
        # HEAD запрос успешен
        mock_head_response = MagicMock()
        mock_head_response.status_code = 200
        mock_head_response.headers = {'Content-Length': '1000000', 'Accept-Ranges': 'bytes'}
        mock_head.return_value = mock_head_response
        
        # GET запрос - сначала 429, потом успех
        mock_response_429 = MagicMock()
        mock_response_429.status_code = 429
        mock_response_429.headers = {}
        
        mock_response_success = MagicMock()
        mock_response_success.status_code = 200
        mock_response_success.iter_content.return_value = [b'fake_video_data']
        
        mock_get.side_effect = [mock_response_429, mock_response_success]
        
        response = client.get('/api/video-proxy?url=https://vm-ftp.anosov.ru/test/video.mp4')
        
        assert response.status_code == 200
        assert mock_get.call_count == 2


class TestRetryLogic:
    """Тесты логики повторных попыток"""
    
    def test_make_request_with_retry_success(self):
        """Успешный запрос с первой попытки"""
        from utils.parser_utils import make_request_with_retry
        
        with patch('utils.parser_utils.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = '<html>test</html>'
            mock_get.return_value = mock_response
            
            result = make_request_with_retry('https://vm-ftp.anosov.ru/test/')
            
            assert result is not None
            assert result.status_code == 200
            mock_get.assert_called_once()
    
    def test_make_request_with_retry_429(self):
        """Обработка 429 ошибки с повторными попытками"""
        from utils.parser_utils import make_request_with_retry
        
        with patch('utils.parser_utils.requests.get') as mock_get:
            # Сначала 429, потом успех
            mock_429 = MagicMock()
            mock_429.status_code = 429
            mock_429.headers = {}
            
            mock_success = MagicMock()
            mock_success.status_code = 200
            mock_success.text = '<html>test</html>'
            
            mock_get.side_effect = [mock_429, mock_success]
            
            result = make_request_with_retry('https://vm-ftp.anosov.ru/test/', base_delay=0.1)
            
            assert result is not None
            assert result.status_code == 200
            assert mock_get.call_count == 2
    
    def test_make_request_with_retry_timeout(self):
        """Обработка таймаута с повторными попытками"""
        from utils.parser_utils import make_request_with_retry
        import requests
        
        with patch('utils.parser_utils.requests.get') as mock_get:
            # Все попытки - таймаут
            mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")
            
            result = make_request_with_retry('https://vm-ftp.anosov.ru/test/', max_retries=3, base_delay=0.1)
            
            assert result is None
            assert mock_get.call_count == 3


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
