// Bochman Lab — small progressive-enhancement helpers (no build step needed)

document.addEventListener("DOMContentLoaded", function () {
  // Publications page: simple client-side filter over the list already in the page.
  var search = document.getElementById("pub-search");
  if (search) {
    var items = Array.prototype.slice.call(document.querySelectorAll("#pub-list > li"));
    search.addEventListener("input", function () {
      var q = search.value.trim().toLowerCase();
      var shown = 0;
      items.forEach(function (li) {
        var match = !q || li.textContent.toLowerCase().indexOf(q) !== -1;
        li.style.display = match ? "" : "none";
        if (match) shown++;
      });
      var count = document.getElementById("pub-count");
      if (count) count.textContent = shown + " of " + items.length + " shown";
    });
  }

  // News & Events page: same simple client-side filter pattern.
  var newsSearch = document.getElementById("news-search");
  if (newsSearch) {
    var newsItems = Array.prototype.slice.call(document.querySelectorAll("#news-list > li"));
    newsSearch.addEventListener("input", function () {
      var q = newsSearch.value.trim().toLowerCase();
      var shown = 0;
      newsItems.forEach(function (li) {
        var match = !q || li.textContent.toLowerCase().indexOf(q) !== -1;
        li.style.display = match ? "" : "none";
        if (match) shown++;
      });
      var count = document.getElementById("news-count");
      if (count) count.textContent = shown + " of " + newsItems.length + " shown";
    });
  }
});
