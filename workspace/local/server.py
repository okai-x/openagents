"""Serve the existing Workspace bundle beside its loopback API."""
from pathlib import Path
import asyncio
import fcntl
from fastapi import HTTPException
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from app.main import app
from manage import PRIVATE


class BackupWriteGate:
    """Drain mutating HTTP requests while a database/blob backup is captured."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] in ('GET', 'HEAD', 'OPTIONS'):
            return await self.app(scope, receive, send)
        with (PRIVATE / 'storage.lock').open('a') as lock:
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    await asyncio.sleep(0.05)
            try:
                await self.app(scope, receive, send)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


app.add_middleware(BackupWriteGate)

BUNDLE = Path(__file__).resolve().parents[1] / "frontend/dist-desktop"


@app.get("/ui/")
def ui():
    html = (BUNDLE / "index.html").read_text()
    html = html.replace("'https://workspace-endpoint.openagents.org'", "window.location.origin")
    return HTMLResponse(html, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@app.get("/{resource:path}")
def static_or_workspace(resource: str):
    if resource.startswith(("v1/", "local/")):
        raise HTTPException(404)
    relative = resource.removeprefix("ui/")
    candidate = (BUNDLE / relative).resolve()
    if candidate.is_relative_to(BUNDLE.resolve()) and candidate.is_file():
        return FileResponse(candidate)
    if not resource:
        return RedirectResponse("/ui/")
    # Workspace links use the shared bundle's hash router.
    if "/" not in resource and "." not in resource:
        return RedirectResponse("/ui/#/" + resource)
    raise HTTPException(404)
