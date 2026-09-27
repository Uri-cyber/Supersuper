# -*- coding: utf-8 -*-
"""
מאיירים את המוצרים המרחפים בכותרת: SVG איזומטרי בסגנון אחיד ונקי.

    python cloud/make_hero_art.py   ->  site/art/*.svg

כללי הסגנון, זהים לכל האיורים:
* הצללה שטוחה בשלושה גוונים לפי כיוון האור: למעלה בהיר, שמאל בינוני,
  ימין כהה. בלי מעברי צבע ובלי ברקים.
* קו מתאר אחד, באותו עובי על המסך בכל גודל (vector-effect).
* צבע בסיס אחד לכל מוצר מתוך צבעי האתר, ולכל היותר פס אחד בצבע שני.
* בלי פרטים קטנים (טיפות, תגיות, חריצים): בגודל של 60 פיקסלים הם רעש.
* כולם באותו גובה בעולם (כ-90 יחידות) ובאותו ריבוע, כדי שבאותו גודל
  CSS ייראו באותו קנה מידה.

אלה איורים מופשטים ולא מוצרים אמיתיים: בקבצי הרשתות אין תמונות.
"""
import math
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "site", "art")

INK = "#14151a"
C30, S30 = math.cos(math.radians(30)), 0.5
ISO_RY = 0.5 / math.cos(math.radians(30))
LINE = (f'stroke="{INK}" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round" '
        f'vector-effect="non-scaling-stroke"')

# לכל צבע בסיס: (למעלה, שמאל, ימין)
WHITE = ("#ffffff", "#eef1ec", "#cfd5cc")
GREEN = ("#5fe08f", "#1fb85a", "#138a42")
RED = ("#ff7a7a", "#e04848", "#a92f2f")
YELLOW = ("#ffe08a", "#ffcb3d", "#d9a11f")
PURPLE = ("#a996ff", "#7d63e6", "#5540c0")
SILVER = ("#f3f4f6", "#dcdfe3", "#b9bdc4")


def P(x, y, z):
    return ((x - z) * C30, (x + z) * S30 - y)


def poly(pts, fill):
    d = " ".join(f"{a:.1f},{b:.1f}" for a, b in (P(*p) for p in pts))
    return f'<polygon points="{d}" fill="{fill}" {LINE}/>'


def box(x0, y0, z0, w, h, d, tone):
    """קופסה: שלוש הפאות הנראות, בגווני tone."""
    x1, y1, z1 = x0 + w, y0 + h, z0 + d
    return (poly([(x1, y0, z0), (x1, y0, z1), (x1, y1, z1), (x1, y1, z0)], tone[2]) +
            poly([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], tone[1]) +
            poly([(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)], tone[0]))


def band_box(x0, y0, z0, w, h, d, tone):
    """רצועה סביב קופסה: רק שתי הפאות הצדדיות."""
    x1, y1, z1 = x0 + w, y0 + h, z0 + d
    return (poly([(x1, y0, z0), (x1, y0, z1), (x1, y1, z1), (x1, y1, z0)], tone[2]) +
            poly([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], tone[1]))


_clip_n = [0]


def cylinder(cx, cy, R, H, tone, top_tone=None):
    """
    גליל אנכי בהצללה שטוחה: הצד השמאלי בגוון הבינוני, השליש הימני כהה,
    מכסה בגוון הבהיר. cy = גובה המכסה במסך.
    """
    ry = R * ISO_RY
    _clip_n[0] += 1
    cid = f"c{_clip_n[0]}"
    body = f"M{cx - R} {cy} L{cx - R} {cy + H} A{R} {ry} 0 0 0 {cx + R} {cy + H} L{cx + R} {cy} Z"
    top = top_tone or tone[0]
    return (f'<clipPath id="{cid}"><path d="{body}"/></clipPath>'
            f'<path d="{body}" fill="{tone[1]}"/>'
            f'<rect x="{cx + R * 0.34:.1f}" y="{cy - ry}" width="{R}" height="{H + 2 * ry}" '
            f'fill="{tone[2]}" clip-path="url(#{cid})"/>'
            f'<path d="{body}" fill="none" {LINE}/>'
            f'<ellipse cx="{cx}" cy="{cy}" rx="{R}" ry="{ry:.1f}" fill="{top}" {LINE}/>')


def cyl_band(cx, cy, R, y1, y2, tone):
    """רצועה על גליל, בין y1 ל-y2 מתחת למכסה."""
    ry = R * ISO_RY
    _clip_n[0] += 1
    cid = f"c{_clip_n[0]}"
    d = (f"M{cx - R} {cy + y1} A{R} {ry} 0 0 0 {cx + R} {cy + y1} "
         f"L{cx + R} {cy + y2} A{R} {ry} 0 0 1 {cx - R} {cy + y2} Z")
    return (f'<clipPath id="{cid}"><path d="{d}"/></clipPath>'
            f'<path d="{d}" fill="{tone[1]}"/>'
            f'<rect x="{cx + R * 0.34:.1f}" y="{cy + y1 - ry}" width="{R}" height="{y2 - y1 + 2 * ry}" '
            f'fill="{tone[2]}" clip-path="url(#{cid})"/>'
            f'<path d="{d}" fill="none" {LINE}/>')


