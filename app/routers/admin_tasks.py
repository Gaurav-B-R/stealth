"""Admin Console › Tasks — the team's own small, Jira-style task board.

Every console member can use it, whatever sections they were granted: tasks are how the
team hands work to each other, not a data section, so a Viewer on AI Costs can still be
handed a task and mark it Done. Visibility follows involvement — you see the tasks you
created or were assigned. Team managers (protected platform administrators, and Admin-role
members holding the Team section) see every task, so whoever hands out console access can
also see what the team is working on.

Lifecycle: pending → in_progress / on_hold → done → closed. "Done" is the assignee saying
"finished"; "Closed" is the person who handed the task out agreeing, and the task leaving the
board. So the assignee moves a task anywhere up to Done, but only its creator (or a team
manager) can close it, or reopen it once closed. Everything else is open to anyone on the
task — the timeline records who did what.
"""

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app import admin_access, admin_sessions, email_service, models
from app.admin_access import console_section, get_current_admin_user
from app.auth import is_enterprise_only_account
from app.database import get_db
from app.routers import admin as admin_router

router = APIRouter(
    prefix="/api/admin/tasks",
    tags=["admin-tasks"],
    dependencies=[Depends(get_current_admin_user), Depends(admin_router.require_admin_turnstile_proof)],
    # Task text is never echoed back in a 422: a lone surrogate in the echoed input would
    # make the error response itself fail to encode (a 500), and nobody needs it repeated.
    route_class=admin_sessions.SensitiveInputRoute,
)
logger = logging.getLogger(__name__)

STATUSES = {
    "pending": "Pending",
    "in_progress": "In progress",
    "on_hold": "On hold",
    "done": "Done",
    "closed": "Closed",
}
OPEN_STATUSES = ("pending", "in_progress", "on_hold")
PRIORITIES = {"low": "Low", "medium": "Medium", "high": "High", "urgent": "Urgent"}
StatusKey = Literal["pending", "in_progress", "on_hold", "done", "closed"]
PriorityKey = Literal["low", "medium", "high", "urgent"]

TITLE_MAX = 200
DESCRIPTION_MAX = 5000
NOTE_MAX = 4000
DB_INT_MAX = 2_147_483_647  # ids are 32-bit INTEGER columns; larger values would 500 on Postgres
OPEN_LIST_LIMIT = 500
CLOSED_LIST_LIMIT = 100
TIMELINE_LIMIT = 500
READ_RATE_LIMIT = 240
WRITE_RATE_LIMIT = 90
RATE_WINDOW_SECONDS = 60
# C0 controls (minus tab/newline) and DEL. Postgres refuses NUL outright, so letting one
# through turns a pasted log line into a 500.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(max_length=TITLE_MAX)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    assignee_user_id: int | None = Field(default=None, ge=1, le=DB_INT_MAX)
    status: StatusKey = "pending"
    priority: PriorityKey = "medium"
    due_date: date | None = None


class TaskUpdate(BaseModel):
    """Partial update: only the fields the client sends are touched (`model_fields_set`),
    so two teammates editing different fields of one task never overwrite each other.
    An explicit null clears assignee / due date / description."""
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=TITLE_MAX)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    assignee_user_id: int | None = Field(default=None, ge=1, le=DB_INT_MAX)
    status: StatusKey | None = None
    priority: PriorityKey | None = None
    due_date: date | None = None
    # Optional note recorded with the change ("why is this on hold?").
    note: str | None = Field(default=None, max_length=NOTE_MAX)


class NoteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(max_length=NOTE_MAX)


@dataclass(frozen=True)
class _Viewer:
    user: models.User
    oversees_all: bool


def _viewer(db: Session, user: models.User) -> _Viewer:
    access = admin_access.require_access(db, user)
    return _Viewer(user, bool(access.protected or access.allows("team", "read")))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        # SQLite hands back naive datetimes; every timestamp here is written in UTC.
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return value.isoformat()


def _format_due(value: date | None) -> str | None:
    return f"{value.day} {value.strftime('%b %Y')}" if value else None


