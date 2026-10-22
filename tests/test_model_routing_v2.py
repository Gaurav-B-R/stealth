"""Model routing after the Gemini 2.5 retirement (Vertex, 2026-10-20) + the B2B pricing v2.

What these pin, and why each matters:

1. No DEFAULT candidate chain under app/ names a Gemini 2.5 or 2.0 id. The assistant led with
   gemini-2.5-flash, so after the retirement every turn fell through to 3.1 Pro (~6x the
   token price) while the org's meter kept charging flash-sized messages.
2. The cheap chain is defined once and is the default for the assistant, Deep Scan and
   enterprise upload reading; env overrides still win.
3. Both cost catalogs price the new models (and their -preview ids) — an unpriced model is
   recorded as $0 and silently inflates the margin report.
4. Enterprise upload reading counts pages and reads PDFs in 15-page blocks with a capped
   output, so the per-block price matches what was actually requested; B2C extraction is
   untouched.
5. The assistant's tool loop honours a per-turn cost budget exactly like its round cap.
6. A mock interview stops at MAX_INTERVIEW_QUESTIONS officer questions, counted server-side.

Run: python3 -m pytest tests/test_model_routing_v2.py
"""

import ast
import importlib.util
import io
import json
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from google.auth.credentials import AnonymousCredentials
from pypdf import PdfReader, PdfWriter

from app import ai_cost_calculation, ai_usage, enterprise_ai, enterprise_interview, growth_agent, models
from app.utils import gemini_service

APP_DIR = Path(__file__).parents[1] / "app"
SPEC_CHEAP_CHAIN = ["gemini-3.1-flash-lite", "gemini-3.5-flash", "gemini-3.1-pro-preview"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_pdf(pages: int) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def make_png() -> bytes:
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buffer, format="PNG")
    return buffer.getvalue()


def load_vertex_service(monkeypatch):
    """An isolated gemini_service in Cloud mode with fake credentials (no network)."""
    monkeypatch.setenv("GEMINI_PROVIDER", "vertex")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "credited-project")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "global")
    monkeypatch.setenv("GEMINI_VERTEX_CREDENTIALS", "/nonexistent/dedicated-gemini.json")
    from google.oauth2 import service_account
    monkeypatch.setattr(service_account.Credentials, "from_service_account_file",
                        Mock(return_value=AnonymousCredentials()))
    spec = importlib.util.spec_from_file_location(
        "isolated_gemini_service_v2", APP_DIR / "utils/gemini_service.py",
    )
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)
    assert service.is_ai_configured()
    return service


def scripted_generate(texts):
    """A stand-in for _generate_content_with_fallback that records every call."""
    calls = []
    queue = list(texts)

    def _generate(model_names, content, usage_source="document_ai", **kwargs):
        calls.append({"models": list(model_names), "content": content,
                      "usage_source": usage_source, **kwargs})
        item = queue.pop(0) if queue else "text"
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(text=item)

    return _generate, calls


def pdf_pages_of(part) -> int:
    return len(PdfReader(io.BytesIO(part.inline_data.data)).pages)


# ---------------------------------------------------------------------------
# 1-2. Default chains
# ---------------------------------------------------------------------------

def _string_lists_bound_as_model_defaults(tree):
    """Every list literal of strings that is a `defaults=` argument or is assigned to a name
    ending in _MODELS / _MODEL_CANDIDATES — i.e. a default candidate chain."""
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "defaults" and isinstance(node.value, ast.List):
            yield node.value
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.List):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.upper().endswith(("_MODELS", "_MODEL_CANDIDATES")):
                    yield node.value


def test_no_default_chain_anywhere_in_app_names_a_retired_model():
    # Every default chain under app/ — routers included, now that the B2C interview chain in
    # app/routers/ai_chat.py starts on a live model — is guarded here so a retired id can
    # never creep back into a chain.
    offenders = []
    scanned_routers = False
    for path in sorted(APP_DIR.rglob("*.py")):
        relative = path.relative_to(APP_DIR.parent).as_posix()
        scanned_routers = scanned_routers or relative.startswith("app/routers/")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for chain in _string_lists_bound_as_model_defaults(tree):
            for element in chain.elts:
                if isinstance(element, ast.Constant) and isinstance(element.value, str):
                    if element.value.startswith(("gemini-2.5", "gemini-2.0", "gemini-1.5")):
                        offenders.append(f"{relative}:{element.lineno} {element.value}")
    assert scanned_routers  # the scan must actually cover app/routers/
    assert not offenders, offenders


def test_cheap_chain_is_the_spec_chain_and_app_default_has_no_retired_ids(monkeypatch):
    assert gemini_service.CHEAP_MODEL_CANDIDATES == SPEC_CHEAP_CHAIN
    for chain in (gemini_service.DEFAULT_GEMINI_MODEL_CANDIDATES, gemini_service.CHEAP_MODEL_CANDIDATES):
        assert not [m for m in chain if m.startswith(("gemini-2.", "gemini-1."))]
    # The app-wide chain: GEMINI_MODEL (or 3.1 Pro preview), then Pro, 3.5 Flash, 3.1 Flash-Lite.
    assert gemini_service.DEFAULT_GEMINI_MODEL_CANDIDATES[1:] == [
        "gemini-3.1-pro-preview", "gemini-3.5-flash", "gemini-3.1-flash-lite",
    ]
    monkeypatch.delenv("GEMINI_DOCUMENT_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_DOCUMENT_MODEL_CANDIDATES", raising=False)
    chain = gemini_service.get_model_candidates("GEMINI_DOCUMENT_MODEL", "GEMINI_DOCUMENT_MODEL_CANDIDATES")
    assert chain == gemini_service._dedupe_model_names(gemini_service.DEFAULT_GEMINI_MODEL_CANDIDATES)


