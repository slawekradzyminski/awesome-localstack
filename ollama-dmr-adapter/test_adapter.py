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


if __name__ == "__main__":
    unittest.main()
