"""Public editorial news must not resolve to the retired dashboard news feed."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def main_app():
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("R2_PUBLIC_URL", "https://cdn.example.test")
        from app import main
    return main


@pytest.fixture
def client(main_app):
    # Static routes do not need schema migrations, seeders or scheduled jobs.
    return TestClient(main_app.app)


@pytest.mark.parametrize("path,canonical,headline", [
    ("/news", "/news", "News for International Students"),
    ("/news/", "/news", "News for International Students"),
    ("/news/us-opt-fee-proposal-2026", "/news/us-opt-fee-proposal-2026",
     "Proposed U.S. OPT fees could total $100,000"),
    ("/news/us-opt-fee-proposal-2026/", "/news/us-opt-fee-proposal-2026",
     "Proposed U.S. OPT fees could total $100,000"),
    ("/news/uk-graduate-visa-18-months-2027", "/news/uk-graduate-visa-18-months-2027",
     "UK Graduate visa drops to 18 months"),
    ("/news/uk-graduate-visa-18-months-2027/", "/news/uk-graduate-visa-18-months-2027",
     "UK Graduate visa drops to 18 months"),
])
def test_news_is_public_indexable_html_with_its_own_canonical(client, path, canonical, headline):
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert f'<link rel="canonical" href="https://rilono.com{canonical}">' in response.text
    assert "noindex" not in response.text
    assert headline in response.text
    assert "<!--@partial:" not in response.text
    assert 'src="/static/app.js' not in response.text


@pytest.mark.parametrize("path", ["/news/missing-story", "/news/missing-story/"])
def test_unknown_news_article_returns_a_real_404(client, path):
    response = client.get(path)
    assert response.status_code == 404


@pytest.mark.parametrize("path", [
    "/news", "/news/us-opt-fee-proposal-2026", "/news/uk-graduate-visa-18-months-2027"
])
def test_missing_news_document_returns_404(client, main_app, monkeypatch, path):
    monkeypatch.setattr(main_app, "_read_static_html", lambda name: None)
    assert client.get(path).status_code == 404


def test_news_no_longer_inherits_dashboard_metadata(main_app):
    assert "/news" not in main_app._SPA_ROUTE_META
