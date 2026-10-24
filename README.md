# Print Guardian

**Hackathon:** SBUHacks 2026 — Steel and Steam  
**Tracks:** Hardware · UI/UX · Beginner · MLH

> **One-line pitch:** A watchdog for 3D printers that sees failures with a camera, feels them with vibration and sound sensors, pauses the print automatically, and shows its state on physical brass-style pressure gauges.

## 1. The Problem

Failed prints waste filament and hours of machine time. An unattended failure—such as a detached part dragged by the nozzle, a clog, or a jammed spool—can also damage the printer. Makerspaces, school labs, and libraries often operate several printers without constant supervision.

Commercial monitoring solutions exist, but some depend on cloud services or specific hardware. **Print Guardian is local-first and designed to work with an existing printer**, subject to compatible control interfaces.

## 2. What It Does

- **Camera monitoring:** Flags spaghetti, detachment, and printing into air.
- **Vibration and sound sensing:** Looks for unusual motion, grinding, and extruder clicking.
- **Filament runout detection:** Uses a micro switch beneath a printed lever.
- **Sensor fusion:** Combines readings into a risk score and pauses a compatible printer when sustained risk is high.
- **Alerts:** Uses a buzzer, LCD, dashboard, and phone notification with a snapshot.
- **Physical feedback:** Drives three servo gauges: **Failure Pressure**, **Tremor Index**, and **Print Progress**.

## 3. Architecture

```text
 Webcam ─── USB ───► ┌───────────────────────────────┐
                     │        Raspberry Pi 4B        │ ──► Pause/cooldown via
 Arduino ── USB ───► │ • Camera capture + vision     │     OctoPrint/Klipper API
 (serial JSON)       │ • Sensor fusion + state logic │ ──► Web dashboard
       ▲             │ • Dashboard + notifications   │ ──► Phone alert + snapshot
       │             └──────────────┬────────────────┘
       │ gauge commands             │ serial JSON
       │                            ▼
 ┌─────┴──────────────────────────────────────────────┐
 │ Arduino + Grove base shield                        │
 │ INPUTS: accelerometer, sound, micro switch, button │
 │ OUTPUTS: 3 servos, buzzer, LCD                     │
 └────────────────────────────────────────────────────┘
```

The **Arduino** handles Grove sensors and gauges; the **Raspberry Pi** runs the vision model, fusion logic, dashboard, notifications, and printer-control integration. The Arduino is useful because the Pi has no built-in analog inputs.

## 4. Materials

| Item | Source | Quantity | Purpose |
|---|---|---:|---|
| Raspberry Pi 4B kit | MLH lab | 1 | Vision, fusion, dashboard, API calls |
| Logitech webcam | MLH lab | 1 | Print monitoring |
| Arduino + Grove base shield | MLH lab | 1 | Sensor hub and gauge driver |
| Grove 3-axis accelerometer | MLH lab | 1 | Vibration and layer-shift signal |
| Grove sound sensor | MLH lab | 1 | Grinding and clicking signal |
| Grove micro switch | MLH lab | 1 | Filament runout lever |
| Grove servos | MLH lab | 3 (4 available) | Gauge needles |
| Grove buzzer | MLH lab | 1 | Steam-whistle-style alarm |
| Grove LCD | MLH lab | 1 | Status text and backlight color |
| Grove button | MLH lab | 1 | Arm/disarm and acknowledge |
| Grove cables, jumpers, breadboard | MLH lab | Assorted | Wiring |
| Multimeter, tweezers, strippers | MLH lab | Shared | Debugging |
| 3D printer | Team | 1 | Monitoring subject and part fabrication |
| Gold or bronze filament | Team brings | 1 spool | Brass-like appearance |
| USB cables, power strip, microSD | Team brings | Several | Power and storage |
| M3 screws, zip ties, hot glue, double-sided tape | Team brings | Assorted | Assembly |
| External 5V supply (optional) | Team brings | 1 | Servo power if needed |
| Router or phone hotspot | Team brings | 1 | Reliable local network |

### Parts to 3D-print

Three gauge bezels and faces, three needles, servo mounts, a webcam clamp, an accelerometer mount, a filament-runout lever housing, and an enclosure for the Pi and Arduino. Add decorative gears if time allows.

### Verify before committing

1. **Grove compatibility:** The Pi does not need a Grove Base Hat because the Arduino reads the Grove sensors.
2. **LCD type:** Check whether the LCD has an RGB backlight; green/amber/red can communicate status.
3. **Printer firmware:** Determine whether the printer uses OctoPrint, Klipper/Moonraker, Marlin, Bambu, Prusa, or another interface; pause control depends on the setup.
4. **Power and pin compatibility:** Confirm the accelerometer interface and servo power requirements before wiring.

