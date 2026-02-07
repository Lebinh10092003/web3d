// Minimal helper to keep modal titles in sync with loaded content.
(function () {
  function setModalTitle(modalId, title) {
    if (!modalId || !title) return;
    var heading = document.getElementById(modalId);
    if (!heading) return;
    heading.textContent = title;
  }

  function refreshAuthModalTitle() {
    var container = document.querySelector("#auth-modal-body .auth-modal[data-aphile-title]");
    var title = container ? container.getAttribute("data-aphile-title") : "";
    if (title) {
      setModalTitle("auth-modal-title", title);
    }
  }

  document.addEventListener("DOMContentLoaded", refreshAuthModalTitle);

  document.addEventListener("htmx:afterSwap", function (event) {
    if (event.target && event.target.id === "auth-modal-body") {
      refreshAuthModalTitle();
    }
  });

  // Expose globally if needed
  window.aphile = { setModalTitle: setModalTitle, refreshAuthModalTitle };
})();
