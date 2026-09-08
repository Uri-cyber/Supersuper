/* תפריט נגישות.
 *
 * נכתב כאן ולא נלקח מתוסף חיצוני, משלוש סיבות:
 * תוסף חיצוני היה שולח את כתובת ה-IP של כל מבקר לצד שלישי וסותר את מה
 * שכתוב בעמוד הפרטיות; הוא היה נחסם על ידי מדיניות התוכן של האתר; והוא
 * מוכר כמפריע לקוראי מסך אמיתיים במקום לעזור להם.
 *
 * התפריט הזה אינו תחליף לנגישות עצמה. הנגישות האמיתית היא שהאתר עובד
 * במקלדת, שהניגודיות עומדת בתקן ושהמבנה סמנטי, וזה נעשה בקוד עצמו.
 * מה שיש כאן הוא התאמות שהמשתמש בוחר, ולא כיסוי על בעיות.
 *
 * הגדלת הטקסט משתמשת ב-zoom ולא בהגדלת גופן השורש, כי האתר בנוי ביחידות
 * px: נמדד שהגדלת font-size בשורש אינה משנה דבר, ו-zoom כן.
 */
(function () {
  "use strict";

  var KEY = "mehiron_a11y";
  var STEPS = [100, 115, 130, 150];

  var state = { zoom: 100, contrast: false, motion: false, links: false, font: false };

  function load() {
    try {
      var raw = localStorage.getItem(KEY);
      if (raw) {
        var v = JSON.parse(raw);
        for (var k in state) if (k in v) state[k] = v[k];
      }
    } catch (e) { /* אין אחסון, ממשיכים עם ברירות המחדל */ }
  }

  function save() {
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {}
  }

  function apply() {
    var root = document.documentElement;
    root.classList.toggle("a11y-contrast", state.contrast);
    root.classList.toggle("a11y-nomotion", state.motion);
    root.classList.toggle("a11y-links", state.links);
    root.classList.toggle("a11y-font", state.font);

    // הזום חל על התוכן בלבד. אילו חל על הדף כולו, גם התפריט עצמו היה
    // גדל ויוצא מהמסך, ומי שהגדיל את הטקסט לא היה יכול להקטין בחזרה.
    var z = state.zoom / 100;
    ["app", "site-legal-footer"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.style.zoom = z === 1 ? "" : String(z);
    });
    paint();
  }

  // ---------------------------------------------------------------- ממשק
  var panel, btn, lastFocus;

  function row(label, on, act) {
    return '<button type="button" class="a11y-item" data-act="' + act + '" ' +
      'aria-pressed="' + (on ? "true" : "false") + '">' +
      '<span class="a11y-check" aria-hidden="true">' + (on ? "✓" : "") + "</span>" +
      "<span>" + label + "</span></button>";
  }

  function paint() {
    if (!panel) return;
    panel.querySelector(".a11y-body").innerHTML =
      '<div class="a11y-group" role="group" aria-label="גודל טקסט">' +
        '<div class="a11y-label">גודל הטקסט</div>' +
        '<div class="a11y-steps">' +
          '<button type="button" class="a11y-step" data-act="zoom-out" aria-label="הקטנת הטקסט">א−</button>' +
          '<span class="a11y-zoomval" aria-live="polite">' + state.zoom + "%</span>" +
          '<button type="button" class="a11y-step" data-act="zoom-in" aria-label="הגדלת הטקסט">א+</button>' +
        "</div></div>" +
      row("ניגודיות גבוהה", state.contrast, "contrast") +
      row("עצירת תנועה ואנימציות", state.motion, "motion") +
      row("הדגשת קישורים וכפתורים", state.links, "links") +
      row("גופן קריא ומרווח", state.font, "font") +
      '<button type="button" class="a11y-reset" data-act="reset">איפוס ההגדרות</button>' +
      '<p class="a11y-note">ההגדרות נשמרות בדפדפן שלכם בלבד ואינן נשלחות לשום מקום. ' +
      'להצהרת הנגישות המלאה: <a href="legal.html#accessibility">כאן</a>.</p>';
  }

  function open() {
    lastFocus = document.activeElement;
    panel.hidden = false;
    btn.setAttribute("aria-expanded", "true");
    var first = panel.querySelector("button");
    if (first) first.focus();
  }

  function close() {
    panel.hidden = true;
    btn.setAttribute("aria-expanded", "false");
    // הפוקוס חוזר לכפתור שפתח, ולא למקום ששהה בו קודם. מי שסגר בעזרת
    // Escape צריך למצוא את עצמו על הכפתור, ולא בתחילת הדף.
    var back = (lastFocus && lastFocus.focus && document.contains(lastFocus)) ? lastFocus : btn;
    if (back === document.body) back = btn;
    back.focus();
  }

  function build() {
    btn = document.createElement("button");
    btn.type = "button";
    btn.id = "a11y-btn";
    btn.setAttribute("aria-expanded", "false");
    btn.setAttribute("aria-controls", "a11y-panel");
    btn.setAttribute("aria-label", "תפריט נגישות");
    btn.innerHTML = '<span aria-hidden="true">♿</span>';

    panel = document.createElement("div");
    panel.id = "a11y-panel";
    panel.hidden = true;
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-modal", "false");
    panel.setAttribute("aria-label", "הגדרות נגישות");
    panel.innerHTML =
      '<div class="a11y-head"><strong>נגישות</strong>' +
      '<button type="button" class="a11y-close" data-act="close" aria-label="סגירת תפריט הנגישות">✕</button></div>' +
      '<div class="a11y-body"></div>';

    document.body.appendChild(btn);
    document.body.appendChild(panel);

    btn.addEventListener("click", function () {
      if (panel.hidden) open(); else close();
    });

    panel.addEventListener("click", function (ev) {
      var t = ev.target.closest("[data-act]");
      if (!t) return;
      var act = t.getAttribute("data-act");
      if (act === "close") return close();
      if (act === "reset") {
        state = { zoom: 100, contrast: false, motion: false, links: false, font: false };
      } else if (act === "zoom-in") {
        var i = STEPS.indexOf(state.zoom);
        state.zoom = STEPS[Math.min(STEPS.length - 1, (i < 0 ? 0 : i) + 1)];
      } else if (act === "zoom-out") {
        var j = STEPS.indexOf(state.zoom);
        state.zoom = STEPS[Math.max(0, (j < 0 ? 0 : j) - 1)];
      } else {
        state[act] = !state[act];
      }
      save();
      apply();
    });

    // Escape סוגר, כפי שמצופה מכל חלון צף
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && !panel.hidden) close();
    });

    // לחיצה מחוץ לתפריט סוגרת אותו
    document.addEventListener("click", function (ev) {
      if (panel.hidden) return;
      if (panel.contains(ev.target) || btn.contains(ev.target)) return;
      close();
    });
  }

  function init() {
    load();
    build();
    apply();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
