"""Does project memory actually save work? Measure it instead of guessing.

Each question is asked twice about the same project: once with long-term memory, once without. For each
run the script records the tool calls, files read, tokens and time. With memory the agent should find
answers in its notes instead of re-reading the code, so it should need fewer tool calls and tokens.

Runs pass remember=False, so the evaluation never writes into the memory it is measuring (no automatic
retain, and no save_note tool).

Usage (from the project root, with Hindsight running and the project learned first):
    python -m scripts.eval_memory <project-id> [--provider ollama] [--model qwen3:4b-instruct]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass

from app.agent import AgentRequest
from app.config import get_settings
from app.main import build_services

QUESTIONS = [
    "Which command runs this project's tests?",
    "Where is the HTTP API defined, and which framework does it use?",
    "What are the main folders of this project and what is each one for?",
    "Which environment variables does this project need?",
]


@dataclass
class Run:
    question: str
    memory: bool
    tool_calls: int = 0
    files_read: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    error: str | None = None


async def evaluate(project_id: str, provider: str, model: str | None) -> list[Run]:
    services = build_services(get_settings())
    project = services.projects.get(project_id)
    if project is None:
        names = ", ".join(p.id for p in services.projects.list()) or "none"
        sys.exit(f"No project '{project_id}' in the workspace. Projects: {names}")
    runs: list[Run] = []
    try:
        for question in QUESTIONS:
            for memory in (True, False):
                run = Run(question, memory)
                request = AgentRequest(
                    project, question, provider, model, mode="ask", use_memory=memory, remember=False
                )
                async for event in services.agent.run(request):
                    if event["type"] == "tool_end":
                        run.tool_calls += 1
                    elif event["type"] == "answer":
                        run.files_read = len(event["files_read"])
                        run.input_tokens = event["usage"]["input"]
                        run.output_tokens = event["usage"]["output"]
                        run.seconds = event["elapsed_ms"] / 1000
                    elif event["type"] == "error":
                        run.error = event["message"]
                runs.append(run)
                print(f"  {'memory' if memory else 'no memory':>9}  {question}", flush=True)
    finally:
        await services.memory.close()
    return runs


def report(runs: list[Run]) -> None:
    print(f"\n{'question':<58} {'memory':>8} {'tools':>6} {'files':>6} {'tokens in':>10} {'seconds':>8}")
    print("-" * 100)
    for run in runs:
        label = run.question if run.memory else ""
        if run.error:
            print(f"{label[:57]:<58} {'on' if run.memory else 'off':>8}  error: {run.error}")
            continue
        print(
            f"{label[:57]:<58} {'on' if run.memory else 'off':>8} {run.tool_calls:>6} {run.files_read:>6} "
            f"{run.input_tokens:>10,} {run.seconds:>8.1f}"
        )
    ok = [r for r in runs if not r.error]
    on = [r for r in ok if r.memory]
    off = [r for r in ok if not r.memory]
    if on and off:
        print("-" * 100)
        for name, group in (("with memory", on), ("without memory", off)):
            tools = sum(r.tool_calls for r in group) / len(group)
            tokens = sum(r.input_tokens for r in group) / len(group)
            print(f"average {name:<15} {tools:>5.1f} tool calls   {tokens:>9,.0f} input tokens")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("project_id")
    parser.add_argument("--provider", default=None, help="provider id; defaults to CODELOOP_DEFAULT_PROVIDER")
    parser.add_argument("--model", default=None)
    args = parser.parse_args()
    provider = args.provider or get_settings().default_provider
    print(f"Asking {len(QUESTIONS)} questions twice about '{args.project_id}' with {provider}...")
    report(asyncio.run(evaluate(args.project_id, provider, args.model)))


if __name__ == "__main__":
    main()
