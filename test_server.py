"""Quick test server — verify team can reach Chris's Mac over DevCon WiFi."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(title="Orphan X - Connection Test")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/")
def root():
    return {"status": "alive", "team": "Orphan X", "message": "If you can see this, we're connected."}

@app.get("/health")
def health():
    return {"ok": True}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8620)
