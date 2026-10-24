"""Admin Console › Tasks: who can see, change and delete team tasks, and who gets emailed.

Real signed session tokens and SQLite rows, without importing app.main or contacting
email, storage, AI, billing, or any production database.
"""

import json
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import admin_access, admin_task_files, auth, email_service, enterprise_storage, models
from app.database import Base, get_db
from app.routers import admin as admin_router
from app.routers import admin_tasks
from app.utils import user_deletion


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def user(db, email, **flags):
    row = models.User(email=email, hashed_password="unchanged-password-hash", full_name=email.split("@")[0].title(),
                      email_verified=True, email_notifications_enabled=False, **flags)
    db.add(row)
    db.commit()
    return row


def grant(db, person, role="viewer", sections=("ai",)):
    db.add(models.AdminConsoleAccess(user_id=person.id, role=role, sections=json.dumps(list(sections))))
    db.commit()


def headers(person):
    return {"Authorization": "Bearer " + auth.create_access_token({"sub": person.email})}


@pytest.fixture
def emails(monkeypatch):
    sent = []

    def capture(**kwargs):
        sent.append(kwargs)
        return True, "email-id", None

    monkeypatch.setattr(email_service, "send_admin_task_email", capture)
    return sent


@pytest.fixture
def client(db, monkeypatch, emails):
    monkeypatch.setattr(admin_router, "_enforce_rate_limit_or_429", lambda **kwargs: None)
    app = FastAPI()
    app.include_router(admin_tasks.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[admin_router.require_admin_turnstile_proof] = lambda: None
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def team(db):
    """owner = protected platform admin (sees everything); ana/ben = scoped members."""
    owner = user(db, "owner@example.com", is_admin=True)
    ana = user(db, "ana@example.com")
    grant(db, ana, "viewer", ["ai"])
    ben = user(db, "ben@example.com")
    grant(db, ben, "editor", ["users"])
    outsider = user(db, "outsider@example.com")  # a Rilono account with no console access
    return {"owner": owner, "ana": ana, "ben": ben, "outsider": outsider}


def create(client, actor, **body):
    payload = {"title": "Reconcile October payouts", **body}
    response = client.post("/api/admin/tasks", headers=headers(actor), json=payload)
    assert response.status_code == 201, response.text
    return response.json()["task"]


def test_every_task_route_declares_a_shared_policy_and_turnstile_proof():
    routes = [route for route in admin_tasks.router.routes if isinstance(route, APIRoute)]
    assert len(routes) == 11
    for route in routes:
        policy = getattr(route.endpoint, "admin_console_policy", None)
        assert isinstance(policy, admin_access.RoutePolicy), route.path
        assert policy.section is None and policy.action == "access", route.path
        calls = {dep.call for dep in route.dependant.dependencies}
        assert admin_access.get_current_admin_user in calls, route.path
        assert admin_router.require_admin_turnstile_proof in calls, route.path


def test_accounts_without_console_access_are_refused_everywhere(client, db, team):
    task = create(client, team["owner"], assignee_user_id=team["ana"].id)
    outsider = headers(team["outsider"])
    for method, path in [("GET", "/api/admin/tasks"), ("GET", "/api/admin/tasks/summary"),
                         ("GET", f"/api/admin/tasks/{task['id']}"), ("POST", "/api/admin/tasks"),
                         ("PATCH", f"/api/admin/tasks/{task['id']}"), ("DELETE", f"/api/admin/tasks/{task['id']}"),
                         ("POST", f"/api/admin/tasks/{task['id']}/notes")]:
        response = client.request(method, path, headers=outsider, json={"title": "x", "body": "x"})
        assert response.status_code == 403, (method, path, response.text)
    assert db.query(models.AdminTeamTask).count() == 1


def test_turnstile_proof_is_still_required(client, team, monkeypatch):
    client.app.dependency_overrides.pop(admin_router.require_admin_turnstile_proof)
    monkeypatch.setattr(admin_router, "_is_admin_turnstile_required", lambda request: True)
    response = client.get("/api/admin/tasks", headers=headers(team["owner"]))
    assert response.status_code == 403
    assert "Cloudflare" in response.json()["detail"]


def test_any_member_can_assign_and_only_the_people_on_a_task_see_it(client, team):
    # A Viewer on AI Costs can still hand work to the owner: tasks are not a data section.
    task = create(client, team["ana"], assignee_user_id=team["owner"].id, priority="high",
                  due_date="2026-11-02", description="  Check the Route ledger.  ")
    assert task["assignee"]["id"] == team["owner"].id
    assert task["created_by"]["id"] == team["ana"].id
    assert task["status"] == "pending" and task["priority"] == "high"
    assert task["description"] == "Check the Route ledger."
    assert task["can_edit"] and task["can_delete"]

    owner_board = client.get("/api/admin/tasks", headers=headers(team["owner"]))
    assert owner_board.status_code == 200
    assert owner_board.headers["cache-control"] == "no-store"
    assert owner_board.json()["can_view_all"] is True
    assert [item["id"] for item in owner_board.json()["tasks"]] == [task["id"]]
    assert {member["id"] for member in owner_board.json()["members"]} == {
        team["owner"].id, team["ana"].id, team["ben"].id}

    ben_board = client.get("/api/admin/tasks", headers=headers(team["ben"])).json()
    assert ben_board["can_view_all"] is False and ben_board["tasks"] == []
    assert client.get(f"/api/admin/tasks/{task['id']}", headers=headers(team["ben"])).status_code == 404
    assert client.patch(f"/api/admin/tasks/{task['id']}", headers=headers(team["ben"]),
                        json={"status": "done"}).status_code == 404
    assert client.post(f"/api/admin/tasks/{task['id']}/notes", headers=headers(team["ben"]),
                       json={"body": "peek"}).status_code == 404


def test_team_section_admins_oversee_every_task(client, db, team):
    manager = user(db, "manager@example.com")
    grant(db, manager, "admin", ["users", "team"])
    task = create(client, team["ana"], assignee_user_id=team["ben"].id)
    board = client.get("/api/admin/tasks", headers=headers(manager)).json()
    assert board["can_view_all"] is True
    assert [item["id"] for item in board["tasks"]] == [task["id"]]
    assert board["tasks"][0]["can_delete"] is True


@pytest.mark.parametrize("flags,membership", [({}, None), ({"is_active": False}, ("viewer", ["ai"])),
                                              ({"is_enterprise_account": True}, ("viewer", ["ai"]))])
def test_tasks_can_only_be_handed_to_current_console_members(client, db, team, flags, membership):
    target = user(db, "target@example.com", **flags)
    if membership:
        grant(db, target, *membership)
    response = client.post("/api/admin/tasks", headers=headers(team["owner"]),
                           json={"title": "Nope", "assignee_user_id": target.id})
    assert response.status_code == 422
    assert db.query(models.AdminTeamTask).count() == 0


@pytest.mark.parametrize("payload", [{"title": "   "}, {"title": "x" * 201}, {"title": "ok", "status": "blocked"},
                                     {"title": "ok", "priority": "p0"}, {"title": "ok", "is_admin": True},
                                     {"title": "ok", "due_date": "1999-12-31"},
                                     {"title": "ok", "assignee_user_id": 2 ** 40}])
def test_invalid_tasks_are_rejected_without_writing(client, db, team, payload):
    response = client.post("/api/admin/tasks", headers=headers(team["owner"]), json=payload)
    assert response.status_code == 422, response.text
    assert db.query(models.AdminTeamTask).count() == 0


def test_status_changes_notes_and_history(client, db, team, emails):
    task = create(client, team["owner"], assignee_user_id=team["ana"].id)
    emails.clear()
    ana = headers(team["ana"])
    response = client.patch(f"/api/admin/tasks/{task['id']}", headers=ana,
                            json={"status": "on_hold", "note": "Waiting on the bank statement."})
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["task"]["status"] == "on_hold"
    assert detail["task"]["note_count"] == 1
    kinds = [entry["kind"] for entry in detail["timeline"]]
    assert kinds == ["note", "status", "created"]
    status_entry = detail["timeline"][1]
    assert (status_entry["from_label"], status_entry["to_label"]) == ("Pending", "On hold")
    assert status_entry["author"]["id"] == team["ana"].id and status_entry["can_delete"] is False
    # The creator hears about it; the actor does not.
    assert [mail["to_email"] for mail in emails] == ["owner@example.com"]
    assert "On hold" in emails[0]["headline"] and emails[0]["note"] == "Waiting on the bank statement."
    assert emails[0]["task_url"].endswith(f"/admin_console#task-{task['id']}")

    # A PATCH that changes nothing writes nothing and emails nobody.
    emails.clear()
    before = db.query(models.AdminTeamTaskNote).count()
    same = client.patch(f"/api/admin/tasks/{task['id']}", headers=ana, json={"status": "on_hold", "note": "  "})
    assert same.status_code == 200
    assert db.query(models.AdminTeamTaskNote).count() == before and emails == []

    cleared = client.patch(f"/api/admin/tasks/{task['id']}", headers=headers(team["owner"]),
                           json={"due_date": "2026-11-30", "priority": "urgent", "title": "  Reconcile   payouts "})
    assert cleared.status_code == 200
    assert cleared.json()["task"]["due_date"] == "2026-11-30"
    assert cleared.json()["task"]["title"] == "Reconcile payouts"
    cleared = client.patch(f"/api/admin/tasks/{task['id']}", headers=headers(team["owner"]), json={"due_date": None})
    assert cleared.json()["task"]["due_date"] is None
    for field in ("title", "status", "priority"):
        response = client.patch(f"/api/admin/tasks/{task['id']}", headers=ana, json={field: None})
        assert response.status_code == 422, field


def test_reassigning_moves_the_task_off_a_non_managers_board(client, db, team, emails):
    task = create(client, team["owner"], assignee_user_id=team["ana"].id)
    emails.clear()
    response = client.patch(f"/api/admin/tasks/{task['id']}", headers=headers(team["ana"]),
                            json={"assignee_user_id": team["ben"].id})
    assert response.status_code == 200
    assert response.json() == {"visible": False, "task": None, "timeline": []}
    assert client.get(f"/api/admin/tasks/{task['id']}", headers=headers(team["ana"])).status_code == 404
    assert client.get(f"/api/admin/tasks/{task['id']}", headers=headers(team["ben"])).status_code == 200
    recipients = {mail["to_email"]: mail["headline"] for mail in emails}
    assert recipients["ben@example.com"] == "Ana assigned you a task"
    assert "owner@example.com" in recipients and "ana@example.com" not in recipients
    timeline = client.get(f"/api/admin/tasks/{task['id']}", headers=headers(team["owner"])).json()["timeline"]
    assert (timeline[0]["kind"], timeline[0]["from_label"], timeline[0]["to_label"]) == ("assignee", "Ana", "Ben")


def test_only_the_creator_or_a_manager_can_delete(client, db, team):
    task = create(client, team["ana"], assignee_user_id=team["ben"].id)
    client.post(f"/api/admin/tasks/{task['id']}/notes", headers=headers(team["ben"]), json={"body": "On it"})
    response = client.delete(f"/api/admin/tasks/{task['id']}", headers=headers(team["ben"]))
    assert response.status_code == 403
    assert client.delete(f"/api/admin/tasks/{task['id']}", headers=headers(team["ana"])).status_code == 200
    assert db.query(models.AdminTeamTask).count() == 0
    assert db.query(models.AdminTeamTaskNote).count() == 0
    second = create(client, team["ana"], assignee_user_id=team["ben"].id)
    assert client.delete(f"/api/admin/tasks/{second['id']}", headers=headers(team["owner"])).status_code == 200


def test_notes_belong_to_their_author_and_history_cannot_be_erased(client, db, team, emails):
    task = create(client, team["owner"], assignee_user_id=team["ana"].id)
    emails.clear()
    added = client.post(f"/api/admin/tasks/{task['id']}/notes", headers=headers(team["ana"]),
                        json={"body": "Drafted the reply."})
    assert added.status_code == 201
    note = added.json()["timeline"][0]
    assert note["kind"] == "note" and note["can_delete"] is True
    assert [mail["to_email"] for mail in emails] == ["owner@example.com"]
    assert emails[0]["headline"] == "Ana added a note to a task"
    assert client.post(f"/api/admin/tasks/{task['id']}/notes", headers=headers(team["ana"]),
                       json={"body": "   "}).status_code == 422
    created = added.json()["timeline"][-1]
    assert client.delete(f"/api/admin/tasks/{task['id']}/notes/{note['id']}",
                         headers=headers(team["owner"])).status_code == 403
    assert client.delete(f"/api/admin/tasks/{task['id']}/notes/{created['id']}",
                         headers=headers(team["ana"])).status_code == 403
    removed = client.delete(f"/api/admin/tasks/{task['id']}/notes/{note['id']}", headers=headers(team["ana"]))
    assert removed.status_code == 200
    assert removed.json()["task"]["note_count"] == 0
    assert client.delete(f"/api/admin/tasks/{task['id']}/notes/{note['id']}",
                         headers=headers(team["ana"])).status_code == 404


def test_people_without_console_access_get_no_email(client, db, team, emails):
    task = create(client, team["ana"], assignee_user_id=team["ben"].id)
    db.query(models.AdminConsoleAccess).filter_by(user_id=team["ana"].id).delete()
    db.commit()
    emails.clear()
    client.patch(f"/api/admin/tasks/{task['id']}", headers=headers(team["ben"]), json={"status": "done"})
    assert emails == []
    board = client.get("/api/admin/tasks", headers=headers(team["owner"])).json()
    assert board["tasks"][0]["created_by"]["has_access"] is False


def test_self_assignment_sends_nothing(client, team, emails):
    create(client, team["ben"], assignee_user_id=team["ben"].id)
    assert emails == []


def test_summary_counts_open_and_overdue_work_assigned_to_me(client, team):
    for status in ("pending", "in_progress", "on_hold", "done", "closed"):
        create(client, team["owner"], assignee_user_id=team["ana"].id, status=status)
    create(client, team["owner"], assignee_user_id=team["ana"].id, due_date="2001-01-01")
    create(client, team["owner"], assignee_user_id=team["ben"].id)
    summary = client.get("/api/admin/tasks/summary", headers=headers(team["ana"])).json()
    assert summary == {"assigned_open": 4, "assigned_overdue": 1}


def test_closed_tasks_are_listed_newest_first_and_counted(client, team, monkeypatch):
    monkeypatch.setattr(admin_tasks, "CLOSED_LIST_LIMIT", 2)
    ids = [create(client, team["owner"], title=f"Old {index}", status="closed")["id"] for index in range(3)]
    board = client.get("/api/admin/tasks", headers=headers(team["owner"])).json()
    assert board["closed_total"] == 3
    assert [task["id"] for task in board["tasks"]] == [ids[2], ids[1]]


def test_huge_ids_are_validation_errors_not_server_errors(client, team):
    for method in ("GET", "PATCH", "DELETE"):
        assert client.request(method, f"/api/admin/tasks/{2 ** 40}", headers=headers(team["owner"]),
                              json={}).status_code == 422


def test_account_deletion_keeps_shared_tasks_and_unassigns_them(client, db, team):
    task = create(client, team["owner"], assignee_user_id=team["ana"].id)
    client.post(f"/api/admin/tasks/{task['id']}/notes", headers=headers(team["ana"]), json={"body": "Done soon"})
    ana_id = team["ana"].id
    user_deletion.purge_user_references(db, ana_id)
    db.delete(db.get(models.User, ana_id))
    db.commit()
    row = db.get(models.AdminTeamTask, task["id"])
    assert row is not None and row.assignee_user_id is None
    detail = client.get(f"/api/admin/tasks/{task['id']}", headers=headers(team["owner"])).json()
    assert detail["task"]["assignee"] is None
    assert detail["timeline"][0]["author"] is None and detail["timeline"][0]["body"] == "Done soon"
    assert db.query(models.AdminTeamTaskNote).count() == 2
    assert date.fromisoformat(detail["task"]["created_at"][:10])


def test_board_shares_names_but_not_console_members_emails(client, team):
    create(client, team["owner"], assignee_user_id=team["ana"].id)
    body = client.get("/api/admin/tasks", headers=headers(team["ana"])).text
    assert "@example.com" not in body
    detail = client.get("/api/admin/tasks/1", headers=headers(team["ana"])).text
    assert "@example.com" not in detail


def test_control_characters_are_stripped_and_unstorable_text_is_a_clean_422(client, db, team):
    # Postgres refuses NUL; a pasted log line must not become a 500.
    task = create(client, team["owner"], title="Fix\x00 the\x07 export", description="line one\r\nline\x00 two")
    assert task["title"] == "Fix the export"
    assert task["description"] == "line one\nline two"
    note = client.post(f"/api/admin/tasks/{task['id']}/notes", headers=headers(team["owner"]), json={"body": "\x00"})
    assert note.status_code == 422
    raw = '{"title": "Broken \\ud800 text"}'
    response = client.post("/api/admin/tasks", headers={**headers(team["owner"]), "Content-Type": "application/json"},
                           content=raw)
    assert response.status_code == 422, response.text
    assert db.query(models.AdminTeamTask).count() == 1


def test_assignee_marks_done_but_only_the_assigner_closes_or_reopens(client, db, team, emails):
    task = create(client, team["ana"], assignee_user_id=team["ben"].id)
    ben, ana = headers(team["ben"]), headers(team["ana"])
    path = f"/api/admin/tasks/{task['id']}"
    assert client.get(path, headers=ben).json()["task"]["can_close"] is False
    assert client.get(path, headers=ana).json()["task"]["can_close"] is True

    emails.clear()
    done = client.patch(path, headers=ben, json={"status": "done", "note": "Shipped."})
    assert done.status_code == 200 and done.json()["task"]["status"] == "done"
    assert {m["to_email"]: m["headline"] for m in emails} == {
        "ana@example.com": "Ben marked a task Done — ready for you to close"}

    events_before = db.query(models.AdminTeamTaskNote).count()
    refused = client.patch(path, headers=ben, json={"status": "closed", "note": "closing it myself"})
    assert refused.status_code == 403
    assert "Mark it Done" in refused.json()["detail"]
    assert db.get(models.AdminTeamTask, task["id"]).status == "done"
    assert db.query(models.AdminTeamTaskNote).count() == events_before, "a refused change writes nothing"

    emails.clear()
    closed = client.patch(path, headers=ana, json={"status": "closed"})
    assert closed.status_code == 200 and closed.json()["task"]["status"] == "closed"
    assert [(m["to_email"], m["headline"]) for m in emails] == [("ben@example.com", "Ana closed a task")]

    reopen = client.patch(path, headers=ben, json={"status": "in_progress"})
    assert reopen.status_code == 403 and "reopen" in reopen.json()["detail"]
    emails.clear()
    back = client.patch(path, headers=ana, json={"status": "in_progress", "note": "One more fix needed."})
    assert back.status_code == 200
    assert emails[0]["headline"] == "Ana sent a task back to In progress"
    # Short of Closed, the assignee moves freely, including back out of Done.
    for status in ("on_hold", "done", "pending"):
        assert client.patch(path, headers=ben, json={"status": status}).status_code == 200


def test_managers_and_self_assigned_owners_can_close(client, team):
    shared = create(client, team["ana"], assignee_user_id=team["ben"].id)
    assert client.patch(f"/api/admin/tasks/{shared['id']}", headers=headers(team["owner"]),
                        json={"status": "closed"}).status_code == 200
    own = create(client, team["ben"], assignee_user_id=team["ben"].id)
    assert own["can_close"] is True
    assert client.patch(f"/api/admin/tasks/{own['id']}", headers=headers(team["ben"]),
                        json={"status": "closed"}).status_code == 200


# ---- Attachments ----------------------------------------------------------------

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture
def storage(tmp_path, monkeypatch):
    """A local directory stands in for the bucket: nothing here reaches R2."""
    monkeypatch.setattr(enterprise_storage, "LOCAL_DIR", str(tmp_path))
    return tmp_path


def stored_blobs(storage):
    return sorted(path for path in storage.rglob("*") if path.is_file())


def attach(client, actor, task_id, name="screenshot.png", data=PNG, content_type="image/png"):
    return client.post(f"/api/admin/tasks/{task_id}/attachments", headers=headers(actor),
                       files={"file": (name, data, content_type)})


def test_files_follow_the_task_and_are_stored_encrypted(client, db, team, storage, emails):
    task = create(client, team["owner"], assignee_user_id=team["ana"].id)
    emails.clear()
    response = attach(client, team["ana"], task["id"])
    assert response.status_code == 201, response.text
    detail = response.json()
    [file] = detail["attachments"]
    assert file["filename"] == "screenshot.png" and file["is_image"] is True and file["ext"] == "png"
    assert file["size"] == len(PNG) and file["uploaded_by"]["id"] == team["ana"].id and file["can_delete"] is True
    assert file["url"] == f"/api/admin/tasks/{task['id']}/attachments/{file['id']}"
    assert detail["task"]["attachment_count"] == 1 and detail["task"]["note_count"] == 0
    assert (detail["timeline"][0]["kind"], detail["timeline"][0]["to_label"]) == ("attachment", "screenshot.png")
    assert emails == [], "attaching a file is recorded, not emailed"

    [blob] = stored_blobs(storage)
    assert PNG not in blob.read_bytes(), "bytes at rest are ciphertext"
    assert str(blob.relative_to(storage)).startswith(f"admin/tasks/{task['id']}/")

    download = client.get(file["url"], headers=headers(team["owner"]))
    assert download.status_code == 200 and download.content == PNG
    assert download.headers["content-type"] == "image/png"
    assert download.headers["x-content-type-options"] == "nosniff"
    assert download.headers["cache-control"] == "private, no-store"
    assert download.headers["content-disposition"].startswith('inline; filename="screenshot.png"')

    board = client.get("/api/admin/tasks", headers=headers(team["owner"])).json()
    assert board["tasks"][0]["attachment_count"] == 1
    assert board["attachment_limits"]["max_files"] == admin_task_files.MAX_FILES_PER_TASK
    assert "png" in board["attachment_limits"]["extensions"] and "svg" not in board["attachment_limits"]["extensions"]

    # Not on the task: every file route is a 404, exactly like the task itself.
    ben = headers(team["ben"])
    assert attach(client, team["ben"], task["id"]).status_code == 404
    assert client.get(file["url"], headers=ben).status_code == 404
    assert client.delete(file["url"], headers=ben).status_code == 404
    assert len(stored_blobs(storage)) == 1


def test_accounts_without_console_access_cannot_touch_files(client, db, team, storage):
    task = create(client, team["owner"], assignee_user_id=team["ana"].id)
    file = attach(client, team["owner"], task["id"]).json()["attachments"][0]
    outsider = team["outsider"]
    assert attach(client, outsider, task["id"]).status_code == 403
    assert client.get(file["url"], headers=headers(outsider)).status_code == 403
    assert client.delete(file["url"], headers=headers(outsider)).status_code == 403
    assert db.query(models.AdminTeamTaskAttachment).count() == 1


@pytest.mark.parametrize("name,data", [("payload.html", b"<script>alert(1)</script>"), ("logo.svg", b"<svg/>"),
                                       ("tool.exe", b"MZ"), ("archive.zip", b"PK"), ("noextension", b"x"),
                                       ("empty.png", b"")])
def test_unsafe_or_empty_files_are_refused_and_nothing_is_stored(client, db, team, storage, name, data):
    task = create(client, team["owner"])
    response = attach(client, team["owner"], task["id"], name=name, data=data, content_type="image/png")
    assert response.status_code == 400, response.text
    assert db.query(models.AdminTeamTaskAttachment).count() == 0
    assert db.query(models.AdminTeamTaskNote).filter_by(kind="attachment").count() == 0
    assert stored_blobs(storage) == []


def test_size_and_count_caps_are_enforced_per_task(client, db, team, storage, monkeypatch):
    task = create(client, team["owner"])
    monkeypatch.setattr(admin_task_files, "MAX_BYTES_PER_FILE", 100)
    too_big = attach(client, team["owner"], task["id"], data=b"x" * 101)
    assert too_big.status_code == 400 and "100 B" in too_big.json()["detail"]

    monkeypatch.setattr(admin_task_files, "MAX_FILES_PER_TASK", 2)
    monkeypatch.setattr(admin_task_files, "MAX_BYTES_PER_TASK", 150)
    assert attach(client, team["owner"], task["id"], name="a.png", data=b"a" * 60).status_code == 201
    over_total = attach(client, team["owner"], task["id"], name="b.png", data=b"b" * 91)
    assert over_total.status_code == 400 and "add up to" in over_total.json()["detail"]
    assert attach(client, team["owner"], task["id"], name="b.png", data=b"b" * 90).status_code == 201
    full = attach(client, team["owner"], task["id"], name="c.png", data=b"c")
    assert full.status_code == 400 and "can hold 2 files" in full.json()["detail"]
    assert db.query(models.AdminTeamTaskAttachment).count() == 2
    assert len(stored_blobs(storage)) == 2


def test_who_can_remove_a_file_and_removal_is_recorded(client, db, team, storage):
    task = create(client, team["ana"], assignee_user_id=team["ben"].id)
    mine = attach(client, team["ben"], task["id"], name="ben.png").json()["attachments"][0]
    theirs = attach(client, team["ana"], task["id"], name="ana.pdf", data=b"%PDF-1.4", content_type="application/pdf")
    theirs = theirs.json()["attachments"][1]
    ben_view = client.get(f"/api/admin/tasks/{task['id']}", headers=headers(team["ben"])).json()["attachments"]
    assert [item["can_delete"] for item in ben_view] == [True, False]

    refused = client.delete(theirs["url"], headers=headers(team["ben"]))
    assert refused.status_code == 403
    removed = client.delete(mine["url"], headers=headers(team["ben"]))
    assert removed.status_code == 200
    assert [item["filename"] for item in removed.json()["attachments"]] == ["ana.pdf"]
    entry = removed.json()["timeline"][0]
    assert (entry["kind"], entry["from_label"], entry["can_delete"]) == ("attachment_removed", "ben.png", False)
    assert client.get(mine["url"], headers=headers(team["ana"])).status_code == 404
    assert len(stored_blobs(storage)) == 1

    # The assigner (and any team manager) can tidy files they didn't add.
    again = attach(client, team["ben"], task["id"], name="again.png").json()["attachments"][-1]
    assert client.delete(again["url"], headers=headers(team["ana"])).status_code == 200
    assert client.delete(theirs["url"], headers=headers(team["owner"])).status_code == 200
    assert stored_blobs(storage) == []


def test_pdf_opens_inline_and_everything_else_downloads(client, team, storage):
    task = create(client, team["owner"])
    pdf = attach(client, team["owner"], task["id"], name="invoice.pdf", data=b"%PDF-1.4", content_type="text/html")
    sheet = attach(client, team["owner"], task["id"], name="payouts.csv", data=b"a,b\n1,2\n", content_type="text/html")
    files = sheet.json()["attachments"]
    assert pdf.status_code == 201 and [item["is_image"] for item in files] == [False, False]
    pdf_download = client.get(files[0]["url"], headers=headers(team["owner"]))
    assert pdf_download.headers["content-type"] == "application/pdf"
    assert pdf_download.headers["content-disposition"].startswith("inline;")
    csv_download = client.get(files[1]["url"], headers=headers(team["owner"]))
    # The uploader's claimed text/html never comes back; text downloads as opaque bytes.
    assert csv_download.headers["content-type"] == "application/octet-stream"
    assert csv_download.headers["content-disposition"].startswith('attachment; filename="payouts.csv"')


def test_filenames_are_cleaned_and_non_ascii_names_still_download(client, team, storage):
    task = create(client, team["owner"])
    mac = attach(client, team["owner"], task["id"], name="../../Screenshot 2026-10-24 at 2.03.12 PM.png")
    assert mac.status_code == 201
    assert mac.json()["attachments"][0]["filename"] == "Screenshot 2026-10-24 at 2.03.12 PM.png"
    japanese = attach(client, team["owner"], task["id"], name="スクリーンショット.png").json()["attachments"][1]
    download = client.get(japanese["url"], headers=headers(team["owner"]))
    assert download.status_code == 200
    disposition = download.headers["content-disposition"]
    assert 'filename="file.png"' in disposition
    assert "filename*=UTF-8''%E3%82%B9" in disposition
    long_name = "x" * 300 + ".png"
    kept = attach(client, team["owner"], task["id"], name=long_name).json()["attachments"][2]
    assert len(kept["filename"]) == admin_task_files.FILENAME_MAX and kept["filename"].endswith(".png")


def test_deleting_a_task_drops_its_files_from_storage(client, db, team, storage):
    task = create(client, team["ana"], assignee_user_id=team["ben"].id)
    attach(client, team["ana"], task["id"], name="one.png")
    attach(client, team["ben"], task["id"], name="two.png")
    assert len(stored_blobs(storage)) == 2
    assert client.delete(f"/api/admin/tasks/{task['id']}", headers=headers(team["ana"])).status_code == 200
    assert db.query(models.AdminTeamTaskAttachment).count() == 0
    assert stored_blobs(storage) == []


def test_storage_failures_are_clean_errors_that_leave_nothing_behind(client, db, team, storage, monkeypatch):
    task = create(client, team["owner"])
    file = attach(client, team["owner"], task["id"]).json()["attachments"][0]
    for blob in stored_blobs(storage):
        blob.unlink()
    gone = client.get(file["url"], headers=headers(team["owner"]))
    assert gone.status_code == 410 and "no longer in storage" in gone.json()["detail"]

    def broken(*args, **kwargs):
        raise RuntimeError("bucket unreachable")

    monkeypatch.setattr(enterprise_storage, "store_document", broken)
    failed = attach(client, team["owner"], task["id"], name="later.png")
    assert failed.status_code == 502
    assert db.query(models.AdminTeamTaskAttachment).count() == 1
    assert db.query(models.AdminTeamTaskNote).filter_by(kind="attachment").count() == 1

    monkeypatch.setattr(enterprise_storage, "LOCAL_DIR", "")
    monkeypatch.setattr(enterprise_storage, "R2_ACCESS_KEY_ID", "")
    assert attach(client, team["owner"], task["id"]).status_code == 503


def test_account_deletion_keeps_the_files_on_the_task(client, db, team, storage):
    task = create(client, team["owner"], assignee_user_id=team["ana"].id)
    attach(client, team["ana"], task["id"])
    ana_id = team["ana"].id
    user_deletion.purge_user_references(db, ana_id)
    db.delete(db.get(models.User, ana_id))
    db.commit()
    [file] = client.get(f"/api/admin/tasks/{task['id']}", headers=headers(team["owner"])).json()["attachments"]
    assert file["uploaded_by"] is None
    assert client.get(file["url"], headers=headers(team["owner"])).content == PNG


def test_uploads_have_their_own_hourly_ceiling(client, team, storage, monkeypatch):
    task = create(client, team["owner"])
    scopes = []

    def limiter(**kwargs):
        scopes.append((kwargs["scope"], kwargs["limit"], kwargs["window_seconds"]))

    monkeypatch.setattr(admin_router, "_enforce_rate_limit_or_429", limiter)
    attach(client, team["owner"], task["id"])
    assert ("admin.tasks.upload", admin_tasks.UPLOAD_RATE_LIMIT, 3600) in scopes
    assert ("admin.tasks.write", admin_tasks.WRITE_RATE_LIMIT, admin_tasks.RATE_WINDOW_SECONDS) in scopes
