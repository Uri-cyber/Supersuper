/* הגדרות מחירון.
   mode "sqlite" = קורא את המסד ישירות מהענן, בלי שרת.
   dbUrl = הכתובת הציבורית של קובץ המסד ב-Cloudflare R2.
   בפיתוח מקומי אפשר להצביע על קובץ מקומי, או להשתמש ב-mode "server". */
window.MEHIRON_CONFIG = {
  mode: "sqlite",
  dbUrl: "https://pub-9f8d54e9d7434c0cbc04eb10276f8b32.r2.dev/mehiron.db",
  // 16KB ולא 4KB: כתובת r2.dev לא נשמרת במטמון של קלאודפלייר וההשהיה שלה
  // כ-280 מ"ש לבקשה, ולכן עדיף פחות בקשות גדולות. עם דומיין משלכם
  // ההשהיה יורדת לכ-40 מ"ש ואפשר לחזור ל-4096 כדי לחסוך בנפח.
  chunkSize: 16384,
  workerUrl: "vendor/sqlite.worker.js",
  wasmUrl: "vendor/sql-wasm.wasm",
  cbsUrl: "cities_cbs.json"
};
