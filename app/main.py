from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.db import DatabaseConnectionError
from app.routes.auth import router as auth_router
from app.routes.ingest import router as ingest_router
from app.routes.papers import router as papers_router
from app.routes.questions import router as questions_router
from app.routes.reference import router as reference_router

app = FastAPI(title="PilloraQuestionBank")

app.include_router(auth_router)
app.include_router(reference_router)
app.include_router(questions_router)
app.include_router(ingest_router)
# Registered after reference_router so its literal GET /api/papers/years route
# is matched before this router's GET /api/papers/{paper_id}.
app.include_router(papers_router)


@app.exception_handler(DatabaseConnectionError)
def database_connection_error_handler(request: Request, exc: DatabaseConnectionError):
    return JSONResponse(status_code=503, content={"detail": "Database is temporarily unavailable — please retry."})
