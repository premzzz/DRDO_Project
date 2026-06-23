"""
html_report.py
--------------
Generates a single self-contained HTML coverage report from:
  - Original source files
  - coverage.log  (one flag name per line, written by the instrumented binary)
  - block_map per file (produced by Analyser)

Colouring rules:
  - Blocks whose flag was hit     → green background
  - Blocks whose flag was never hit → red background
  - Inner block colour always wins over outer (most-specific wins)
  - Comments, blank lines, #define, #include → no highlight (neutral)
  - Hit count shown on right side of FIRST line of each block only
"""

import re
import html
from collections import Counter
from pathlib import Path


# ---------------------------------------------------------------------------
# Non-executable line detector
# ---------------------------------------------------------------------------

_BLANK_RE       = re.compile(r"^\s*$")
_LINE_COMMENT   = re.compile(r"^\s*//")
_BLOCK_COMMENT  = re.compile(r"^\s*/\*")
_PREPROC        = re.compile(r"^\s*#")

def is_neutral_line(line: str) -> bool:
    """Returns True for lines that can never be 'executed'."""
    return bool(
        _BLANK_RE.match(line)
        or _LINE_COMMENT.match(line)
        or _BLOCK_COMMENT.match(line)
        or _PREPROC.match(line)
    )


# ---------------------------------------------------------------------------
# Per-line colour resolver
# ---------------------------------------------------------------------------

