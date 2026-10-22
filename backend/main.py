from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from simulator import Controls, simulate

app = FastAPI(title='SteamForge API')
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173', 'http://127.0.0.1:5173'], allow_methods=['*'], allow_headers=['*'])

class SimulationInput(BaseModel):
    fuel: float = Field(50, ge=0, le=100)
    water: float = Field(50, ge=0, le=100)
    valve: float = Field(50, ge=0, le=100)

@app.get('/health')
def health():
    return {'status': 'ok'}

@app.post('/simulate')
def run_simulation(payload: SimulationInput):
    return simulate(Controls(**payload.model_dump()))
