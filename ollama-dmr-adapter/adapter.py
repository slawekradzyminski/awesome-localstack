#!/usr/bin/env python3
"""Minimal Ollama-to-Docker-Model-Runner compatibility adapter."""

from __future__ import annotations

import http.client
import json
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


UPSTREAM_HOST = os.environ.get("UPSTREAM_HOST", "model-runner.docker.internal")
UPSTREAM_PORT = int(os.environ.get("UPSTREAM_PORT", "80"))
OPENAI_CHAT_PATH = "/engines/llama.cpp/v1/chat/completions"


def without_nulls(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: without_nulls(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [without_nulls(item) for item in value]
    return value


def should_translate_thinking_request(path: str, payload: dict[str, Any]) -> bool:
    """Use llama.cpp's native switch when the Ollama-compatible API ignores think=false."""
    return (
        path in {"/api/generate", "/api/chat"}
        and payload.get("think") is False
        and payload.get("raw") is not True
    )


def _openai_tool_call(tool_call: dict[str, Any]) -> dict[str, Any]:
    function = tool_call.get("function") or {}
    arguments = function.get("arguments", "{}")
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments, separators=(",", ":"))

    result = {
        "type": tool_call.get("type") or "function",
        "function": {
            "name": function.get("name", ""),
            "arguments": arguments,
        },
    }
    if tool_call.get("id"):
        result["id"] = tool_call["id"]
    return result


def _openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    translated = []
    pending_tool_ids: dict[str, list[str]] = {}

    for message in messages:
        role = message.get("role")
        if role == "tool":
            tool_name = message.get("tool_name") or message.get("name", "")
            matching_ids = pending_tool_ids.get(tool_name, [])
            tool_call_id = message.get("tool_call_id")
            if not tool_call_id and matching_ids:
                tool_call_id = matching_ids.pop(0)
            translated.append(
                {
                    "role": "tool",
                    "content": message.get("content", ""),
                    "tool_call_id": tool_call_id or tool_name,
                }
            )
            continue

        translated_message = {
            "role": role,
            "content": message.get("content", ""),
        }
        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            translated_calls = [_openai_tool_call(call) for call in tool_calls]
            translated_message["tool_calls"] = translated_calls
            for call in translated_calls:
                function_name = call["function"]["name"]
                call_id = call.get("id")
                if function_name and call_id:
                    pending_tool_ids.setdefault(function_name, []).append(call_id)
        translated.append(translated_message)

    return translated


def translate_ollama_request(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Translate the subset used by the app to llama.cpp's OpenAI-compatible API."""
    if path == "/api/generate":
        messages = []
        if payload.get("system"):
            messages.append({"role": "system", "content": payload["system"]})
        messages.append({"role": "user", "content": payload.get("prompt", "")})
    else:
        messages = _openai_messages(payload.get("messages") or [])

    translated: dict[str, Any] = {
        "model": payload.get("model"),
        "messages": messages,
        "stream": payload.get("stream", True),
        "chat_template_kwargs": {"enable_thinking": False},
    }

    options = payload.get("options") or {}
    option_names = {
        "temperature": "temperature",
        "top_p": "top_p",
        "stop": "stop",
        "presence_penalty": "presence_penalty",
        "frequency_penalty": "frequency_penalty",
        "num_predict": "max_tokens",
    }
    for ollama_name, openai_name in option_names.items():
        if ollama_name in options:
            translated[openai_name] = options[ollama_name]

    for name in ("tools", "tool_choice", "logprobs", "top_logprobs"):
        if name in payload:
            translated[name] = payload[name]

    return without_nulls(translated)


def _created_at(value: Any) -> str:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value or "")


def normalize_openai_response_line(
    line: bytes,
    response_kind: str,
    request_model: str,
    tool_states: dict[int, dict[str, Any]] | None = None,
) -> bytes:
    """Convert OpenAI SSE/JSON chunks back to the Ollama NDJSON response contract."""
    stripped = line.strip()
    if not stripped:
        return b""
    if stripped.startswith(b"data:"):
        stripped = stripped.removeprefix(b"data:").strip()
    if stripped == b"[DONE]":
        return b""

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return line
    if "error" in payload:
        return json.dumps(payload, separators=(",", ":")).encode() + b"\n"

    choices = payload.get("choices") or []
    if not choices:
        return b""
    choice = choices[0]
    message = choice.get("delta") or choice.get("message") or {}
    finish_reason = choice.get("finish_reason")
    done = finish_reason is not None or payload.get("object") == "chat.completion"
    content = message.get("content")
    thinking = message.get("reasoning_content") or message.get("reasoning")

    result: dict[str, Any] = {
        "model": request_model,
        "created_at": _created_at(payload.get("created")),
        "done": done,
    }
    if response_kind == "generate":
        result["response"] = content or ""
        if thinking:
            result["thinking"] = thinking
    else:
        ollama_message: dict[str, Any] = {
            "role": message.get("role") or "assistant",
            "content": content or "",
        }
        if thinking:
            ollama_message["thinking"] = thinking
        if message.get("tool_calls"):
            ollama_message["tool_calls"] = message["tool_calls"]
        result["message"] = ollama_message

    usage = payload.get("usage") or {}
    if usage.get("prompt_tokens") is not None:
        result["prompt_eval_count"] = usage["prompt_tokens"]
    if usage.get("completion_tokens") is not None:
        result["eval_count"] = usage["completion_tokens"]

    normalized = json.dumps(result, separators=(",", ":")).encode() + b"\n"
    if response_kind == "chat":
        return normalize_response_line(normalized, tool_states)
    return normalized


def normalize_response_line(line: bytes, tool_states: dict[int, dict[str, Any]] | None = None) -> bytes:
    """Convert DMR's stringified tool arguments to Ollama's object shape."""
    if tool_states is None:
        tool_states = {}
    try:
        payload = json.loads(line)
        message = payload.get("message", {})
        tool_calls = message.get("tool_calls") or []
        completed_calls = []
        for position, tool_call in enumerate(tool_calls):
            function = tool_call.get("function") or {}
            arguments = function.get("arguments")
            index = int(function.get("index", position))
            state = tool_states.setdefault(
                index,
                {"id": tool_call.get("id"), "type": tool_call.get("type"), "name": "", "arguments": ""},
            )
            state["id"] = tool_call.get("id") or state["id"]
            state["type"] = tool_call.get("type") or state["type"]
            if function.get("name") and not state["name"]:
                state["name"] = function["name"]

            if isinstance(arguments, str):
                state["arguments"] += arguments
                try:
                    decoded_arguments = json.loads(state["arguments"])
                except json.JSONDecodeError:
                    continue
            else:
                decoded_arguments = arguments

            if isinstance(decoded_arguments, str):
                decoded_arguments = json.loads(decoded_arguments)
            if not isinstance(decoded_arguments, dict):
                continue

            completed_call = {
                "function": {"name": state["name"], "arguments": decoded_arguments},
            }
            if state["id"]:
                completed_call["id"] = state["id"]
            if state["type"]:
                completed_call["type"] = state["type"]
            completed_calls.append(completed_call)
            del tool_states[index]

        if tool_calls:
            if completed_calls:
                message["tool_calls"] = completed_calls
            else:
                message.pop("tool_calls", None)
        suffix = b"\n" if line.endswith(b"\n") else b""
        return json.dumps(payload, separators=(",", ":")).encode() + suffix
    except (AttributeError, json.JSONDecodeError, TypeError):
        return line


class AdapterHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok\n")
            return
        self._proxy(None)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        upstream_path = self.path
        response_kind = None
        request_model = ""
        if self.headers.get_content_type() == "application/json" and body:
            payload = without_nulls(json.loads(body))
            request_model = payload.get("model", "")
            if should_translate_thinking_request(self.path, payload):
                response_kind = "generate" if self.path == "/api/generate" else "chat"
                payload = translate_ollama_request(self.path, payload)
                upstream_path = OPENAI_CHAT_PATH
            body = json.dumps(payload, separators=(",", ":")).encode()
        self._proxy(body, upstream_path, response_kind, request_model)

    def _proxy(
        self,
        body: bytes | None,
        upstream_path: str | None = None,
        response_kind: str | None = None,
        request_model: str = "",
    ) -> None:
        connection = http.client.HTTPConnection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=600)
        headers = {"Accept": self.headers.get("Accept", "*/*")}
        if body is not None:
            headers["Content-Type"] = self.headers.get("Content-Type", "application/json")

        try:
            connection.request(self.command, upstream_path or self.path, body=body, headers=headers)
            response = connection.getresponse()
            self.send_response(response.status)
            content_type = "application/x-ndjson" if response_kind else response.getheader("Content-Type")
            if content_type:
                self.send_header("Content-Type", content_type)
            self.end_headers()
            tool_states: dict[int, dict[str, Any]] = {}
            while line := response.readline():
                if response_kind:
                    normalized = normalize_openai_response_line(
                        line, response_kind, request_model, tool_states
                    )
                else:
                    normalized = normalize_response_line(line, tool_states)
                if not normalized:
                    continue
                self.wfile.write(normalized)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            connection.close()

    def log_message(self, format_string: str, *args: object) -> None:
        print(f"{self.address_string()} {format_string % args}", flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 11434), AdapterHandler).serve_forever()
