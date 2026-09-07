"""Empty catalog/results never consume a student's run or a consultancy's credits."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app import course_catalog
from app.routers import courses, enterprise


@pytest.fixture
def endpoint(monkeypatch, request):
    surface = request.param
    db = Mock(spec=["add", "commit", "refresh", "rollback", "flush"])
    user = SimpleNamespace(id=81, full_name="Offline fixture", email="fixture@example.invalid",
                           destination_country_code="AU")
    subscription = SimpleNamespace(course_finder_runs_used=3)
    query = Mock(return_value=([], 0))
    available = Mock(return_value=True)
    generate = Mock(return_value={"available": True, "recommendations": [], "no_matches": True})
    reserve, refund, enforce, debit = (Mock() for _ in range(4))
    monkeypatch.setattr(course_catalog, "query_catalog", query)
    monkeypatch.setattr(course_catalog, "ai_available", available)
    monkeypatch.setattr(course_catalog, "recommend_courses", generate)

    if surface == "b2c":
        def reserve_run(*args):
            subscription.course_finder_runs_used += 1
            return True
        def refund_run(*args):
            subscription.course_finder_runs_used -= 1
        reserve.side_effect = reserve_run
        refund.side_effect = refund_run
        monkeypatch.setattr(courses, "_rate_limit_or_429", Mock())
        monkeypatch.setattr(courses, "get_or_create_user_subscription", lambda *args: subscription)
        monkeypatch.setattr(courses, "_student_profile_block", lambda *args: "Offline profile")
        monkeypatch.setattr(courses, "_student_history_block", lambda *args: "")
        monkeypatch.setattr(courses.visa_pass, "reserve_feature_or_402", reserve)
        monkeypatch.setattr(courses.visa_pass, "refund_feature", refund)
        monkeypatch.setattr(courses.visa_pass, "feature_entitlement",
                            lambda *args: {"used": subscription.course_finder_runs_used, "remaining": 0})
        handler, payload_type = courses.courses_recommend, courses.CourseRecommendRequest
        extra = {}
    else:
        organization = SimpleNamespace(id=92)
        role = SimpleNamespace(ctx=object())
        client = SimpleNamespace(id=17, full_name="Offline client", destination_country_code="AU")
        monkeypatch.setattr(enterprise, "_require_enterprise_membership", lambda **kwargs: (None, organization, role))
        monkeypatch.setattr(enterprise, "_get_org_client_or_404", lambda *args, **kwargs: client)
        monkeypatch.setattr(enterprise, "_enforce_rate_limit_or_429", Mock())
        monkeypatch.setattr(enterprise, "_enterprise_permissions_for_role", lambda *args: {"coursefinder": True})
        monkeypatch.setattr(enterprise.credits, "enforce_action_or_402", enforce)
        monkeypatch.setattr(enterprise.credits, "charge_action", debit)
        handler, payload_type = enterprise.enterprise_course_finder_recommend, enterprise.EnterpriseCourseFinderRecommend
        extra = {"client_id": client.id}

    def call(**overrides):
        values = {"country_code": "AU", "discipline": "Computer Science & IT", **extra, **overrides}
        return handler(payload_type(**values), request=Mock(), db=db, current_user=user)

    return SimpleNamespace(surface=surface, db=db, subscription=subscription, query=query,
                           available=available, generate=generate, reserve=reserve, refund=refund,
                           enforce=enforce, debit=debit, call=call)


def assert_no_saved_shortlist(endpoint):
    endpoint.db.add.assert_not_called()
    endpoint.db.commit.assert_not_called()
    endpoint.db.flush.assert_not_called()
    endpoint.debit.assert_not_called()


@pytest.mark.parametrize("endpoint", ["b2c", "b2b"], indirect=True)
@pytest.mark.parametrize("empty_rows", [[], [(SimpleNamespace(id=1), [])]])
def test_empty_catalog_returns_no_matches_before_ai_availability_and_quota(endpoint, empty_rows):
    endpoint.query.return_value = (empty_rows, len(empty_rows))
    endpoint.available.return_value = False
    endpoint.reserve.side_effect = HTTPException(status_code=402, detail="No runs remain")
    endpoint.enforce.side_effect = HTTPException(status_code=402, detail="No credits remain")
    result = endpoint.call()
    assert result["rec"] is None and result["no_matches"] is True
    assert result["message"]
    if endpoint.surface == "b2b":
        assert result["credits_charged"] == 0
    else:
        assert result["entitlement"]["used"] == 3
    endpoint.available.assert_not_called()
    endpoint.reserve.assert_not_called()
    endpoint.refund.assert_not_called()
    endpoint.enforce.assert_not_called()
    endpoint.generate.assert_not_called()
    assert_no_saved_shortlist(endpoint)


@pytest.mark.parametrize("endpoint", ["b2c", "b2b"], indirect=True)
def test_empty_specific_search_and_widened_catalog_both_return_no_matches_without_spending(endpoint):
    result = endpoint.call(field_of_study="Robotics")
    assert result["rec"] is None and result["no_matches"] is True
    assert endpoint.query.call_count == 2
    assert endpoint.query.call_args_list[0].kwargs["q"] == "Robotics"
    assert "q" not in endpoint.query.call_args_list[1].kwargs
    endpoint.generate.assert_not_called()
    endpoint.reserve.assert_not_called()
    endpoint.enforce.assert_not_called()
    assert_no_saved_shortlist(endpoint)


@pytest.mark.parametrize("endpoint", ["b2c", "b2b"], indirect=True)
@pytest.mark.parametrize("explanation_field", ["message", "summary"])
def test_model_no_matches_refunds_b2c_reservation_and_never_debits_b2b(endpoint, explanation_field):
    endpoint.query.return_value = ([(SimpleNamespace(id=1), [SimpleNamespace(id=2)])], 1)
    endpoint.generate.return_value = {"available": True, "recommendations": [], "no_matches": True,
                                      explanation_field: "No saved courses fit these preferences."}
    result = endpoint.call()
    assert result["rec"] is None and result["no_matches"] is True
    suffix = "No run was used." if endpoint.surface == "b2c" else "No credits were used."
    assert result["message"] == f"No saved courses fit these preferences. {suffix}"
    endpoint.generate.assert_called_once()
    if endpoint.surface == "b2c":
        endpoint.reserve.assert_called_once()
        endpoint.refund.assert_called_once()
        assert endpoint.subscription.course_finder_runs_used == 3
        assert result["entitlement"]["used"] == 3
    else:
        endpoint.enforce.assert_called_once()
        assert result["credits_charged"] == 0
    assert_no_saved_shortlist(endpoint)


@pytest.mark.parametrize("endpoint", ["b2c"], indirect=True)
def test_model_no_matches_does_not_refund_when_reservation_enforcement_is_off(endpoint):
    endpoint.query.return_value = ([(SimpleNamespace(id=1), [SimpleNamespace(id=2)])], 1)
    endpoint.reserve.side_effect = None
    endpoint.reserve.return_value = False
    result = endpoint.call()
    assert result["no_matches"] is True
    endpoint.reserve.assert_called_once()
    endpoint.refund.assert_not_called()
    assert endpoint.subscription.course_finder_runs_used == 3
    assert_no_saved_shortlist(endpoint)


@pytest.mark.parametrize("endpoint", ["b2c", "b2b"], indirect=True)
@pytest.mark.parametrize("invalid", [{"discipline": "Unknown subject"}, {"budget": "invalid budget"}])
def test_empty_catalog_does_not_hide_invalid_requests(endpoint, invalid):
    with pytest.raises(HTTPException) as error:
        endpoint.call(**invalid)
    assert error.value.status_code == 400
    endpoint.query.assert_not_called()
    endpoint.generate.assert_not_called()
    endpoint.reserve.assert_not_called()
    endpoint.enforce.assert_not_called()
    assert_no_saved_shortlist(endpoint)


@pytest.mark.parametrize("endpoint", ["b2c", "b2b"], indirect=True)
def test_nonempty_catalog_still_requires_available_ai_before_reserving_or_debiting(endpoint):
    endpoint.query.return_value = ([(SimpleNamespace(id=1), [SimpleNamespace(id=2)])], 1)
    endpoint.available.return_value = False
    with pytest.raises(HTTPException) as error:
        endpoint.call()
    assert error.value.status_code == 503
    endpoint.generate.assert_not_called()
    endpoint.reserve.assert_not_called()
    endpoint.enforce.assert_not_called()
    assert_no_saved_shortlist(endpoint)


@pytest.mark.parametrize("endpoint", ["b2c", "b2b"], indirect=True)
@pytest.mark.parametrize("model_result,expected_status", [
    ({"available": False, "recommendations": [], "message": "AI unavailable"}, 503),
    ({"available": True, "recommendations": []}, 502),
])
def test_ai_failures_remain_errors_and_return_b2c_reservation_without_b2b_debit(endpoint, model_result, expected_status):
    endpoint.query.return_value = ([(SimpleNamespace(id=1), [SimpleNamespace(id=2)])], 1)
    endpoint.generate.return_value = model_result
    with pytest.raises(HTTPException) as error:
        endpoint.call()
    assert error.value.status_code == expected_status
    if endpoint.surface == "b2c":
        endpoint.reserve.assert_called_once()
        endpoint.refund.assert_called_once()
        assert endpoint.subscription.course_finder_runs_used == 3
        endpoint.db.rollback.assert_called_once()
    else:
        endpoint.enforce.assert_called_once()
    assert_no_saved_shortlist(endpoint)


@pytest.mark.parametrize("endpoint", ["b2c", "b2b"], indirect=True)
def test_nonempty_catalog_still_blocks_ai_when_quota_or_wallet_is_exhausted(endpoint):
    endpoint.query.return_value = ([(SimpleNamespace(id=1), [SimpleNamespace(id=2)])], 1)
    endpoint.reserve.side_effect = HTTPException(status_code=402, detail="No runs remain")
    endpoint.enforce.side_effect = HTTPException(status_code=402, detail="No credits remain")
    with pytest.raises(HTTPException) as error:
        endpoint.call()
    assert error.value.status_code == 402
    endpoint.generate.assert_not_called()
    endpoint.refund.assert_not_called()
    assert_no_saved_shortlist(endpoint)
