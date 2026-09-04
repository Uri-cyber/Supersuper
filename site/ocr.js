/* קריאת קבלה מצילום.
 *
 * המנוע הוא Tesseract והוא רץ כולו בדפדפן. שום תמונה לא נשלחת לשום מקום.
 *
 * למה שתי ריצות ולא אחת. מודל העברית קורא את שמות המוצרים מצוין אבל הורס
 * את הספרות: "7.93" יוצא ממנו "3". מודל האנגלית, כשמגבילים אותו לספרות
 * בלבד, קורא את עמודת המחירים בדיוק מלא - ואת העברית הוא הופך לג'יבריש.
 * לכן רצות שתיהן על אותה תמונה, ומכל אחת נלקח רק מה שהיא טובה בו:
 * השם מריצת העברית, המחיר מריצת הספרות.
 *
 * המחיר נבחר לפי מיקומו בשורה ולא לפי סדר המילים, כי בקבלה ישראלית הוא
 * יושב בקצה השמאלי, ואילו שם מוצר עשוי להכיל מספר משלו ("1.5 ליטר").
 *
 * שורה שלא נקרא בה מחיר תקין יוצאת בלי מחיר כלל. מחיר שגוי גרוע ממחיר
 * חסר: הוא נכנס לחישוב בשקט ואיש לא שם לב שהוא לא נכון.
 *
 * הקריאה לעולם לא מוזנת ישירות להשוואה. היא נכתבת לתיבת הטקסט כדי
 * שהמשתמש יראה מה זוהה ויתקן לפני שמשווים.
 */
