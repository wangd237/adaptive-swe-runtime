"""Structured LLM replies with OpenAI-compatible JSON-text fallback.

Some providers implement chat completions but reject LangChain's
tool/function-based `with_structured_output` request. Fallback is bounded
to known provider schema-rejection errors, never used to mask execution or
network failures. Both paths are still genuine model calls.
"""
from __future__ import annotations

import json
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError


T = TypeVar("T",bound=BaseModel)
_SCHEMA_REJECTION = frozenset({
    "OpenAIInvalidRequestError",
    "BadRequestError",
    "UnsupportedFeatureError",
    "NotImplementedError",
    "OutputParserException",
})


def _parse_json_text(raw: Any, schema: type[T]) -> T:
    if isinstance(raw, schema):
        return raw
    if isinstance(raw, dict):
        return schema.model_validate(raw)
    content = getattr(raw, "content", raw)
    if isinstance(content, list):
        # LangChain content blocks: only concatenate explicit text fields.
        content = "".join(str(x.get("text","")) for x in content
                          if isinstance(x,dict) and x.get("type")=="text")
    if not isinstance(content,str) or len(content)>14000:
        raise ValueError("LLM_STRUCTURED_JSON_CONTENT_INVALID")
    text=content.strip()
    if text.startswith("```"):
        lines=text.splitlines()
        if lines and lines[-1].strip()=="```":
            text="\n".join(lines[1:-1]).strip()
    try:
        decoded=json.loads(text)
    except json.JSONDecodeError:
        # Some compatible providers add one line of commentary. Accept one
        # exact JSON object, not arbitrary synthesized field values.
        start=text.find("{")
        end=text.rfind("}")
        if start<0 or end<=start:
            raise ValueError("LLM_STRUCTURED_JSON_PARSE_FAILED") from None
        try:
            decoded=json.loads(text[start:end+1])
        except json.JSONDecodeError:
            raise ValueError("LLM_STRUCTURED_JSON_PARSE_FAILED") from None
    return schema.model_validate(decoded)


async def invoke_structured_compat(
    model: Any, schema: type[T], messages: list[tuple[str,str]],
) -> T:
    try:
        structured = model.with_structured_output(schema)
        raw = await structured.ainvoke(messages)
        return _parse_json_text(raw,schema)
    except Exception as exc:
        # A provider may reject JSON/function-call requests outright *or*
        # return a partial/invalid structured payload. Both are recoverable
        # with exactly one ordinary-chat JSON request, then strict validation.
        if (type(exc).__name__ not in _SCHEMA_REJECTION
                and not isinstance(exc, ValidationError)):
            raise
        fields = schema.model_json_schema()
        json_request = messages + [(
            "human", "Return ONLY a single JSON object. Do NOT call tools, "
            "write prose, or use Markdown. Use all required keys exactly, "
            "with these types and constraints: " + json.dumps(fields,sort_keys=True)
        )]
        raw = await model.ainvoke(json_request)
        return _parse_json_text(raw,schema)