def test_assistant_and_deep_scan_default_to_the_cheap_chain(monkeypatch):
    monkeypatch.delenv("ENTERPRISE_AI_MODEL", raising=False)
    monkeypatch.delenv("ENTERPRISE_AI_MODEL_CANDIDATES", raising=False)
    assert enterprise_ai._DEFAULT_ASSISTANT_MODELS == SPEC_CHEAP_CHAIN
    assert enterprise_ai._enterprise_model_candidates() == SPEC_CHEAP_CHAIN

    tried = []

    class FakeModel:
        def __init__(self, name, **kwargs):
            self.name = name

        def generate_content(self, prompt):
            tried.append(self.name)
            if self.name == "gemini-3.1-flash-lite":
                raise RuntimeError("simulated outage")
            return SimpleNamespace(text="{}")

    monkeypatch.setattr(enterprise_ai.gemini_utils, "genai", SimpleNamespace(GenerativeModel=FakeModel))
    monkeypatch.setattr(enterprise_ai.ai_usage, "record_gemini_usage", lambda *a, **k: None)
    state = {}
    enterprise_ai._deep_scan_generate("system", "prompt", "deep_scan", state)
    assert tried == ["gemini-3.1-flash-lite", "gemini-3.5-flash"]
    assert state["ok"] == "gemini-3.5-flash"


def test_env_override_still_wins_for_assistant_and_reading(monkeypatch):
    monkeypatch.setenv("ENTERPRISE_AI_MODEL", "gemini-3.1-pro-preview")
    assert enterprise_ai._enterprise_model_candidates()[0] == "gemini-3.1-pro-preview"
    monkeypatch.setenv("ENTERPRISE_READ_MODEL", "custom-reader")
    monkeypatch.setenv("ENTERPRISE_READ_MODEL_CANDIDATES", "custom-b, gemini-3.5-flash")
    assert gemini_service.enterprise_read_model_candidates() == [
        "custom-reader", "custom-b", "gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3.1-pro-preview",
    ]
    monkeypatch.delenv("ENTERPRISE_READ_MODEL")
    monkeypatch.delenv("ENTERPRISE_READ_MODEL_CANDIDATES")
    assert gemini_service.enterprise_read_model_candidates() == SPEC_CHEAP_CHAIN


def test_growth_agent_chain_has_no_retired_ids(monkeypatch):
    monkeypatch.delenv("ADMIN_GROWTH_AGENT_MODEL", raising=False)
    monkeypatch.delenv("ADMIN_GROWTH_AGENT_MODEL_CANDIDATES", raising=False)
    chain = growth_agent._model_candidates()
    assert chain and not [m for m in chain if "gemini-2." in m]
    assert "gemini-3.5-flash" in chain


def test_deep_scan_document_cap_defaults_to_20():
    import os
    if os.getenv("DEEP_SCAN_MAX_DOCUMENTS"):
        pytest.skip("DEEP_SCAN_MAX_DOCUMENTS overridden in this environment")
    assert enterprise_ai.DEEP_SCAN_MAX_DOCUMENTS == 20


def test_deep_scan_over_the_cap_audits_the_newest_documents(monkeypatch):
    monkeypatch.setattr(enterprise_ai, "DEEP_SCAN_MAX_DOCUMENTS", 3)
    monkeypatch.setattr(enterprise_ai, "is_ai_configured", lambda: True)
    reduce_prompts = []

    def fake_generate(system, prompt, usage_source, model_state):
        if usage_source == "deep_scan_extract":
            return SimpleNamespace(text=json.dumps({"document_type": "doc"}))
        reduce_prompts.append(prompt)
        return SimpleNamespace(text=json.dumps({"risk_level": "low", "summary": "ok", "findings": []}))

    monkeypatch.setattr(enterprise_ai, "_deep_scan_generate", fake_generate)
    # Oldest-first, exactly as the router passes them.
    docs = [SimpleNamespace(id=i, document_type=f"Doc{i}", original_filename=f"doc{i}.pdf",
                            extracted_text=f"text {i}", created_at=None, validation_status=None)
            for i in range(1, 6)]
    client = models.EnterpriseClient(full_name="Asha Rao", destination_country_code="GB",
                                     destination_country_name="United Kingdom", visa_type="Student")
    result = enterprise_ai.run_deep_scan_audit(client=client, organization=SimpleNamespace(id=1),
                                               documents=docs)
    assert result["stats"]["documents_analyzed"] == 3
    assert result["stats"]["documents_over_cap"] == 2
    audited = reduce_prompts[0]
    assert "doc3.pdf" in audited and "doc4.pdf" in audited and "doc5.pdf" in audited
    assert "doc1.pdf" not in audited and "doc2.pdf" not in audited
    # Kept in upload order.
    assert audited.index("doc3.pdf") < audited.index("doc4.pdf") < audited.index("doc5.pdf")


# ---------------------------------------------------------------------------
# 3. Cost catalogs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("model,rates", [
    ("gemini-3.1-flash-lite", (0.25, 1.50)),
    ("gemini-3.1-flash-lite-preview", (0.25, 1.50)),
    ("gemini-3.5-flash", (1.50, 9.00)),
    ("gemini-3.5-flash-preview", (1.50, 9.00)),
    ("gemini-3.5-flash-lite", (0.30, 2.50)),
    ("gemini-3.5-flash-lite-preview", (0.30, 2.50)),
    ("publishers/google/models/gemini-3.5-flash-lite", (0.30, 2.50)),
])
def test_ledger_estimate_prices_the_new_models_and_preview_ids(model, rates):
    assert ai_usage._rates_for(model) == rates
    # 1M input + 1M output, no cache: exactly the two list rates added together.
    assert ai_usage.estimate_cost(model, 1_000_000, 1_000_000) == Decimal(str(rates[0] + rates[1])).quantize(Decimal("0.000001"))


