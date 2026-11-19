"use strict";

/* Spares the reload after a decision. Without this file every form still works. */

document.addEventListener("submit", async (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || !form.matches("form.decision")) {
    return;
  }
  const card = form.closest(".card");
  if (!card || form.dataset.plain) {
    return;
  }
  event.preventDefault();
  const button = event.submitter;
  try {
    const body = new URLSearchParams(new FormData(form, button));
    const response = await fetch(form.action, { method: "POST", body });
    if (!response.ok) {
      throw new Error(String(response.status));
    }
    /* The answer is the page after the decision. Its heading and counts replace the old ones. */
    const page = new DOMParser().parseFromString(await response.text(), "text/html");
    const top = page.querySelector(".top");
    card.remove();
    if (!top || !document.querySelector(".card")) {
      window.location.reload();
      return;
    }
    document.querySelector(".top").replaceWith(document.adoptNode(top));
    document.title = page.title;
  } catch {
    /* Anything unexpected: send the form the plain way, with a reload. */
    form.dataset.plain = "1";
    form.requestSubmit(button);
  }
});

document.addEventListener("change", (event) => {
  const input = event.target;
  if (input instanceof HTMLInputElement && input.matches(".switch input") && input.form) {
    input.form.requestSubmit();
  }
});
