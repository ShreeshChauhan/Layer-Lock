import time
from collections import deque


class RiskEngine:
    def __init__(self):
        self.armed = False
        self.state = "IDLE"
        self.risk_score = 0
        self.high_risk_since = None
        self.paused = False
        self.events = deque(maxlen=100)

        self.warning_threshold = 70
        self.watch_threshold = 40
        self.sustain_seconds = 5

    def log(self, message):
        self.events.appendleft({
            "time": time.strftime("%H:%M:%S"),
            "message": message
        })

    def arm(self):
        if self.paused:
            return self.status()

        self.armed = True
        self.state = "WATCHING"
        self.high_risk_since = None
        self.log("Monitoring armed")
        return self.status()

    def disarm(self):
        self.armed = False
        self.high_risk_since = None
        self.state = "PAUSED" if self.paused else "IDLE"
        self.log("Monitoring disarmed")
        return self.status()

    def calculate_risk(self, camera):
        return round(max(0, min(100, camera)))

    def process(self, camera, filament_runout):
        self.risk_score = (
            100 if filament_runout
            else self.calculate_risk(camera)
        )

        if not self.armed or self.paused:
            return self.status(), False

        if filament_runout:
            self.state = "WARNING"
            self.log("Filament runout detected")
            return self.status(), True

        if self.risk_score >= self.warning_threshold:
            if self.high_risk_since is None:
                self.high_risk_since = time.monotonic()
                self.log("High failure risk detected")

            self.state = "WARNING"

            if time.monotonic() - self.high_risk_since >= self.sustain_seconds:
                return self.status(), True

        elif self.risk_score >= self.watch_threshold:
            self.state = "WATCHING"
            self.high_risk_since = None

        else:
            self.state = "WATCHING"
            self.high_risk_since = None

        return self.status(), False

    def confirm_pause(self):
        self.paused = True
        self.state = "PAUSED"
        self.high_risk_since = None
        self.log("Printer pause command accepted")

    def recover(self, resume=False):
        self.paused = False
        self.high_risk_since = None
        self.risk_score = 0
        if not resume:
            self.armed = False
        self.state = "WATCHING" if self.armed else "IDLE"
        self.log("Resume command accepted" if resume else "Cancel command accepted; monitoring disarmed")
        return self.status()

    def reset_simulation(self):
        self.armed = False
        self.state = "IDLE"
        self.risk_score = 0
        self.high_risk_since = None
        self.paused = False
        self.log("Simulation reset; monitoring disarmed")
        return self.status()

    def status(self):
        return {
            "armed": self.armed,
            "state": self.state,
            "risk_score": self.risk_score,
            "paused": self.paused,
            "events": list(self.events)
        }


risk_engine = RiskEngine()
