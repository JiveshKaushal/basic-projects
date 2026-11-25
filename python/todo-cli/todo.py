"""Minimal to-do list stored in todos.json.

Usage:
  python3 todo.py add "Task text"
  python3 todo.py list
  python3 todo.py done <number>
  python3 todo.py remove <number>
"""
import json
import sys
from pathlib import Path

DB = Path(__file__).with_name("todos.json")


def load() -> list:
    return json.loads(DB.read_text()) if DB.exists() else []


def save(todos: list) -> None:
    DB.write_text(json.dumps(todos, indent=2))


def main(argv: list) -> None:
    todos = load()
    cmd = argv[0] if argv else "list"
    if cmd == "add" and len(argv) > 1:
        todos.append({"text": " ".join(argv[1:]), "done": False})
        save(todos)
        print("Added.")
    elif cmd == "list":
        if not todos:
            print("No tasks yet.")
        for i, t in enumerate(todos, 1):
            print(f"{i}. [{'x' if t['done'] else ' '}] {t['text']}")
    elif cmd in {"done", "remove"} and len(argv) > 1 and argv[1].isdigit():
        i = int(argv[1]) - 1
        if not 0 <= i < len(todos):
            print("No such task.")
            return
        if cmd == "done":
            todos[i]["done"] = True
        else:
            todos.pop(i)
        save(todos)
        print("Updated.")
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