## 5. Implementation

### 5.1 Arduino Sensor Hub

Every **100 ms**, sample the sensors and send a newline-delimited JSON record over USB serial:

```json
{"vib": 0.12, "snd": 0.30, "runout": 0}
```

**Vibration:** Compute root-mean-square acceleration over a short window:

$$
\mathrm{RMS} = \sqrt{\frac{1}{N}\sum_{i=1}^{N}a_i^2}
$$

Record a baseline mean $\mu$ and standard deviation $\sigma$ during a calibration print. Score deviations with:

$$
z = \frac{x-\mu}{\sigma}
$$

Handle near-zero $\sigma$ safely, then normalize the result to a vibration score $s_a \in [0,1]$.

**Sound:** The Grove sound sensor provides an amplitude envelope, not a full frequency spectrum. It can flag spikes associated with clicking or grinding but cannot reliably identify tones. Normalize its deviation into $s_s \in [0,1]$.

**Filament runout:** A micro switch supplies a binary signal $s_f \in \{0,1\}$.

**Proposed port plan:** Switch D2, buzzer D3, button D4, servos D5–D7, sound A0, accelerometer and LCD on I²C. Verify the actual sensor modules and shield pin mapping.

### 5.2 Vision on the Raspberry Pi

Build two tiers so there is always a working fallback.

**Tier 1 — Classical vision:** Capture a reference frame at print start. Compare subsequent frames in a build-area region of interest using image differencing and edge density. Spaghetti may create chaotic edges; detachment may cause abrupt changes. This is fast but sensitive to normal print growth and camera movement.

**Tier 2 — Learned classifier:** Fine-tune a small pretrained model, such as MobileNet, on **healthy** versus **failed** frames. Run it with TFLite or ONNX on the Pi, sampling roughly every 2–3 seconds. Collect original examples, including safely staged failures, and check public dataset licenses. **Split training and test data by print**, not individual frame, to avoid leakage.

**Optional MLH extension:** Ask a vision-language API for a structured second opinion when local confidence is low. The local detector remains primary and works offline.

Output a vision risk score $s_v \in [0,1]$.

### 5.3 Sensor Fusion and State Machine

Combine the signals into a weighted score:

$$
R = w_v s_v + w_a s_a + w_s s_s + w_f s_f,
\qquad w_v+w_a+w_s+w_f=1
$$

Give vision the largest weight. Treat confirmed filament runout as an **immediate pause override**.

To reduce false pauses, use hysteresis and debouncing: enter the high-risk state only after $R>\tau_{high}$ for $k$ consecutive checks; recover only when $R<\tau_{low}$, where $\tau_{low}<\tau_{high}$.

```text
IDLE → ARMED → WATCHING → WARNING → PAUSED → ACKNOWLEDGED
```

Define reset/rearm transitions explicitly during implementation. Tune for a low false-pause rate.

### 5.4 Printer Actions and Notifications

- **OctoPrint:** Send an authenticated pause request to its job API.
- **Klipper/Moonraker:** Use the relevant print-pause endpoint.
- **Cooldown:** After a configurable pause timeout, lower heater targets when safe and appropriate for the printer/material. Confirm the commands against the installed firmware.
- **Notifications:** Send a Discord, Telegram, or email webhook containing the snapshot, risk score, and contributing signals.

### 5.5 Servo Gauges

Map each measured value to a servo angle, clamped to the calibrated mechanical range:

$$
\theta = 180^\circ\frac{x-x_{min}}{x_{max}-x_{min}}
$$

Smooth the needle with an exponential moving average:

$$
\hat{x}_t = \alpha x_t + (1-\alpha)\hat{x}_{t-1},
\qquad 0<\alpha<1
$$

Calibrate end stops manually and avoid driving a servo against its mechanical limits. Give the Failure Pressure gauge a red zone. Use Victorian-engineering labels such as **Boiler Pressure** and **Tremor Index**.

### 5.6 Dashboard

Use **FastAPI or Flask** on the Pi to serve:

- Live camera feed
- Rolling risk graph
- Per-signal contributions
- Event log
- Arm/disarm and acknowledge controls
- Current printer state

Use **WebSockets** for live updates and **SQLite** for event logging. The dashboard is also a fallback if a physical gauge fails.

## 6. Four-Minute Demo Plan

