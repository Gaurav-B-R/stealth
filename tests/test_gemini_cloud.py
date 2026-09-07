"""Offline regression coverage for switching Gemini's billing/auth provider."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from google.auth.credentials import AnonymousCredentials
from google.genai import types
from google.generativeai import protos
from google.generativeai.types import content_types

from app.utils.gemini_cloud import GenerativeModel, Part, normalize_contents


def answer(text="answer", *, parts=None):
    return types.GenerateContentResponse(candidates=[types.Candidate(
        content=types.Content(role="model", parts=parts or [types.Part(text=text)]),
        finish_reason="STOP",
    )], usage_metadata=types.GenerateContentResponseUsageMetadata(
        prompt_token_count=10, candidates_token_count=2, total_token_count=12,
    ))


def model_client(responses):
    client = SimpleNamespace(models=SimpleNamespace(generate_content=Mock(side_effect=responses)))
    return client


def load_service(monkeypatch, *, provider="vertex", valid_credentials=True):
    monkeypatch.setenv("GEMINI_PROVIDER", provider)
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaOldPaidKeyForOfflineTest")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "credited-project")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "global")
    monkeypatch.setenv("GEMINI_VERTEX_CREDENTIALS", "/nonexistent/dedicated-gemini.json")
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    from google.oauth2 import service_account
    credentials = AnonymousCredentials()
    loader = Mock(return_value=credentials) if valid_credentials else Mock(side_effect=FileNotFoundError)
    monkeypatch.setattr(service_account.Credentials, "from_service_account_file", loader)
    spec = importlib.util.spec_from_file_location(
        "isolated_gemini_service", Path(__file__).parents[1] / "app/utils/gemini_service.py",
    )
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)
    return service, credentials, loader


def test_cloud_uses_explicit_credential_and_credited_project(monkeypatch):
    service, credential, loader = load_service(monkeypatch)
    # Constructing the real SDK client does not send a request. This also checks
    # that GEMINI_API_KEY in the environment cannot override Cloud credentials.
    client = service.get_genai_client()
    assert client._api_client.vertexai is True
    assert client._api_client.project == "credited-project"
    assert client._api_client.location == "global"
    assert client._api_client._credentials is credential
    assert client._api_client.api_key is None
    assert service.get_genai_client() is client
    loader.assert_called_once_with(
        "/nonexistent/dedicated-gemini.json",
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    assert service.SERVICE_ACCOUNT_PATH != service.CLOUD_SERVICE_ACCOUNT_PATH
    client.close()


def test_invalid_cloud_credentials_never_fall_back_to_paid_key(monkeypatch):
    service, _, _ = load_service(monkeypatch, valid_credentials=False)
    assert service.USE_VERTEX_AI
    assert not service.is_ai_configured()
    assert not service.GENAI_AVAILABLE
    with pytest.raises(RuntimeError, match="selected Gemini provider"):
        service.get_genai_client()
    with pytest.raises(RuntimeError, match="selected Gemini provider"):
        service.genai.GenerativeModel("gemini-3.1-pro-preview").generate_content("hello")
    assert service.build_generative_model("gemini-3.1-pro-preview") is None


def test_cloud_requires_explicit_billing_project(monkeypatch):
    service, _, _ = load_service(monkeypatch)
    # Re-execute with both project inputs removed; no inferred personal project.
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT")
    monkeypatch.delenv("GCP_PROJECT", raising=False)
    spec = importlib.util.spec_from_file_location("missing_project_gemini", service.__file__)
    unconfigured = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(unconfigured)
    assert unconfigured.USE_VERTEX_AI
    assert not unconfigured.is_ai_configured()


def test_developer_mode_keeps_existing_api_key_path(monkeypatch):
    service, _, loader = load_service(monkeypatch, provider="developer")
    from google import genai
    client_factory = Mock()
    monkeypatch.setattr(genai, "Client", client_factory)
    service.get_genai_client(http_options={"timeout": 12345})
    assert not service.USE_VERTEX_AI
    assert service.is_ai_configured()
    loader.assert_not_called()
    client_factory.assert_called_once_with(
        enterprise=False, api_key="AIzaOldPaidKeyForOfflineTest", http_options={"timeout": 12345},
    )


def test_generation_preserves_model_config_system_and_usage():
    response = answer()
    client = model_client([response])
    model = GenerativeModel(
        "gemini-3.1-pro-preview", client_factory=lambda: client,
        generation_config={"temperature": 0.3, "max_output_tokens": 4096},
        system_instruction="original system prompt",
    )
    assert model.generate_content("original user prompt") is response
    request = client.models.generate_content.call_args.kwargs
    assert request["model"] == "gemini-3.1-pro-preview"
    assert request["contents"][0].parts[0].text == "original user prompt"
    assert request["config"].system_instruction == "original system prompt"
    assert request["config"].temperature == 0.3
    assert request["config"].max_output_tokens == 4096
    assert request["config"].automatic_function_calling.disable is True
    assert response.usage_metadata.total_token_count == 12


def test_pdf_and_image_attachments_keep_bytes_and_mime_types():
    pdf = b"%PDF-1.4 offline sample"
    png = b"offline image sample"
    contents = normalize_contents([
        "attachment prompt", Part.from_data(pdf, mime_type="application/pdf"),
        {"data": png, "mime_type": "image/png"},
    ])
    assert len(contents) == 1
    assert contents[0].role == "user"
    assert contents[0].parts[1].inline_data.data == pdf
    assert contents[0].parts[1].inline_data.mime_type == "application/pdf"
    assert contents[0].parts[2].inline_data.data == png
    assert contents[0].parts[2].inline_data.mime_type == "image/png"


@pytest.mark.parametrize("image_mode", ["RGBA", "P"])
def test_cloud_document_extraction_accepts_transparent_and_palette_pngs(monkeypatch, image_mode):
    import io
    from PIL import Image
    service, _, _ = load_service(monkeypatch)
    image = Image.new(image_mode, (2, 2))
    image_bytes = io.BytesIO()
    image.save(image_bytes, format="PNG")
    generate = Mock(return_value=answer("extracted document"))
    monkeypatch.setattr(service, "_generate_content_with_fallback", generate)
    assert service.extract_text_from_document(image_bytes.getvalue(), "scan.png", "image/png") == "extracted document"
    image_part = generate.call_args.args[1][1]
    assert image_part.inline_data.mime_type == "image/png"
    restored = Image.open(io.BytesIO(image_part.inline_data.data))
    assert restored.mode == image_mode


def test_native_empty_candidate_keeps_existing_retry_behavior():
    from app import enterprise_ai
    native = types.GenerateContentResponse(candidates=[types.Candidate(
        content=types.Content(role="model"), finish_reason="STOP",
    )])
    legacy = SimpleNamespace(candidates=[SimpleNamespace(content=protos.Content(role="model"))])
    assert enterprise_ai._is_empty_candidate(native)
    assert enterprise_ai._is_empty_candidate(legacy)
    assert not enterprise_ai._is_empty_candidate(types.GenerateContentResponse())


def test_interview_history_and_system_survive_chat_turns():
    client = model_client([answer("first response"), answer("second response")])
    model = GenerativeModel("gemini-2.5-pro", client_factory=lambda: client,
                            system_instruction="original interview instructions")
    chat = model.start_chat(history=[
        {"role": "user", "parts": ["earlier question"]},
        {"role": "model", "parts": ["earlier answer"]},
    ])
    chat.send_message("new answer")
    chat.send_message("next answer")
    request = client.models.generate_content.call_args.kwargs
    assert [c.role for c in request["contents"]] == ["user", "model", "user", "model", "user"]
    assert [c.parts[0].text for c in request["contents"]] == [
        "earlier question", "earlier answer", "new answer", "first response", "next answer",
    ]
    assert request["config"].system_instruction == "original interview instructions"


def test_legacy_tool_schema_does_not_gain_zero_bounds_or_lose_signature():
    def lookup(city: str) -> dict:
        """Find city details."""
        return {"city": city}
    library = content_types.to_function_library([lookup])
    signed = types.Content(role="model", parts=[types.Part(
        function_call=types.FunctionCall(name="lookup", args={"city": "London"}),
        thought_signature=b"opaque-signature",
    )])
    legacy_result = protos.Content(role="user", parts=[protos.Part(
        function_response=protos.FunctionResponse(name="lookup", response={"city": "London"}),
    )])
    client = model_client([answer()])
    model = GenerativeModel("gemini-3.1-pro-preview", client_factory=lambda: client, tools=library)
    model.generate_content([signed, legacy_result], tool_config={"function_calling_config": {"mode": "NONE"}})
    request = client.models.generate_content.call_args.kwargs
    assert request["contents"][0] is signed
    assert request["contents"][0].parts[0].thought_signature == b"opaque-signature"
    assert request["contents"][1].parts[0].function_response.response == {"city": "London"}
    declaration = request["config"].tools[0].function_declarations[0]
    assert declaration.parameters.properties["city"].type == "STRING"
    assert declaration.parameters.properties["city"].max_items is None
    assert request["config"].tool_config.function_calling_config.mode == "NONE"


def test_real_enterprise_loop_executes_tool_and_preserves_signed_content(monkeypatch):
    from app import enterprise_ai
    calls = []
    def lookup(city: str) -> dict:
        """Find city details."""
        calls.append(city)
        return {"city": city}
    signed = types.Part(function_call=types.FunctionCall(name="lookup", args={"city": "London"}),
                        thought_signature=b"enterprise-signature")
    first = answer(parts=[signed])
    client = model_client([first, answer("London details")])
    monkeypatch.setattr(enterprise_ai.gemini_utils, "genai", SimpleNamespace(
        GenerativeModel=lambda name, **kwargs: GenerativeModel(name, client_factory=lambda: client, **kwargs),
    ))
    monkeypatch.setattr(enterprise_ai, "_meter_round", Mock())
    usage = enterprise_ai.TurnUsage()
    result = enterprise_ai._run_metered_tool_loop(
        model_name="gemini-3.1-pro-preview", system="original system", tools=[lookup],
        history=[{"role": "user", "parts": ["earlier turn"]}], message="Look up London",
        source="test", organization_id=None, user_id=None, usage=usage,
    )
    assert result == "London details"
    assert calls == ["London"]
    assert usage.tools_called == ["lookup"]
    assert enterprise_ai._meter_round.call_count == 2
    second = client.models.generate_content.call_args_list[1].kwargs
    assert second["contents"][2] is first.candidates[0].content
    assert second["contents"][2].parts[0].thought_signature == b"enterprise-signature"
    assert second["contents"][3].parts[0].function_response.response == {"city": "London"}
