"""BBP admin. Local only: run with `uvicorn admin.main:app --reload` (default host 127.0.0.1)."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from admin import db, repo, routes, sync

ADMIN_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    with db.new_session() as session:
        repo.ensure_default_settings(session)
        session.commit()
        try:
            sync.check(session)
        except sync.SyncError:
            pass  # surfaced as a banner on every page until fixed
        sync.status.imported_notice = False  # startup import is expected, no banner
    yield


app = FastAPI(title="BBP 後台", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

db.AVATAR_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=ADMIN_DIR / "static"), name="static")
app.mount("/avatars", StaticFiles(directory=db.AVATAR_DIR), name="avatars")
app.include_router(routes.router)


@app.exception_handler(repo.RepoError)
def repo_error(_request: Request, exc: repo.RepoError):
    return PlainTextResponse(str(exc), status_code=400)


@app.get("/")
def root():
    return RedirectResponse("/admin")