def test_ledger_still_prices_retired_models_for_history():
    assert ai_usage._rates_for("gemini-2.5-flash") == (0.30, 2.50)
    assert ai_usage._rates_for("gemini-2.5-pro") == (1.25, 10.00)


def calc_event(model, prompt=1000, candidate=100, thinking=0, cached=0, *, details=None, location="global",
               provider="vertex", **kwargs):
    total = prompt + candidate + thinking
    raw = {"promptTokenCount": prompt, "candidatesTokenCount": candidate, "thoughtsTokenCount": thinking,
           "cachedContentTokenCount": cached, "totalTokenCount": total,
           "_rilono_pricing": {"service_tier": "standard", "location": location}}
    if details is not None:
        raw["promptTokensDetails"] = details
    row = dict(model=model, prompt_tokens=prompt, candidate_tokens=candidate, thought_tokens=thinking,
               output_tokens=candidate + thinking, cached_tokens=cached, total_tokens=total,
               unit_type="tokens", metering_version=2, usage_state="measured", provider=provider,
               search_queries=0, tool_tokens=0, created_at="2026-10-21T12:00:00+00:00",
               raw_usage_json=json.dumps(raw))
    row.update(kwargs)
    return row


@pytest.mark.parametrize("model,expected", [
    # 1,000 in at $0.25/M + 100 out at $1.50/M
    ("gemini-3.1-flash-lite", "0.0004"),
    ("gemini-3.1-flash-lite-preview", "0.0004"),
    # 1,000 in at $1.50/M + 100 out at $9.00/M
    ("gemini-3.5-flash", "0.0024"),
    ("gemini-3.5-flash-preview", "0.0024"),
    # 1,000 in at $0.30/M + 100 out at $2.50/M
    ("gemini-3.5-flash-lite", "0.00055"),
    ("projects/p/locations/global/publishers/google/models/gemini-3.5-flash-lite", "0.00055"),
])
def test_exact_catalog_values_new_models_but_flags_them_unreconciled(model, expected):
    result = ai_cost_calculation.calculate_event(
        calc_event(model, details=[{"modality": "TEXT", "tokenCount": 1000}]))
    assert result["available"] is True
    assert Decimal(result["calculated_cost_usd"]) == Decimal(expected)
    # Public-price-list rates are never presented as a verified, complete calculation.
    assert result["calculation_status"] == "partial"
    assert "rate_from_public_price_list_not_invoice_reconciled" in result["coverage_reasons"]


def test_new_flash_models_bill_cache_at_ten_percent():
    result = ai_cost_calculation.calculate_event(
        calc_event("gemini-3.5-flash", prompt=1_000_000, candidate=0, cached=1_000_000,
                   details=[{"modality": "TEXT", "tokenCount": 1_000_000}]))
    assert Decimal(result["calculated_cost_usd"]) == Decimal("0.15")


def test_new_flash_models_never_value_audio_input_at_the_text_rate():
    audio = calc_event("gemini-3.1-flash-lite", details=[{"modality": "TEXT", "tokenCount": 600},
                                                        {"modality": "AUDIO", "tokenCount": 400}])
    result = ai_cost_calculation.calculate_event(audio)
    assert result["available"] is False and result["unavailable_reason"] == "audio_rate_not_verified"
    # No modality evidence at all: valued as text, and says so.
    bare = ai_cost_calculation.calculate_event(calc_event("gemini-3.1-flash-lite"))
    assert bare["available"] is True
    assert "input_modality_not_recorded_text_rates_used" in bare["coverage_reasons"]


def test_new_models_regional_vertex_rate_is_not_assumed():
    result = ai_cost_calculation.calculate_event(
        calc_event("gemini-3.5-flash", location="us-central1", details=[{"modality": "TEXT", "tokenCount": 1000}]))
    assert result["unavailable_reason"] == "region_rate_not_verified"
    # 3.1 Pro preview keeps its existing rule.
    pro = ai_cost_calculation.calculate_event(
        calc_event("gemini-3.1-pro-preview", location="europe-west4", details=[{"modality": "TEXT", "tokenCount": 1000}]))
    assert pro["unavailable_reason"] == "region_rate_not_verified"


@pytest.mark.parametrize("model", ["gemini-3.5-flash-tts", "gemini-3.1-flash-lite-preview-09-2026", "gemini-3.5"])
def test_exact_catalog_still_never_substring_matches(model):
    result = ai_cost_calculation.calculate_event(calc_event(model))
    assert result["unavailable_reason"] == "model_rate_not_verified"


def test_enterprise_read_source_has_a_report_label():
    assert gemini_service.ENTERPRISE_READ_USAGE_SOURCE in ai_usage.SOURCE_LABELS


# ---------------------------------------------------------------------------
# 4. Page counting / block reading
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pages,blocks", [(0, 1), (1, 1), (15, 1), (16, 2), (30, 2), (31, 3), (47, 4), (150, 10)])
def test_read_blocks_for_is_ceil_pages_over_15_with_a_floor_of_one(pages, blocks):
    assert gemini_service.read_blocks_for(pages) == blocks


def test_read_blocks_for_tolerates_garbage_and_applies_cap():
    assert gemini_service.read_blocks_for(None) == 1
    assert gemini_service.read_blocks_for("many") == 1
    assert gemini_service.read_blocks_for(-5) == 1
    assert gemini_service.read_blocks_for(400, max_blocks=10) == 10
    assert gemini_service.read_blocks_for(400, max_blocks=0) == 27  # 0/invalid cap = no cap
    assert gemini_service.read_blocks_for(20, max_blocks=10) == 2


