"""Conservative, plain-text math for paste imports and editable table cells.

Delimited math and escaped currency are cleaned. Unsupported expressions retain
their source instead of silently dropping operators. The queue retains the original paste.
"""
import re

_SYMBOLS = {
    "times": "×", "cdot": "·", "div": "÷", "pm": "±", "mp": "∓",
    "Delta": "Δ", "delta": "δ", "alpha": "α", "beta": "β",
    "gamma": "γ", "mu": "μ", "pi": "π", "theta": "θ",
    "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "neq": "≠",
    "approx": "≈", "rightarrow": "→", "to": "→", "infty": "∞",
    "circ": "°", "quad": " ", "qquad": " ", "left": "", "right": "",
    "tau": "τ", "propto": "∝", "sim": "∼", "gg": "≫", "ll": "≪",
}
_SUB = str.maketrans("0123456789+-=()aeioruvx", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑᵢₒᵣᵤᵥₓ")
_SUP = str.maketrans("0123456789+-=()ni", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱ")
_MATH = re.compile(
    r"(?P<slash>\\+)\((?P<inline>.*?)\\+\)"
    r"|\\+\[(?P<display>.*?)\\+\]"
    r"|(?<![\\$])\$\$(?P<block>.*?)\$\$(?!\$)"
    r"|(?<![\\$])\$(?!\$)(?P<dollar>[^$\n]+)\$(?!\$)", re.S)
TEXT_FIELDS = ("question_text", "stimulus", "passage", "rationale", "explanation",
               "choice_a", "choice_b", "choice_c", "choice_d", "choice_e", "subtopic", "tags")


def _expression(source):
    # Clipboard content may escape each LaTeX slash more than once.
    source = re.sub(r"\\{2,}", lambda _: "\\", source)
    pos = 0

    def group():
        nonlocal pos
        if pos >= len(source) or source[pos] != "{":
            raise ValueError("Expected group")
        pos += 1
        return parse(True)

    def parse(grouped=False):
        nonlocal pos
        result = ""
        while pos < len(source):
            char = source[pos]
            pos += 1
            if char == "}":
                if not grouped:
                    raise ValueError("Unexpected brace")
                return result
            if char == "{":
                pos -= 1
                result += group()
            elif char == "\\":
                command = re.match(r"[A-Za-z]+|.", source[pos:])
                if not command:
                    raise ValueError("Incomplete command")
                name = command[0]
                pos += len(name)
                if name in ("text", "mathrm", "mathbf", "mathit", "operatorname", "boxed"):
                    result += group()
                elif name in ("frac", "dfrac", "tfrac"):
                    numerator, denominator = group(), group()
                    result += f"({numerator})/({denominator})"
                elif name == "sqrt":
                    result += f"√({group()})"
                elif name == "dot":
                    value = group()
                    if len(value) != 1:
                        raise ValueError("Unsupported accent group")
                    result += value + "\u0307"
                elif name in _SYMBOLS:
                    result += _SYMBOLS[name]
                elif name in (",", ";", ":", " ", "!"):
                    result += "" if name == "!" else " "
                elif name in ("%", "$", "{", "}", "_"):
                    result += name
                else:
                    raise ValueError("Unsupported command")
            elif char in "_^":
                if pos >= len(source):
                    raise ValueError("Incomplete script")
                if source[pos] == "{":
                    script = group()
                elif source[pos] == "\\":
                    command = re.match(r"\\[A-Za-z]+", source[pos:])
                    if not command:
                        raise ValueError("Unsupported script command")
                    pos += len(command[0])
                    if command[0][1:] in ("text", "mathrm", "mathbf", "mathit", "operatorname"):
                        script = group()
                    else:
                        script = _expression(command[0])
                else:
                    script = source[pos]
                    pos += 1
                table = _SUB if char == "_" else _SUP
                if char == "^" and script == "°":
                    result += script
                else:
                    result += script.translate(table) if script and all(ord(c) in table for c in script) else char + (script if len(script) == 1 else "(" + script + ")")
            else:
                result += char
        if grouped:
            raise ValueError("Unclosed group")
        return result

    return parse()


def readable_math(text):
    if not isinstance(text, str):
        return text

    def replace(match):
        source = next(match[name] for name in ("inline", "display", "block", "dollar") if match[name] is not None)
        # A pair of currency amounts is not a math span.
        plain_math = re.fullmatch(
            r"(?:[A-Za-z]{1,12}[0-9]*|[A-Za-z]:[A-Za-z]|(?:[A-Za-z]{1,3}\s*)?[<>]?\s*[0-9][0-9.,:/+%−–— -]*)",
            source)
        if match["dollar"] is not None and not re.search(r"[\\_^=]", source) and not plain_math:
            return match[0]
        try:
            return _expression(source)
        except ValueError:
            return match[0]

    # Unescape currency only after identifying math, so two currency amounts
    # cannot accidentally become a dollar-delimited expression.
    return re.sub(r"\\+\$", "$", _MATH.sub(replace, text))


def readable_question_text(text):
    """Plain text for the question card, clipboard, and speech controls."""
    text = readable_math(text)
    if not isinstance(text, str):
        return text
    # Remove paired Markdown emphasis, retaining the words and math operators.
    for marker in ("**", "__", "*", "_"):
        pattern = r"(?<!\w)" + re.escape(marker) + r"(?=\S)(.+?)(?<=\S)" + re.escape(marker) + r"(?!\w)"
        text = re.sub(pattern, r"\1", text)
    return text


def math_markdown(text):
    """Adapt pasted LaTeX delimiters for Streamlit while retaining rich math.

    Streamlit renders dollar-delimited math, but not \\( ... \\) / \\[ ... \\].
    Leave existing dollar math and Markdown formatting intact.
    """
    def replace(match):
        inline = match.group("inline")
        display = match.group("display")
        if inline is None and display is None:
            return match[0]
        source = inline if inline is not None else display
        source = re.sub(r"\\{2,}", lambda _: "\\", source).strip()
        # A currency sign inside math must not close its enclosing math span.
        source = re.sub(r"(?<!\\)\$", lambda _: r"\$", source)
        if inline is not None:
            return "$" + source + "$"
        return "\n\n$$\n" + source + "\n$$\n\n"

    return _MATH.sub(replace, text)


def normalize_math_row(row):
    return {key: readable_math(value) if key in TEXT_FIELDS else value for key, value in row.items()}
