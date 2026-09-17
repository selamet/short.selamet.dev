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

  function closeModal() {
    const modal = document.getElementById("modal");
    if (modal) modal.innerHTML = "";
  }

  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-modal-close]")) closeModal();
  });

  document.addEventListener("htmx:afterSwap", (event) => {
    const modal = document.getElementById("modal");
    const target = event.detail.target;
    if (modal && target && !modal.contains(target)) closeModal();
  });

  window.short = { toast, setTheme: (value) => root.setAttribute("data-theme", value) };
})();
