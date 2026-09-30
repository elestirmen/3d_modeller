// Tema tercihini sayfa çizilmeden önce uygula (açılışta renk yanıp sönmesini önler).
(function () {
  try {
    var theme = localStorage.getItem('theme');
    if (theme === 'dark' || theme === 'light') document.documentElement.setAttribute('data-theme', theme);
  } catch (error) { /* depolama kapalı olabilir */ }
})();
