import io
import os
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

import camera_feed


class CameraFeedTests(unittest.TestCase):
    def test_continuous_stream_and_cleanup(self):
        class Frames(httpx.AsyncByteStream):
            closed = False
            async def __aiter__(self):
                yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\nfirst\r\n'
                yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\nsecond\r\n'
            async def aclose(self):
                self.closed = True
        frames = Frames()
        def handler(request):
            self.assertEqual(str(request.url), 'http://camera.test/stream')
            return httpx.Response(200, headers={'content-type': 'multipart/x-mixed-replace; boundary=frame'}, stream=frames)
        with patch.dict(os.environ, {'STREAM_URL': 'http://camera.test/stream'}), patch.object(
                camera_feed.httpx, 'AsyncClient', side_effect=lambda **kwargs:
                self.original_client(transport=httpx.MockTransport(handler), **kwargs)):
            response = self.client.get('/camera/stream')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'first', response.content)
        self.assertIn(b'second', response.content)
        self.assertEqual(response.headers['x-accel-buffering'], 'no')
        self.assertTrue(frames.closed)

    def test_stream_rejects_invalid_content_and_missing_configuration(self):
        with patch.dict(os.environ, {'STREAM_URL': ''}):
            self.assertEqual(self.client.get('/camera/stream').status_code, 503)
        with patch.dict(os.environ, {'STREAM_URL': 'http://camera.test/stream'}), patch.object(
                camera_feed.httpx, 'AsyncClient', side_effect=lambda **kwargs:
                self.original_client(transport=httpx.MockTransport(lambda req: httpx.Response(200, text='not video')), **kwargs)):
            self.assertEqual(self.client.get('/camera/stream').status_code, 502)

    def setUp(self):
        app = FastAPI()
        app.include_router(camera_feed.router)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        env = patch.dict(os.environ, {'SNAPSHOT_URL': 'http://camera.test/snapshot'})
        env.start()
        self.addCleanup(env.stop)
        image = io.BytesIO()
        Image.new('RGB', (16, 16)).save(image, 'JPEG')
        self.jpeg = image.getvalue()
        self.original_client = httpx.AsyncClient

    def request(self, handler):
        with patch.object(camera_feed.httpx, 'AsyncClient', side_effect=lambda **kwargs:
                          self.original_client(transport=httpx.MockTransport(handler), **kwargs)):
            return self.client.get('/camera/snapshot')

    def test_jpeg_no_cache_timestamp_and_server_url(self):
        def camera(request):
            self.assertEqual(str(request.url), 'http://camera.test/snapshot')
            self.assertEqual(request.method, 'GET')
            self.assertEqual(request.extensions['timeout']['read'], 5)
            return httpx.Response(200, content=self.jpeg)
        response = self.request(camera)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, self.jpeg)
        self.assertEqual(response.headers['content-type'], 'image/jpeg')
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertIn('x-frame-received-at', response.headers)

    def test_unconfigured_or_invalid_url(self):
        for url in ['', 'file:///camera.jpg', 'not-a-url']:
            with patch.dict(os.environ, {'SNAPSHOT_URL': url}), patch.object(camera_feed.httpx, 'AsyncClient') as client:
                self.assertEqual(self.client.get('/camera/snapshot').status_code, 503)
                client.assert_not_called()

    def test_upstream_errors_and_redirects(self):
        for status in [302, 401, 404, 500]:
            response = self.request(lambda request: httpx.Response(status, headers={'location': 'http://elsewhere.test'}))
            self.assertEqual(response.status_code, 502)

    def test_timeout_and_connection_error(self):
        for error, expected in [(httpx.ReadTimeout('test'), 504), (httpx.ConnectError('test'), 502)]:
            def camera(request):
                raise error
            self.assertEqual(self.request(camera).status_code, expected)

    def test_invalid_image_and_size_limit(self):
        self.assertEqual(self.request(lambda request: httpx.Response(200, content=b'not JPEG')).status_code, 502)
        with patch.object(camera_feed, 'MAX_SNAPSHOT_BYTES', 10):
            self.assertEqual(self.request(lambda request: httpx.Response(200, content=self.jpeg)).status_code, 502)

    def test_failure_does_not_serve_previous_image(self):
        self.assertEqual(self.request(lambda request: httpx.Response(200, content=self.jpeg)).status_code, 200)
        response = self.request(lambda request: httpx.Response(503))
        self.assertEqual(response.status_code, 502)
        self.assertNotEqual(response.content, self.jpeg)

    def test_repository_config_and_environment_precedence(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / '.env'
            config.write_text('SNAPSHOT_URL=http://configured-camera.test/snapshot\n')
            with patch.object(camera_feed, 'CONFIG_FILE', config), patch.dict(os.environ):
                os.environ.pop('SNAPSHOT_URL', None)
                def camera(request):
                    self.assertEqual(str(request.url), 'http://configured-camera.test/snapshot')
                    return httpx.Response(200, content=self.jpeg)
                self.assertEqual(self.request(camera).status_code, 200)
                os.environ['SNAPSHOT_URL'] = 'http://override.test/snapshot'
                def override(request):
                    self.assertEqual(str(request.url), 'http://override.test/snapshot')
                    return httpx.Response(200, content=self.jpeg)
                self.assertEqual(self.request(override).status_code, 200)

    def test_configured_camera_recovers_without_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / '.env'
            with patch.object(camera_feed, 'CONFIG_FILE', config), patch.dict(os.environ):
                os.environ.pop('SNAPSHOT_URL', None)
                self.assertEqual(self.client.get('/camera/snapshot').status_code, 503)
                config.write_text('SNAPSHOT_URL=http://camera.test/snapshot\n')
                self.assertEqual(self.request(lambda request: httpx.Response(200, content=self.jpeg)).status_code, 200)


if __name__ == '__main__':
    unittest.main()
