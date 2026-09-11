/* הגדרות מחירון.
   mode "sqlite" = קורא את המסד ישירות מהענן, בלי שרת.
   dbUrl = הכתובת הציבורית של קובץ המסד ב-Cloudflare R2.
   בפיתוח מקומי אפשר להצביע על קובץ מקומי, או להשתמש ב-mode "server". */
window.MEHIRON_CONFIG = {
  mode: "sqlite",
  dbUrl: "https://data.mehiron.app/mehiron-20260911-9123be0d.db",
  // הנתונים נקראים מ-data.mehiron.app, דומיין מותאם על דלי ה-R2. הכתובת
  // מתעדכנת אוטומטית בכל העלאה לפי public_base ב-cloud/r2_config.json.
  chunkSize: 16384,
  workerUrl: "vendor/sqlite.worker.js",
  wasmUrl: "vendor/sql-wasm.wasm",
  cbsUrl: "cities_cbs.json"
};