| Segment | Duration | What to show |
|---|---:|---|
| Hook | 20 sec | Failed prints waste material and can damage equipment |
| Idle state | 20 sec | Gauges at zero, green LCD, clean bed on dashboard |
| Healthy print | 45 sec | Progress needle advances while risk stays low |
| Failure | 60 sec | Failure Pressure enters red; buzzer, LCD, pause, and snapshot alert activate |
| Second signal | 30 sec | Tap the frame to show vibration response, or trip the runout lever |
| Results | 30 sec | Precision, recall, latency, and estimated filament saved |

**Total planned segments:** 3 min 25 sec, leaving approximately 35 sec for transitions and questions.

### Safe failure demonstration

- **Pre-staged:** Use a small failure-prone print with reduced bed adhesion, tested in advance.
- **Controlled:** Pause and park the head, safely remove a test part using appropriate tools, and resume to demonstrate printing into air. Avoid contact with hot components or moving machinery.
- **Fallback:** Replay a recorded failure clip through the **same detection pipeline**. Clearly label it **Replay Mode**.

Choose a short demo print early (roughly **15–25 minutes**). Print console parts first, before the printer is needed for testing.

## 7. Evaluation Metrics

**Precision**

$$
\mathrm{Precision} = \frac{TP}{TP+FP}
$$

**Recall**

$$
\mathrm{Recall} = \frac{TP}{TP+FN}
$$

Also report:

- **False pauses per print-hour** — important for practical usability.
- **Detection latency** — seconds from failure onset to the automatic pause.
- **Estimated filament saved**, with assumptions:

$$
m_{saved}\approx \dot{m}\,(t_{unattended}-t_{detect})
$$

Here $\dot{m}$ is filament consumption in grams per minute and both times use compatible units.

**Ablation study:** Compare vision-only against vision-plus-sensors. If sensor fusion does not improve aggregate metrics, report that honestly and describe which distinct failure types the sensors cover.

## 8. Build Timeline

| Phase | Work |
|---|---|
| Hours 0–2 | Claim hardware, assign roles, start gauge prints, verify printer pause API |
| Hours 2–8 | Arduino firmware, serial protocol, webcam capture, start data recording |
| Hours 8–16 | Classical vision, optional classifier training, dashboard v1, gauge assembly |
| Hours 16–24 | Fusion, state machine, pause action, notifications, servo calibration |
| Hours 24–36 | Evaluation, threshold tuning, false-pause testing, two demo rehearsals |
| Final hours | Replay mode, submission, demo video, code freeze |

**Suggested team split:** (1) Hardware and printed parts, (2) Vision and ML, (3) Fusion, printer integration, and dashboard.

## 9. Risks and Fallbacks

| Risk | Mitigation |
|---|---|
| Printer API unavailable | Test immediately; fall back to a clearly labeled manual pause demonstration and alerts |
| Not enough failure data | Record from the start and stage small, safe failures |
| Pi too slow | Reduce resolution/frame rate or use a smaller model |
| Servo jitter or brownouts | Smooth signals and use an appropriate external 5V supply |
| Venue Wi-Fi unreliable | Use a local router or hotspot; keep cloud features optional |
| False pause during demo | Debouncing, hysteresis, arm/disarm, and replay mode |
| Printer unavailable for testing | Print enclosure parts first; keep test prints short |

## 10. Safety and Scope

**Print Guardian is not a certified safety device.** It is a monitoring and intervention prototype, not a replacement for firmware thermal-runaway protection, proper maintenance, or human supervision. Do not present it as a reason to leave a printer unattended.

## 11. Hackathon Track Fit

| Track | Strongest angle |
|---|---|
| **Hardware** | Sensors, servo gauges, printed mechanics, physical console |
| **UI/UX** | Clear physical alerts, dashboard, intuitive status communication |
| **Beginner** | End-to-end working prototype and understandable demonstration |
| **MLH** | Optional vision-language second opinion, notifications, and sponsor integrations |

Check the event's actual prize rules and sponsor list before choosing submissions.

## 12. Stretch Goals

- Time-lapse video with failure markers
- Multi-printer monitoring view
- Steam-whistle audio via a Bluetooth speaker
- Automatic cooldown timer and daily print report

## 13. Open Questions

1. **Printer firmware:** OctoPrint, Klipper, Marlin, Bambu, Prusa, or something else?
2. **Team size and skills:** Who owns hardware, ML, and dashboard integration?
3. **Event duration:** 24 or 36 hours?
4. **Hardware availability:** Which listed MLH components are actually on hand?

---

*Project concept and implementation plan for SBUHacks 2026.*