def _rate_limit(request: Request, user: models.User, *, write: bool) -> None:
    # Looked up on the module at call time so tests can stub the shared limiter.
    admin_router._enforce_rate_limit_or_429(
        request=request,
        scope="admin.tasks.write" if write else "admin.tasks.read",
        limit=WRITE_RATE_LIMIT if write else READ_RATE_LIMIT,
        window_seconds=RATE_WINDOW_SECONDS,
        extra_key=f"user:{user.id}",
    )


def _clean_title(value: str | None) -> str:
    title = " ".join(_CONTROL_CHARS.sub(" ", str(value or "")).split())
    if not title:
        raise HTTPException(422, "Give the task a title.")
    return title


def _clean_text(value: str | None) -> str | None:
    text = _CONTROL_CHARS.sub("", str(value or "").replace("\r\n", "\n").replace("\r", "\n")).strip()
    return text or None


def _valid_due(value: date | None) -> date | None:
    if value is not None and not 2000 <= value.year <= 2100:
        raise HTTPException(422, "Choose a due date between the years 2000 and 2100.")
    return value


def _team_members(db: Session) -> dict[int, models.User]:
    """Everyone who can sign in to the console right now — the only people a task can be
    handed to, and the only people task emails go to."""
    rows = (db.query(models.User, models.AdminConsoleAccess)
            .outerjoin(models.AdminConsoleAccess, models.AdminConsoleAccess.user_id == models.User.id)
            .filter(or_(models.User.is_admin.is_(True), models.User.is_developer.is_(True),
                        models.AdminConsoleAccess.user_id.is_not(None)))
            .all())
    members: dict[int, models.User] = {}
    for user, membership in rows:
        if not user.is_active or not user.email_verified or is_enterprise_only_account(user):
            continue
        if admin_access.access_for(db, user, membership) is None:
            continue
        members[user.id] = user
    return members


def _display_name(user: models.User | None) -> str:
    if user is None:
        return "Former member"
    return (user.full_name or "").strip() or (user.email or "").split("@")[0] or "Teammate"


def _person(user: models.User | None, members: dict) -> dict | None:
    # Names only: who holds console access, and their sign-in emails, stays behind the
    # Team section (GET /api/admin/team). Assigning someone needs no more than this.
    if user is None:
        return None
    return {"id": user.id, "name": _display_name(user), "has_access": user.id in members}


def _people(db: Session, ids, members: dict) -> dict[int, models.User]:
    wanted = {int(item) for item in ids if item}
    people = {uid: members[uid] for uid in wanted if uid in members}
    missing = wanted - set(people)
    if missing:
        for user in db.query(models.User).filter(models.User.id.in_(missing)).all():
            people[user.id] = user
    return people


def _user_ref(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def _is_visible(task: models.AdminTeamTask, viewer: _Viewer) -> bool:
    return viewer.oversees_all or viewer.user.id in (task.assignee_user_id, task.created_by_user_id)


def _can_delete(task: models.AdminTeamTask, viewer: _Viewer) -> bool:
    return viewer.oversees_all or task.created_by_user_id == viewer.user.id


def _can_close(task: models.AdminTeamTask, viewer: _Viewer) -> bool:
    """Closing (and reopening a closed task) is the assigner's call, not the assignee's:
    the assignee marks Done, the person who handed the task out reviews and closes it."""
    return viewer.oversees_all or task.created_by_user_id == viewer.user.id


def _visible_query(db: Session, viewer: _Viewer):
    query = db.query(models.AdminTeamTask)
    if not viewer.oversees_all:
        query = query.filter(or_(models.AdminTeamTask.assignee_user_id == viewer.user.id,
                                 models.AdminTeamTask.created_by_user_id == viewer.user.id))
    return query


def _task_or_404(db: Session, viewer: _Viewer, task_id: int, *, lock: bool = False) -> models.AdminTeamTask:
    query = db.query(models.AdminTeamTask).populate_existing().filter(models.AdminTeamTask.id == task_id)
    if lock:
        query = query.with_for_update()
    task = query.first()
    # 404 (not 403) for tasks you aren't on, so ids don't reveal what others are working on.
    if task is None or not _is_visible(task, viewer):
        raise HTTPException(404, "Task not found.")
    return task


def _valid_assignee(user_id: int | None, members: dict, *, current: int | None = None) -> int | None:
    if user_id is None or user_id == current:
        return user_id
    if user_id not in members:
        raise HTTPException(422, "Choose a teammate who currently has Admin Console access.")
    return user_id


def _note_counts(db: Session, task_ids: list[int]) -> dict[int, int]:
    if not task_ids:
        return {}
    rows = (db.query(models.AdminTeamTaskNote.task_id, func.count(models.AdminTeamTaskNote.id))
            .filter(models.AdminTeamTaskNote.task_id.in_(task_ids), models.AdminTeamTaskNote.kind == "note")
            .group_by(models.AdminTeamTaskNote.task_id).all())
    return {task_id: int(count) for task_id, count in rows}


def _serialize_task(task, viewer: _Viewer, people: dict, members: dict, note_count: int) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description or "",
        "status": task.status,
        "priority": task.priority,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "assignee": _person(people.get(task.assignee_user_id), members),
        "created_by": _person(people.get(task.created_by_user_id), members),
        "created_at": _iso(task.created_at),
        "updated_at": _iso(task.updated_at),
        "status_changed_at": _iso(task.status_changed_at),
        "note_count": note_count,
        "can_edit": _is_visible(task, viewer),
        "can_delete": _can_delete(task, viewer),
        "can_close": _can_close(task, viewer),
    }


