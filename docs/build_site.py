"""Build docs/index.html from docs/site/template.html. Standard library only.

    python docs/diagrams/build_diagrams.py   # if a diagram changed
    python docs/build_site.py

Placeholders in the template:
    {{FIG:name}}   inlines diagrams/name.svg
    {{IMG:name}}   embeds diagrams/name (png/webp/jpg) as a data URI
The output is one self-contained file: GitHub Pages (main /docs), a local file, or print to PDF.
"""
import base64
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "site", "template.html")
DIAGRAMS = os.path.join(HERE, "diagrams")
OUT = os.path.join(HERE, "index.html")
MIME = {".png": "image/png", ".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def inline_svg(m):
    name = m.group(1)
    path = os.path.join(DIAGRAMS, name + ".svg")
    if not os.path.exists(path):
        sys.exit(f"missing diagram: {path} (run python docs/diagrams/build_diagrams.py)")
    svg = open(path, encoding="utf-8").read().strip()
    ns = "f" + re.sub(r"[^a-z0-9]", "", name.lower())[:12]  # keep marker ids unique per figure
    svg = svg.replace('id="m', f'id="{ns}m').replace("url(#m", f"url(#{ns}m")
    return re.sub(r'\swidth="\d+"\sheight="\d+"', "", svg, count=1)


def embed_img(m):
    name = m.group(1)
    path = os.path.join(DIAGRAMS, name)
    if not os.path.exists(path):
        sys.exit(f"missing image: {path}")
    data = base64.b64encode(open(path, "rb").read()).decode()
    return f"data:{MIME[os.path.splitext(name)[1].lower()]};base64,{data}"


html = open(TEMPLATE, encoding="utf-8").read()
html = re.sub(r"\{\{FIG:([\w-]+)\}\}", inline_svg, html)
html = re.sub(r"\{\{IMG:([\w.-]+)\}\}", embed_img, html)
open(OUT, "w", encoding="utf-8").write(html)
print(f"wrote {OUT} ({len(html) // 1024} KB)")
