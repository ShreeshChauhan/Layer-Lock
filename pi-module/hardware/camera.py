"""Camera access.

OctoPi owns the camera. We only fetch snapshots from its HTTP endpoint, so there
is never a conflict over the device.

get_frame() returns a Frame (JPEG bytes + timestamp), or raises CameraError.
It never returns stale data silently.
"""
import io
import logging
import random
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from . import config

log = logging.getLogger(__name__)


class CameraError(Exception):
    """Snapshot fetch failed, timed out, or returned something that is not a JPEG."""


@dataclass
class Frame:
    jpeg: bytes
    t: float  # unix time the frame was captured/fetched

    def to_pil(self):
        from PIL import Image
        return Image.open(io.BytesIO(self.jpeg))

    def to_array(self):
        """RGB numpy array (H, W, 3). Needs numpy. For OpenCV, convert with arr[:, :, ::-1]."""
        import numpy as np
        return np.asarray(self.to_pil().convert("RGB"))

    def save(self, path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(self.jpeg)


class SnapshotCamera:
    def __init__(self, url: str | None = None, timeout: float | None = None):
        self.url = url or config.SNAPSHOT_URL
        self.timeout = timeout or config.HTTP_TIMEOUT
        self.session = requests.Session()

    def get_frame(self) -> Frame:
        try:
            r = self.session.get(self.url, timeout=self.timeout)
        except requests.RequestException as e:
            raise CameraError(f"snapshot fetch failed ({self.url}): {e}") from e
        if r.status_code != 200:
            raise CameraError(f"snapshot HTTP {r.status_code} from {self.url}")
        data = r.content
        if not data.startswith(b"\xff\xd8"):  # JPEG magic bytes
            raise CameraError("snapshot response is not a JPEG")
        return Frame(jpeg=data, t=time.time())


class ReplayCamera:
    """Mock camera. Plays .jpg files from REPLAY_DIR in name order (loops).

    If the folder is empty or missing, it generates noisy synthetic frames with a
    moving box so health checks and the pipeline still have something to chew on.
    To make a replay set from a video:  ffmpeg -i clip.mp4 -vf fps=0.4 replay/f_%04d.jpg
    """

    def __init__(self, folder: str | None = None, loop: bool = True):
        self.folder = Path(folder or config.REPLAY_DIR)
        self.files = sorted(self.folder.glob("*.jpg")) if self.folder.is_dir() else []
        self.loop = loop
        self.i = 0
        if not self.files:
            log.warning("[mock] no frames in %s, using synthetic frames", self.folder)

    def get_frame(self) -> Frame:
        if self.files:
            if self.i >= len(self.files) and not self.loop:
                raise CameraError("replay finished")
            data = self.files[self.i % len(self.files)].read_bytes()
        else:
            data = self._synthetic()
        self.i += 1
        return Frame(jpeg=data, t=time.time())

    def _synthetic(self) -> bytes:
        from PIL import Image, ImageDraw
        # Gradient background (so it looks like a real scene, not "blocked") plus sensor-like noise
        grad = Image.linear_gradient("L").resize((640, 480))
        noise = Image.effect_noise((640, 480), 40)
        img = Image.blend(grad, noise, 0.15).convert("RGB")
        x = (self.i * 7) % 500 + random.randint(0, 3)
        ImageDraw.Draw(img).rectangle([x, 200, x + 80, 280], fill=(200, 80, 60))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=80)
        return buf.getvalue()