/* הגדרות מחירון.
   mode "sqlite" = קורא את המסד ישירות מהענן, בלי שרת.
   dbUrl = הכתובת הציבורית של קובץ המסד ב-Cloudflare R2.
   בפיתוח מקומי אפשר להצביע על קובץ מקומי, או להשתמש ב-mode "server". */
window.MEHIRON_CONFIG = {
  mode: "sqlite",
  dbUrl: "https://pub-9f8d54e9d7434c0cbc04eb10276f8b32.r2.dev/mehiron-20260911-971d5a70.db",
  // הנתונים נקראים מכתובת r2.dev ולא מ-data.mehiron.app בכוונה: נמדד
  // (11.09.2026, 80 בקשות על חיבור קבוע) חציון 79 מ"ש מול 201 מ"ש בדומיין
  // המותאם. המטמון של Cloudflare במסלול החינמי מוגבל ל-512 מגה לקובץ,
  // וקובץ הנתונים גדול פי ארבעה, ולכן הדומיין המותאם רק מוסיף תחנה.
  // הכתובת מתעדכנת בכל העלאה לפי public_base ב-cloud/r2_config.json.
  chunkSize: 16384,
  workerUrl: "vendor/sqlite.worker.js",
  wasmUrl: "vendor/sql-wasm.wasm",
  cbsUrl: "cities_cbs.json"
};