def svg(body, cx, cy, half=62):
    """ריבוע אחיד סביב מרכז הגוף, כדי שכל האיורים יהיו באותו קנה מידה."""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{cx - half:.0f} {cy - half:.0f} '
            f'{2 * half} {2 * half}">{body}</svg>\n')


# ------------------------------------------------------------------ איורים
def milk():
    w = d = 38
    h, g, fin = 58, 16, 6
    b = box(0, 0, 0, w, h, d, WHITE)
    b += band_box(0, 22, 0, w, 16, d, GREEN)
    b += poly([(0, h, d), (w, h, d), (w, h + g, d / 2), (0, h + g, d / 2)], WHITE[0])
    b += poly([(w, h, 0), (w, h, d), (w, h + g, d / 2)], WHITE[2])
    b += poly([(0, h + g, d / 2), (w, h + g, d / 2), (w, h + g + fin, d / 2), (0, h + g + fin, d / 2)], WHITE[1])
    return svg(b, 0, -26)


def can():
    R, H = 28, 70
    b = cylinder(0, 0, R, H, RED, top_tone=SILVER[0])
    b += cyl_band(0, 0, R, 26, 44, WHITE)
    b += f'<rect x="-8" y="-4" width="16" height="7" rx="3.5" fill="{SILVER[2]}" {LINE}/>'
    return svg(b, 0, 36)


def cheese():
    w, d, h = 66, 52, 28
    b = poly([(w, 0, 0), (0, 0, d), (0, h, d), (w, h, 0)], YELLOW[1])
    b += poly([(0, h, 0), (w, h, 0), (0, h, d)], YELLOW[0])
    for x, z, r in [(14, 12, 5.5), (30, 8, 4)]:
        sx, sy = P(x, h, z)
        b += f'<ellipse cx="{sx:.1f}" cy="{sy:.1f}" rx="{r * 1.2:.1f}" ry="{r * 0.7:.1f}" fill="{YELLOW[2]}"/>'
    for t, yy, r in [(0.32, 13, 4.5), (0.66, 15, 3.5)]:
        sx, sy = P(w * (1 - t), yy, d * t)
        b += f'<ellipse cx="{sx:.1f}" cy="{sy:.1f}" rx="{r:.1f}" ry="{r * 1.15:.1f}" fill="{YELLOW[2]}"/>'
    return svg(b, 6, 4)


def bag():
    w, d, h = 52, 22, 58
    # ידית אחורית, ואז הגוף, ואז ידית קדמית
    def handle(z):
        pts = []
        for i in range(21):
            t = i / 20
            x = 13 + 26 * t
            y = h + 26 * math.sin(math.pi * t)
            pts.append(P(x, y, z))
        d_ = "M" + " L".join(f"{a:.1f} {b_:.1f}" for a, b_ in pts)
        # קו כהה עבה ומעליו קו בצבע השקית, כדי שהידית תיראה גם על רקע כהה
        return (f'<path d="{d_}" fill="none" {LINE.replace("2.4", "6", 1)}/>'
                f'<path d="{d_}" fill="none" stroke="{PURPLE[0]}" stroke-width="2.6" '
                f'stroke-linecap="round" vector-effect="non-scaling-stroke"/>')
    b = handle(3)
    b += box(0, 0, 0, w, h, d, (PURPLE[2], PURPLE[1], PURPLE[2]))
    b += poly([(0, h, 0), (w, h, 0), (w, h, d), (0, h, d)], "#2c1f6b")
    b += handle(d)
    return svg(b, 14, -14)


def coins():
    R, T = 36, 10
    b = ""
    for i in range(3):
        cy = -i * T
        b += cylinder(0, cy, R, T, GREEN)
    # ₪ על המטבע העליון, במישור האופקי
    top = -2 * T
    b += (f'<g transform="matrix({C30:.4f},{S30 * 0.95:.4f},{-C30:.4f},{S30 * 0.95:.4f},0,{top})">'
          f'<path d="M-11 9 V -9 H 4 V 4 M 11 -9 V 9 H -4 V -4" fill="none" {LINE.replace("2.4", "2.8", 1)}/></g>')
    return svg(b, 0, -6)


def main():
    os.makedirs(OUT, exist_ok=True)
    keep = {"milk", "can", "cheese", "bag", "coins"}
    for name in keep:
        p = os.path.join(OUT, name + ".svg")
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(globals()[name]())
        print(os.path.relpath(p, BASE), os.path.getsize(p), "bytes")
    # הביצה יצאה מהסט: צורה אורגנית עם מעבר צבע, שונה מכל השאר
    for fn in os.listdir(OUT):
        if fn.endswith(".svg") and fn[:-4] not in keep:
            os.remove(os.path.join(OUT, fn))
            print("removed", fn)


if __name__ == "__main__":
    main()