def _label(kind: str, value: str | None, people: dict) -> str | None:
    if kind in {"assignee", "created"}:
        uid = _user_ref(value)
        if uid is None:
            return "Unassigned" if kind == "assignee" else None
        return _display_name(people.get(uid))
    if kind == "status":
        return STATUSES.get(value or "", value)
    if kind == "priority":
        return PRIORITIES.get(value or "", value)
    if kind == "due_date":
        try:
            return _format_due(date.fromisoformat(value)) if value else "No due date"
        except ValueError:
            return value
    return value


def _detail(db: Session, task, viewer: _Viewer, members: dict) -> dict:
    entries = (db.query(models.AdminTeamTaskNote)
               .filter(models.AdminTeamTaskNote.task_id == task.id)
               .order_by(models.AdminTeamTaskNote.created_at.desc(), models.AdminTeamTaskNote.id.desc())
               .limit(TIMELINE_LIMIT).all())
    ids = {task.assignee_user_id, task.created_by_user_id}
    for entry in entries:
        ids.add(entry.author_user_id)
        if entry.kind in {"assignee", "created"}:
            ids.update({_user_ref(entry.from_value), _user_ref(entry.to_value)})
    people = _people(db, ids, members)
    note_count = _note_counts(db, [task.id]).get(task.id, 0)
    timeline = [{
        "id": entry.id,
        "kind": entry.kind,
        "body": entry.body or "",
        "from": entry.from_value,
        "to": entry.to_value,
        "from_label": _label(entry.kind, entry.from_value, people),
        "to_label": _label(entry.kind, entry.to_value, people),
        "author": _person(people.get(entry.author_user_id), members),
        "created_at": _iso(entry.created_at),
        "can_delete": entry.kind == "note" and entry.author_user_id == viewer.user.id,
    } for entry in entries]
    return {
        "visible": True,
        "task": _serialize_task(task, viewer, people, members, note_count),
        "timeline": timeline,
    }


def _send_task_email(**kwargs) -> None:
    try:
        ok, _email_id, error = email_service.send_admin_task_email(**kwargs)
        if not ok:
            logger.info("Admin task email to user was not sent: %s", error)
    except Exception:  # pragma: no cover - a notice must never break the board
        logger.exception("Admin task email failed")


