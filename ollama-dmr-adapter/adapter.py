#!/usr/bin/env python3
"""Minimal Ollama-to-Docker-Model-Runner compatibility adapter."""

from __future__ import annotations

import http.client
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


UPSTREAM_HOST = os.environ.get("UPSTREAM_HOST", "model-runner.docker.internal")
UPSTREAM_PORT = int(os.environ.get("UPSTREAM_PORT", "80"))


def without_nulls(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: without_nulls(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [without_nulls(item) for item in value]
    return value


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
        if self.headers.get_content_type() == "application/json" and body:
            body = json.dumps(without_nulls(json.loads(body)), separators=(",", ":")).encode()
        self._proxy(body)

    def _proxy(self, body: bytes | None) -> None:
        connection = http.client.HTTPConnection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=600)
        headers = {"Accept": self.headers.get("Accept", "*/*")}
        if body is not None:
            headers["Content-Type"] = self.headers.get("Content-Type", "application/json")

        try:
            connection.request(self.command, self.path, body=body, headers=headers)
            response = connection.getresponse()
            self.send_response(response.status)
            content_type = response.getheader("Content-Type")
            if content_type:
                self.send_header("Content-Type", content_type)
            self.end_headers()
            tool_states: dict[int, dict[str, Any]] = {}
            while line := response.readline():
                self.wfile.write(normalize_response_line(line, tool_states))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            connection.close()

    def log_message(self, format_string: str, *args: object) -> None:
        print(f"{self.address_string()} {format_string % args}", flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 11434), AdapterHandler).serve_forever()