(function () {
  "use strict";

  var BASE = "vendor/tesseract/";
  var loading = null;

  // הספרייה נטענת רק כשבאמת בוחרים תמונה. היא כבדה, ורוב המשתמשים
  // מדביקים טקסט ולא צריכים אותה בכלל.
  function loadEngine() {
    if (window.Tesseract) return Promise.resolve();
    if (loading) return loading;
    loading = new Promise(function (ok, fail) {
      var s = document.createElement("script");
      s.src = BASE + "tesseract.min.js";
      s.onload = function () { ok(); };
      s.onerror = function () { loading = null; fail(new Error("טעינת מנוע הקריאה נכשלה")); };
      document.head.appendChild(s);
    });
    return loading;
  }

  var MAX_W = 1600;   // מעבר לזה רק מאט; הדיוק כבר לא משתפר
  var MIN_W = 900;    // מתחת לזה הספרות מתחילות להישבר

  /* התמונה מהטלפון מגיעה גדולה, צבעונית ולא תמיד מוארת אחיד.
   * מקטינים, הופכים לאפור, ומותחים ניגודיות לפי הפיזור בפועל. */
  function prepare(img) {
    var w = img.naturalWidth || img.width, h = img.naturalHeight || img.height;
    var scale = 1;
    if (w > MAX_W) scale = MAX_W / w;
    else if (w < MIN_W) scale = Math.min(2, MIN_W / w);
    var cv = document.createElement("canvas");
    cv.width = Math.round(w * scale);
    cv.height = Math.round(h * scale);
    var x = cv.getContext("2d", { willReadFrequently: true });
    x.drawImage(img, 0, 0, cv.width, cv.height);

    var d = x.getImageData(0, 0, cv.width, cv.height);
    var px = d.data, hist = new Uint32Array(256), i;
    for (i = 0; i < px.length; i += 4) {
      var g = (px[i] * 0.299 + px[i + 1] * 0.587 + px[i + 2] * 0.114) | 0;
      px[i] = px[i + 1] = px[i + 2] = g;
      hist[g]++;
    }
    // חותכים 2% מכל קצה כדי שצל או בוהק לא יקבעו את הסקאלה
    var total = cv.width * cv.height, cut = total * 0.02, acc = 0, lo = 0, hi = 255;
    for (i = 0; i < 256; i++) { acc += hist[i]; if (acc > cut) { lo = i; break; } }
    acc = 0;
    for (i = 255; i >= 0; i--) { acc += hist[i]; if (acc > cut) { hi = i; break; } }
    if (hi - lo > 20) {
      var span = hi - lo;
      for (i = 0; i < px.length; i += 4) {
        var v = (px[i] - lo) / span * 255;
        v = v < 0 ? 0 : v > 255 ? 255 : v;
        px[i] = px[i + 1] = px[i + 2] = v;
      }
    }
    x.putImageData(d, 0, 0);
    return cv;
  }

  function fileToImage(file) {
    return new Promise(function (ok, fail) {
      var url = URL.createObjectURL(file);
      var img = new Image();
      img.onload = function () { URL.revokeObjectURL(url); ok(img); };
      img.onerror = function () { URL.revokeObjectURL(url); fail(new Error("לא הצלחנו לפתוח את התמונה")); };
      img.src = url;
    });
  }

  function recognize(canvas, lang, params, onProgress) {
    return window.Tesseract.createWorker(lang, 1, {
      workerPath: BASE + "worker.min.js",
      corePath: BASE,
      langPath: BASE,
      gzip: true,
      logger: function (m) {
        if (onProgress && m && typeof m.progress === "number") onProgress(m.progress, m.status);
      }
    }).then(function (w) {
      var pre = params ? w.setParameters(params) : Promise.resolve();
      return pre
        .then(function () { return w.recognize(canvas); })
        .then(function (r) {
          return w.terminate().then(function () {
            return r.data.lines.map(function (l) {
              return {
                text: String(l.text || "").trim(),
                words: (l.words || []).map(function (x) {
                  return { t: String(x.text || ""), x0: x.bbox ? x.bbox.x0 : 0, conf: x.confidence };
                })
              };
            }).filter(function (l) { return l.text; });
          });
        });
    });
  }

  var PRICE = /^\d{1,4}[.,]\d{1,2}$/;
  var TAIL = /[\s]*[\d.,]+\s*$/;              // זנב מספרי שבור בסוף שורת שם
  var BIDI = /[‎‏‪-‮⁦-⁩]/g;
  var MIN_CONF = 60;

  function clean(t) { return String(t || "").replace(BIDI, "").trim(); }

  // המילה המספרית השמאלית ביותר בשורה היא המחיר
  function priceOf(line) {
    var best = null;
    line.words.forEach(function (w) {
      var t = clean(w.t);
      if (!PRICE.test(t) || w.conf < MIN_CONF) return;
      if (!best || w.x0 < best.x0) best = { x0: w.x0, t: t };
    });
    return best ? best.t.replace(",", ".") : null;
  }

  function merge(names, digits) {
    // ספירת שורות שונה פירושה שאי אפשר להתאים ביניהן. במקרה כזה מוותרים
    // על המחירים לגמרי ומחזירים רק את השמות, והמשתמש ישלים.
    var aligned = names.length > 0 && names.length === digits.length;
    return names.map(function (a, i) {
      var full = clean(a.text);
      var name = full.replace(TAIL, "").trim() || full;
      var price = aligned ? priceOf(digits[i]) : null;
      return price ? name + "   " + price : name;
    });
  }

  /* שורות שאינן פריטים: סיכומים, אמצעי תשלום, פרטי עוסק, כותרות.
   * הן לא נמחקות בשקט - מספרן מדווח למשתמש. */
  var NOISE = new RegExp(
    ['סה"כ', "סה״כ", "סהכ", "לתשלום", "מזומן", "אשראי", "ויזה", "מסטרקארד",
     "כרטיס", "עודף", 'מע"מ', "מעמ", "חשבונית", "קבלה", "ח\\.פ", "עוסק",
     "טלפון", "כתובת", "תודה", "להתראות", "קופה", "קופאי", "תאריך", "שעה",
     "מספר עסקה", "סניף", "סכום ביניים", "הנחה", "מבצע"].join("|"));

  function looksLikeItem(line) {
    if (!line || line.length < 3) return false;
    if (NOISE.test(line)) return false;
    // שם בעברית באורך סביר, או ברקוד
    if (!/[֐-׿]{2,}/.test(line) && !/\d{8,}/.test(line)) return false;
    return true;
  }

  window.MehironOCR = {
    /* קורא קבלה מקובץ תמונה.
     * onStage(pct, text) מדווח התקדמות; pct בין 0 ל-1. */
    read: function (file, onStage) {
      var stage = onStage || function () {};
      stage(0.02, "טוען את מנוע הקריאה");
      return loadEngine()
        .then(function () { return fileToImage(file); })
        .then(function (img) {
          stage(0.1, "מכינים את התמונה");
          var cv = prepare(img);
          stage(0.15, "קוראים את השמות");
          return recognize(cv, "heb", null, function (p) {
            stage(0.15 + p * 0.4, "קוראים את השמות");
          }).then(function (names) {
            stage(0.55, "קוראים את המחירים");
            return recognize(cv, "eng", {
              tessedit_char_whitelist: "0123456789.,",
              tessedit_pageseg_mode: "6"
            }, function (p) {
              stage(0.55 + p * 0.42, "קוראים את המחירים");
            }).then(function (digits) {
              var all = merge(names, digits);
              var items = all.filter(looksLikeItem);
              var dropped = all.filter(function (l) { return !looksLikeItem(l); });
              var withPrice = items.filter(function (l) { return /\d[.,]\d/.test(l); }).length;
              stage(1, "סיימנו");
              return { lines: items, dropped: dropped, all: all, withPrice: withPrice };
            });
          });
        });
    },
    looksLikeItem: looksLikeItem
  };
})();