def test_count_document_pages_counts_pdfs_and_floors_everything_else():
    pdf47 = make_pdf(47)
    assert gemini_service.count_document_pages(pdf47, "statement.pdf", "application/pdf") == 47
    # Detected by mime type or by content even without a .pdf name.
    assert gemini_service.count_document_pages(pdf47, "upload", "application/pdf") == 47
    assert gemini_service.count_document_pages(pdf47, "upload.bin", "") == 47
    assert gemini_service.count_document_pages(make_png(), "scan.png", "image/png") == 1
    assert gemini_service.count_document_pages(b"plain text", "notes.txt", "text/plain") == 1


@pytest.mark.parametrize("contents", [b"", None, b"%PDF-1.7 truncated", b"\x00\x01garbage"])
def test_count_document_pages_never_raises_and_returns_at_least_one(contents):
    assert gemini_service.count_document_pages(contents, "broken.pdf", "application/pdf") == 1


def test_count_document_pages_falls_back_to_raw_page_objects_without_pypdf(monkeypatch):
    monkeypatch.setitem(sys.modules, "pypdf", None)  # import pypdf -> ImportError
    assert gemini_service.count_document_pages(make_pdf(20), "a.pdf", "application/pdf") == 20
    # The reader would read such a file in ONE request, so it is one read.
    assert gemini_service.enterprise_read_units(make_pdf(20), "a.pdf", "application/pdf") == 1


def test_enterprise_read_units_mirror_what_the_reader_requests(monkeypatch):
    pdf47 = make_pdf(47)
    assert gemini_service.enterprise_read_units(pdf47, "a.pdf", "application/pdf") == 4
    assert gemini_service.enterprise_read_units(pdf47, "a.pdf", "application/pdf", max_blocks=2) == 2
    assert gemini_service.enterprise_read_units(make_png(), "a.png", "image/png") == 1
    assert gemini_service.enterprise_read_units(b"x" * 10, "a.txt", "text/plain") == 1
    monkeypatch.setattr(gemini_service, "ENTERPRISE_READ_MAX_BLOCKS", 3)
    # A caller can never ask past the env ceiling.
    assert gemini_service.enterprise_read_units(make_pdf(200), "a.pdf", "", max_blocks=50) == 3


def test_read_env_defaults():
    assert gemini_service.READ_BLOCK_PAGES == 15
    import os
    if not os.getenv("ENTERPRISE_READ_MAX_BLOCKS"):
        assert gemini_service.ENTERPRISE_READ_MAX_BLOCKS == 10
    if not os.getenv("ENTERPRISE_READ_MAX_OUTPUT_TOKENS"):
        assert gemini_service.ENTERPRISE_READ_MAX_OUTPUT_TOKENS == 2048


def test_b2c_extraction_path_is_unchanged(monkeypatch):
    service = load_vertex_service(monkeypatch)
    monkeypatch.delenv("GEMINI_DOCUMENT_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_DOCUMENT_MODEL_CANDIDATES", raising=False)
    generate = Mock(return_value=SimpleNamespace(text="whole file"))
    monkeypatch.setattr(service, "_generate_content_with_fallback", generate)
    pdf47 = make_pdf(47)
    assert service.extract_text_from_document(pdf47, "statement.pdf", "application/pdf") == "whole file"
    # One request, the whole file, the document chain, no output cap, the shared source.
    assert generate.call_count == 1
    models_used, content = generate.call_args.args[:2]
    assert models_used == service._dedupe_model_names(service.DEFAULT_GEMINI_MODEL_CANDIDATES)
    assert content[1].inline_data.data == pdf47
    assert "generation_config" not in generate.call_args.kwargs
    assert "usage_source" not in generate.call_args.kwargs and len(generate.call_args.args) == 2


def test_enterprise_reading_splits_long_pdfs_into_capped_15_page_blocks(monkeypatch):
    service = load_vertex_service(monkeypatch)
    for key in ("ENTERPRISE_READ_MODEL", "ENTERPRISE_READ_MODEL_CANDIDATES"):
        monkeypatch.delenv(key, raising=False)
    generate, calls = scripted_generate(["block one", "block two", "block three", "block four"])
    monkeypatch.setattr(service, "_generate_content_with_fallback", generate)

    text = service.extract_text_from_document(make_pdf(47), "statement.pdf", "application/pdf",
                                              model_candidates=service.enterprise_read_model_candidates())
    assert len(calls) == 4
    assert [pdf_pages_of(call["content"][1]) for call in calls] == [15, 15, 15, 2]
    for call in calls:
        assert call["models"] == SPEC_CHEAP_CHAIN
        assert call["generation_config"] == {"max_output_tokens": service.ENTERPRISE_READ_MAX_OUTPUT_TOKENS}
        assert call["usage_source"] == service.ENTERPRISE_READ_USAGE_SOURCE
    assert "pages 16–30 of a 47-page document" in calls[1]["content"][0]
    assert text.index("[Pages 1–15 of 47]\nblock one") < text.index("[Pages 46–47 of 47]\nblock four")
    assert "were not read" not in text


def test_enterprise_reading_stops_at_the_block_cap_and_says_so(monkeypatch):
    service = load_vertex_service(monkeypatch)
    generate, calls = scripted_generate(["one", "two"])
    monkeypatch.setattr(service, "_generate_content_with_fallback", generate)
    text = service.extract_text_from_document(make_pdf(47), "s.pdf", "application/pdf", max_blocks=2)
    assert len(calls) == 2
    # max_blocks alone selects enterprise reading, on the enterprise chain.
    assert calls[0]["models"] == service.enterprise_read_model_candidates()
    assert "[Pages 31–47 were not read: reading stops after 30 pages per document.]" in text


