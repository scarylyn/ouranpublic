#!/usr/bin/env python3
"""Build no-install reviewer files from the translation review CSV."""

import argparse
import csv
import json
from pathlib import Path


FEEDBACK_FIELDS = [
    "file",
    "id",
    "type",
    "speaker",
    "jp",
    "current_english",
    "suggested_english",
    "notes",
    "status",
]


def read_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def feedback_row(row):
    return {
        "file": row.get("file", ""),
        "id": row.get("id", ""),
        "type": row.get("type", ""),
        "speaker": row.get("speaker", ""),
        "jp": row.get("jp", ""),
        "current_english": row.get("en", ""),
        "suggested_english": "",
        "notes": "",
        "status": "",
    }


def write_feedback_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FEEDBACK_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(feedback_row(row))


def editor_html(rows):
    data = json.dumps([
        {
            "file": r.get("file", ""),
            "id": r.get("id", ""),
            "type": r.get("type", ""),
            "speaker": r.get("speaker", ""),
            "status": r.get("status", ""),
            "jp": r.get("jp", ""),
            "en": r.get("en", ""),
        }
        for r in rows
    ], ensure_ascii=False)

    template = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ouran Translation Reviewer</title>
<style>
body { margin: 0; font-family: Arial, Helvetica, sans-serif; background: #f7f7f4; color: #202124; }
header { position: sticky; top: 0; z-index: 2; background: white; border-bottom: 1px solid #d9d9d2; padding: 12px 16px; }
h1 { margin: 0 0 10px; font-size: 20px; }
.controls { display: grid; grid-template-columns: minmax(180px,1fr) 190px 150px 150px 130px; gap: 8px; align-items: end; }
label { display: grid; gap: 4px; font-size: 12px; color: #676b70; }
input, select, textarea, button { font: inherit; border: 1px solid #d9d9d2; border-radius: 6px; }
input, select, button { min-height: 36px; padding: 6px 8px; }
button { cursor: pointer; color: white; background: #8b1e3f; border-color: #8b1e3f; }
main { padding: 14px 16px 32px; }
.summary { color: #676b70; }
.row { display: grid; grid-template-columns: 120px 1fr 1fr 1fr; gap: 10px; background: white; border: 1px solid #d9d9d2; border-radius: 8px; padding: 10px; margin-bottom: 10px; }
.meta { font-size: 12px; color: #676b70; overflow-wrap: anywhere; }
.box h2 { margin: 0 0 6px; font-size: 12px; color: #676b70; text-transform: uppercase; }
.text { white-space: pre-wrap; line-height: 1.35; }
textarea { width: 100%; min-height: 110px; padding: 8px; line-height: 1.35; resize: vertical; box-sizing: border-box; }
textarea.notes { min-height: 56px; margin-top: 6px; }
.feedback-status { margin-top: 6px; width: 100%; }
@media (max-width: 1000px) { .controls { grid-template-columns: 1fr 1fr; } .row { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<header>
  <h1>Ouran Translation Reviewer</h1>
  <div class="controls">
    <label>Search <input id="search" placeholder="English, Japanese, file, id"></label>
    <label>Chapter/file <select id="fileFilter"></select></label>
    <label>Type <select id="typeFilter"></select></label>
    <label>Show
      <select id="editFilter">
        <option value="all">All rows</option>
        <option value="edited">Only my edits</option>
        <option value="unedited">Only unedited</option>
      </select>
    </label>
    <button id="exportBtn">Download edits</button>
  </div>
</header>
<main>
  <p class="summary" id="summary"></p>
  <div id="rows"></div>
</main>
<script>
const rows = __DATA__;
const STORAGE_KEY = "ouran-review-edits-v1";
const edits = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
const rowsEl = document.getElementById("rows");
const summaryEl = document.getElementById("summary");
const searchEl = document.getElementById("search");
const fileFilter = document.getElementById("fileFilter");
const typeFilter = document.getElementById("typeFilter");
const editFilter = document.getElementById("editFilter");

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
function key(row) { return row.file + "#" + row.id; }
function save() { localStorage.setItem(STORAGE_KEY, JSON.stringify(edits)); }
function csvEscape(value) {
  value = String(value ?? "");
  return /[",\n\r]/.test(value) ? '"' + value.replace(/"/g, '""') + '"' : value;
}
function optionList(values, label) {
  return [`<option value="">${label}</option>`].concat(
    [...new Set(values.filter(Boolean))].sort().map(v => `<option>${escapeHtml(v)}</option>`)
  ).join("");
}
function exportEdits() {
  const fields = ["file","id","type","speaker","jp","current_english","suggested_english","notes","status"];
  const lines = [fields.join(",")];
  for (const row of rows) {
    const edit = edits[key(row)];
    if (!edit || (!edit.suggested_english && !edit.notes && !edit.status)) continue;
    lines.push(fields.map(field => {
      if (field === "current_english") return csvEscape(row.en);
      if (field === "suggested_english") return csvEscape(edit.suggested_english || "");
      if (field === "notes") return csvEscape(edit.notes || "");
      if (field === "status") return csvEscape(edit.status || "");
      return csvEscape(row[field] || "");
    }).join(","));
  }
  const blob = new Blob(["\ufeff" + lines.join("\n")], {type: "text/csv;charset=utf-8"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "ouran_review_edits.csv";
  a.click();
  URL.revokeObjectURL(a.href);
}
function render() {
  const q = searchEl.value.trim().toLowerCase();
  const file = fileFilter.value;
  const type = typeFilter.value;
  const mode = editFilter.value;
  const filtered = rows.filter(row => {
    const edit = edits[key(row)] || {};
    const hasEdit = !!(edit.suggested_english || edit.notes || edit.status);
    if (file && row.file !== file) return false;
    if (type && row.type !== type) return false;
    if (mode === "edited" && !hasEdit) return false;
    if (mode === "unedited" && hasEdit) return false;
    if (!q) return true;
    return [row.file, row.id, row.type, row.speaker, row.jp, row.en].join("\n").toLowerCase().includes(q);
  });
  const editedCount = Object.values(edits).filter(e => e.suggested_english || e.notes || e.status).length;
  summaryEl.textContent = `${filtered.length} rows shown. ${editedCount} rows with saved edits in this browser. Click Download edits when finished.`;
  rowsEl.innerHTML = filtered.slice(0, 300).map(row => {
    const k = key(row);
    const edit = edits[k] || {};
    const statusOptions = ["", "looks good", "needs edit", "question"].map(v =>
      `<option ${((edit.status || "") === v) ? "selected" : ""}>${escapeHtml(v)}</option>`
    ).join("");
    return `<section class="row" data-key="${escapeHtml(k)}">
      <div class="meta"><strong>${escapeHtml(row.file)}</strong><br>id: ${escapeHtml(row.id)}<br>type: ${escapeHtml(row.type)}<br>speaker: ${escapeHtml(row.speaker)}<br>status: ${escapeHtml(row.status)}</div>
      <div class="box"><h2>Japanese</h2><div class="text">${escapeHtml(row.jp)}</div></div>
      <div class="box"><h2>Current English</h2><div class="text">${escapeHtml(row.en)}</div></div>
      <div class="box"><h2>Your Feedback</h2>
        <textarea data-field="suggested_english" placeholder="Suggested English, if changing this line">${escapeHtml(edit.suggested_english || "")}</textarea>
        <textarea class="notes" data-field="notes" placeholder="Notes, concern, typo, tone issue">${escapeHtml(edit.notes || "")}</textarea>
        <select class="feedback-status" data-field="status">${statusOptions}</select>
      </div>
    </section>`;
  }).join("");
  if (filtered.length > 300) rowsEl.insertAdjacentHTML("beforeend", `<p class="summary">Showing first 300 matching rows. Narrow the search/filter to see more.</p>`);
}
fileFilter.innerHTML = optionList(rows.map(r => r.file), "All files");
typeFilter.innerHTML = optionList(rows.map(r => r.type), "All types");
for (const el of [searchEl, fileFilter, typeFilter, editFilter]) el.addEventListener("input", render);
document.getElementById("exportBtn").addEventListener("click", exportEdits);
rowsEl.addEventListener("input", event => {
  const field = event.target.dataset.field;
  if (!field) return;
  const section = event.target.closest(".row");
  const k = section.dataset.key;
  edits[k] = edits[k] || {};
  edits[k][field] = event.target.value;
  save();
});
render();
</script>
</body>
</html>
"""
    return template.replace("__DATA__", data)


def write_start_here(path):
    path.write_text(
        """Ouran Translation Review - Start Here

You do not need programming tools to review this translation.

Easiest option:
1. Open reviewer_editor.html in Chrome, Edge, Firefox, or Safari.
2. Search or choose a chapter/file.
3. Type suggested English only for lines you want changed.
4. Add notes for anything that sounds wrong, confusing, out of character, or too literal.
5. Click Download edits.
6. Send back the downloaded ouran_review_edits.csv file.

Spreadsheet option:
1. Open reviewer_feedback_template.csv in Excel, LibreOffice, or Google Sheets.
2. Do not edit file, id, type, speaker, jp, or current_english.
3. Put replacement wording in suggested_english.
4. Put comments in notes.
5. Put looks good, needs edit, or question in status if useful.
6. Send back the edited CSV.

Reading-only option:
- Open review_transcripts/ and pick a chapter Markdown file.
- Send feedback by quoting the line and the file name.

Helpful feedback:
- Better natural English.
- Wrong name, honorific, gender, or relationship.
- A line that sounds out of character.
- A line that is confusing without context.
- Typos, missing spaces, or leftover Japanese.

Please include the file and id whenever possible. That lets us apply fixes quickly.
""",
        encoding="utf-8",
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build simple reviewer packet files")
    parser.add_argument("--review-csv", default="release/full_translation_review.csv")
    parser.add_argument("--out-dir", default="release")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    rows = read_rows(args.review_csv)
    write_feedback_csv(out_dir / "reviewer_feedback_template.csv", rows)

    chapter_dir = out_dir / "reviewer_chapter_csvs"
    chapter_dir.mkdir(parents=True, exist_ok=True)
    by_file = {}
    for row in rows:
        by_file.setdefault(row.get("file", "unknown"), []).append(row)
    for name, file_rows in sorted(by_file.items()):
        write_feedback_csv(chapter_dir / name.replace(".json", ".csv"), file_rows)

    (out_dir / "reviewer_editor.html").write_text(editor_html(rows), encoding="utf-8")
    write_start_here(out_dir / "START_HERE_REVIEWERS.txt")
    print(f"wrote reviewer packet to {out_dir}")
    print(f"rows={len(rows)} files={len(by_file)}")


if __name__ == "__main__":
    raise SystemExit(main())
