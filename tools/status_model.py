"""Shared status model for the translation workbench.

Every translatable pointer carries these fields (added incrementally by the
pipeline; older JSON without them is treated as 'untranslated'):

  Original Text : Japanese source (from extraction)         -- never edited
  MT Text       : raw Argos machine-translation             -- reference, never edited after MT
  New Text      : current best English -> this is what gets inserted into the ROM
  Status        : workflow stage (see STATUSES below)
  Note          : optional reviewer/AI note

Status lifecycle:
  untranslated -> mt (Argos first pass) -> ai (an AI reviewed it) -> approved (human signed off)

Anyone can promote/demote a line by editing New Text + Status. The ROM only ever
reads New Text, so Status is purely for tracking and review -- it never affects
insertion.
"""

# ordered best-to-rawest, for progress rollups
STATUSES = ["approved", "ai", "mt", "untranslated"]

STATUS_LABEL = {
    "untranslated": "Untranslated",
    "mt":           "Machine (Argos)",
    "ai":           "AI reviewed",
    "approved":     "Human approved",
}


def is_translatable(pointer):
    """A pointer worth translating = its Original Text contains Japanese."""
    s = pointer.get("Original Text", "")
    return any(0x3040 <= ord(c) <= 0x30FF or 0x4E00 <= ord(c) <= 0x9FFF
               or 0xFF66 <= ord(c) <= 0xFF9D for c in s)


def status_of(pointer):
    """Derive a pointer's status, tolerant of older JSON missing the field."""
    st = pointer.get("Status")
    if st in STATUS_LABEL:
        return st
    # infer for files translated before the status field existed
    return "mt" if pointer.get("New Text", "").strip() else "untranslated"


def file_progress(pointers):
    """Return a dict of counts for one file's translatable pointers."""
    counts = {s: 0 for s in STATUSES}
    translatable = 0
    for p in pointers:
        if not is_translatable(p):
            continue
        translatable += 1
        counts[status_of(p)] += 1
    counts["translatable"] = translatable
    # 'done' = anything past untranslated
    counts["done"] = translatable - counts["untranslated"]
    return counts
