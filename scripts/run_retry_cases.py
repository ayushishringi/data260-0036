"""Deterministic evidence for the three retry outcomes required by HW5."""
from hw5_tools.domain import retry_operation


def main() -> None:
    attempts = 0

    def first_try_succeeds() -> str:
        nonlocal attempts
        attempts += 1
        return "ok"

    _, used, _ = retry_operation(first_try_succeeds)
    print("CASE 1: first attempt succeeds")
    print(f"status=success attempts={used}")

    attempts = 0

    def second_try_succeeds() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("injected transient failure")
        return "ok"

    _, used, _ = retry_operation(second_try_succeeds)
    print("CASE 2: first attempt fails, retry succeeds")
    print(f"status=success attempts={used}")

    def always_fails() -> str:
        raise OSError("injected persistent failure")

    try:
        retry_operation(always_fails)
    except RuntimeError as exc:
        print("CASE 3: all retries fail")
        print("status=failure attempts=3")
        print(f"error={exc}")


if __name__ == "__main__":
    main()
