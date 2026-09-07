"""Small compatibility surface for existing Gemini callers on Google Cloud.

The application still uses the legacy model/chat interface in several features.
Keep that interface while sending Cloud requests through the current google-genai
SDK. Native responses are retained, including Gemini function-call signatures.
"""

from __future__ import annotations

import io
from typing import Callable

from google.genai import types
from google.protobuf.json_format import MessageToDict
from PIL import Image
import proto


def _proto_dict(value: proto.Message) -> dict:
    # JSON field aliases avoid legacy Schema.type_/format_ and omit unset fields.
    return MessageToDict(type(value).pb(value))


def _part(value) -> types.Part:
    if isinstance(value, types.Part):
        return value
    if isinstance(value, str):
        return types.Part(text=value)
    if isinstance(value, proto.Message):
        return types.Part.model_validate(_proto_dict(value))
    if isinstance(value, Image.Image):
        image_bytes = io.BytesIO()
        value.save(image_bytes, format="PNG")
        return types.Part.from_bytes(data=image_bytes.getvalue(), mime_type="image/png")
    if isinstance(value, dict):
        if "mime_type" in value and "data" in value:
            return types.Part.from_bytes(data=value["data"], mime_type=value["mime_type"])
        return types.Part.model_validate(value)
    raise TypeError(f"Unsupported Gemini content part: {type(value).__name__}")


def _is_content(value) -> bool:
    return (
        isinstance(value, types.Content)
        or (isinstance(value, proto.Message) and type(value).__name__ == "Content")
        or (isinstance(value, dict) and "parts" in value)
    )


def normalize_contents(contents) -> list[types.Content]:
    """Accept existing strings, attachments, histories, and tool-loop protos."""
    values = contents if isinstance(contents, (list, tuple)) else [contents]
    result = []
    pending = []
    for value in values:
        if _is_content(value):
            if pending:
                result.append(types.Content(role="user", parts=pending))
                pending = []
            if isinstance(value, types.Content):
                result.append(value)
                continue
            if isinstance(value, proto.Message):
                value = _proto_dict(value)
            result.append(types.Content(
                role=value.get("role", "user"),
                parts=[_part(part) for part in value.get("parts", [])],
            ))
        else:
            pending.append(_part(value))
    if pending:
        result.append(types.Content(role="user", parts=pending))
    return result


def _tools(value) -> list[types.Tool]:
    if hasattr(value, "to_proto"):
        value = value.to_proto()
    values = value if isinstance(value, (list, tuple)) else [value]
    return [
        item if isinstance(item, types.Tool) else types.Tool.model_validate(
            _proto_dict(item) if isinstance(item, proto.Message) else item
        )
        for item in values
    ]


class Part:
    @staticmethod
    def from_data(data: bytes, mime_type: str) -> types.Part:
        return types.Part.from_bytes(data=data, mime_type=mime_type)


class GenerativeModel:
    def __init__(self, model_name: str, *, client_factory: Callable,
                 generation_config=None, system_instruction=None, tools=None):
        self.model_name = model_name
        self._client_factory = client_factory
        self._generation_config = dict(generation_config or {})
        self._system_instruction = system_instruction
        self._tools = tools

    def generate_content(self, contents, *, generation_config=None, tools=None,
                         tool_config=None):
        config = dict(self._generation_config)
        if generation_config:
            config.update(generation_config)
        if self._system_instruction is not None:
            config["system_instruction"] = self._system_instruction
        selected_tools = self._tools if tools is None else tools
        if selected_tools is not None:
            config["tools"] = _tools(selected_tools)
        if tool_config is not None:
            config["tool_config"] = tool_config
        # Enterprise runs and meters its existing function loop explicitly.
        config["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)
        return self._client_factory().models.generate_content(
            model=self.model_name,
            contents=normalize_contents(contents),
            config=types.GenerateContentConfig(**config),
        )

    def start_chat(self, *, history=None):
        return _Chat(self, history or [])


class _Chat:
    def __init__(self, model: GenerativeModel, history):
        self._model = model
        self.history = normalize_contents(history)

    def send_message(self, content, **kwargs):
        contents = self.history + normalize_contents(content)
        response = self._model.generate_content(contents, **kwargs)
        candidates = getattr(response, "candidates", None) or []
        if candidates and getattr(candidates[0], "content", None) is not None:
            self.history = contents + [candidates[0].content]
        return response
