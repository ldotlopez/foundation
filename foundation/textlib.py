import re


def slugify(text: str, separator: str = "-") -> str:
    return re.sub(r"[^a-zA-Z0-9]", separator, text)