def test_enterprise_reading_marks_a_failed_block_and_abandons_on_a_dead_first_block(monkeypatch):
    service = load_vertex_service(monkeypatch)
    generate, calls = scripted_generate(["one", RuntimeError("all candidates failed"), "three"])
    monkeypatch.setattr(service, "_generate_content_with_fallback", generate)
    text = service.extract_text_from_document(make_pdf(40), "s.pdf", "", max_blocks=10)
    assert "[Pages 16–30 of 40: could not be read]" in text and "[Pages 31–40 of 40]\nthree" in text

    generate, calls = scripted_generate([RuntimeError("outage"), "never"])
    monkeypatch.setattr(service, "_generate_content_with_fallback", generate)
    assert service.extract_text_from_document(make_pdf(40), "s.pdf", "", max_blocks=10) is None
    assert len(calls) == 1  # the remaining blocks are not tried against a dead chain


def test_enterprise_reading_small_pdf_and_no_pypdf_send_the_original_file_once(monkeypatch):
    service = load_vertex_service(monkeypatch)
    pdf10 = make_pdf(10)
    generate, calls = scripted_generate(["small"])
    monkeypatch.setattr(service, "_generate_content_with_fallback", generate)
    assert service.extract_text_from_document(pdf10, "s.pdf", "", model_candidates=["m"]) == "small"
    assert len(calls) == 1 and calls[0]["content"][1].inline_data.data == pdf10
    assert calls[0]["models"] == ["m"]

    # A deploy without pypdf: a long PDF degrades to the old one-request read (still capped).
    pdf47 = make_pdf(47)  # PdfWriter is already bound at import; the reader's lazy import is not
    generate, calls = scripted_generate(["whole"])
    monkeypatch.setattr(service, "_generate_content_with_fallback", generate)
    monkeypatch.setitem(sys.modules, "pypdf", None)  # import pypdf -> ImportError
    assert service.extract_text_from_document(pdf47, "s.pdf", "", max_blocks=10) == "whole"
    assert len(calls) == 1 and calls[0]["content"][1].inline_data.data == pdf47
    assert calls[0]["generation_config"]["max_output_tokens"] == service.ENTERPRISE_READ_MAX_OUTPUT_TOKENS


def test_enterprise_reading_images_and_text_are_one_capped_request(monkeypatch):
    service = load_vertex_service(monkeypatch)
    generate, calls = scripted_generate(["image text", "txt text"])
    monkeypatch.setattr(service, "_generate_content_with_fallback", generate)
    assert service.extract_text_from_document(make_png(), "p.png", "image/png", max_blocks=10) == "image text"
    assert calls[0]["content"][1].inline_data.mime_type == "image/png"
    assert service.extract_text_from_document(b"Name: Asha", "n.txt", "text/plain", max_blocks=10) == "txt text"
    assert "Name: Asha" in calls[1]["content"]
    assert all(c["generation_config"] == {"max_output_tokens": service.ENTERPRISE_READ_MAX_OUTPUT_TOKENS}
               for c in calls)
    # Not an image, not a PDF, not text: nothing to read, no model call.
    assert service.extract_text_from_document(b"\x00\x01", "x.bin", "", max_blocks=1) is None
    assert len(calls) == 2


def test_enterprise_reading_on_the_developer_api_uploads_each_block_and_cleans_up(monkeypatch):
    service = load_vertex_service(monkeypatch)
    monkeypatch.setattr(service, "USE_VERTEX_AI", False)
    monkeypatch.setattr(service, "GEMINI_API_KEY", "AIzaOfflineTestKey")
    assert service.is_ai_configured()
    uploads, deleted = [], []

    def upload_file(path, mime_type):
        uploads.append(len(PdfReader(path).pages))
        return SimpleNamespace(name=f"files/{len(uploads)}", state=SimpleNamespace(name="ACTIVE"))

    monkeypatch.setattr(service, "genai", SimpleNamespace(
        upload_file=upload_file, get_file=Mock(), delete_file=lambda name: deleted.append(name)))
    generate, calls = scripted_generate(["a", "b"])
    monkeypatch.setattr(service, "_generate_content_with_fallback", generate)
    text = service.extract_text_from_document(make_pdf(20), "s.pdf", "", max_blocks=10)
    assert uploads == [15, 5] and deleted == ["files/1", "files/2"]
    assert "[Pages 16–20 of 20]\nb" in text


def _answer(text=None, finish="STOP", *, raises=False):
    """A generate_content() response: candidates[0].finish_reason plus .text, which raises
    on a part-less candidate the way the Developer SDK does (Vertex returns None instead)."""
    reason = finish if isinstance(finish, int) else SimpleNamespace(name=finish)

    class Response:
        candidates = [SimpleNamespace(finish_reason=reason)]

        @property
        def text(self):
            if raises:
                raise ValueError("The response has no parts (finish_reason MAX_TOKENS).")
            return text

    return Response()


def models_answering(monkeypatch, service, answers):
    """Real _generate_content_with_fallback over fake models: answers = {model: [response, ...]}."""
    calls = []

    class Model:
        def __init__(self, name, usage_source):
            self.name, self.usage_source = name, usage_source

        def generate_content(self, content, **kwargs):
            calls.append((self.name, self.usage_source))
            item = answers[self.name].pop(0)
            if isinstance(item, Exception):
                raise item
            return item

    monkeypatch.setattr(service, "build_generative_model",
                        lambda name, usage_source="document_ai", **kw: Model(name, usage_source))
    return calls


