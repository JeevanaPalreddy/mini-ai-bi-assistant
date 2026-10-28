"""FastAPI backend: /health and /ask."""

import logging
import os
import sqlite3

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.analytics import describe_spec, get_known_values, run_query
from app.database import (
    DatabaseUnavailableError,
    database_is_ready,
    get_readonly_connection,
)
from app.interpreter import interpret
from app.schemas import AskRequest, AskResponse, ResultRow

load_dotenv()
logger = logging.getLogger(__name__)

app = FastAPI(title="Mini AI BI Assistant", version="1.0.0")

origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/health")
def health():
    return {"status": "ok", "database_ready": database_is_ready()}


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest):
    try:
        with get_readonly_connection() as conn:
            known = get_known_values(conn)
            interpretation = interpret(request.question, known)
            result = run_query(conn, interpretation.spec)
    except DatabaseUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except sqlite3.Error:
        logger.exception("Database error while answering a question")
        raise HTTPException(status_code=500, detail="A database error occurred.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    notice = interpretation.notice
    if not result.rows:
        extra = "No completed orders matched this question."
        notice = f"{notice} {extra}" if notice else extra

    return AskResponse(
        question=request.question,
        interpreted_by=interpretation.source,
        notice=notice,
        spec=interpretation.spec,
        description=describe_spec(interpretation.spec),
        rows=[ResultRow(label=label, value=value) for label, value in result.rows],
        total=result.total,
    )