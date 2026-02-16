from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from app.core.database import SessionLocal
from app.api.routes.tickets import router as tickets_router
from app.api.routes.approvals import router as approvals_router
from app.api.routes.properties import router as properties_router
from app.api.routes.events import router as events_router
from app.api.routes.units import router as units_router
from app.api.routes.reports import router as reports_router


# 1) Create the app FIRST
app = FastAPI(title="Internal Automation Backend")

# 2) Add CORS Middleware BEFORE routes
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5000",
        "http://localhost:5173",
        "https://automated-dashboard-frontend.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3) Include routers AFTER app is created
app.include_router(tickets_router)
app.include_router(approvals_router)
app.include_router(properties_router)
app.include_router(events_router)
app.include_router(units_router)
app.include_router(reports_router)
# 4) Health check endpoints
@app.get("/health")
def health():
    return {"ok": True, "service": "backend"}

@app.get("/db-health")
def db_health():
    db = SessionLocal()
    try:
        db.execute(text("select 1"))
        return {"ok": True, "db": "connected"}
    finally:
        db.close()