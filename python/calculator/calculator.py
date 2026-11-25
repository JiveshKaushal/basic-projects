"""Simple command-line calculator."""

OPERATIONS = {
    "+": lambda a, b: a + b,
    "-": lambda a, b: a - b,
    "*": lambda a, b: a * b,
    "/": lambda a, b: a / b,
}


def calculate(a: float, op: str, b: float) -> float:
    if op not in OPERATIONS:
        raise ValueError(f"Unknown operator: {op}")
    if op == "/" and b == 0:
        raise ZeroDivisionError("Cannot divide by zero")
    return OPERATIONS[op](a, b)


def main() -> None:
    print("Calculator — enter e.g. '3 + 4' (or 'q' to quit)")
    while True:
        line = input("> ").strip()
        if line.lower() in {"q", "quit", "exit"}:
            break
        try:
            a, op, b = line.split()
            print(calculate(float(a), op, float(b)))
        except ValueError as e:
            print(f"Error: {e if 'operator' in str(e) else 'use the format: number op number'}")
        except ZeroDivisionError as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    main()