def _notify(background: BackgroundTasks, db: Session, *, task, actor: models.User, members: dict,
            new_assignee_id: int | None = None, previous_assignee_id: int | None = None,
            previous_status: str | None = None, changes: list[str] | None = None,
            note: str | None = None) -> None:
    """Email the other people on a task. The actor never gets their own change, and only
    current console members get anything — an ex-member's inbox is not the team's."""
    changes = changes or []
    actor_label = _display_name(actor)
    status_label = STATUSES.get(task.status, task.status)
    status_changed = previous_status is not None and previous_status != task.status
    recipients: dict[int, str] = {}
    if new_assignee_id and new_assignee_id != actor.id:
        recipients[new_assignee_id] = f"{actor_label} assigned you a task"
    if status_changed and task.status == "done" and task.created_by_user_id and task.created_by_user_id != actor.id:
        # Done is a hand-back: tell the assigner it is waiting on them.
        recipients.setdefault(task.created_by_user_id, f"{actor_label} marked a task Done — ready for you to close")
    if changes or note:
        if status_changed and task.status == "closed":
            headline = f"{actor_label} closed a task"
        elif status_changed and previous_status in {"done", "closed"}:
            headline = f"{actor_label} sent a task back to {status_label}"
        elif status_changed:
            headline = f"{actor_label} moved a task to {status_label}"
        elif note and not changes:
            headline = f"{actor_label} added a note to a task"
        else:
            headline = f"{actor_label} updated a task"
        for uid in (task.created_by_user_id, task.assignee_user_id, previous_assignee_id):
            if uid and uid != actor.id and uid not in recipients:
                recipients[uid] = headline
    if not recipients:
        return
    # Everything the email needs is read now: the request's session is closed by the time
    # background tasks run.
    assignee = _people(db, {task.assignee_user_id}, members).get(task.assignee_user_id)
    base_url = email_service.DEFAULT_PUBLIC_BASE_URL.rstrip("/")
    for uid, headline in recipients.items():
        recipient = members.get(uid)
        if recipient is None:
            continue
        background.add_task(
            _send_task_email,
            to_email=recipient.email,
            recipient_name=_display_name(recipient),
            actor_label=actor_label,
            headline=headline,
            task_title=task.title,
            status_label=STATUSES.get(task.status, task.status),
            priority_label=PRIORITIES.get(task.priority, task.priority),
            assignee_label=_display_name(assignee) if task.assignee_user_id else "Unassigned",
            due_label=_format_due(task.due_date),
            changes=list(changes),
            note=note,
            task_url=f"{base_url}/admin_console#task-{task.id}",
        )


