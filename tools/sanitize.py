"""Shift-JIS safety for inserted text.

The game stores and reads text as Shift-JIS. Machine translation (and humans on
modern keyboards) routinely emit characters that do NOT exist in Shift-JIS --
em dashes, accented Latin letters, ellipsis glyphs, etc. Writing any of these
during insertion raises UnicodeEncodeError and corrupts a batch run partway
through.

`sanitize()` maps the common offenders to Shift-JIS-safe equivalents and reports
anything it could not fix, so the pipeline can fail loudly on a single string
instead of dying mid-write.

Note: curly quotes (' ' " ") and the full-width space (U+3000, used by the game
for centering) ARE valid Shift-JIS and are deliberately left untouched.
"""

# Direct replacements for characters absent from Shift-JIS.
_REPLACEMENTS = {
    "—": "--",   # — em dash
    "–": "-",    # – en dash
    "…": "...",  # … horizontal ellipsis
    "é": "e", "è": "e", "ê": "e", "ë": "e",  # e accents
    "à": "a", "á": "a", "â": "a", "ä": "a",  # a accents
    "î": "i", "ï": "i", "í": "i", "ì": "i",  # i accents
    "ô": "o", "ö": "o", "ó": "o", "ò": "o",  # o accents
    "û": "u", "ü": "u", "ú": "u", "ù": "u",  # u accents
    "ā": "a", "ē": "e", "ī": "i", "ō": "o", "ū": "u",  # romanization macrons
    "Ā": "A", "Ē": "E", "Ī": "I", "Ō": "O", "Ū": "U",
    "ç": "c", "ñ": "n",                                # ç ñ
    "É": "E", "È": "E", "À": "A", "Ç": "C",  # caps
    "½": "1/2", "¾": "3/4", "¼": "1/4",
    "™": "(TM)", "®": "(R)", "©": "(C)",
    "′": "'", "″": '"',
}


def sanitize(text):
    """Return a Shift-JIS-encodable version of `text`.

    Raises ValueError listing any characters that still cannot be encoded after
    substitution, so callers can surface the exact offending string.
    """
    for bad, good in _REPLACEMENTS.items():
        text = text.replace(bad, good)
    try:
        text.encode("shiftjis")
    except UnicodeEncodeError:
        bad_chars = sorted({c for c in text if not _encodable(c)})
        detail = ", ".join(f"{c!r} (U+{ord(c):04X})" for c in bad_chars)
        raise ValueError(f"un-encodable character(s) for Shift-JIS: {detail}")
    return text


def _encodable(ch):
    try:
        ch.encode("shiftjis")
        return True
    except UnicodeEncodeError:
        return False


def check(text):
    """Non-raising check: return list of characters that cannot be encoded
    (after substitution). Empty list means the string is safe."""
    for bad, good in _REPLACEMENTS.items():
        text = text.replace(bad, good)
    return sorted({c for c in text if not _encodable(c)})
