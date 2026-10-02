"""The agent loop, driven by a scripted model: what it sends, what it streams, what it remembers."""

from app.agent import AgentRequest, trim_history
from app.llm.base import AssistantTurn, ToolCall, ToolsUnsupportedError, Usage
from app.tools import Toolbox
from app.workspace import Project
from tests.conftest import make_agent
from tests.fakes import DOWN, FakeMemoryStore, ScriptedLLM, answer, call


def project(root) -> Project:
    return Project("shop-api", "shop-api", root / "shop-api", False)


async def collect(agent, req):
    return [event async for event in agent.run(req)]


def kinds(events):
    return [e["type"] for e in events]


async def test_reads_a_file_then_answers_and_streams_each_step(workspace_root, memory):
    llm = ScriptedLLM(call("read_file", path="src/cart.py"), answer("`total` multiplies price by qty."))
    agent = make_agent(memory, llm, workspace_root)

    events = await collect(agent, AgentRequest(project(workspace_root), "How is the cart total computed?", "ollama"))

    assert kinds(events) == ["start", "memory", "tool_start", "tool_end", "answer"]
    tool_end = events[3]
    assert tool_end["ok"] is True and tool_end["summary"].startswith("Read src/cart.py")
    final = events[-1]
    assert final["text"] == "`total` multiplies price by qty."
    assert final["files_read"] == ["src/cart.py"]
    assert final["steps"] == 1
    assert final["usage"] == {"input": 220, "output": 50, "cached": 100}
    # The model saw the file contents as the tool result.
    tool_message = llm.calls[1]["messages"][-1]
    assert tool_message["role"] == "tool" and "def total(items)" in tool_message["content"]


async def test_recalled_notes_go_into_the_prompt_and_the_exchange_is_remembered(workspace_root, memory):
    memory.banks["shop-api"] = ["Tests run with pytest -q from the repo root"]
    llm = ScriptedLLM(answer("Run `pytest -q`."))
    agent = make_agent(memory, llm, workspace_root)

    events = await collect(
        agent, AgentRequest(project(workspace_root), "How do I run the tests?", "ollama", mode="test")
    )
    await agent.drain()

    assert events[1] == {"type": "memory", "available": True, "notes": [
        {"text": "Tests run with pytest -q from the repo root", "type": None, "occurred_at": None}]}  # fmt: skip
    assert "<memories>" in llm.calls[0]["system"] and "pytest -q from the repo root" in llm.calls[0]["system"]
    saved = memory.banks["shop-api"][-1]
    assert saved.startswith("Developer (test): How do I run the tests?") and "Agent: Run `pytest -q`." in saved
    assert memory.contexts[-1] == "coding session (test)"


async def test_remember_false_leaves_memory_untouched(workspace_root, memory):
    llm = ScriptedLLM(answer("ok"))
    agent = make_agent(memory, llm, workspace_root)

    await collect(agent, AgentRequest(project(workspace_root), "hi there", "ollama", remember=False))
    await agent.drain()

    assert memory.banks == {}
    assert "recall_memory" in llm.calls[0]["tools"] and "save_note" not in llm.calls[0]["tools"]


async def test_memory_off_means_no_recall_no_memory_tools_and_nothing_saved(workspace_root, memory):
    llm = ScriptedLLM(answer("ok"))
    agent = make_agent(memory, llm, workspace_root)

    events = await collect(agent, AgentRequest(project(workspace_root), "hello agent", "ollama", use_memory=False))
    await agent.drain()

    assert "memory" not in kinds(events)
    assert "recall_memory" not in llm.calls[0]["tools"]
    assert "Long-term memory is off" in llm.calls[0]["system"]
    assert memory.banks == {}


async def test_memory_outage_still_answers_and_says_so(workspace_root):
    memory = FakeMemoryStore(fail_recall=True)
    llm = ScriptedLLM(answer("Still here."))
    agent = make_agent(memory, llm, workspace_root)

    events = await collect(agent, AgentRequest(project(workspace_root), "anything", "ollama"))

    assert events[1]["available"] is False
    assert events[-1]["text"] == "Still here."
    assert "save_note" not in llm.calls[0]["tools"]


async def test_permissions_decide_which_tools_exist(workspace_root, memory):
    llm = ScriptedLLM(answer("a"), answer("b"))
    agent = make_agent(memory, llm, workspace_root)

    await collect(agent, AgentRequest(project(workspace_root), "q", "ollama"))
    await collect(agent, AgentRequest(project(workspace_root), "q", "ollama", allow_edits=True, allow_commands=True))

    read_only, full = llm.calls[0]["tools"], llm.calls[1]["tools"]
    assert {"read_file", "search_code", "list_files", "git_changes"} <= set(read_only)
    assert not {"edit_file", "write_file", "run_command"} & set(read_only)
    assert {"edit_file", "write_file", "run_command"} <= set(full)


