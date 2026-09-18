// Theme, clipboard and toast helpers. Kept intentionally small; HTMX does the rest.
(function () {
  const root = document.documentElement;

  function toast(message, kind) {
    const host = document.getElementById("toasts");
    if (!host) return;
    const el = document.createElement("div");
    el.className = "toast toast-" + (kind || "info");
    el.setAttribute("role", "status");
    el.textContent = message;
    host.appendChild(el);
    setTimeout(() => el.remove(), 2600);
  }

  document.addEventListener("click", async (event) => {
    const trigger = event.target.closest("[data-copy]");
    if (!trigger) return;
    event.preventDefault();
    try {
      await navigator.clipboard.writeText(trigger.getAttribute("data-copy"));
      toast("Copied", "success");
    } catch (_) {
      toast("Copy failed", "error");
    }
  });

  document.addEventListener("htmx:afterRequest", (event) => {
    const message = event.detail.xhr && event.detail.xhr.getResponseHeader("X-Toast");
    if (message) toast(message, "success");
  });

  // The vendored htmx build has no configurable responseHandling for a 422: by
  // default any 4xx is treated as an error and skipped. Views use 422 for
  // validation failures they still want swapped back into the page, so swap it
  // like a normal response instead of treating it as a request failure.
  document.addEventListener("htmx:beforeSwap", (event) => {
    if (event.detail.xhr && event.detail.xhr.status === 422) {
      event.detail.shouldSwap = true;
      event.detail.isError = false;
    }
  });

  // The element focus returns to once the confirm dialog closes: whatever had focus
  // right before it opened (normally the button that triggered it).
  let modalTrigger = null;

  function closeModal() {
    const modal = document.getElementById("modal");
    if (!modal) return;
    modal.innerHTML = "";
    if (modalTrigger && document.contains(modalTrigger)) modalTrigger.focus();
    modalTrigger = null;
  }

  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-modal-close]")) closeModal();
  });

  document.addEventListener("keydown", (event) => {
    const modal = document.getElementById("modal");
    if (event.key === "Escape" && modal && modal.firstElementChild) closeModal();
  });

  document.addEventListener("htmx:afterSwap", (event) => {
    const modal = document.getElementById("modal");
    const target = event.detail.target;
    if (!modal) return;
    if (target === modal) {
      // The confirm dialog was just swapped into the modal host: remember what
      // triggered it and move focus into the dialog itself, not its backdrop wrapper.
      modalTrigger = document.activeElement;
      const dialog = modal.querySelector('[role="dialog"]');
      if (dialog) dialog.focus();
      return;
    }
    if (modal.firstElementChild && !modal.contains(target)) closeModal();
  });

  // A full-page (non-htmx) re-render with form errors moves focus to the error
  // summary, so a screen reader and keyboard user land on it immediately.
  document.addEventListener("DOMContentLoaded", () => {
    const errorSummary = document.getElementById("form-errors");
    if (errorSummary) errorSummary.focus();
  });

  window.short = { toast, setTheme: (value) => root.setAttribute("data-theme", value) };
})();
