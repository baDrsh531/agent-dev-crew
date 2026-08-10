"""Notes API.

A small FastAPI service with CRUD over notes. Every route is currently public —
there is no authentication and no notion of a user or an administrator. That
gap is the starting point for the agent crew's demo task.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query

from .models import Note, NoteCreate, NoteUpdate
from .store import NoteNotFound, store

app = FastAPI(title="Notes API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    """Public liveness probe."""
    return {"status": "ok"}


@app.get("/notes", response_model=list[Note])
def list_notes(tag: str | None = Query(default=None)) -> list[Note]:
    return store.list(tag=tag)


@app.get("/notes/{note_id}", response_model=Note)
def get_note(note_id: int) -> Note:
    try:
        return store.get(note_id)
    except NoteNotFound:
        raise HTTPException(status_code=404, detail="note not found") from None


@app.post("/notes", response_model=Note, status_code=201)
def create_note(payload: NoteCreate) -> Note:
    return store.create(payload)


@app.patch("/notes/{note_id}", response_model=Note)
def update_note(note_id: int, payload: NoteUpdate) -> Note:
    try:
        return store.update(note_id, payload)
    except NoteNotFound:
        raise HTTPException(status_code=404, detail="note not found") from None


@app.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: int) -> None:
    try:
        store.delete(note_id)
    except NoteNotFound:
        raise HTTPException(status_code=404, detail="note not found") from None


@app.delete("/admin/notes", status_code=204)
def purge_notes() -> None:
    """Destructive maintenance endpoint. Anyone can call it today."""
    store.clear()
