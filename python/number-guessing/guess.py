"""Guess the number between 1 and 100."""
import random


def main() -> None:
    secret = random.randint(1, 100)
    attempts = 0
    print("I'm thinking of a number between 1 and 100.")
    while True:
        guess = input("Your guess: ").strip()
        if not guess.isdigit():
            print("Please enter a whole number.")
            continue
        attempts += 1
        n = int(guess)
        if n < secret:
            print("Too low!")
        elif n > secret:
            print("Too high!")
        else:
            print(f"Correct! You got it in {attempts} attempts.")
            break


if __name__ == "__main__":
    main()
