import re


def search_tokens(text: str) -> str:
    words = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    for sequence in re.findall(r"[\u3400-\u9fff]+", text):
        words.extend(sequence)
        words.extend(sequence[i : i + 2] for i in range(len(sequence) - 1))
    return " ".join(dict.fromkeys(words))
