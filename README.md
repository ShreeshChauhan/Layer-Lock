# ⚙️ SteamForge

### AI-Powered Industrial Factory Simulator

**SteamForge** is a full-stack, interactive steam factory simulator that combines simplified industrial physics, real-time monitoring, and intelligent decision-making to explore how steam-powered systems operate.

Inspired by the **Steel and Steam** hackathon theme, SteamForge transforms industrial plant management into an interactive experience where users can experiment with boiler controls, monitor performance, and explore the trade-offs between efficiency, power generation, and equipment safety.

---

## Overview

Industrial systems involve complex relationships between temperature, pressure, fuel consumption, and equipment performance.

SteamForge makes these relationships easier to explore through a virtual control center where users can adjust operating parameters and observe simulated factory behavior.

The project is being developed with the goal of combining **simulation, machine learning, and interactive visualization** into a single application.

## Features

### Current Foundation

- **Interactive Dashboard:** Monitor simulated industrial operating conditions.
- **Boiler Simulation:** Calculate simulated temperature, steam pressure, and power output.
- **Adjustable Controls:** Experiment with fuel input, water flow, and valve opening.
- **Performance Monitoring:** View estimated system efficiency and operating risk.
- **Full-Stack Architecture:** Connect a React frontend to a Python simulation engine through REST APIs.

### Planned Features

- **Predictive Maintenance:** Machine learning models to estimate equipment failure risks.
- **Interactive Factory Visualization:** Animated steam pipes, boilers, turbines, and industrial machinery.
- **AI Optimization:** Recommend operating adjustments to improve simulated performance.
- **Failure Scenarios:** Simulate overheating, pressure spikes, and equipment breakdowns.
- **Factory Scoring:** Evaluate performance based on energy efficiency, safety, and resource consumption.
- **Historical Analytics:** Visualize operating trends and compare simulation runs.

---

## Tech Stack

| Layer | Technologies |
|---|---|
| Frontend | React, TypeScript, Vite |
| Backend | Python, FastAPI |
| Simulation | Python-based numerical calculations |
| Machine Learning (Planned) | Scikit-learn |
| Visualization (Planned) | Recharts |
| Database (Planned) | SQLite |
| Version Control | Git, GitHub |

---

## System Architecture

```text
                  USER
                   |
                   v
          React + TypeScript
           Factory Dashboard
                   |
                   | HTTP Requests
                   v
             FastAPI Backend
                   |
                   v
          Python Simulation Engine
                   |
                   v
       Pressure | Temperature
       Efficiency | Power | Risk
                   |
                   v
          JSON API Response
                   |
                   v
          Updated Dashboard
```

The frontend handles user interaction and visualization, while the backend processes simulation inputs and calculates the corresponding system behavior.

The simulation currently uses simplified mathematical relationships intended for interactive experimentation rather than engineering-grade equipment analysis.

---

## Project Structure

```text
SteamForge/
├── frontend/
│   ├── src/
│   ├── package.json
│   └── ...
│
├── backend/
│   ├── main.py
│   ├── simulator.py
│   └── requirements.txt
│
├── .gitignore
└── README.md
```

---

## Getting Started

### Prerequisites

Make sure you have installed:

- Node.js and npm
- Python 3.10 or newer
- Git

### 1. Clone the Repository

```bash
git clone https://github.com/YOUR_USERNAME/SteamForge.git
cd SteamForge
```

Replace `YOUR_USERNAME` with your GitHub username.

### 2. Start the Backend

Create and activate a Python virtual environment.

**Windows Git Bash:**

```bash
python -m venv .venv
source .venv/Scripts/activate
```

Install dependencies and start the API:

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

The backend will run at:

`http://127.0.0.1:8000`

API documentation:

`http://127.0.0.1:8000/docs`

### 3. Start the Frontend

Open a second terminal from the project root:

```bash
cd frontend
npm install
npm run dev
```

Open the local URL provided by Vite, typically:

`http://localhost:5173`

---

## How the Simulation Works

SteamForge uses a simplified numerical model to represent the relationship between boiler operating conditions and factory performance.

Users adjust three primary variables:

| Input | Purpose |
|---|---|
| Fuel Input | Influences heat generation and steam production |
| Water Flow | Influences boiler temperature and operating conditions |
| Valve Opening | Influences steam pressure and system behavior |

The simulation processes these inputs and returns estimated operating metrics, including:

- Steam pressure
- Boiler temperature
- Power output
- System efficiency
- Operating risk

These calculations are designed for educational and gameplay purposes and are not intended to control or validate real industrial equipment.

---

## Development Roadmap

- [x] Establish React and FastAPI project structure
- [x] Create initial Python simulation logic
- [x] Implement frontend controls and simulated metrics
- [ ] Build interactive factory visualizations
- [ ] Add historical performance charts
- [ ] Implement equipment failure scenarios
- [ ] Train a predictive maintenance model
- [ ] Develop an AI-powered optimization assistant
- [ ] Introduce factory scoring and game mechanics
- [ ] Deploy the full-stack application

---

## Project Vision

SteamForge aims to bridge the gap between industrial simulation and interactive software by creating a system that is both technically interesting and visually engaging.

The long-term goal is to explore how machine learning and simulation can support better operational decisions, while presenting those concepts through an accessible, game-inspired interface.

---

## Hackathon

**Theme:** Steel and Steam

**Focus Areas:** Software Engineering, AI/ML, Industrial Simulation, Gaming, and UI/UX

**Project Status:** In Development

---

## License

No license has been selected yet.