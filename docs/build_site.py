"""Build docs/index.html from docs/site/template.html with the SVG figures inlined.

    python docs/diagrams/build_diagrams.py   # if you changed a diagram
    python docs/build_site.py                # rebuild the page

Standard library only. The output is a single self-contained page, so it works from
GitHub Pages (Settings → Pages → Deploy from branch → main /docs), from a local file,
or printed to PDF.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "site", "template.html")
DIAGRAMS = os.path.join(HERE, "diagrams")
OUT = os.path.join(HERE, "index.html")

PLACEHOLDER = re.compile(r"\{\{FIG:([\w-]+)\}\}")


def inline_svg(match):
    path = os.path.join(DIAGRAMS, match.group(1) + ".svg")
    if not os.path.exists(path):
        sys.exit(f"missing diagram: {path} (run python docs/diagrams/build_diagrams.py)")
    svg = open(path, encoding="utf-8").read().strip()
    # Every figure defines the same arrow-marker ids; namespace them so ids stay unique on the page.
    ns = "f" + match.group(1).split("-")[0]
    svg = svg.replace('id="m', f'id="{ns}m').replace("url(#m", f"url(#{ns}m")
    # Drop the fixed size so CSS can scale the figure to the column width.
    return re.sub(r'\swidth="\d+"\sheight="\d+"', "", svg, count=1)


html = PLACEHOLDER.sub(inline_svg, open(TEMPLATE, encoding="utf-8").read())
open(OUT, "w", encoding="utf-8").write(html)
print(f"wrote {OUT} ({len(html) // 1024} KB)")