@pytest.mark.parametrize("raises", [True, False], ids=["developer-raises", "vertex-none"])
def test_enterprise_reading_falls_back_when_a_model_spends_its_cap_reasoning(monkeypatch, raises):
    """A thinking model can spend the whole 2,048-token cap reasoning and answer MAX_TOKENS
    with no text. The SDK call 'succeeded', so the chain used to stop there and the document
    was marked failed without the next model ever being tried."""
    service = load_vertex_service(monkeypatch)
    calls = models_answering(monkeypatch, service, {
        "lite": [_answer(None, "MAX_TOKENS", raises=raises)],
        "flash": [_answer("Name: Asha Rao")],
    })
    text = service.extract_text_from_document(b"Name: Asha Rao", "n.txt", "text/plain", model_candidates=["lite", "flash"])
    assert text == "Name: Asha Rao"
    assert [name for name, _ in calls] == ["lite", "flash"]


@pytest.mark.parametrize("finish", ["MAX_TOKENS", 2])
def test_enterprise_reading_marks_a_transcription_cut_off_at_the_output_cap(monkeypatch, finish):
    service = load_vertex_service(monkeypatch)
    models_answering(monkeypatch, service, {"m": [_answer("Opening balance 1,200 on 3 Mar", finish)]})
    text = service.extract_text_from_document(b"statement", "s.txt", "text/plain", model_candidates=["m"])
    assert text.startswith("Opening balance 1,200 on 3 Mar")
    assert "cut off at the output limit" in text

    models_answering(monkeypatch, service, {"m": [_answer("block one", finish), _answer("block two", "STOP")]})
    text = service.extract_text_from_document(make_pdf(20), "s.pdf", "application/pdf", model_candidates=["m"])
    assert ("[Pages 1–15 of 20]\nblock one\n[The transcription of pages 1–15 was cut off at the "
            "output limit; later facts in it are missing.]") in text
    assert "[Pages 16–20 of 20]\nblock two" in text and text.count("cut off") == 1


def test_enterprise_reading_leaves_a_complete_answer_alone(monkeypatch):
    service = load_vertex_service(monkeypatch)
    models_answering(monkeypatch, service, {"m": [_answer("All of it.", "STOP")]})
    assert service.extract_text_from_document(b"x", "s.txt", "text/plain", model_candidates=["m"]) == "All of it."


def test_a_first_block_no_model_could_answer_is_marked_and_the_rest_still_read(monkeypatch):
    """No text from every model is that block's problem, not an outage: aborting the whole
    document on it (the old behaviour on the Developer API) threw away readable pages."""
    service = load_vertex_service(monkeypatch)
    models_answering(monkeypatch, service, {"m": [_answer(None, "MAX_TOKENS", raises=True), _answer("block two")]})
    text = service.extract_text_from_document(make_pdf(20), "s.pdf", "application/pdf", model_candidates=["m"])
    assert "[Pages 1–15 of 20: could not be read]" in text
    assert "[Pages 16–20 of 20]\nblock two" in text


def test_the_paid_checks_reading_is_booked_to_its_own_source(monkeypatch):
    service = load_vertex_service(monkeypatch)
    calls = models_answering(monkeypatch, service, {"m": [_answer("one"), _answer("two")]})
    service.extract_text_from_document(make_pdf(20), "s.pdf", "application/pdf", model_candidates=["m"],
                                       usage_source=service.ENTERPRISE_SCAN_READ_USAGE_SOURCE)
    assert calls == [("m", service.ENTERPRISE_SCAN_READ_USAGE_SOURCE)] * 2
    calls = models_answering(monkeypatch, service, {"m": [_answer("one")]})
    service.extract_text_from_document(b"x", "s.txt", "text/plain", model_candidates=["m"])
    assert calls == [("m", service.ENTERPRISE_READ_USAGE_SOURCE)]
    assert service.ENTERPRISE_SCAN_READ_USAGE_SOURCE in ai_usage.SOURCE_LABELS


def test_generation_config_is_forwarded_only_when_given(monkeypatch):
    seen = []

    class Model:
        def generate_content(self, content, **kwargs):
            seen.append(kwargs)
            return SimpleNamespace(text="ok")

    monkeypatch.setattr(gemini_service, "build_generative_model", lambda *a, **k: Model())
    gemini_service._generate_content_with_fallback(["m"], "x")
    gemini_service._generate_content_with_fallback(["m"], "x", generation_config={"max_output_tokens": 5})
    assert seen == [{}, {"generation_config": {"max_output_tokens": 5}}]


# ---------------------------------------------------------------------------
# 5. Assistant cost budget
# ---------------------------------------------------------------------------

class _Call:
    def __init__(self, name, args=None):
        self.name = name
        self.args = args or {}


class _Part:
    def __init__(self, text=None, call=None):
        self.text = text
        self.function_call = call


class _Response:
    def __init__(self, parts):
        content = SimpleNamespace(parts=parts, role="model")
        self.candidates = [SimpleNamespace(content=content)]
        self.text = "".join(p.text or "" for p in parts if p.function_call is None) if parts else ""


def tool_call():
    return _Response([_Part(call=_Call("lookup", {"city": "Pune"}))])


def answer(text):
    return _Response([_Part(text=text)])


