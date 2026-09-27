# -*- coding: utf-8 -*-
"""
מאיירים את המוצרים המרחפים בכותרת: SVG איזומטרי, בסגנון האתר (קו מתאר
כהה עבה, צבעים שטוחים, שלושה גוונים לכל גוף לפי כיוון האור).

    python cloud/make_hero_art.py   ->  site/art/*.svg

אלה איורים מופשטים בצבעי האתר ולא מוצרים אמיתיים: בקבצי הרשתות אין
תמונות. אין טקסט בתוך האיורים, כי SVG שנטען כתמונה לא רואה את הגופנים
של הדף.

הקרנה איזומטרית: x ימינה-למטה, z שמאלה-למטה, y למעלה. האור מלמעלה-שמאל:
פאה עליונה בהירה, פאה שמאלית (z מקסימלי) בינונית, פאה ימנית (x מקסימלי) כהה.
"""
import math
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "site", "art")

INK = "#14151a"
C30, S30 = math.cos(math.radians(30)), 0.5
ISO_RY = 0.5 / math.cos(math.radians(30))   # יחס האליפסה של עיגול אופקי


def P(x, y, z):
    return ((x - z) * C30, (x + z) * S30 - y)


def poly(pts, fill, extra=""):
    d = " ".join(f"{a:.1f},{b:.1f}" for a, b in (P(*p) for p in pts))
    return f'<polygon points="{d}" fill="{fill}" {extra}/>'


def face_matrix(plane, k):
    """
    מטריצה שממפה קואורדינטות דו-ממדיות על פאה לקואורדינטות מסך.
    plane: 'z' = פאה z=k (צירי הפאה: x ימינה, y למעלה), 'x' = פאה x=k (z, y),
    'y' = פאה אופקית y=k (x, z).
    """
    if plane == "z":
        e, f = P(0, 0, k)
        return f"matrix({C30:.4f},{S30:.4f},0,-1,{e:.2f},{f:.2f})"
    if plane == "x":
        e, f = P(k, 0, 0)
        return f"matrix({-C30:.4f},{S30:.4f},0,-1,{e:.2f},{f:.2f})"
    e, f = P(0, k, 0)
    return f"matrix({C30:.4f},{S30:.4f},{-C30:.4f},{S30:.4f},{e:.2f},{f:.2f})"


STROKE = f'stroke="{INK}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"'


def svg(body, box, defs=""):
    x0, y0, x1, y1 = box
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0:.0f} {y0:.0f} {x1 - x0:.0f} {y1 - y0:.0f}">'
            f"<defs>{defs}</defs>{body}</svg>\n")


# ------------------------------------------------------------------ קרטון חלב
def milk():
    w, d, h, g = 44, 44, 76, 22
    b = []
    # גוף
    b.append(poly([(w, 0, 0), (w, 0, d), (w, h, d), (w, h, 0)], "#c9cfc6", STROKE))       # ימין, כהה
    b.append(poly([(0, 0, d), (w, 0, d), (w, h, d), (0, h, d)], "#f4f6f2", STROKE))       # שמאל, בהיר
    # פס ירוק סביב
    b.append(poly([(0, 30, d), (w, 30, d), (w, 50, d), (0, 50, d)], "#1fb85a", STROKE))
    b.append(poly([(w, 30, 0), (w, 30, d), (w, 50, d), (w, 50, 0)], "#15964a", STROKE))
    # טיפה לבנה על הפס השמאלי, בקואורדינטות של הפאה
    b.append(f'<g transform="{face_matrix("z", d)}"><path d="M22 47 C 16 40, 15 36, 18 33 '
             f'C 20 31, 24 31, 26 33 C 29 36, 28 40, 22 47 Z" fill="#fff" {STROKE.replace("3", "2.4", 1)}/></g>')
    # גג משולש
    b.append(poly([(0, h, d), (w, h, d), (w, h + g, d / 2), (0, h + g, d / 2)], "#ffffff", STROKE))
    b.append(poly([(w, h, 0), (w, h, d), (w, h + g, d / 2)], "#dde2da", STROKE))
    # הסנפיר בראש
    b.append(poly([(0, h + g, d / 2), (w, h + g, d / 2), (w, h + g + 8, d / 2), (0, h + g + 8, d / 2)],
                  "#eef1ec", STROKE))
    # ברק על הפאה הבהירה
    b.append(f'<g transform="{face_matrix("z", d)}"><path d="M6 8 V 24" stroke="#fff" stroke-width="3" '
             f'stroke-linecap="round" opacity=".9"/></g>')
    return svg("".join(b), (-44, -110, 44, 48))


