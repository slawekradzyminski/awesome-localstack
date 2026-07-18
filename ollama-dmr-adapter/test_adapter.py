import importlib.util
import json
import pathlib
import unittest


MODULE_PATH = pathlib.Path(__file__).with_name("adapter.py")
SPEC = importlib.util.spec_from_file_location("adapter", MODULE_PATH)
adapter = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(adapter)


class AdapterTest(unittest.TestCase):
    def test_removes_nulls_recursively(self) -> None:
        value = {"required": None, "properties": {"name": {"enum": None, "type": "string"}}}
        self.assertEqual(
            {"properties": {"name": {"type": "string"}}},
            adapter.without_nulls(value),
        )

    def test_decodes_stringified_tool_arguments(self) -> None:
        line = json.dumps(
            {
                "message": {
                    "tool_calls": [
                        {"function": {"name": "list_products", "arguments": '{"limit":25}'}}
                    ]
                }
            }
        ).encode() + b"\n"

        result = json.loads(adapter.normalize_response_line(line))
        self.assertEqual(
            {"limit": 25},
            result["message"]["tool_calls"][0]["function"]["arguments"],
        )

    def test_decodes_double_stringified_tool_arguments(self) -> None:
        arguments = json.dumps(json.dumps({"inStockOnly": True}))
        line = json.dumps(
            {"message": {"tool_calls": [{"function": {"arguments": arguments}}]}}
        ).encode()

        result = json.loads(adapter.normalize_response_line(line))
        self.assertEqual(
            {"inStockOnly": True},
            result["message"]["tool_calls"][0]["function"]["arguments"],
        )

    def test_joins_streamed_tool_arguments(self) -> None:
        states = {}
        first = json.dumps(
            {"message": {"tool_calls": [{"function": {"index": 0, "name": "list_products", "arguments": "{"}}]}}
        ).encode() + b"\n"
        second = json.dumps(
            {"message": {"tool_calls": [{"function": {"index": 0, "arguments": '\"limit\":25}'}}]}}
        ).encode() + b"\n"

        first_result = json.loads(adapter.normalize_response_line(first, states))
        second_result = json.loads(adapter.normalize_response_line(second, states))

        self.assertNotIn("tool_calls", first_result["message"])
        self.assertEqual(
            {"limit": 25},
            second_result["message"]["tool_calls"][0]["function"]["arguments"],
        )
        self.assertEqual(
            "list_products",
            second_result["message"]["tool_calls"][0]["function"]["name"],
        )

    def test_translates_generate_think_false_to_llama_cpp_switch(self) -> None:
        request = adapter.translate_ollama_request(
            "/api/generate",
            {
                "model": "bonsai",
                "prompt": "Reply with OK",
                "stream": True,
                "think": False,
                "options": {"temperature": 0.2, "num_predict": 10},
            },
        )

        self.assertEqual(
            {"enable_thinking": False},
            request["chat_template_kwargs"],
        )
        self.assertEqual(
            [{"role": "user", "content": "Reply with OK"}],
            request["messages"],
        )
        self.assertEqual(0.2, request["temperature"])
        self.assertEqual(10, request["max_tokens"])

    def test_does_not_translate_raw_learning_request(self) -> None:
        self.assertFalse(
            adapter.should_translate_thinking_request(
                "/api/generate", {"think": False, "raw": True}
            )
        )

    def test_keeps_thinking_enabled_request_on_ollama_endpoint(self) -> None:
        self.assertFalse(
            adapter.should_translate_thinking_request(
                "/api/generate", {"think": True}
            )
        )

    def test_translates_tool_history_to_openai_contract(self) -> None:
        request = adapter.translate_ollama_request(
            "/api/chat",
            {
                "model": "bonsai",
                "think": False,
                "messages": [
                    {"role": "user", "content": "List products"},
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "function": {
                                    "name": "list_products",
                                    "arguments": {"limit": 2},
                                },
                            }
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_name": "list_products",
                        "content": '{"products":[]}',
                    },
                ],
            },
        )

        self.assertEqual(
            '{"limit":2}',
            request["messages"][1]["tool_calls"][0]["function"]["arguments"],
        )
        self.assertEqual("call-1", request["messages"][2]["tool_call_id"])
        self.assertNotIn("tool_name", request["messages"][2])

    def test_converts_openai_generate_chunk_to_ollama(self) -> None:
        line = (
            b'data: {"choices":[{"finish_reason":null,"delta":{"content":"OK"}}],'
            b'"created":123,"object":"chat.completion.chunk"}\n'
        )

        result = json.loads(
            adapter.normalize_openai_response_line(line, "generate", "bonsai")
        )

        self.assertEqual("bonsai", result["model"])
        self.assertEqual("OK", result["response"])
        self.assertFalse(result["done"])
        self.assertNotIn("thinking", result)

    def test_converts_streamed_openai_tool_arguments_to_ollama_object(self) -> None:
        states = {}
        first = (
            b'data: {"choices":[{"finish_reason":null,"delta":{"tool_calls":['
            b'{"index":0,"id":"call-1","type":"function","function":'
            b'{"name":"list_products","arguments":"{"}}]}}],"created":123}\n'
        )
        second = (
            b'data: {"choices":[{"finish_reason":null,"delta":{"tool_calls":['
            b'{"index":0,"function":{"arguments":"\\\"limit\\\":2}"}}]}}],'
            b'"created":123}\n'
        )

        first_result = json.loads(
            adapter.normalize_openai_response_line(first, "chat", "bonsai", states)
        )
        second_result = json.loads(
            adapter.normalize_openai_response_line(second, "chat", "bonsai", states)
        )

        self.assertNotIn("tool_calls", first_result["message"])
        self.assertEqual(
            {"limit": 2},
            second_result["message"]["tool_calls"][0]["function"]["arguments"],
        )
        self.assertEqual(
            "call-1", second_result["message"]["tool_calls"][0]["id"]
        )


if __name__ == "__main__":
    unittest.main()