@pytest.fixture()
def scripted_loop(monkeypatch):
    """Run _run_metered_tool_loop against scripted responses; every round costs $0.01."""
    from app.utils import gemini_service as gu

    class FakeModel:
        script = []
        requests = []

        def __init__(self, *a, **k):
            pass

        def generate_content(self, *a, **kwargs):
            FakeModel.requests.append(kwargs)
            return FakeModel.script.pop(0)

    def meter(response, *, usage, **kwargs):
        usage.rounds += 1
        usage.cost_usd += Decimal("0.01")

    monkeypatch.setattr(gu.genai, "GenerativeModel", FakeModel)
    monkeypatch.setattr(enterprise_ai, "_meter_round", meter)
    tool_runs = []

    def lookup(city: str) -> dict:
        """Look up a city."""
        tool_runs.append(city)
        return {"city": city}

    def run(script, budget=None, usage=None):
        FakeModel.script = list(script)
        FakeModel.requests = []
        tool_runs.clear()
        usage = usage or enterprise_ai.TurnUsage()
        text = enterprise_ai._run_metered_tool_loop(
            model_name="fake", system="sys", tools=[lookup], history=None, message="hi",
            source="test", organization_id=1, user_id=1, usage=usage, cost_budget_usd=budget)
        return text, usage, list(FakeModel.requests), list(tool_runs)

    return run


def _no_tool_round(request):
    return request.get("tool_config") == {"function_calling_config": {"mode": "NONE"}}


def test_no_budget_keeps_the_existing_round_cap_behaviour(scripted_loop):
    rounds = enterprise_ai.MAX_TOOL_ROUNDS
    text, usage, requests, tools = scripted_loop([tool_call()] * rounds + [answer("capped")])
    assert text == "capped" and usage.hit_round_cap and not usage.hit_cost_budget
    assert len(requests) == rounds + 1 and _no_tool_round(requests[-1])
    assert len(tools) == rounds


def test_budget_stops_tool_calling_and_forces_the_final_answer(scripted_loop):
    # Round 1 costs $0.01 -> budget $0.02 still open; round 2 reaches it: its tools still run
    # (they are free DB reads the answer needs), then exactly one no-tool round answers.
    text, usage, requests, tools = scripted_loop(
        [tool_call(), tool_call(), answer("from what I have"), answer("never reached")],
        budget=Decimal("0.02"))
    assert text == "from what I have"
    assert usage.hit_cost_budget and not usage.hit_round_cap
    assert tools == ["Pune", "Pune"]
    assert len(requests) == 3
    assert not _no_tool_round(requests[0]) and not _no_tool_round(requests[1])
    assert _no_tool_round(requests[2]) and "tools" not in requests[2]
    assert usage.as_dict()["hit_cost_budget"] is True


def test_budget_never_cuts_off_a_turn_that_answers_in_time(scripted_loop):
    text, usage, requests, _ = scripted_loop([tool_call(), answer("done")], budget=Decimal("1"))
    assert text == "done" and not usage.hit_cost_budget and len(requests) == 2


def test_budget_already_spent_answers_without_any_tool_round(scripted_loop):
    spent = enterprise_ai.TurnUsage(cost_usd=Decimal("0.05"))  # e.g. a failed earlier candidate
    text, usage, requests, tools = scripted_loop([answer("no tools")], budget=Decimal("0.05"), usage=spent)
    assert text == "no tools" and usage.hit_cost_budget and tools == []
    assert len(requests) == 1 and _no_tool_round(requests[0])
    text, usage, requests, _ = scripted_loop([answer("zero")], budget=0)
    assert text == "zero" and len(requests) == 1 and _no_tool_round(requests[0])


def test_budget_reached_on_an_empty_candidate_skips_the_tool_reask(scripted_loop):
    text, usage, requests, _ = scripted_loop([_Response([]), answer("recovered")], budget=Decimal("0.01"))
    assert text == "recovered" and usage.hit_cost_budget
    assert len(requests) == 2 and _no_tool_round(requests[1])


def test_malformed_budget_is_ignored_not_fatal():
    assert enterprise_ai._normalize_cost_budget("not money") is None
    assert enterprise_ai._normalize_cost_budget(float("nan")) is None
    assert enterprise_ai._normalize_cost_budget(-1) == Decimal("0")
    assert enterprise_ai._normalize_cost_budget(0.1) == Decimal("0.1")


def test_run_enterprise_ai_chat_threads_the_budget_through(monkeypatch):
    seen = {}

    def fake_loop(**kwargs):
        seen.update(kwargs)
        return "answer"

    monkeypatch.setattr(enterprise_ai, "is_ai_configured", lambda: True)
    monkeypatch.setattr(enterprise_ai, "build_org_tools", lambda *a, **k: [])
    monkeypatch.setattr(enterprise_ai, "_run_metered_tool_loop", fake_loop)
    org = SimpleNamespace(id=7, company_name="Acme")
    user = SimpleNamespace(id=3, full_name="Staff", email="s@example.com")
    turn = enterprise_ai.run_enterprise_ai_chat(db=None, organization=org, user=user, role="owner",
                                                message="hi", cost_budget_usd=Decimal("0.004"))
    assert turn.answer == "answer" and seen["cost_budget_usd"] == Decimal("0.004")
    enterprise_ai.run_enterprise_ai_chat(db=None, organization=org, user=user, role="owner", message="hi")
    assert seen["cost_budget_usd"] is None


# ---------------------------------------------------------------------------
# 6. Mock interview question cap
# ---------------------------------------------------------------------------

def test_interview_cap_defaults_to_12_and_the_prompt_says_so():
    import os
    if not os.getenv("ENTERPRISE_INTERVIEW_MAX_QUESTIONS"):
        assert enterprise_interview.MAX_INTERVIEW_QUESTIONS == 12
    cap = enterprise_interview.MAX_INTERVIEW_QUESTIONS
    client = SimpleNamespace(destination_country_code="UK", full_name="Asha Rao",
                             destination_country_name="United Kingdom", visa_type="Student",
                             intake=None, nationality=None)
    prompt = enterprise_interview.build_interview_system_prompt(client, None, [])
    assert f"never more than {cap}" in prompt or f"at most {cap}" in prompt
    assert enterprise_interview._question_budget_rule(12) == "Ask roughly 8–12 questions in total, and never more than 12."
    assert enterprise_interview._question_budget_rule(5) == "Ask at most 5 questions in total — never more."
    assert enterprise_interview._question_budget_rule(1) == "Ask at most 1 question in total — never more."
    # The officer must still see every question it asked when it decides.
    assert enterprise_interview.MAX_INTERVIEW_QUESTIONS * 2 <= enterprise_interview.MAX_HISTORY_TURNS


