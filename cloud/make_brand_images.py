# -*- coding: utf-8 -*-
"""
מייצר את תמונת השיתוף (og.png) ואת אייקוני האפליקציה לתיקיית site/.

הקובץ נשמר בגיט כדי שאפשר יהיה לחדש את התמונות אם העיצוב משתנה:
    python cloud/make_brand_images.py

Pillow בלי libraqm לא מסדר טקסט מימין לשמאל, ולכן מחרוזות עבריות
נהפכות כאן ידנית. זה נכון רק לטקסט עברי בלי ספרות ובלי אותיות לטיניות,
וכל הטקסט העברי כאן הוא כזה.
"""
import os

from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(BASE, "site")
FONTS = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")

INK = (20, 21, 26)
GREEN = (31, 184, 90)
YELLOW = (255, 203, 61)
WHITE = (255, 255, 255)
MUTED = (170, 172, 180)


def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS, name), size)


def rtl(s):
    return s[::-1]


def logo(size, radius_ratio=0.22, full_bleed=False):
    """ריבוע ירוק עם ₪, כמו ה-favicon של האתר."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if full_bleed:
        d.rectangle([0, 0, size, size], fill=GREEN)
        glyph = int(size * 0.46)      # אזור בטוח לאייקון maskable
    else:
        d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * radius_ratio), fill=GREEN)
        glyph = int(size * 0.62)
    f = font("arialbd.ttf", glyph)
    d.text((size / 2, size / 2 + size * 0.02), "₪", font=f, fill=INK, anchor="mm")
    return img


def og_image():
    W, H = 1200, 630
    img = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(img)
    # צורות רקע, כמו בעמוד הבית
    d.ellipse([-160, -220, 420, 360], fill=(24, 60, 40))
    d.rounded_rectangle([900, 525, 1300, 925], radius=60, fill=(60, 52, 22))
    # לוגו בצד ימין
    lg = logo(190)
    img.paste(lg, (W - 90 - 190, 110), lg)
    right = W - 90 - 190 - 40
    d.text((right, 205), rtl("מחירון"), font=font("arialbd.ttf", 124), fill=WHITE, anchor="rm")
    d.text((W - 90, 390), rtl("השוואת מחירי סופרמרקט בישראל"), font=font("arialbd.ttf", 58),
           fill=WHITE, anchor="rm")
    d.text((W - 90, 470), rtl("כל סניף. כל רשת. לפי הקבצים שהרשתות מפרסמות"), font=font("arial.ttf", 38),
           fill=MUTED, anchor="rm")
    # פס צהוב עם הכתובת
    d.rounded_rectangle([90, 530, 420, 590], radius=30, fill=YELLOW)
    d.text((255, 560), "mehiron.app", font=font("arialbd.ttf", 34), fill=INK, anchor="mm")
    out = os.path.join(SITE, "og.png")
    img.save(out, optimize=True)
    return out


def icons():
    outs = []
    for size, name, bleed in ((192, "icon-192.png", False), (512, "icon-512.png", False),
                              (512, "icon-maskable-512.png", True), (180, "apple-touch-icon.png", True)):
        im = logo(size, full_bleed=bleed)
        if name == "apple-touch-icon.png":
            # iOS לא תומך בשקיפות: רקע מלא, והמערכת מעגלת את הפינות בעצמה
            bg = Image.new("RGB", (size, size), GREEN)
            bg.paste(im, (0, 0), im)
            im = bg
        p = os.path.join(SITE, name)
        im.save(p, optimize=True)
        outs.append(p)
    return outs


if __name__ == "__main__":
    for p in [og_image()] + icons():
        print(os.path.relpath(p, BASE), os.path.getsize(p), "bytes")
