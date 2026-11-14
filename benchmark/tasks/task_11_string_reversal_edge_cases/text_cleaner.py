def reverse_words(text: str) -> str:
    """Reverse order of words in text, preserving single spacing."""
    # Bug: naive split(' ') preserves empty string tokens on multiple spaces
    words = text.split(" ")
    return " ".join(reversed(words))
