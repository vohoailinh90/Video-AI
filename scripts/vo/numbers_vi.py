"""Vietnamese number words, so the synthesizer reads 62.958 as a number and not as a string of digits.

speak_text() rewrites the standalone numbers of a sentence and the version of a license-like name (AGPL-3.0 becomes AGPL ba chấm
không), not MP4 or Qwen3, whose digits belong to the name, and leaves everything else alone. The result goes to the synthesizer only; the displayed text keeps its digits.
"""
import re
import unicodedata

DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]
GROUPS = ["", " nghìn", " triệu", " tỷ"]


def plain_char(c: str) -> str:
    """The plain ASCII character that a compatibility form stands for, or c itself. A viewer reads Ｏ (full-width), 𝐎 (mathematical), K
    (Kelvin), ﬁ (ligature) and ⓞ (circled) as letters, ¹⁹ (superscript), ⑲ (circled) and ١٩ (Arabic-Indic) as digits, ／ ： － ． as the
    punctuation they imitate: the gate and the voice have to read them that way too, or a name, a number or an address made of them
    goes by unseen. Folding is one character at a time and only to ASCII, not NFKC of the text: NFKC turns ™ into the letters TM and
    … into three dots, which are not what is on the screen. Vietnamese letters, symbols and other alphabets are left alone."""
    if ord(c) < 128:
        return c
    if c in "\u2010\u2011\u2212":                         # the hyphen, the non-breaking hyphen and the minus sign: NFKC leaves them, they read as -
        return "-"
    category, folded = unicodedata.category(c), unicodedata.normalize("NFKC", c)
    if category[0] == "L" or category == "Nl":              # Nl: the Roman numeral characters, Ⅹ Ⅸ ... (NFKC: X IX)
        return folded if folded.isascii() and folded.isalpha() else c
    if category in ("Nd", "No"):
        if folded.isascii() and folded.isdigit():
            return folded
        if "\u2044" in folded and folded.replace("\u2044", "").isascii() and folded.replace("\u2044", "").isdigit():     # a vulgar fraction, ½ ⅓ ¼ (NFKC: 1⁄2): the numerator and the denominator, set apart
            return " " + folded.replace("\u2044", "/") + " "      # from a digit before it (1½ is 1 and 1/2) and from a % after it
        digit = unicodedata.digit(c, None)
        return str(digit) if digit is not None else c
    if category == "So" and len(folded) == 1 and folded.isascii() and folded.isalpha():
        return folded                                       # circled and squared Latin letters
    if category[0] in "PS" and len(folded) == 1 and folded.isascii() and not folded.isalnum() and not folded.isspace():
        return folded
    return c


def plain_text(text: str) -> str:
    return "".join(plain_char(c) for c in text)


# The signs of a number. Each has the look-alikes a page can show for it (full-width, small, heavy, superscript, a true hyphen); the facts
# gate reads the same ones (scripts/vo/check_facts.py imports these), so a sign cannot be swapped for a twin that is neither traced nor read.
PLUS = "+＋﹢➕⁺"
MINUS = "-−－﹣➖⁻‐‑"
PERCENT_SIGNS = "%％﹪٪"
SIGNS, PERCENT_CLASS = re.escape(PLUS + MINUS), re.escape(PERCENT_SIGNS)
# A sign stands right before its digits (-19), or one space before them (- 19, as a table or a bullet shows a change) when what comes
# before it is neither a word nor a number: "Stars - 62.958", "tăng + 19%" and "5 - 10" have a dash, an addition and a range, not a sign.
SIGN_BEFORE = (rf"(?<![\w.,{SIGNS}%])[{SIGNS}](?=(?:\$\s?)?\d)"
               rf"|(?<![\w.,{SIGNS}%])(?<![\w.,{SIGNS}%]\s)[{SIGNS}]\s(?=(?:\$\s?)?\d)")

# a number that stands alone: not glued to letters, a hyphen or another number; an optional minus (read "âm") or plus (read "cộng") sign in front and an
# optional percent sign after it (19% and 19 % are the same value to the facts gate, so both are read "phần trăm")
# a version glued to a name by a hyphen (AGPL-3.0, Apache-2.0) is read as a number; Qwen3, MP4 and gpt-4o keep their digits
VERSION = re.compile(rf"(?<=[A-Za-z])[{re.escape(MINUS)}](\d+(?:[.,]\d+)*)(?![\w])")
# The dollar sign is the one currency symbol in ASCII and part of the figure: $19 and $ 19 are a price, 19 is not (and 19$).
NUMBER = re.compile(rf"(?:({SIGN_BEFORE})|(?<![\w.,{re.escape(MINUS)}]))(\$\s?)?(\d+(?:[.,]\d+)*)(\s?[{PERCENT_CLASS}])?(\$)?(?![\w\-]|[.,]\d)")


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
        token = re.sub(r"[.,]", "", token)
    if re.fullmatch(r"\d+", token):
        if len(token) > 1 and token[0] == "0" or len(token) > 12:     # integer_words stops at 999 tỷ ... (12 digits)
            return _digit_by_digit(token)
        return integer_words(int(token))
    decimal = re.fullmatch(r"(\d+)([.,])(\d+)", token)       # 3.5 or 3,5
    if decimal:
        whole, sep, frac = decimal.groups()
        head = _token_words(whole)
        return f"{head} {'phẩy' if sep == ',' else 'chấm'} {_digit_by_digit(frac)}" if head else None
    return None                                              # 1.2.3 and the like


def speak_text(text: str) -> str:
    text = plain_text(text)         # what is read is what the viewer sees: ¹⁹% is 19%
    def replace(match):
        words = _token_words(match.group(3))
        if words is None:
            return match.group(0)
        sign = (match.group(1) or "")[:1]                        # the sign is group 1, with the space after it when it has one
        sign = "cộng " if sign and sign in PLUS else "âm " if sign else ""
        return sign + words + (" phần trăm" if match.group(4) else "") + (" đô la" if match.group(2) or match.group(5) else "")

    def version(match):
        words = _token_words(match.group(1))
        return match.group(0) if words is None else " " + words

    return NUMBER.sub(replace, VERSION.sub(version, text))
