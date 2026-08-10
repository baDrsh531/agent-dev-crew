"""In-memory storage.

Deliberately simple: this project exists to be modified by the agent crew, so
the persistence layer stays out of the way.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .models import Note, NoteCreate, NoteUpdate


class NoteNotFound(KeyError):
    pass


class NoteStore:
    def __init__(self) -> None:
        self._notes: dict[int, Note] = {}
        self._next_id = 1

    def create(self, payload: NoteCreate) -> Note:
        note = Note(id=self._next_id, **payload.model_dump())
        self._notes[note.id] = note
        self._next_id += 1
        return note

    def get(self, note_id: int) -> Note:
        if note_id not in self._notes:
            raise NoteNotFound(note_id)
        return self._notes[note_id]

    def list(self, tag: str | None = None) -> list[Note]:
        notes = list(self._notes.values())
        if tag:
            notes = [n for n in notes if tag in n.tags]
        return sorted(notes, key=lambda n: n.id)

    def update(self, note_id: int, payload: NoteUpdate) -> Note:
        note = self.get(note_id)
        changes = payload.model_dump(exclude_none=True)
        if changes:
            updated = note.model_copy(update={**changes, "updated_at": datetime.now(timezone.utc)})
            self._notes[note_id] = updated
            return updated
        return note

    def delete(self, note_id: int) -> None:
        if note_id not in self._notes:
            raise NoteNotFound(note_id)
        del self._notes[note_id]

    def clear(self) -> None:
        self._notes.clear()
        self._next_id = 1


store = NoteStore()