def resolve_line_colours(
    source_lines: list[str],
    block_map: list[dict],
    counts: Counter,
) -> dict[int, dict]:
    """
    Returns a dict:  line_number (1-based) → {colour, hit_count, flag, is_first}

    colour    : "green" | "red" | None
    hit_count : int (only meaningful when colour == "green")
    flag      : flag name responsible for the colour
    is_first  : True if this is the first line of the block (shows the count)
    """
    total_lines = len(source_lines)

    # line_info[lineno] = list of (priority, colour, hit_count, flag, is_first)
    # priority = block length (shorter = more specific = higher priority)
    line_info: dict[int, list] = {i: [] for i in range(1, total_lines + 1)}

    for entry in block_map:
        flag       = entry["flag"]
        start      = entry["start_line"]
        end        = entry["end_line"]
        hit_count  = counts.get(flag, 0)
        colour     = "green" if hit_count > 0 else "red"
        span       = end - start + 1          # shorter span = higher specificity

        for lineno in range(start, end + 1):
            if lineno < 1 or lineno > total_lines:
                continue
            is_first = (lineno == start)
            line_info[lineno].append((span, colour, hit_count, flag, is_first))

    result: dict[int, dict] = {}
    for lineno, candidates in line_info.items():
        if not candidates:
            continue
        line_text = source_lines[lineno - 1]
        if is_neutral_line(line_text):
            continue   # never colour neutral lines
        # Sort by span ascending → shortest (most specific) block wins
        candidates.sort(key=lambda c: c[0])
        span, colour, hit_count, flag, is_first = candidates[0]

        # is_first: only mark as first if THIS entry is the shortest-span one
        # re-check: is this lineno the start_line of the winning block?
        winning_flag = flag
        winning_start = next(
            e["start_line"] for e in block_map if e["flag"] == winning_flag
        )
        is_first = (lineno == winning_start)

        result[lineno] = {
            "colour":    colour,
            "hit_count": hit_count,
            "flag":      flag,
            "is_first":  is_first,
        }

    return result


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    background: #fff;
    color: #111;
    font-family: Arial, sans-serif;
    padding: 24px;
}
h1 {
    font-size: 1.2rem;
    font-weight: bold;
    margin-bottom: 4px;
}
.subtitle {
    font-size: 0.82rem;
    color: #555;
    margin-bottom: 16px;
}
.summary {
    font-size: 0.9rem;
    margin-bottom: 24px;
}
.file-section { margin-bottom: 36px; }
.file-header {
    display: flex;
    align-items: baseline;
    gap: 12px;
    margin-bottom: 4px;
}
.file-title {
    font-size: 0.95rem;
    font-weight: bold;
}
.coverage-pct { font-size: 0.82rem; color: #444; }

.code-table {
    width: 100%;
    border-collapse: collapse;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 0.8rem;
    line-height: 1.5;
    border: 1px solid #ddd;
}

td.ln {
    width: 40px;
    text-align: right;
    padding: 0 8px;
    color: #aaa;
    user-select: none;
    border-right: 1px solid #ddd;
    vertical-align: top;
}
td.code {
    padding: 0 8px;
    white-space: pre;
    width: 100%;
}
td.hits {
    padding: 0 10px;
    text-align: right;
    white-space: nowrap;
    font-size: 0.75rem;
    color: #333;
    vertical-align: top;
    min-width: 60px;
}

/* Row colours — light green / light red */
tr.green td { background: #e6ffed; }
tr.red   td { background: #fff0f0; }

/* Legend */
.legend {
    display: flex;
    gap: 16px;
    margin-bottom: 8px;
    font-size: 0.78rem;
}
.legend-dot {
    width: 12px; height: 12px;
    display: inline-block;
    margin-right: 4px;
    vertical-align: middle;
    border: 1px solid #ccc;
}
.dot-green { background: #e6ffed; }
.dot-red   { background: #fff0f0; }
.dot-none  { background: #fff; }
"""


def _html_line(lineno: int, raw_line: str, info: dict | None) -> str:
    colour    = info["colour"]    if info else None
    hit_count = info["hit_count"] if info else 0
    is_first  = info["is_first"]  if info else False

    row_class = f' class="{colour}"' if colour else ""

    # hits cell
    if colour == "green" and is_first:
        hits_html = f'<span title="{info["flag"]}">×{hit_count}</span>'
    elif colour == "red" and is_first:
        hits_html = '<span title="never executed">✗</span>'
    else:
        hits_html = ""

    code_html = html.escape(raw_line.rstrip("\n"))

    return (
        f'<tr{row_class}>'
        f'<td class="ln">{lineno}</td>'
        f'<td class="code">{code_html}</td>'
        f'<td class="hits">{hits_html}</td>'
        f'</tr>\n'
    )


def build_file_page(filename: str, rel_name: str, file_pct: int,
                     file_hit_flags: int, file_flags: int, rows_html: str) -> str:
    """Builds one standalone HTML page for a single source file."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(filename)} — Coverage</title>
<style>
{CSS}
</style>
</head>
<body>
<p><a href="index.html">&larr; Back to file list</a></p>
<div class="file-section">
  <div class="file-header">
    <span class="file-title">{html.escape(filename)}</span>
    <span class="coverage-pct">{file_pct}% covered ({file_hit_flags}/{file_flags})</span>
  </div>
  <table class="code-table">
    <tbody>
{rows_html}    </tbody>
  </table>
</div>

<div class="legend">
  <span><span class="legend-dot dot-green"></span>Executed</span>
  <span><span class="legend-dot dot-red"></span>Never executed</span>
  <span><span class="legend-dot dot-none"></span>Non-executable</span>
</div>
</body>
</html>"""


def build_index_html(file_summaries: list[dict], log_path: str) -> str:
    """
    file_summaries: [{filename, page_name, pct, hit, total}]
    Builds the landing page — a list of files with coverage %, each linking
    to its own page.
    """
    all_flags = sum(f["total"] for f in file_summaries)
    hit_flags = sum(f["hit"] for f in file_summaries)
    pct_overall = int(100 * hit_flags / all_flags) if all_flags else 0

    rows = []
    for f in file_summaries:
        rows.append(
            f'<tr>'
            f'<td class="idx-file"><a href="{html.escape(f["page_name"])}">{html.escape(f["filename"])}</a></td>'
            f'<td class="idx-pct">{f["pct"]}% ({f["hit"]}/{f["total"]})</td>'
            f'</tr>\n'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Coverage Report</title>
<style>
{CSS}
.idx-table {{
    width: 100%;
    border-collapse: collapse;
    font-family: Arial, sans-serif;
    font-size: 0.9rem;
    margin-top: 16px;
}}
.idx-table td {{
    padding: 8px 10px;
    border-bottom: 1px solid #eee;
}}
.idx-file a {{
    color: #1155cc;
    text-decoration: none;
    font-family: 'Consolas', 'Courier New', monospace;
}}
.idx-file a:hover {{ text-decoration: underline; }}
.idx-pct {{ text-align: right; color: #444; white-space: nowrap; }}
</style>
</head>
<body>
<h1>Coverage Report</h1>
<div class="subtitle">Log: {html.escape(log_path)} &nbsp;·&nbsp; {len(file_summaries)} file(s)</div>
<div class="summary">Blocks covered: <strong>{pct_overall}%</strong> ({hit_flags}/{all_flags})</div>

<table class="idx-table">
  <tbody>
{''.join(rows)}  </tbody>
</table>
</body>
</html>"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _make_page_name(rel_path: Path) -> str:
    """
    Turns a relative source path into a unique, readable HTML filename.
    e.g.  drivers/sensor.c  ->  drivers_sensor.c.html
          main.c            ->  main.c.html
    """
    safe = str(rel_path).replace("/", "_").replace("\\", "_")
    return f"{safe}.html"


def generate_report(
    source_files: list[str],
    log_path: str = "coverage.log",
    output_dir: str = "coverage_report",
    base_folder: str | None = None,
):
    """
    Generates a coverage_report/ folder containing:
      index.html         — list of files + overall coverage %, clickable
      <file>.html         — one page per source file, same style as before

    base_folder: if given, page names are derived from each file's path
                 relative to this folder (keeps nested files unique and
                 readable, e.g. drivers_sensor.c.html). Defaults to using
                 just the filename if not provided.
    """
    from instrumenter import Analyser

    log = Path(log_path)
    if not log.exists():
        print(f"[ERROR] {log_path} not found. Run the instrumented binary first.")
        return

    counts = Counter(l.strip() for l in log.read_text().splitlines() if l.strip())

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    base = Path(base_folder) if base_folder else None

    file_summaries = []   # for index.html

    for src in source_files:
        p = Path(src)
        if not p.exists():
            print(f"[WARN] {src} not found, skipping.")
            continue

        source = p.read_text(encoding="utf-8")
        analyser = Analyser(source, p.stem)
        analyser.run()   # populate block_map without writing files

        norm_source = analyser.source       # matches block_map line numbers
        block_map   = analyser.block_map
        lines       = norm_source.splitlines(keepends=True)

        line_colours = resolve_line_colours(lines, block_map, counts)

        rows = []
        for i, raw in enumerate(lines, start=1):
            info = line_colours.get(i)
            rows.append(_html_line(i, raw, info))
        rows_html = "".join(rows)

        file_flags     = len(block_map)
        file_hit_flags = sum(1 for b in block_map if counts.get(b["flag"], 0) > 0)
        file_pct       = int(100 * file_hit_flags / file_flags) if file_flags else 0

        # Display name: relative to base_folder if given, else just filename
        if base:
            try:
                rel_path = p.resolve().relative_to(base.resolve())
            except ValueError:
                rel_path = Path(p.name)
        else:
            rel_path = Path(p.name)

        display_name = str(rel_path)
        page_name = _make_page_name(rel_path)

        page_html = build_file_page(
            display_name, page_name, file_pct, file_hit_flags, file_flags, rows_html
        )
        (out_dir / page_name).write_text(page_html, encoding="utf-8")

        file_summaries.append({
            "filename":  display_name,
            "page_name": page_name,
            "pct":       file_pct,
            "hit":       file_hit_flags,
            "total":     file_flags,
        })

    # Sort index alphabetically by filename for a stable, predictable list
    file_summaries.sort(key=lambda f: f["filename"])

    index_html = build_index_html(file_summaries, log_path)
    index_path = out_dir / "index.html"
    index_path.write_text(index_html, encoding="utf-8")

    print(f"✅  Report written: {out_dir}/  ({len(file_summaries)} file page(s) + index.html)")
    return index_path


if __name__ == "__main__":
    import argparse, sys, webbrowser

    if len(sys.argv) > 1:
        # Ran from terminal with arguments — use argparse
        ap = argparse.ArgumentParser(
            description="Generate HTML coverage report from a folder of original .c files."
        )
        ap.add_argument("folder", metavar="FOLDER",
                        help="Path to project folder (scanned recursively for .c files)")
        ap.add_argument("--log",    default="coverage.log",      help="coverage.log path")
        ap.add_argument("--output", default="coverage_report",   help="Output folder (default: coverage_report/)")
        args = ap.parse_args()
        folder  = args.folder
        log     = args.log
        output  = args.output
    else:
        # Ran directly (e.g. IDLE "Run") with no arguments — prompt instead
        print("=== HTML Coverage Report Generator ===")
        folder = input("Project folder path (original .c files, subfolders included): ").strip()

        log_in = input("coverage.log path [coverage.log]: ").strip()
        log = log_in if log_in else "coverage.log"

        output_in = input("Output folder [coverage_report]: ").strip()
        output = output_in if output_in else "coverage_report"

    folder_path = Path(folder)
    if not folder_path.is_dir():
        print(f"❌  Not a valid folder: {folder}")
        sys.exit(1)

    sources = sorted(str(p) for p in folder_path.rglob("*.c"))
    if not sources:
        print(f"❌  No .c files found in: {folder} (or its subfolders)")
        sys.exit(1)

    print(f"\n📂  Found {len(sources)} .c file(s) in {folder_path}/ (including subfolders)")

    # Safety check: warn if this looks like the INSTRUMENTED folder, not the original
    already_instrumented = [
        s for s in sources if "LOG_FLAG(" in Path(s).read_text(encoding="utf-8")
    ]
    if already_instrumented:
        print(f"⚠️   Warning: {len(already_instrumented)} file(s) already contain LOG_FLAG(...) calls.")
        print(f"     This looks like the INSTRUMENTED folder, not your original source.")
        print(f"     Point this script at your ORIGINAL project folder instead.\n")

    index_path = generate_report(sources, log, output, base_folder=folder)
    if index_path:
        webbrowser.open(index_path.resolve().as_uri())
