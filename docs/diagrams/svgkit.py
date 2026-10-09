"""Tiny SVG helper used to hand-lay-out the architecture diagrams.

Diagrams are code: edit build_diagrams.py, run `python docs/diagrams/build_diagrams.py`,
and the SVGs in docs/diagrams/ are regenerated. No dependencies beyond the stdlib.
"""
from html import escape

FONT = "Inter, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
INK, SUB, LINE, BORDER, BG = "#0F172A", "#475569", "#64748B", "#CBD5E1", "#FFFFFF"
ACCENT = "#4F46E5"

ZONES = {
    "twilio":   ("#E11D48", "#FFF1F2"),
    "zingly":   ("#4F46E5", "#EEF2FF"),
    "airline":  ("#059669", "#ECFDF5"),
    "genesys":  ("#D97706", "#FFFBEB"),
    "neutral":  ("#64748B", "#F8FAFC"),
    "danger":   ("#DC2626", "#FEF2F2"),
}


class SVG:
    def __init__(self, w, h, title, subtitle=""):
        self.w, self.h = w, h
        self.title, self.subtitle = title, subtitle
        self.parts = []

    # ---------- primitives ----------
    def raw(self, s):
        self.parts.append(s)

    def text(self, x, y, s, size=11, weight=400, color=SUB, anchor="start", italic=False, halo=False):
        style = ' font-style="italic"' if italic else ""
        h = (f' stroke="{BG}" stroke-width="4" stroke-linejoin="round" paint-order="stroke"' if halo else "")
        lines = s.split("\n")
        if len(lines) == 1:
            self.raw(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{color}" '
                     f'text-anchor="{anchor}"{style}{h}>{escape(s)}</text>')
        else:
            lh = size + 3
            y0 = y - (len(lines) - 1) * lh / 2
            spans = "".join(f'<tspan x="{x}" y="{y0 + i * lh:.1f}">{escape(l)}</tspan>' for i, l in enumerate(lines))
            self.raw(f'<text font-size="{size}" font-weight="{weight}" fill="{color}" text-anchor="{anchor}"{style}{h}>{spans}</text>')

    def zone(self, x, y, w, h, label, kind="neutral", dashed=False, label_right=False, label_x=None):
        stroke, fill = ZONES[kind]
        dash = ' stroke-dasharray="5 4"' if dashed else ""
        self.raw(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{fill}" stroke="{stroke}" stroke-width="1.2"{dash}/>')
        if label_x is not None:
            self.text(label_x, y + 20, label.upper(), size=10.5, weight=700, color=stroke)
        elif label_right:
            self.text(x + w - 14, y + 20, label.upper(), size=10.5, weight=700, color=stroke, anchor="end")
        else:
            self.text(x + 14, y + 20, label.upper(), size=10.5, weight=700, color=stroke)

    def box(self, x, y, w, h, title, sub="", kind=None, accent=False, fill=BG, title_size=12.5):
        stroke = ZONES[kind][0] if kind else (ACCENT if accent else BORDER)
        sw = 1.6 if (accent or kind) else 1.2
        self.raw(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
        cx = x + w / 2
        if sub:
            n = len(sub.split("\n"))
            ty = y + h / 2 - (n * 7) + 2
            self.text(cx, ty, title, size=title_size, weight=650, color=INK, anchor="middle")
            self.text(cx, ty + 9 + n * 7, sub, size=10.5, color=SUB, anchor="middle")
        else:
            self.text(cx, y + h / 2 + 4.5, title, size=title_size, weight=650, color=INK, anchor="middle")

    def badge(self, x, y, n, color=ACCENT):
        self.raw(f'<circle cx="{x}" cy="{y}" r="9" fill="{color}"/>')
        self.text(x, y + 3.8, str(n), size=10.5, weight=700, color="#fff", anchor="middle")

    def path(self, d, color=LINE, width=1.5, dashed=False, start=False, end=True):
        dash = ' stroke-dasharray="5 4"' if dashed else ""
        mid = _marker_id(color)
        ms = f' marker-start="url(#{mid}s)"' if start else ""
        me = f' marker-end="url(#{mid})"' if end else ""
        self.raw(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}"{dash}{ms}{me}/>')

    def arrow(self, pts, label=None, lx=None, ly=None, color=LINE, dashed=False, both=False,
              anchor="middle", lcolor=None, width=1.5):
        d = "M" + " L".join(f"{x},{y}" for x, y in pts)
        self.path(d, color=color, dashed=dashed, start=both, width=width)
        if label:
            self.text(lx, ly, label, size=10.5, color=lcolor or (color if color != LINE else SUB),
                      anchor=anchor, halo=True)

    # ---------- output ----------
    def render(self):
        markers = ""
        for c in dict.fromkeys([LINE, ACCENT] + [v[0] for v in ZONES.values()]):
            mid = _marker_id(c)
            markers += (f'<marker id="{mid}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
                        f'<path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>'
                        f'<marker id="{mid}s" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
                        f'<path d="M10,0 L0,5 L10,10 z" fill="{c}"/></marker>')
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" width="{self.w}" '
                f'height="{self.h}" role="img" aria-label="{escape(self.title)}" font-family="{FONT}">'
                f'<defs>{markers}</defs>'
                f'<rect width="{self.w}" height="{self.h}" rx="14" fill="{BG}" stroke="{BORDER}"/>')
        t = (f'<text x="28" y="38" font-size="17" font-weight="700" fill="{INK}">{escape(self.title)}</text>')
        if self.subtitle:
            t += f'<text x="28" y="58" font-size="11.5" fill="{SUB}">{escape(self.subtitle)}</text>'
        return head + t + "".join(self.parts) + "</svg>\n"

    def save(self, path):
        with open(path, "w") as f:
            f.write(self.render())


def _marker_id(color):
    return "m" + color.strip("#").lower()


# ---------- sequence-diagram helper ----------
class Seq:
    """Lifelines at fixed x; messages laid out top-down with a running y cursor."""

    def __init__(self, svg, actors, top=90, bottom=None, head_h=46, box_w=150):
        self.s, self.actors, self.top = svg, actors, top
        self.head_h, self.box_w = head_h, box_w
        self.y = top + head_h + 26
        self.bottom = bottom or svg.h - 30
        self.n = 0

    def x(self, name):
        return self.actors[name][0]

    def draw_heads(self):
        self._life_idx = len(self.s.parts)
        for name, (x, title, sub, kind) in self.actors.items():
            stroke, fill = ZONES[kind]
            bw = self.box_w
            self.s.raw(f'<rect x="{x - bw / 2}" y="{self.top}" width="{bw}" height="{self.head_h}" rx="8" '
                       f'fill="{fill}" stroke="{stroke}" stroke-width="1.4"/>')
            self.s.text(x, self.top + 19, title, size=12, weight=650, color=INK, anchor="middle")
            if sub:
                self.s.text(x, self.top + 35, sub, size=10, color=SUB, anchor="middle")

    def finish(self, pad=6, life_end=None):
        """Insert lifelines under everything, sized to the content, and fit the canvas height."""
        bottom = life_end or self.y
        lines = "".join(f'<line x1="{x}" y1="{self.top + self.head_h}" x2="{x}" y2="{bottom}" '
                        f'stroke="{BORDER}" stroke-width="1.2" stroke-dasharray="4 4"/>'
                        for (x, *_rest) in self.actors.values())
        self.s.parts.insert(self._life_idx, lines)
        self.s.h = int(self.y + pad + 14)

    def msg(self, a, b, label, dashed=False, color=LINE, step=True, gap=34, note_side=None):
        xa, xb = self.x(a), self.x(b)
        y = self.y
        if a == b:  # self call
            self.s.path(f"M{xa},{y} H{xa + 40} V{y + 16} H{xa + 3}", color=color, dashed=dashed)
            self.s.text(xa + 48, y + 11, label, size=10.5, color=SUB if color == LINE else color, halo=True)
            self.y += gap + 14
            return
        pad = 3 if xb > xa else -3
        self.s.path(f"M{xa},{y} H{xb - pad}", color=color, dashed=dashed)
        lines = label.count("\n") + 1
        # Centre the label on the arrow, unless it is wide enough to run into the step badge;
        # then start it just past the badge and let it run in the arrow's direction.
        label_w = max(len(l) for l in label.split("\n")) * 5.9
        if label_w > abs(xb - xa) - 30:
            tx, anchor = (xa + 16, "start") if xb > xa else (xa - 16, "end")
        else:
            tx, anchor = (xa + xb) / 2, "middle"
        self.s.text(tx, y - 7 - (lines - 1) * 7, label, size=10.5, anchor=anchor,
                    color=SUB if color == LINE else color, halo=True)
        if step:
            self.n += 1
            self.s.badge(xa, y, self.n, color=color if color != LINE else ACCENT)
        self.y += gap + (lines - 1) * 12

    def frame(self, x1, x2, y1, y2, label, kind="neutral"):
        stroke, _ = ZONES[kind]
        self.s.raw(f'<rect x="{x1}" y="{y1}" width="{x2 - x1}" height="{y2 - y1}" rx="6" fill="none" '
                   f'stroke="{stroke}" stroke-width="1.2" stroke-dasharray="6 4"/>')
        w = len(label) * 6.3 + 16
        self.s.raw(f'<path d="M{x1},{y1 + 6} a6,6 0 0 1 6,-6 H{x1 + w} V{y1 + 14} L{x1 + w - 8},{y1 + 20} H{x1} Z" fill="{stroke}"/>')
        self.s.text(x1 + 8, y1 + 14, label, size=10, weight=700, color="#fff")

    def divider(self, x1, x2, label, kind="neutral"):
        stroke, _ = ZONES[kind]
        y = self.y - 14
        self.s.raw(f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{stroke}" stroke-dasharray="6 4"/>')
        self.s.text(x1 + 8, y + 14, label, size=10, weight=700, color=stroke, italic=True)
        self.y += 10

    def note(self, x, w, text, kind="neutral", h=None):
        stroke, fill = ZONES[kind]
        n = text.count("\n") + 1
        h = h or (n * 14 + 10)
        y = self.y - 12
        self.s.raw(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1"/>')
        self.s.text(x + w / 2, y + h / 2 + 4, text, size=10.5, color=INK, anchor="middle")
        self.y += h + 12
