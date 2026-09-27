from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from auth import router as auth_router
from dashboard import router as dashboard_router  

app = FastAPI(title="Fraud Dashboard API")

# CORS - allow all origins 
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# Include routers
app.include_router(auth_router)
app.include_router(dashboard_router) 

@app.get("/health")
def health():
    return {"status": "ok"}