# Notes API — demo workspace

The repository the agent crew works on. It is intentionally incomplete: a small
FastAPI service with working CRUD, a green test suite, and **no authentication
whatsoever**. `DELETE /admin/notes` wipes the database and anyone can call it.

That gap is the demo task: *"add JWT authentication so that read routes stay
public, write routes require a valid token, and `/admin/*` requires an admin
role."*

Keeping the workspace small and its conventions obvious is deliberate — it lets
you judge the crew's output by reading it, rather than by trusting a summary.

## Layout

```
app/models.py   Pydantic request/response models
app/store.py    In-memory storage, raises NoteNotFound
app/main.py     Routes. Every one is public today.
tests/          The behaviour that must keep working
```

## Running it

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload    # http://127.0.0.1:8000/docs
python -m pytest -q
```

## Resetting after a run

Each run works on its own `agent/*` branch, so nothing here is destroyed:

```bash
git checkout main && git branch -D agent/<run-id>-<slug>
```
