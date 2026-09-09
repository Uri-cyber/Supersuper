/* הכתובת הקבועה של האתר היא mehiron.app.
   הכתובת הישנה mehiron.pages.dev ממשיכה לעבוד, אבל מי שמגיע אליה מועבר
   לכתובת הקבועה, כדי שקישורים ששותפו יובילו תמיד למקום אחד.
   הקובץ נטען ראשון, לפני טעינת הנתונים, כדי לא להוריד את המסד פעמיים. */
(function () {
  var h = location.hostname;
  if (h === "mehiron.pages.dev" || h === "www.mehiron.app") {
    location.replace("https://mehiron.app" + location.pathname + location.search + location.hash);
  }
})();
