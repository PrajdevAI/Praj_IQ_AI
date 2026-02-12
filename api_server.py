"""Lightweight FastAPI server exposing /api/me and /api/session endpoints.

Run with:
    uvicorn api_server:app --host 0.0.0.0 --port 8502

Endpoints require `Authorization: Bearer <Clerk JWT>` header.
"""
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.responses import JSONResponse
from starlette.requests import Request
from typing import Optional, Dict
import logging

import importlib.util
import os

# Load auth/jwt_verifier.py directly to avoid importing auth package __init__
jwt_verifier_path = os.path.join(os.path.dirname(__file__), "auth", "jwt_verifier.py")
spec = importlib.util.spec_from_file_location("auth.jwt_verifier", jwt_verifier_path)
jwt_verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jwt_verifier)
verify_clerk_token = jwt_verifier.verify_clerk_token
InvalidTokenError = jwt_verifier.InvalidTokenError
from config.database import get_db, set_tenant_context
from config.settings import settings

logger = logging.getLogger(__name__)
app = FastAPI(title="Acadia IQ API")


def get_bearer_token(authorization: Optional[str] = Header(None)) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    return parts[1]


async def verify_token_dep(token: str = Depends(get_bearer_token)) -> Dict:
    try:
        info = verify_clerk_token(token)
    except InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=str(e))

    return {"user_id": info["user_id"], "claims": info["claims"], "token": token}


@app.get("/api/me")
async def api_me(token_info: Dict = Depends(verify_token_dep)):
    """Return basic user info and tenant id.

    For this app, tenant_id is equal to the Clerk user_id (sub).
    """
    user_id = token_info["user_id"]
    tenant_id = user_id  # using Clerk user_id as tenant boundary

    return JSONResponse({"user_id": user_id, "tenant_id": tenant_id})


@app.post("/api/session")
async def api_session(token_info: Dict = Depends(verify_token_dep)):
    """Lightweight session check endpoint. Returns OK if token valid."""
    return JSONResponse({"ok": True, "user_id": token_info["user_id"]})


# Example protected endpoint that sets DB tenant context when using DB
@app.get("/api/protected-db")
async def protected_db_endpoint(request: Request, token_info: Dict = Depends(verify_token_dep)):
    # Example showing how to set tenant context for DB usage
    db_gen = get_db()
    db = next(db_gen)
    try:
        tenant_id = token_info["user_id"]
        set_tenant_context(db, tenant_id)
        # perform queries scoped to tenant here
        return {"status": "ok", "tenant_id": tenant_id}
    finally:
        db.close()
