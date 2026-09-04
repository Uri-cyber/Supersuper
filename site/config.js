/* הגדרות מחירון.
   mode "sqlite" = קורא את המסד ישירות מהענן, בלי שרת.
   dbUrl = הכתובת הציבורית של קובץ המסד ב-Cloudflare R2.
   בפיתוח מקומי אפשר להצביע על קובץ מקומי, או להשתמש ב-mode "server". */
window.MEHIRON_CONFIG = {
  mode: "sqlite",
  dbUrl: "mehiron.db",
  chunkSize: 4096,
  workerUrl: "vendor/sqlite.worker.js",
  wasmUrl: "vendor/sql-wasm.wasm",
  cbsUrl: "cities_cbs.json"
};
