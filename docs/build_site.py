"""Build the web pages from docs/site/. Standard library only.

    python docs/diagrams/build_diagrams.py              # if a design diagram changed
    python prototype/docs/diagrams/build_diagrams.py    # if a prototype diagram changed
    python docs/build_site.py

docs/site/template.html  -> docs/index.html      (solution design)
docs/site/prototype.html -> docs/prototype.html  (prototype)

Placeholders:
    {{FIG:name}}    inlines docs/diagrams/name.svg
    {{PFIG:name}}   inlines prototype/docs/diagrams/name.svg
    {{IMG:name}}    embeds docs/diagrams/name (png/webp/jpg) as a data URI
    {{STYLE}} {{SCRIPT}}  the <style> and <script> of template.html, so both pages share one look
    {{GH}}          GitHub URL of prototype/ (Pages only serves docs/, so code and flow docs link there)
Each output is one self-contained file: GitHub Pages (main /docs), a local file, or print to PDF.
"""
import base64
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, "site")
DIAGRAMS = os.path.join(HERE, "diagrams")
PROTO_DIAGRAMS = os.path.join(HERE, "..", "prototype", "docs", "diagrams")
GH = "https://github.com/dharam1291/assignment_zingly/blob/main/prototype"
MIME = {".png": "image/png", ".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
PAGES = [("template.html", "index.html"), ("prototype.html", "prototype.html")]


def svg_inliner(folder, prefix):
    def inline(m):
        name = m.group(1)
        path = os.path.join(folder, name + ".svg")
        if not os.path.exists(path):
            sys.exit(f"missing diagram: {path} (run the build_diagrams.py next to it)")
        svg = open(path, encoding="utf-8").read().strip()
        ns = prefix + re.sub(r"[^a-z0-9]", "", name.lower())[:12]  # keep marker ids unique per figure
        svg = svg.replace('id="m', f'id="{ns}m').replace("url(#m", f"url(#{ns}m")
        return re.sub(r'\swidth="\d+"\sheight="\d+"', "", svg, count=1)
    return inline


def embed_img(m):
    name = m.group(1)
    path = os.path.join(DIAGRAMS, name)
    if not os.path.exists(path):
        sys.exit(f"missing image: {path}")
    data = base64.b64encode(open(path, "rb").read()).decode()
    return f"data:{MIME[os.path.splitext(name)[1].lower()]};base64,{data}"


base = open(os.path.join(SITE, "template.html"), encoding="utf-8").read()
shared = {"STYLE": re.search(r"<style>.*?</style>", base, re.S).group(0),
          "SCRIPT": re.search(r"<script>.*?</script>", base, re.S).group(0),
          "GH": GH}

for src, dst in PAGES:
    html = open(os.path.join(SITE, src), encoding="utf-8").read()
    for key, value in shared.items():
        html = html.replace("{{" + key + "}}", value)
    html = re.sub(r"\{\{FIG:([\w-]+)\}\}", svg_inliner(DIAGRAMS, "f"), html)
    html = re.sub(r"\{\{PFIG:([\w-]+)\}\}", svg_inliner(PROTO_DIAGRAMS, "p"), html)
    html = re.sub(r"\{\{IMG:([\w.-]+)\}\}", embed_img, html)
    out = os.path.join(HERE, dst)
    open(out, "w", encoding="utf-8").write(html)
    print(f"wrote {out} ({len(html) // 1024} KB)")
