#!/usr/bin/env python3
"""Agent-side graph process; intentionally accepts no database configuration."""

from __future__ import annotations

import argparse
import json
from typing import TypedDict

from http_checkpointer import HttpCheckpointer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class State(TypedDict, total=False):
    question: str
    answer: str
    result: str


def approval(state: State) -> State:
    answer = interrupt({"kind": "approval", "question": state["question"]})
    return {"answer": str(answer), "result": f"approved:{answer}"}


def graph(checkpointer: HttpCheckpointer):
    builder = StateGraph(State)
    builder.add_node("approval", approval)
    builder.add_edge(START, "approval")
    builder.add_edge("approval", END)
    return builder.compile(checkpointer=checkpointer)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-api", required=True)
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--resume")
    args = parser.parse_args()
    config = {"configurable": {"thread_id": args.thread_id}}
    input_value = (
        Command(resume=args.resume)
        if args.resume is not None
        else {"question": "Allow the bounded operation?"}
    )
    result = graph(HttpCheckpointer(args.state_api)).invoke(input_value, config)
    print(json.dumps(result, default=str, sort_keys=True))


if __name__ == "__main__":
    main()
