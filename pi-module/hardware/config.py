"""Central config. Everything comes from environment variables (or a .env file).

Nothing secret is ever hardcoded here. Set OCTO_KEY in your environment or .env.
"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # python-dotenv is optional
    pass


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


# --- Mode -------------------------------------------------------------------
MOCK = os.environ.get("MOCK", "0") == "1"

# --- OctoPrint --------------------------------------------------------------
# On the Pi use http://localhost. From your laptop use http://<pi-address>.
OCTO_URL = os.environ.get("OCTO_URL", "http://localhost").rstrip("/")
OCTO_KEY = os.environ.get("OCTO_KEY", "")
HTTP_TIMEOUT = _float("HTTP_TIMEOUT", 5)  # seconds, applied to every request

# --- Camera -----------------------------------------------------------------
SNAPSHOT_URL = os.environ.get("SNAPSHOT_URL", "http://localhost:8080/?action=snapshot")
REPLAY_DIR = os.environ.get("REPLAY_DIR", "replay")  # folder of .jpg frames for mock mode

# --- Health thresholds (tune these during your soak test) --------------------
FRAME_MAX_AGE_S = _float("FRAME_MAX_AGE_S", 10)   # frame older than this = stale
DARK_MEAN = _float("DARK_MEAN", 20)               # mean brightness (0-255) below this = dark
FLAT_STD = _float("FLAT_STD", 6)                  # brightness std-dev below this = blocked/uniform
FROZEN_DIFF = _float("FROZEN_DIFF", 0.05)         # mean pixel diff between frames below this = identical
FROZEN_COUNT = _int("FROZEN_COUNT", 3)            # consecutive identical frames before "frozen"
PI_TEMP_WARN_C = _float("PI_TEMP_WARN_C", 75)
PI_TEMP_CRIT_C = _float("PI_TEMP_CRIT_C", 80)
RESUME_MIN_TEMP_C = _float("RESUME_MIN_TEMP_C", 180)  # nozzle must be at least this hot to resume
