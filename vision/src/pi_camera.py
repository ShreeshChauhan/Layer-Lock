import urllib.request

import cv2
import numpy as np


def get_pi_frame(url, timeout=5):
    """Fetch one JPEG frame from the Raspberry Pi."""

    request = urllib.request.Request(
        url,
        headers={"Cache-Control": "no-cache"},
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        image_bytes = response.read()

    image_array = np.frombuffer(image_bytes, dtype=np.uint8)
    frame = cv2.imdecode(image_array, cv2.IMREAD_COLOR)

    if frame is None:
        raise ValueError("Could not decode Raspberry Pi camera image")

    return frame