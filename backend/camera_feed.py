"""Read-only camera preview; never changes monitoring or printer state."""
import io
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Response
from starlette.responses import StreamingResponse
from starlette.background import BackgroundTask
from PIL import Image, UnidentifiedImageError
from dotenv import dotenv_values

router = APIRouter()
MAX_SNAPSHOT_BYTES = 5 * 1024 * 1024
CONFIG_FILE = Path(__file__).resolve().parents[1] / '.env'


@router.get('/camera/stream')
async def camera_stream():
    settings = {**dotenv_values(CONFIG_FILE.parent / 'pi-module' / '.env'),
                **dotenv_values(CONFIG_FILE), **os.environ}
    url = settings.get('STREAM_URL', '')
    try:
        parsed = urlsplit(url)
        valid = parsed.scheme in ('http', 'https') and bool(parsed.hostname)
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(503, 'Set STREAM_URL on the backend')
    client = httpx.AsyncClient(timeout=httpx.Timeout(10, read=15), follow_redirects=False)
    upstream = None

    async def close():
        if upstream is not None:
            await upstream.aclose()
        await client.aclose()

    try:
        upstream = await client.send(client.build_request('GET', url), stream=True)
        upstream.raise_for_status()
        content_type = upstream.headers.get('content-type', '')
        if not content_type.lower().startswith('multipart/x-mixed-replace') or 'boundary=' not in content_type.lower():
            raise ValueError('Expected an MJPEG stream')
    except (httpx.HTTPError, ValueError) as error:
        await close()
        raise HTTPException(502, 'Camera stream unavailable; check the Pi camera service') from error

    async def chunks():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await close()

    return StreamingResponse(chunks(), media_type=content_type,
        headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'},
        background=BackgroundTask(close))


@router.get('/camera/snapshot')
async def camera_snapshot():
    # Server configuration only; clients cannot supply a URL to proxy.
    # Explicit process settings win. Otherwise use this repository's local
    # config, regardless of the shell's working directory. Read on each request
    # so configuring a missing camera does not require restarting the backend.
    url = os.getenv('SNAPSHOT_URL')
    if url is None:
        url = dotenv_values(CONFIG_FILE).get('SNAPSHOT_URL')
    url = (url or '').strip()
    try:
        parsed = urlsplit(url)
        valid = parsed.scheme in ('http', 'https') and bool(parsed.hostname)
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(503, 'Camera not configured: set SNAPSHOT_URL on the backend')
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
            async with client.stream('GET', url, headers={'Cache-Control': 'no-cache'}) as upstream:
                upstream.raise_for_status()
                data = bytearray()
                async for chunk in upstream.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_SNAPSHOT_BYTES:
                        raise HTTPException(502, 'Camera snapshot exceeds the 5 MB limit')
        with Image.open(io.BytesIO(data)) as image:
            if image.format != 'JPEG':
                raise HTTPException(502, 'Camera must return a JPEG snapshot')
            image.verify()
    except httpx.TimeoutException as error:
        raise HTTPException(504, 'Camera timed out; check the Pi connection') from error
    except (httpx.HTTPError, httpx.InvalidURL) as error:
        raise HTTPException(502, 'Camera unavailable; check the snapshot URL and access settings') from error
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise HTTPException(502, 'Camera returned an invalid image') from error
    return Response(bytes(data), media_type='image/jpeg', headers={
        'Cache-Control': 'no-store',
        'X-Frame-Received-At': datetime.now(timezone.utc).isoformat(),
        'X-Content-Type-Options': 'nosniff',
    })
