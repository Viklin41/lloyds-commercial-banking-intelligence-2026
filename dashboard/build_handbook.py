"""Build a document: <name>.md  ->  .html  ->  .pdf

Run it after editing the markdown and the other two follow. Nothing here writes
prose; the markdown is the only source, and this just dresses it for paper.

    python dashboard/build_handbook.py                  # the handbook
    python dashboard/build_handbook.py dashboard_design # the design doc
    python dashboard/build_handbook.py --open           # ...and open it

Headless Chrome is the only PDF engine on these machines (no pandoc, no
wkhtmltopdf) and recent builds ignore --print-to-pdf without saying so, so
--open is the reliable route: it opens the HTML in the browser and you print
to PDF with Ctrl+P yourself.
"""
import io
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent

args = [a for a in sys.argv[1:] if not a.startswith("-")]
OPEN_IT = "--open" in sys.argv[1:]
STEM = (args[0] if args else "dashboard_handbook").removesuffix(".md")

MD = HERE / f"{STEM}.md"
HTML = HERE / f"{STEM}.html"
PDF = HERE / f"{STEM}.pdf"

# Print styling. Screen-first CSS would waste ink and split tables across pages,
# so this is written for A4 and the page-break rules are the point of it.
CSS = """
@page { size: A4; margin: 18mm 16mm; }
:root{ --ink:#0d1512; --rule:#d8e0dc; --green:#046A38; --mint:#0f8f6a; }
*{ box-sizing:border-box; }
body{
  font-family:"Segoe UI Variable Text","Segoe UI",system-ui,sans-serif;
  font-size:10.6pt; line-height:1.62; color:var(--ink);
  max-width:190mm; margin:0 auto; padding:14mm 6mm 20mm;
  -webkit-font-smoothing:antialiased;
}
h1{ font-size:23pt; line-height:1.2; margin:0 0 4mm; color:var(--green);
    letter-spacing:-.01em; border-bottom:2.5px solid var(--green); padding-bottom:4mm; }
h2{ font-size:15pt; margin:11mm 0 3mm; color:var(--green); letter-spacing:-.005em;
    page-break-after:avoid; break-after:avoid; }
h3{ font-size:12pt; margin:7mm 0 2mm; color:var(--mint);
    page-break-after:avoid; break-after:avoid; }
p{ margin:0 0 3.4mm; }
strong{ color:#08120f; font-weight:650; }
em{ color:#33443e; }
a{ color:var(--mint); }
hr{ border:0; border-top:1px solid var(--rule); margin:9mm 0; }

/* A table split across a page boundary is unreadable, hence the break rules. */
table{ border-collapse:collapse; width:100%; margin:4mm 0 6mm; font-size:9.3pt;
       page-break-inside:avoid; break-inside:avoid; }
th{ text-align:left; background:#eef4f1; color:#08251c; font-weight:650;
    padding:2.2mm 3mm; border-bottom:1.5px solid var(--green); }
td{ padding:2.2mm 3mm; border-bottom:1px solid var(--rule); vertical-align:top; }
tr:nth-child(even) td{ background:#fafcfb; }

code{ font-family:"Cascadia Mono",Consolas,ui-monospace,monospace; font-size:9pt;
      background:#eef4f1; padding:.4mm 1.4mm; border-radius:2px; color:#0a3c2c; }
pre{ background:#f4f8f6; border:1px solid var(--rule); border-left:3px solid var(--green);
     padding:3.5mm 4mm; border-radius:3px; overflow-x:auto;
     page-break-inside:avoid; break-inside:avoid; }
pre code{ background:none; padding:0; font-size:8.8pt; line-height:1.5; }

/* The screenshots are dark, so they get a light rule to sit against the page. */
img{ max-width:100%; height:auto; display:block; margin:4mm auto 6mm;
     border:1px solid var(--rule); border-radius:4px;
     page-break-inside:avoid; break-inside:avoid; }

ul{ margin:0 0 3.4mm; padding-left:6mm; }
li{ margin-bottom:1.6mm; }

@media print{
  body{ padding:0; max-width:none; }
  a{ color:var(--ink); text-decoration:none; }   /* a blue underline on paper is noise */
}
@media screen{ html{ background:#e9eeec; } body{ background:#fff; } }
"""

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]


def build_html():
    try:
        import markdown
    except ImportError:
        sys.exit("The `markdown` package is required:  pip install markdown")
    src = io.open(MD, encoding="utf-8").read()
    body = markdown.markdown(
        src, extensions=["tables", "fenced_code", "sane_lists", "attr_list"])
    title = src.lstrip().splitlines()[0].lstrip("# ").strip()
    io.open(HTML, "w", encoding="utf-8", newline="").write(
        f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8">\n'
        f"<title>{title}</title>\n<style>{CSS}</style>\n</head><body>\n{body}\n</body></html>")
    print(f"html : {HTML.name}  ({body.count('<table>')} tables, "
          f"{body.count('<img')} images)")
    return body


def build_pdf():
    chrome = next((c for c in CHROME_CANDIDATES if Path(c).exists()), None) \
        or shutil.which("chrome") or shutil.which("msedge")
    if not chrome:
        print("pdf  : skipped, no Chrome or Edge found. "
              "Open the HTML and print it with Ctrl+P instead.")
        return False
    # file:// rather than the dev server, so this works whether or not it is running.
    subprocess.run([chrome, "--headless", "--disable-gpu", "--no-sandbox",
                    "--no-pdf-header-footer",
                    f"--print-to-pdf={PDF}", HTML.resolve().as_uri()],
                   check=True, capture_output=True, timeout=180)
    print(f"pdf  : {PDF.name}  ({PDF.stat().st_size:,} bytes)")
    return True


def open_in_browser():
    chrome = next((c for c in CHROME_CANDIDATES if Path(c).exists()), None) \
        or shutil.which("chrome") or shutil.which("msedge")
    url = HTML.resolve().as_uri()
    if chrome:
        subprocess.Popen([chrome, url])
    else:
        import webbrowser
        webbrowser.open(url)
    print(f"open : {url}\n       Ctrl+P, then Save as PDF. Margins are already set by @page.")


if __name__ == "__main__":
    if not MD.exists():
        sys.exit(f"No such document: {MD}")
    build_html()
    if OPEN_IT:
        open_in_browser()
    else:
        build_pdf()