def test_count_officer_questions_counts_officer_turns_not_question_marks():
    transcript = [
        {"role": "officer", "content": "Good morning. Why this university?"},
        {"role": "user", "content": "Because of the course?"},
        {"role": "model", "content": "Walk me through your sponsor's income."},   # imperative
        {"role": "applicant", "content": "My father funds it."},
        {"role": "assistant", "content": "   "},                                     # empty: skipped
        "not a turn",
        {"role": "ai", "content": "Who pays the rest?"},
    ]
    assert enterprise_interview.count_officer_questions(transcript) == 3
    assert enterprise_interview.count_officer_questions(None) == 0
    closing = [{"role": "officer", "content": "Q1?"},
               {"role": "officer", "content": "Approved. [[INTERVIEW_COMPLETE: APPROVED]]"},
               {"role": "officer", "content": "Thank you, approved.", "finished": True},
               {"role": "officer", "content": "Refused.", "decision": "refused"}]
    assert enterprise_interview.count_officer_questions(closing) == 1


@pytest.fixture()
def interview(monkeypatch):
    sent = []
    replies = []

    class Chat:
        def send_message(self, message):
            sent.append(message)
            return SimpleNamespace(text=replies.pop(0))

    class Model:
        def start_chat(self, history=None):
            return Chat()

    monkeypatch.setattr(enterprise_interview, "is_ai_configured", lambda: True)
    monkeypatch.setattr(enterprise_interview, "_model", lambda name, system: Model())
    monkeypatch.setattr(enterprise_interview, "_model_candidates", lambda: ["fake"])
    monkeypatch.setattr(enterprise_interview.ai_usage, "record_gemini_usage", lambda *a, **k: None)
    client = SimpleNamespace(destination_country_code="US", full_name="Asha Rao",
                             destination_country_name="United States", visa_type="F-1",
                             intake=None, nationality=None)

    def turn(reply, **kwargs):
        replies.append(reply)
        kwargs.setdefault("history", [])
        kwargs.setdefault("message", "My answer.")
        return enterprise_interview.run_interview_turn(client=client, organization=None,
                                                       recent_notes=[], **kwargs)

    return SimpleNamespace(turn=turn, sent=sent)


def test_below_the_cap_the_officer_asks_and_the_count_advances(interview):
    result = interview.turn("Why Boston?", questions_asked=3)
    assert result["finished"] is False and result["questions_asked"] == 4
    assert result["forced_close"] is False and result["max_questions"] == enterprise_interview.MAX_INTERVIEW_QUESTIONS
    assert interview.sent[-1] == "My answer."  # no stage direction below the cap


def test_at_the_cap_the_officer_must_close_with_a_decision(interview):
    cap = enterprise_interview.MAX_INTERVIEW_QUESTIONS
    result = interview.turn("Thank you, I'm pleased to approve your visa.\n[[INTERVIEW_COMPLETE: APPROVED]]",
                            questions_asked=cap)
    assert result == {"reply": "Thank you, I'm pleased to approve your visa.", "finished": True,
                      "decision": "approved", "questions_asked": cap, "max_questions": cap,
                      "forced_close": True}
    assert f"You have now asked all {cap} of your questions" in interview.sent[-1]
    assert interview.sent[-1].startswith("My answer.")


def test_a_cap_closing_without_its_tag_is_still_final(interview):
    cap = enterprise_interview.MAX_INTERVIEW_QUESTIONS
    result = interview.turn("I'm sorry, I'm unable to approve your visa today.", questions_asked=cap)
    assert result["finished"] is True and result["decision"] == "refused"
    assert result["reply"] == "I'm sorry, I'm unable to approve your visa today."


def test_an_officer_that_ignores_the_cap_cannot_ask_another_question(interview):
    cap = enterprise_interview.MAX_INTERVIEW_QUESTIONS
    result = interview.turn("And what will you do after graduating?", questions_asked=cap + 3)
    assert result["finished"] is True and result["decision"] is None
    assert "?" not in result["reply"] and result["questions_asked"] == cap + 3


def test_cap_counts_from_the_transcript_when_no_count_is_passed(interview):
    history = []
    for i in range(3):
        history += [{"role": "officer", "content": f"Question {i}?"}, {"role": "user", "content": "Answer."}]
    result = interview.turn("Final words. [[INTERVIEW_COMPLETE: REFUSED]]", history=history, max_questions=3)
    assert result["forced_close"] is True and result["finished"] is True and result["decision"] == "refused"
    result = interview.turn("Next question?", history=history, max_questions=4)
    assert result["forced_close"] is False and result["questions_asked"] == 4


def test_opening_turn_is_never_forced_closed(interview):
    result = interview.turn("Good morning. Why this course?", is_start=True, questions_asked=99)
    assert result["forced_close"] is False and result["finished"] is False
    assert "Greet them briefly" in interview.sent[-1]


def test_interview_signature_stays_backward_compatible(interview):
    # The pre-v2 call shape (no count, no cap) still works and returns the old keys.
    result = interview.turn("Why Boston?")
    assert {"reply", "finished", "decision"} <= set(result)
    assert result["questions_asked"] == 1