async def test_a_tool_the_chat_does_not_allow_is_refused_even_if_called(workspace_root, memory, project_dir):
    llm = ScriptedLLM(call("write_file", path="src/evil.py", content="x"), answer("couldn't"))
    agent = make_agent(memory, llm, workspace_root)

    events = await collect(agent, AgentRequest(project(workspace_root), "q", "ollama"))

    assert events[3]["ok"] is False and "no tool called 'write_file'" in events[3]["summary"]
    assert not (project_dir / "src" / "evil.py").exists()


async def test_edits_show_a_diff_and_are_recorded(workspace_root, memory, project_dir):
    edit = call("edit_file", path="src/cart.py", old_text="    return []", new_text="    return list()")
    agent = make_agent(memory, ScriptedLLM(edit, answer("Changed it.")), workspace_root)

    events = await collect(
        agent, AgentRequest(project(workspace_root), "use list()", "ollama", mode="write", allow_edits=True)
    )

    tool_end = events[3]
    assert tool_end["kind"] == "diff" and "+    return list()" in tool_end["detail"]
    assert events[-1]["files_changed"] == ["src/cart.py"]
    assert "return list()" in (project_dir / "src" / "cart.py").read_text()


async def test_step_limit_forces_an_answer_without_tools(workspace_root, memory):
    looping = [call("list_files", path=".", depth=i) for i in range(1, 6)]
    llm = ScriptedLLM(*looping, answer("Here's what I found."))
    agent = make_agent(memory, llm, workspace_root, max_steps=2)

    events = await collect(agent, AgentRequest(project(workspace_root), "explore", "ollama"))

    assert events[-1]["type"] == "answer" and events[-1]["steps"] == 2
    assert [c["tool_choice"] for c in llm.calls] == ["auto", "auto", "none"]
    assert "step limit" in llm.calls[-1]["messages"][-1]["content"]


async def test_model_without_tool_support_falls_back_to_answering_directly(workspace_root, memory):
    unsupported = ToolsUnsupportedError("no tools", "'tiny' can't use tools, so it answers without reading code.")
    llm = ScriptedLLM(unsupported, answer("From memory: ..."))
    agent = make_agent(memory, llm, workspace_root)

    events = await collect(agent, AgentRequest(project(workspace_root), "q", "ollama", model="tiny"))

    assert "notice" in kinds(events) and events[-1]["text"] == "From memory: ..."
    assert llm.calls[1]["tools"] == []
    assert "can't use tools" in llm.calls[1]["system"]


async def test_model_outage_ends_with_an_error_event(workspace_root, memory):
    agent = make_agent(memory, ScriptedLLM(DOWN), workspace_root)

    events = await collect(agent, AgentRequest(project(workspace_root), "q", "ollama"))

    assert events[-1] == {"type": "error", "message": "Can't reach Ollama."}


async def test_unconfigured_provider_is_an_error_not_a_crash(workspace_root, memory):
    agent = make_agent(memory, ScriptedLLM(), workspace_root)

    events = await collect(agent, AgentRequest(None, "q", "anthropic"))

    assert events == [{"type": "error", "message": "Anthropic isn't set up. Add ANTHROPIC_API_KEY to .env."}]


async def test_chat_without_a_project_has_no_file_tools_and_uses_scratch_memory(workspace_root, memory):
    llm = ScriptedLLM(call("save_note", note="Prefers type hints everywhere"), answer("Noted."))
    agent = make_agent(memory, llm, workspace_root)

    events = await collect(agent, AgentRequest(None, "I like type hints", "ollama"))
    await agent.drain()

    assert set(llm.calls[0]["tools"]) == {"recall_memory", "save_note"}
    assert "No project is open" in llm.calls[0]["system"]
    assert memory.banks["scratch"][0] == "Prefers type hints everywhere"
    assert events[-1]["notes_saved"] == 1


async def test_narration_between_tool_calls_is_streamed(workspace_root, memory):
    narrated = AssistantTurn(
        text="Let me look at the cart first.",
        tool_calls=[ToolCall("c1", "read_file", {"path": "src/cart.py"})],
        usage=Usage(1, 1),
    )
    agent = make_agent(memory, ScriptedLLM(narrated, answer("done")), workspace_root)

    events = await collect(agent, AgentRequest(project(workspace_root), "q", "ollama"))

    assert {"type": "thought", "text": "Let me look at the cart first."} in events


async def test_repeating_the_same_call_is_cut_short(workspace_root, memory):
    toolbox = Toolbox(None, memory, "scratch")
    same = ToolCall("x", "recall_memory", {"query": "tests"})

    results = [await toolbox.run(same) for _ in range(3)]

    assert [r.ok for r in results] == [True, True, False]


def test_trim_history_starts_on_a_developer_turn():
    history = [
        {"role": "user", "content": "1"},
        {"role": "assistant", "content": "2"},
        {"role": "user", "content": "3"},
    ]
    assert trim_history(history, 2) == [{"role": "user", "content": "3"}]
    assert trim_history(history, 0) == []
