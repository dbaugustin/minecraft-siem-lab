// Small progressive enhancements. Everything works without this file; it's
// loaded from /static because the CSP blocks inline scripts.

// Keep the console and server log scrolled to their newest lines.
document.querySelectorAll("[data-scroll-bottom]").forEach(function (el) {
  el.scrollTop = el.scrollHeight;
});

// Ask before submitting forms marked data-confirm.
document.querySelectorAll("form[data-confirm]").forEach(function (form) {
  form.addEventListener("submit", function (event) {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  });
});

// Large uploads take a while; say so instead of looking frozen.
document.querySelectorAll("form[data-busy]").forEach(function (form) {
  form.addEventListener("submit", function (event) {
    if (event.defaultPrevented) return;
    var button = form.querySelector("button[type=submit]");
    if (button) {
      button.disabled = true;
      button.textContent = form.dataset.busy;
    }
  });
});
