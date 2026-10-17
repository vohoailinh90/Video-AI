"""Vietnamese number words, so the synthesizer reads 62.958 as a number and not as a string of digits.

speak_text() rewrites the standalone numbers of a sentence and the version of a license-like name (AGPL-3.0 becomes AGPL ba chấm
không), not MP4 or Qwen3, whose digits belong to the name, and leaves everything else alone. The result goes to the synthesizer only; the displayed text keeps its digits.
"""
import re

DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]
GROUPS = ["", " nghìn", " triệu", " tỷ"]

# a number that stands alone: not glued to letters, a hyphen or another number; an optional minus sign in front (read "âm") and an
# optional percent sign after it
# a version glued to a name by a hyphen (AGPL-3.0, Apache-2.0) is read as a number; Qwen3, MP4 and gpt-4o keep their digits
VERSION = re.compile(r"(?<=[A-Za-z])-(\d+(?:[.,]\d+)*)(?![\w])")
NUMBER = re.compile(r"(?<![\w.,\-−])([-−]?)(\d+(?:[.,]\d+)*)(%?)(?![\w\-]|[.,]\d)")


def _three(n: int, spoken_hundreds: bool) -> str:
    hundreds, rest = divmod(n, 100)
    tens, units = divmod(rest, 10)
    parts = []
    if hundreds or spoken_hundreds:
        parts.append(f"{DIGITS[hundreds]} trăm")
    if tens == 0:
        if units:
            parts.append(("lẻ " if (hundreds or spoken_hundreds) else "") + DIGITS[units])
    elif tens == 1:
        parts.append("mười" + ("" if units == 0 else " " + ("lăm" if units == 5 else DIGITS[units])))
    else:
        word = f"{DIGITS[tens]} mươi"
        if units:
            word += " " + ("mốt" if units == 1 else "lăm" if units == 5 else DIGITS[units])
        parts.append(word)
    return " ".join(parts)


def integer_words(n: int) -> str:
    if n == 0:
        return DIGITS[0]
    groups = []
    while n:
        groups.append(n % 1000)
        n //= 1000
    if len(groups) > len(GROUPS):
        raise ValueError("number too large")
    out = []
    for index in reversed(range(len(groups))):
        if groups[index]:
            out.append(_three(groups[index], index < len(groups) - 1) + GROUPS[index])
    return " ".join(out)


def _digit_by_digit(token: str) -> str:
    return " ".join(DIGITS[int(c)] for c in token if c.isdigit())


def _token_words(token: str):
    """Words for one number token, or None to leave it as it is."""
    if re.fullmatch(r"[1-9]\d{0,2}(?:[.,]\d{3})+", token):  # 62.958 and 62,958 -> thousands separators, as the facts gate reads them
        return integer_words(int(re.sub(r"[.,]", "", token)))
    if re.fullmatch(r"\d+", token):
        if len(token) > 1 and token[0] == "0" or len(token) > 12:
            return _digit_by_digit(token)
        return integer_words(int(token))
    decimal = re.fullmatch(r"(\d+)([.,])(\d+)", token)       # 3.5 or 3,5
    if decimal:
        whole, sep, frac = decimal.groups()
        head = _token_words(whole)
        return f"{head} {'phẩy' if sep == ',' else 'chấm'} {_digit_by_digit(frac)}" if head else None
    return None                                              # 1.2.3 and the like


def speak_text(text: str) -> str:
    def replace(match):
        words = _token_words(match.group(2))
        if words is None:
            return match.group(0)
        return ("âm " if match.group(1) else "") + words + (" phần trăm" if match.group(3) else "")

    def version(match):
        words = _token_words(match.group(1))
        return match.group(0) if words is None else " " + words

    return NUMBER.sub(replace, VERSION.sub(version, text))
