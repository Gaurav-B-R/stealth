"""Offline regression coverage for callers of the shared Gemini provider boundary."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from google.genai import types
from google.generativeai import protos

from app import ai_usage, course_catalog, enterprise_ai
from app.routers import ai_chat, news
from app.services import daily_ai_notifications
from app.utils import gemini_service


class GeminiCloudConsumerTests(unittest.TestCase):
    def patch(self, target, name, value, raising=True):
        patcher = patch.object(target, name, value, create=not raising)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def test_news_uses_shared_client_with_selected_auth_mode(self, use_vertex=True, auth_mode="vertex"):
        client = object()
        factory = Mock(return_value=client)
        self.patch(news, "_load_latest_genai", lambda: True)
        self.patch(gemini_service, "get_genai_client", factory, raising=False)
        self.patch(gemini_service, "USE_VERTEX_AI", use_vertex)
        # A leftover key must not override the shared provider selection.
        self.patch(gemini_service, "GEMINI_API_KEY", "AIza-old-account-test-only")

        assert news._build_latest_genai_client() == (client, auth_mode)
        factory.assert_called_once_with()


    def test_news_cloud_configuration_error_returns_public_503(self):
        self.patch(news, "_load_latest_genai", lambda: True)
        self.patch(gemini_service, "USE_VERTEX_AI", True)
        self.patch(gemini_service, "GEMINI_API_KEY", "AIza-old-account-test-only")
        self.patch(
            gemini_service, "get_genai_client",
            Mock(side_effect=RuntimeError("Cloud project configuration missing")), raising=False,
        )

        with self.assertRaises(HTTPException) as error:
            news._build_latest_genai_client()

        assert error.exception.status_code == 503
        assert error.exception.detail == news.PUBLIC_NEWS_GENERATION_ERROR_DETAIL


    def test_feature_availability_follows_selected_provider(self, configured=True):
        self.patch(gemini_service, "is_ai_configured", lambda: configured)
        self.patch(gemini_service, "GEMINI_API_KEY", "")

        assert course_catalog.ai_available() is configured
        assert enterprise_ai.is_ai_configured() is configured


    def test_catalog_grounding_uses_cloud_client_and_preserves_options(self):
        response = SimpleNamespace(text='{"courses": []}')
        generate = Mock(return_value=response)
        factory = Mock(return_value=SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
        meter = Mock(side_effect=lambda source, model, call, **kwargs: call())
        self.patch(gemini_service, "is_ai_configured", lambda: True)
        self.patch(gemini_service, "GEMINI_API_KEY", "")
        self.patch(gemini_service, "get_genai_client", factory, raising=False)
        self.patch(course_catalog, "GROUNDING_ENABLED", True)
        self.patch(course_catalog, "_extract_grounding_urls", lambda response: ["https://example.edu"])
        self.patch(course_catalog, "_extract_grounding_domains", lambda response: ["example.edu"])
        self.patch(ai_usage, "tracked_gemini_call", meter)

        result = course_catalog._grounded_generate("original prompt", ["original-model"], "catalog-test")

        assert result == (response.text, ["https://example.edu"], ["example.edu"])
        assert factory.call_args.kwargs["http_options"].timeout == course_catalog.GROUNDED_REQUEST_TIMEOUT_MS
        kwargs = generate.call_args.kwargs
        assert kwargs["model"] == "original-model"
        assert kwargs["contents"] == "original prompt"
        assert kwargs["config"].temperature == 0.3
        assert kwargs["config"].tools[0].google_search is not None
        meter.assert_called_once()
        assert meter.call_args.args[:2] == ("catalog-test", "original-model")
        assert meter.call_args.kwargs == {
            "product": "shared", "trigger": "automation",
            "pricing_context": {"service_tier": "standard", "input_modalities": ["TEXT"]},
        }
        assert kwargs["config"].automatic_function_calling.disable is True


    def test_daily_notifier_uses_shared_cloud_model(self):
        model = object()
        factory = Mock(return_value=model)
        self.patch(gemini_service, "is_ai_configured", lambda: True)
        self.patch(gemini_service, "USE_VERTEX_AI", True)
        self.patch(gemini_service, "GenerativeModel", factory, raising=False)

        assert daily_ai_notifications._build_gemini_model("original-model") == (model, "vertex")
        factory.assert_called_once_with("original-model")


    def test_daily_notifier_rejects_invalid_cloud_without_old_key_fallback(self):
        legacy_factory = Mock()
        self.patch(gemini_service, "is_ai_configured", lambda: False)
        self.patch(gemini_service, "USE_VERTEX_AI", True)
        self.patch(gemini_service, "genai", SimpleNamespace(GenerativeModel=legacy_factory))

        with self.assertRaisesRegex(RuntimeError, "selected provider"):
            daily_ai_notifications._build_gemini_model("original-model")

        legacy_factory.assert_not_called()


    def test_chat_cloud_model_preserves_config_and_inline_attachment(self):
        model = SimpleNamespace(generate_content=Mock(return_value="response"))
        factory = Mock(return_value=model)
        part = object()
        make_part = Mock(return_value=part)
        config = {"max_output_tokens": 4096, "temperature": 0.85}
        self.patch(gemini_service, "GenerativeModel", factory, raising=False)
        self.patch(gemini_service, "Part", SimpleNamespace(from_data=make_part), raising=False)

        result_model = ai_chat._build_ai_chat_model("vertex", "original-model", config)
        result = ai_chat._generate_with_ai_chat_model(
            model=result_model, provider="vertex", full_prompt="original prompt",
            inline_session_attachment_parts=[{"data": b"pdf bytes", "mime_type": "application/pdf"}],
        )

        assert result == "response"
        factory.assert_called_once_with("original-model", generation_config=config)
        make_part.assert_called_once_with(data=b"pdf bytes", mime_type="application/pdf")
        model.generate_content.assert_called_once_with(["original prompt", part])


    def test_enterprise_function_calls_support_native_and_legacy_response_parts(self, modern=True):
        if modern:
            parts = [
                types.Part(text="text only"),
                types.Part(function_call=types.FunctionCall(name="lookup", args={"client_id": 7})),
            ]
        else:
            parts = [
                protos.Part(text="text only"),
                protos.Part(function_call=protos.FunctionCall(name="lookup", args={"client_id": 7})),
            ]
        response = SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=parts))])

        calls = enterprise_ai._function_calls_in(response)

        assert len(calls) == 1
        assert calls[0].name == "lookup"
        assert dict(calls[0].args) == {"client_id": 7}


    def test_enterprise_empty_parts_return_no_function_calls(self):
        response = SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=None))])
        assert enterprise_ai._function_calls_in(response) == []

    def test_news_developer_api_auth_mode(self):
        self.test_news_uses_shared_client_with_selected_auth_mode(False, "api_key")

    def test_unconfigured_features_are_unavailable(self):
        self.test_feature_availability_follows_selected_provider(False)

    def test_enterprise_legacy_function_calls(self):
        self.test_enterprise_function_calls_support_native_and_legacy_response_parts(False)


if __name__ == "__main__":
    unittest.main()
