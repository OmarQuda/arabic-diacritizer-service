import json
import re
from dataclasses import dataclass

DIACRITICS = frozenset(chr(c) for c in (*range(0x064B, 0x0653), 0x0670))
_MARKDOWN = re.compile(
    r"```|~~~|`|\*\*|__|\*[^*\n]+\*|_[^_\n]+_|"
    r"(?m:^\s{0,3}(?:#{1,6}\s|>\s|[-*+]\s|\d+\.\s))|\[[^\]]+\]\([^)]+\)"
)


def strip_diacritics(text: str) -> str:
    # Tatweel U+0640 is a base character, not a removable diacritic.
    return "".join(c for c in text if c not in DIACRITICS)


@dataclass(frozen=True)
class Verdict:
    valid: bool
    reason: str = ""
    detail: str = ""


def validate(source: str, output: str) -> Verdict:
    if not output.strip():
        return Verdict(False, "empty", "The provider returned empty text.")
    # Identical literal source syntax is legal; new wrappers are not.
    if _MARKDOWN.search(output) and not _MARKDOWN.search(source):
        return Verdict(False, "markdown", "The provider added Markdown formatting.")
    try:
        parsed = json.loads(output)
    except (ValueError, TypeError):
        parsed = None
    if isinstance(parsed, (dict, list)) and strip_diacritics(output) != strip_diacritics(source):
        return Verdict(False, "json", "The provider returned a JSON wrapper.")
    original, result = strip_diacritics(source), strip_diacritics(output)
    if original == result:
        return Verdict(True)
    before, after = original.split(), result.split()
    if len(after) > len(before):
        return Verdict(False, "added_words", "The provider added words.")
    if len(after) < len(before):
        return Verdict(False, "removed_words", "The provider removed words.")
    return Verdict(False, "changed_letters", "Base characters, spacing, or punctuation changed.")


def _marks(text: str) -> dict[int, str]:
    groups: dict[int, str] = {}
    position = 0
    for char in text:
        if char in DIACRITICS:
            groups[position] = groups.get(position, "") + char
        else:
            position += 1
    return groups


def _distance(a: str, b: str) -> int:
    row = list(range(len(b) + 1))
    for i, char in enumerate(a, 1):
        nxt = [i]
        for j, other in enumerate(b, 1):
            nxt.append(min(nxt[-1] + 1, row[j] + 1, row[j - 1] + (char != other)))
        row = nxt
    return row[-1]


def count_changed(before: str, after: str) -> int:
    a, b = _marks(before), _marks(after)
    return sum(_distance(a.get(i, ""), b.get(i, "")) for i in a.keys() | b.keys())