@router.get("")
@console_section(None, "access")
def list_tasks(
    request: Request,
    response: Response,
    current_user: models.User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """The board: every open task you can see, plus the most recently closed ones."""
    _rate_limit(request, current_user, write=False)
    response.headers["Cache-Control"] = "no-store"
    viewer = _viewer(db, current_user)
    members = _team_members(db)
    open_tasks = (_visible_query(db, viewer)
                  .filter(models.AdminTeamTask.status != "closed")
                  .order_by(models.AdminTeamTask.updated_at.desc(), models.AdminTeamTask.id.desc())
                  .limit(OPEN_LIST_LIMIT + 1).all())
    truncated = len(open_tasks) > OPEN_LIST_LIMIT
    open_tasks = open_tasks[:OPEN_LIST_LIMIT]
    closed_query = _visible_query(db, viewer).filter(models.AdminTeamTask.status == "closed")
    closed_total = closed_query.count()
    closed_tasks = (closed_query
                    .order_by(models.AdminTeamTask.status_changed_at.desc(), models.AdminTeamTask.id.desc())
                    .limit(CLOSED_LIST_LIMIT).all())
    tasks = open_tasks + closed_tasks
    people = _people(db, {uid for task in tasks for uid in (task.assignee_user_id, task.created_by_user_id)}, members)
    counts = _note_counts(db, [task.id for task in tasks])
    roster = sorted(members.values(), key=lambda user: (_display_name(user).lower(), user.id))
    return {
        "me": current_user.id,
        "can_view_all": viewer.oversees_all,
        "members": [{"id": user.id, "name": _display_name(user)} for user in roster],
        "tasks": [_serialize_task(task, viewer, people, members, counts.get(task.id, 0)) for task in tasks],
        "closed_total": closed_total,
        "truncated": truncated,
    }


@router.get("/summary")
@console_section(None, "access")
def task_summary(
    request: Request,
    response: Response,
    current_user: models.User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """Counts for the sidebar badge: open tasks waiting on you."""
    _rate_limit(request, current_user, write=False)
    response.headers["Cache-Control"] = "no-store"
    mine = db.query(models.AdminTeamTask).filter(models.AdminTeamTask.assignee_user_id == current_user.id,
                                                 models.AdminTeamTask.status.in_(OPEN_STATUSES))
    today = datetime.now(timezone.utc).date()
    return {
        "assigned_open": mine.count(),
        "assigned_overdue": mine.filter(models.AdminTeamTask.due_date.is_not(None),
                                        models.AdminTeamTask.due_date < today).count(),
    }


@router.get("/{task_id}")
@console_section(None, "access")
def get_task(
    request: Request,
    response: Response,
    task_id: int = Path(ge=1, le=DB_INT_MAX),
    current_user: models.User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    _rate_limit(request, current_user, write=False)
    response.headers["Cache-Control"] = "no-store"
    viewer = _viewer(db, current_user)
    task = _task_or_404(db, viewer, task_id)
    return _detail(db, task, viewer, _team_members(db))


@router.post("", status_code=201)
@console_section(None, "access")
@admin_sessions.sensitive_input
def create_task(
    payload: TaskCreate,
    request: Request,
    background: BackgroundTasks,
    current_user: models.User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    _rate_limit(request, current_user, write=True)
    viewer = _viewer(db, current_user)
    members = _team_members(db)
    title = _clean_title(payload.title)
    assignee_id = _valid_assignee(payload.assignee_user_id, members)
    now = _now()
    task = models.AdminTeamTask(
        title=title,
        description=_clean_text(payload.description),
        status=payload.status,
        priority=payload.priority,
        assignee_user_id=assignee_id,
        created_by_user_id=current_user.id,
        due_date=_valid_due(payload.due_date),
        status_changed_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(task)
    db.flush()
    db.add(models.AdminTeamTaskNote(task_id=task.id, author_user_id=current_user.id, kind="created",
                                    to_value=str(assignee_id) if assignee_id else None, created_at=now))
    db.commit()
    db.refresh(task)
    _notify(background, db, task=task, actor=current_user, members=members, new_assignee_id=assignee_id)
    return _detail(db, task, viewer, members)


@router.patch("/{task_id}")
@console_section(None, "access")
@admin_sessions.sensitive_input
def update_task(
    payload: TaskUpdate,
    request: Request,
    background: BackgroundTasks,
    task_id: int = Path(ge=1, le=DB_INT_MAX),
    current_user: models.User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    _rate_limit(request, current_user, write=True)
    viewer = _viewer(db, current_user)
    fields = payload.model_fields_set
    for required in ("title", "status", "priority"):
        if required in fields and getattr(payload, required) is None:
            raise HTTPException(422, f"A task always has a {required}.")
    task = _task_or_404(db, viewer, task_id, lock=True)
    if ("status" in fields and payload.status != task.status and "closed" in (payload.status, task.status)
            and not _can_close(task, viewer)):
        raise HTTPException(403, "Only the person who assigned this task can close it. Mark it Done and they'll review it."
                            if payload.status == "closed" else
                            "This task is closed. Only the person who assigned it can reopen it.")
    members = _team_members(db)
    now = _now()
    entries: list[tuple[str, str | None, str | None]] = []
    changes: list[str] = []
    previous_assignee = task.assignee_user_id
    previous_status = task.status
    new_assignee = None

    edited = []
    if "title" in fields:
        title = _clean_title(payload.title)
        if title != task.title:
            task.title = title
            edited.append("title")
    if "description" in fields:
        description = _clean_text(payload.description)
        if description != (task.description or None):
            task.description = description
            edited.append("description")
    if edited:
        entries.append(("edited", None, ",".join(edited)))
        changes.append(f"Edited the {' and '.join(edited)}")
    if "priority" in fields and payload.priority != task.priority:
        entries.append(("priority", task.priority, payload.priority))
        changes.append(f"Priority: {PRIORITIES.get(task.priority, task.priority)} → {PRIORITIES[payload.priority]}")
        task.priority = payload.priority
    if "due_date" in fields:
        due = _valid_due(payload.due_date)
        if due != task.due_date:
            entries.append(("due_date", _iso(task.due_date), _iso(due)))
            changes.append(f"Due date: {_format_due(task.due_date) or 'none'} → {_format_due(due) or 'none'}")
            task.due_date = due
    if "assignee_user_id" in fields:
        assignee_id = _valid_assignee(payload.assignee_user_id, members, current=task.assignee_user_id)
        if assignee_id != task.assignee_user_id:
            people = _people(db, {task.assignee_user_id, assignee_id}, members)
            old_label = _display_name(people.get(task.assignee_user_id)) if task.assignee_user_id else "Unassigned"
            new_label = _display_name(people.get(assignee_id)) if assignee_id else "Unassigned"
            entries.append(("assignee", str(task.assignee_user_id) if task.assignee_user_id else None,
                            str(assignee_id) if assignee_id else None))
            changes.append(f"Assignee: {old_label} → {new_label}")
            task.assignee_user_id = assignee_id
            new_assignee = assignee_id
    if "status" in fields and payload.status != task.status:
        entries.append(("status", task.status, payload.status))
        changes.append(f"Status: {STATUSES.get(task.status, task.status)} → {STATUSES[payload.status]}")
        task.status = payload.status
        task.status_changed_at = now
    note = _clean_text(payload.note) if "note" in fields else None

    if not entries and not note:
        db.rollback()  # nothing changed: release the row lock without writing
        task = _task_or_404(db, viewer, task_id)
        return _detail(db, task, viewer, members)

    for kind, before, after in entries:
        db.add(models.AdminTeamTaskNote(task_id=task.id, author_user_id=current_user.id, kind=kind,
                                        from_value=before, to_value=after, created_at=now))
    if note:
        db.add(models.AdminTeamTaskNote(task_id=task.id, author_user_id=current_user.id, kind="note",
                                        body=note, created_at=now))
    task.updated_at = now
    db.commit()
    db.refresh(task)
    _notify(background, db, task=task, actor=current_user, members=members, new_assignee_id=new_assignee,
            previous_assignee_id=previous_assignee, previous_status=previous_status, changes=changes, note=note)
    if not _is_visible(task, viewer):
        # Handed to someone else by a teammate who isn't a manager: it leaves their board.
        return {"visible": False, "task": None, "timeline": []}
    return _detail(db, task, viewer, members)


@router.delete("/{task_id}")
@console_section(None, "access")
def delete_task(
    request: Request,
    task_id: int = Path(ge=1, le=DB_INT_MAX),
    current_user: models.User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    _rate_limit(request, current_user, write=True)
    viewer = _viewer(db, current_user)
    task = _task_or_404(db, viewer, task_id, lock=True)
    if not _can_delete(task, viewer):
        raise HTTPException(403, "Only the person who created this task, or a team manager, can delete it.")
    db.query(models.AdminTeamTaskNote).filter(models.AdminTeamTaskNote.task_id == task.id).delete(synchronize_session=False)
    db.delete(task)
    db.commit()
    return {"id": task_id, "message": "Task deleted."}


@router.post("/{task_id}/notes", status_code=201)
@console_section(None, "access")
@admin_sessions.sensitive_input
def add_task_note(
    payload: NoteCreate,
    request: Request,
    background: BackgroundTasks,
    task_id: int = Path(ge=1, le=DB_INT_MAX),
    current_user: models.User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    _rate_limit(request, current_user, write=True)
    body = _clean_text(payload.body)
    if not body:
        raise HTTPException(422, "Write a note first.")
    viewer = _viewer(db, current_user)
    task = _task_or_404(db, viewer, task_id, lock=True)
    members = _team_members(db)
    now = _now()
    db.add(models.AdminTeamTaskNote(task_id=task.id, author_user_id=current_user.id, kind="note",
                                    body=body, created_at=now))
    task.updated_at = now
    db.commit()
    db.refresh(task)
    _notify(background, db, task=task, actor=current_user, members=members, note=body)
    return _detail(db, task, viewer, members)


@router.delete("/{task_id}/notes/{note_id}")
@console_section(None, "access")
def delete_task_note(
    request: Request,
    task_id: int = Path(ge=1, le=DB_INT_MAX),
    note_id: int = Path(ge=1, le=DB_INT_MAX),
    current_user: models.User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    _rate_limit(request, current_user, write=True)
    viewer = _viewer(db, current_user)
    task = _task_or_404(db, viewer, task_id, lock=True)
    entry = (db.query(models.AdminTeamTaskNote)
             .filter(models.AdminTeamTaskNote.id == note_id, models.AdminTeamTaskNote.task_id == task.id).first())
    if entry is None:
        raise HTTPException(404, "Note not found.")
    # Recorded changes are history, not notes: nobody can erase them.
    if entry.kind != "note" or entry.author_user_id != current_user.id:
        raise HTTPException(403, "You can only delete notes you wrote.")
    db.delete(entry)
    db.commit()
    return _detail(db, task, viewer, _team_members(db))
