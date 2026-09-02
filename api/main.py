# api/main.py
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from core.db import create_db_and_tables
from api.endpoints import pages, results, runs, samples, studies

app = FastAPI(title="LCMS Pipeline API")


class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    """During active development the JS/CSS under /static change often
    between reloads; browsers otherwise cache them heuristically (no
    explicit Cache-Control is set by StaticFiles by default) and a stale
    copy silently "works" but ignores every edit -- easy to mistake for a
    server-side bug. Revisit/remove this once the frontend stabilizes."""
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response


app.add_middleware(NoCacheStaticMiddleware)
app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parent / "static"), name="static")

# pages.router's "/studies/{study_id}" catch-all HTML route must be
# included LAST: FastAPI matches routes in the order they land in
# app.routes, and every other /studies/... route below is more specific
# than that single-segment catch-all. Include order across routers matters
# here just as much as declaration order within one router (pages.py's own
# "/studies/new" vs "/studies/{study_id}" ordering still matters too).
app.include_router(studies.router)
app.include_router(samples.router)
app.include_router(runs.router)
app.include_router(results.router)
app.include_router(pages.router)


@app.on_event("startup")
async def on_startup():
    await create_db_and_tables()
