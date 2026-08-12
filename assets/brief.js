// Progressive enhancement only. The page is complete without this file.
// 1) Thin scroll-progress bar tinted by the brief currently in view.
// 2) Scroll-spy highlighting the sidebar TOC.
(function () {
  'use strict';
  var bar = document.getElementById('progress');
  var briefs = Array.prototype.slice.call(document.querySelectorAll('section.brief'));
  var accents = { exec: '#17a673', prac: '#6a63f0', stack: '#2aa8c4', mkts: '#e0443e', land: '#8f5ce0' };

  function briefClass(el) {
    var m = el.className.match(/\b(exec|prac|stack|mkts|land)\b/);
    return m ? m[1] : null;
  }

  function onScroll() {
    if (!bar) return;
    var doc = document.documentElement;
    var max = doc.scrollHeight - window.innerHeight;
    bar.style.width = (max > 0 ? (window.scrollY / max) * 100 : 0) + '%';
    for (var i = briefs.length - 1; i >= 0; i--) {
      if (briefs[i].getBoundingClientRect().top <= 90) {
        var c = briefClass(briefs[i]);
        if (c && accents[c]) bar.style.background = accents[c];
        return;
      }
    }
    bar.style.background = '#ff4a1c';
  }
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  var links = Array.prototype.slice.call(document.querySelectorAll('.side-in a[href^="#"]'));
  if (!links.length || !('IntersectionObserver' in window)) return;
  var byId = {};
  links.forEach(function (a) { byId[a.getAttribute('href').slice(1)] = a; });
  var current = null;
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (!e.isIntersecting) return;
      if (current) current.classList.remove('on');
      current = byId[e.target.id] || null;
      if (current) current.classList.add('on');
    });
  }, { rootMargin: '-70px 0px -70% 0px' });
  Object.keys(byId).forEach(function (id) {
    var el = document.getElementById(id);
    if (el) io.observe(el);
  });
})();
