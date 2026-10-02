"""Provider adapters: message conversion and parsing, tested without any network."""

from types import SimpleNamespace

import pytest

from app.llm.anthropic_llm import replayable_content, to_anthropic_messages, to_anthropic_tool
from app.llm.base import LLMUnavailableError, ToolCall, ToolSpec, parse_arguments, parse_text_tool_calls, strip_thinking
from app.llm.openai_compat import to_openai_messages, to_openai_tool
from app.llm.providers import ProviderRegistry
from tests.conftest import isolated_settings

CALL = ToolCall("call_1", "read_file", {"path": "src/app.py"})
RUN = [
    {"role": "user", "content": "Why does it crash?"},
    {"role": "assistant", "content": "Let me look.", "tool_calls": [CALL], "raw": None},
    {"role": "tool", "tool_call_id": "call_1", "name": "read_file", "content": "1 | import os", "is_error": False},
    {"role": "user", "content": "Answer now."},
]
SPEC = ToolSpec("read_file", "Read a file", {"type": "object", "properties": {"path": {"type": "string"}}})


def test_openai_messages_carry_tool_calls_and_results():
    out = to_openai_messages(RUN)

    assert out[1] == {
        "role": "assistant",
        "content": "Let me look.",
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "read_file", "arguments": '{"path": "src/app.py"}'},
            }
        ],
    }
    assert out[2] == {"role": "tool", "tool_call_id": "call_1", "content": "1 | import os"}
    assert out[3] == {"role": "user", "content": "Answer now."}


def test_openai_tool_shape():
    assert to_openai_tool(SPEC)["function"]["name"] == "read_file"
    assert to_openai_tool(SPEC)["type"] == "function"


def test_anthropic_merges_tool_results_and_following_text_into_one_user_turn():
    out = to_anthropic_messages(RUN)

    assert [m["role"] for m in out] == ["user", "assistant", "user"]
    assert out[1]["content"] == [
        {"type": "text", "text": "Let me look."},
        {"type": "tool_use", "id": "call_1", "name": "read_file", "input": {"path": "src/app.py"}},
    ]
    assert out[2]["content"] == [
        {"type": "tool_result", "tool_use_id": "call_1", "content": "1 | import os", "is_error": False},
        {"type": "text", "text": "Answer now."},
    ]


def test_anthropic_replays_this_runs_own_content_unchanged():
    raw = [SimpleNamespace(type="thinking"), SimpleNamespace(type="tool_use")]
    out = to_anthropic_messages(
        [{"role": "user", "content": "q"}, {"role": "assistant", "content": "", "tool_calls": [CALL], "raw": raw}]
    )
    assert out[1]["content"] is raw


def test_anthropic_tool_shape():
    assert to_anthropic_tool(SPEC) == {
        "name": "read_file",
        "description": "Read a file",
        "input_schema": SPEC.parameters,
    }


def test_declined_partial_before_a_fallback_is_not_replayed():
    blocks = [SimpleNamespace(type=t) for t in ("thinking", "text", "tool_use", "fallback", "thinking", "tool_use")]

    kept = [b.type for b in replayable_content(blocks)]

    assert kept == ["text", "fallback", "thinking", "tool_use"]


def test_text_tool_calls_from_small_models_are_recovered():
    text = 'Checking.\n<tool_call>{"name": "read_file", "arguments": {"path": "a.py"}}</tool_call>'

    rest, calls = parse_text_tool_calls(text, {"read_file"})

    assert rest == "Checking."
    assert calls[0].name == "read_file" and calls[0].arguments == {"path": "a.py"}


def test_text_tool_calls_for_unknown_tools_are_left_as_text():
    text = '<tool_call>{"name": "rm_rf", "arguments": {}}</tool_call>'
    assert parse_text_tool_calls(text, {"read_file"}) == (text, [])


def test_thinking_tags_are_removed():
    assert strip_thinking("<think>hmm, maybe</think>\nThe answer is 4.") == "The answer is 4."
    assert strip_thinking("<think>never closed") == ""


@pytest.mark.parametrize(
    "raw,expected", [('{"a": 1}', {"a": 1}), ({"a": 1}, {"a": 1}), ("not json", {}), (None, {}), ("[1]", {})]
)
def test_parse_arguments(raw, expected):
    assert parse_arguments(raw) == expected


def test_registry_reports_which_providers_are_ready():
    registry = ProviderRegistry(isolated_settings(anthropic_api_key="sk-ant-test"))

    ready = {s.spec.id: s.configured for s in registry.statuses()}

    assert ready["ollama"] is True and ready["anthropic"] is True
    assert ready["openai"] is False and ready["custom"] is False
    assert registry.default_model("anthropic") == "claude-opus-5-5"


def test_registry_explains_a_missing_key():
    registry = ProviderRegistry(isolated_settings())
    with pytest.raises(LLMUnavailableError) as err:
        registry.get("openai")
    assert err.value.user_message == "OpenAI isn't set up. Add OPENAI_API_KEY to .env."


def test_registry_builds_each_client_once():
    registry = ProviderRegistry(isolated_settings(groq_api_key="gsk-test"))
    assert registry.get("groq") is registry.get("groq")