# ------------------------------------------------------------------ פחית
def can():
    R, H = 30, 80
    ry = R * ISO_RY * 0.9
    top, bot = 0, H
    grad = ('<linearGradient id="cb" x1="0" x2="1">'
            '<stop offset="0" stop-color="#8f2020"/><stop offset=".3" stop-color="#e04848"/>'
            '<stop offset=".42" stop-color="#ff9b9b"/><stop offset=".58" stop-color="#d44040"/>'
            '<stop offset="1" stop-color="#6d1515"/></linearGradient>'
            '<linearGradient id="cw" x1="0" x2="1">'
            '<stop offset="0" stop-color="#bfc3c9"/><stop offset=".4" stop-color="#ffffff"/>'
            '<stop offset="1" stop-color="#9ea3aa"/></linearGradient>')
    b = []
    # גוף: מלבן עם קשת תחתונה
    b.append(f'<path d="M{-R} {top} L{-R} {bot} A{R} {ry} 0 0 0 {R} {bot} L{R} {top} Z" fill="url(#cb)" {STROKE}/>')
    # רצועה לבנה שעוקבת אחרי הקימור
    y1, y2 = 30, 50
    b.append(f'<path d="M{-R} {y1} A{R} {ry} 0 0 0 {R} {y1} L{R} {y2} A{R} {ry} 0 0 1 {-R} {y2} Z" '
             f'fill="url(#cw)" {STROKE}/>')
    # מכסה
    b.append(f'<ellipse cx="0" cy="{top}" rx="{R}" ry="{ry}" fill="#e3e5e9" {STROKE}/>')
    b.append(f'<ellipse cx="0" cy="{top + 1}" rx="{R - 6}" ry="{ry - 4}" fill="none" stroke="{INK}" stroke-width="2" opacity=".5"/>')
    b.append(f'<rect x="-9" y="{top - 5}" width="18" height="7" rx="3.5" fill="#c3c7cd" {STROKE.replace("3", "2.2", 1)}/>')
    # ברק אנכי
    b.append(f'<path d="M-10 {top + 10} V {bot - 6}" stroke="#fff" stroke-width="3" stroke-linecap="round" opacity=".55"/>')
    return svg("".join(b), (-36, -24, 36, bot + ry + 6), grad)


# ------------------------------------------------------------------ גבינה
def cheese():
    w, d, h = 70, 56, 30
    b = []
    # פאת האלכסון (הצד שפונה אלינו)
    b.append(poly([(w, 0, 0), (0, 0, d), (0, h, d), (w, h, 0)], "#e8a91c", STROKE))
    # חורים על פאת האלכסון: במישור שלה, בקירוב כפאה z עם הזזה
    holes_side = [(0.28, 12, 5), (0.6, 18, 4), (0.8, 9, 3.5)]
    for t, yy, r in holes_side:
        x, z = w * (1 - t), d * t
        sx, sy = P(x, yy, z)
        b.append(f'<ellipse cx="{sx:.1f}" cy="{sy:.1f}" rx="{r * 0.95:.1f}" ry="{r * 1.1:.1f}" fill="#b97c0c" '
                 f'stroke="{INK}" stroke-width="2"/>')
    # פאה עליונה, משולש
    b.append(poly([(0, h, 0), (w, h, 0), (0, h, d)], "#ffd75f", STROKE))
    for x, z, r in [(14, 12, 6), (32, 8, 4.5), (12, 30, 4)]:
        sx, sy = P(x, h, z)
        b.append(f'<ellipse cx="{sx:.1f}" cy="{sy:.1f}" rx="{r * 1.2:.1f}" ry="{r * 0.7:.1f}" fill="#d9a622" '
                 f'stroke="{INK}" stroke-width="2"/>')
    return svg("".join(b), (-56, -40, 66, 54))


# ------------------------------------------------------------------ שקית
def bag():
    w, d, h = 50, 20, 56
    b = []
    # ידית אחורית (נראית מעל הגוף)
    b.append(f'<g transform="{face_matrix("z", 3)}"><path d="M14 {h} C 14 {h + 26}, 36 {h + 26}, 36 {h}" '
             f'fill="none" stroke="{INK}" stroke-width="5" stroke-linecap="round"/>'
             f'<path d="M14 {h} C 14 {h + 26}, 36 {h + 26}, 36 {h}" fill="none" stroke="#4a33a8" '
             f'stroke-width="2" stroke-linecap="round"/></g>')
    b.append(poly([(w, 0, 0), (w, 0, d), (w, h, d), (w, h, 0)], "#4a33a8", STROKE))
    b.append(poly([(0, 0, d), (w, 0, d), (w, h, d), (0, h, d)], "#7d63e6", STROKE))
    b.append(poly([(0, h, 0), (w, h, 0), (w, h, d), (0, h, d)], "#2c1f6b", STROKE))
    # ידית קדמית
    b.append(f'<g transform="{face_matrix("z", d)}"><path d="M14 {h} C 14 {h + 26}, 36 {h + 26}, 36 {h}" '
             f'fill="none" stroke="{INK}" stroke-width="5" stroke-linecap="round"/>'
             f'<path d="M14 {h} C 14 {h + 26}, 36 {h + 26}, 36 {h}" fill="none" stroke="#b9a8ff" '
             f'stroke-width="2" stroke-linecap="round"/></g>')
    # תגית צהובה על הפאה
    b.append(f'<g transform="{face_matrix("z", d)}"><rect x="12" y="14" width="26" height="22" rx="4" '
             f'fill="#ffcb3d" {STROKE.replace("3", "2.4", 1)}/>'
             f'<path d="M18 30 V 20 H 26 V 26 M 32 20 V 30 H 24 V 24" fill="none" stroke="{INK}" '
             f'stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></g>')
    return svg("".join(b), (-22, -74, 50, 40))


