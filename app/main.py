from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI, HTTPException, status
from app.config import settings
from app.database import Database
from app.models import RuleCreateRequest, RuleResponse, StatsResponse
from app.rules import RuleEngine
from app.webhook import router as webhook_router
from app.worker import BackgroundWorkerManager

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("linkplease")

db = Database(settings.DATABASE_PATH)
rule_engine = RuleEngine(db)
worker_manager = BackgroundWorkerManager(db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting LinkPlease service...")
    worker_manager.start()
    yield
    # Shutdown
    logger.info("Stopping LinkPlease service...")
    await worker_manager.stop()


app = FastAPI(
    title="LinkPlease Placement Service",
    version="1.0.0",
    description="Instagram DM Automation Service for LinkPlease placement assignment",
    lifespan=lifespan,
)

app.include_router(webhook_router)


@app.post(
    "/rules", response_model=RuleResponse, status_code=status.HTTP_201_CREATED
)
def create_rule(req: RuleCreateRequest):
    if not req.keyword or not req.keyword.strip():
        raise HTTPException(status_code=400, detail="Keyword cannot be empty")
    if not req.dm_message or not req.dm_message.strip():
        raise HTTPException(status_code=400, detail="dm_message cannot be empty")

    rule = rule_engine.create_rule(
        keyword=req.keyword.strip(), dm_message=req.dm_message.strip()
    )
    return RuleResponse(**rule)


@app.get("/rules")
def list_rules():
    return rule_engine.get_rules()


@app.get("/stats", response_model=StatsResponse)
def get_stats():
    stats_data = db.get_stats()
    return StatsResponse(**stats_data)


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "verify_signature": settings.VERIFY_WEBHOOK_SIGNATURE,
    }
