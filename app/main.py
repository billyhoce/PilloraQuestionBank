from fastapi import FastAPI

from app.routes.auth import router as auth_router
from app.routes.questions import router as questions_router
from app.routes.reference import router as reference_router

app = FastAPI(title="PilloraQuestionBank")

app.include_router(auth_router)
app.include_router(reference_router)
app.include_router(questions_router)