# ------------------------------------------------------------------ ערימת מטבעות
def coins():
    R, T = 26, 7
    ry = R * ISO_RY
    grad = ('<linearGradient id="ce" x1="0" x2="1">'
            '<stop offset="0" stop-color="#0d6b33"/><stop offset=".45" stop-color="#1fb85a"/>'
            '<stop offset="1" stop-color="#0b5c2c"/></linearGradient>'
            '<radialGradient id="ct" cx=".4" cy=".35" r=".8">'
            '<stop offset="0" stop-color="#7dea9f"/><stop offset=".55" stop-color="#1fb85a"/>'
            '<stop offset="1" stop-color="#15964a"/></radialGradient>')
    b = []
    stack = [(0, 0), (1, 0), (-1, 0), (1, 0)]
    y = 0
    for i, (dx, _) in enumerate(stack):
        cy = -i * T
        b.append(f'<path d="M{dx - R} {cy} L{dx - R} {cy + T} A{R} {ry} 0 0 0 {dx + R} {cy + T} '
                 f'L{dx + R} {cy} Z" fill="url(#ce)" {STROKE}/>')
        # חריצים בשפה
        for k in range(-2, 3):
            xx = dx + k * 9
            b.append(f'<path d="M{xx} {cy + ry * 0.9 * (1 - (k / 3) ** 2) ** .5 + 1:.1f} v {T - 2}" '
                     f'stroke="{INK}" stroke-width="1.4" opacity=".35"/>')
        if i < len(stack) - 1:
            b.append(f'<ellipse cx="{dx}" cy="{cy}" rx="{R}" ry="{ry}" fill="#15964a" {STROKE}/>')
        y = cy
    dx = stack[-1][0]
    b.append(f'<ellipse cx="{dx}" cy="{y}" rx="{R}" ry="{ry}" fill="url(#ct)" {STROKE}/>')
    b.append(f'<ellipse cx="{dx}" cy="{y}" rx="{R - 6}" ry="{ry - 3.5}" fill="none" stroke="{INK}" stroke-width="1.6" opacity=".45"/>')
    # ₪ על הפאה העליונה, במישור האופקי
    e, f = dx, y
    b.append(f'<g transform="matrix({C30:.4f},{S30 * 0.9:.4f},{-C30:.4f},{S30 * 0.9:.4f},{e},{f})">'
             f'<path d="M-9 7 V -7 H 3 V 3 M 9 -7 V 7 H -3 V -3" fill="none" stroke="{INK}" '
             f'stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/></g>')
    return svg("".join(b), (-32, -44, 38, 30), grad)


# ------------------------------------------------------------------ ביצה
def egg():
    grad = ('<radialGradient id="eg" cx=".38" cy=".3" r=".85">'
            '<stop offset="0" stop-color="#ffffff"/><stop offset=".5" stop-color="#f3e6d3"/>'
            '<stop offset="1" stop-color="#c9a883"/></radialGradient>')
    body = (f'<path d="M0 -38 C 18 -38, 28 -8, 28 10 C 28 28, 15 38, 0 38 C -15 38, -28 28, -28 10 '
            f'C -28 -8, -18 -38, 0 -38 Z" fill="url(#eg)" {STROKE}/>'
            f'<path d="M-12 -18 C -16 -10, -18 -2, -17 6" stroke="#fff" stroke-width="3.5" '
            f'stroke-linecap="round" fill="none" opacity=".9"/>')
    return svg(body, (-32, -42, 32, 42), grad)


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, fn in (("milk", milk), ("can", can), ("cheese", cheese), ("bag", bag),
                     ("coins", coins), ("egg", egg)):
        p = os.path.join(OUT, name + ".svg")
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(fn())
        print(os.path.relpath(p, BASE), os.path.getsize(p), "bytes")


if __name__ == "__main__":
    main()
