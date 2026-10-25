"""Read-only camera preview; never changes monitoring or printer state."""
import io
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Response
from PIL import Image, UnidentifiedImageError
from dotenv import dotenv_values

router = APIRouter()
MAX_SNAPSHOT_BYTES = 5 * 1024 * 1024
CONFIG_FILE = Path(__file__).resolve().parent / '.env'


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
