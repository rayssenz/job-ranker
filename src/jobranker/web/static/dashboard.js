"use strict";

/* Spares the reload after a decision and adds the motion that needs a script:
   the applied celebration, the quiet leave and the eyes that follow the pointer.
   Without this file every form still works. */

const calm = window.matchMedia("(prefers-reduced-motion: reduce)");
const STAR_SHAPES = ["★", "✦", "●"];
const STARS = 10;
/* How far a pupil moves inside its eye, in pixels. */
const GAZE = 6;
/* The longest wait for a leaving animation, should its end never be reported. */
const LEAVE_LIMIT = 2500;

/* Decisions that were sent and are not answered and shown yet. */
let pending = 0;
/* More than one decision was on its way at once. Then no single answer shows the final
   page, and the page is asked for again when the last one is done. */
let overlapped = false;

/* Resolves when the leaving animation of the card itself has ended. */
function left(card) {
  return new Promise((resolve) => {
    if (!card.isConnected) {
      resolve();
      return;
    }
    const timer = window.setTimeout(resolve, LEAVE_LIMIT);
    card.addEventListener("animationend", (event) => {
      /* The sticker and the stars end their own animations inside the card. */
      if (event.target === card) {
        window.clearTimeout(timer);
        resolve();
      }
    });
  });
}

function celebrate(card) {
  for (let index = 0; index < STARS; index += 1) {
    const star = document.createElement("span");
    star.className = "star";
    star.textContent = STAR_SHAPES[index % STAR_SHAPES.length];
    star.setAttribute("aria-hidden", "true");
    star.style.setProperty("--x", `${Math.round(Math.cos(index * 0.63) * 230)}px`);
    star.style.setProperty("--y", `${Math.round(Math.sin(index * 0.63) * 130)}px`);
    card.append(star);
  }
}

function settle(card) {
  card.classList.remove("applied-now", "leaving");
  card.querySelectorAll(".star").forEach((star) => star.remove());
  delete card.dataset.busy;
}

function parse(text) {
  return new DOMParser().parseFromString(text, "text/html");
}

/* Puts the heading, the counts and, when needed, the list of a fresh page in place. */
function show(page) {
  const top = page.querySelector(".top");
  const list = page.querySelector("main");
  if (!top || !list) {
    window.location.reload();
    return;
  }
  /* With several pages, cards move up from the next page. The whole list is replaced then,
     so no card is skipped and the page links stay right. The same when no card is left. */
  if (document.querySelector(".pager") || !document.querySelector(".card")) {
    const cards = list.querySelector(".cards");
    if (cards) {
      cards.classList.remove("entering");
    }
    document.querySelector("main").replaceWith(document.adoptNode(list));
  }
  document.querySelector(".top").replaceWith(document.adoptNode(top));
  document.title = page.title;
  const badge = document.querySelector(".badge");
  if (badge && !calm.matches) {
    badge.classList.add("bump");
  }
}

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
  /* A second click while the card is leaving must not decide twice. */
  if (card.dataset.busy) {
    return;
  }
  card.dataset.busy = "1";
  const button = event.submitter;
  if (pending > 0) {
    overlapped = true;
  }
  pending += 1;
  let page = null;
  try {
    /* The decision is sent at once. The animation plays while the answer is on its way. */
    const answer = fetch(form.action, {
      method: "POST",
      body: new URLSearchParams(new FormData(form, button)),
    });
    let gone = Promise.resolve();
    if (!calm.matches) {
      const applied = button instanceof HTMLButtonElement && button.value === "applied";
      const cards = card.closest(".cards");
      if (cards) {
        cards.classList.remove("entering");
      }
      gone = left(card);
      card.classList.add(applied ? "applied-now" : "leaving");
      if (applied) {
        celebrate(card);
      }
    }
    const response = await answer;
    if (!response.ok) {
      throw new Error(String(response.status));
    }
    /* The answer is the page after this decision. */
    page = parse(await response.text());
    await gone;
  } catch {
    /* Anything unexpected: bring the card back and send the form the plain way, with a reload. */
    pending -= 1;
    settle(card);
    form.dataset.plain = "1";
    form.requestSubmit(button);
    return;
  }
  pending -= 1;
  card.remove();
  /* While another decision is on its way, the page is shown when that one is done. */
  if (pending > 0) {
    return;
  }
  if (overlapped) {
    overlapped = false;
    try {
      const response = await fetch(window.location.href);
      if (!response.ok) {
        throw new Error(String(response.status));
      }
      page = parse(await response.text());
    } catch {
      window.location.reload();
      return;
    }
    /* A decision that started meanwhile will ask again when it is done. */
    if (pending > 0) {
      overlapped = true;
      return;
    }
  }
  show(page);
});

document.addEventListener("change", (event) => {
  const input = event.target;
  if (input instanceof HTMLInputElement && input.matches(".switch input") && input.form) {
    input.form.requestSubmit();
  }
});

/* The eyes of the new cards follow the pointer, at most once per frame. */
let pointer = null;
let waiting = false;

function look() {
  waiting = false;
  /* Every box is read before any pupil is moved. Reading after a write would make the
     browser work out the layout again for each eye. */
  const eyes = [];
  for (const eye of document.querySelectorAll(".eye")) {
    const box = eye.getBoundingClientRect();
    if (box.bottom >= 0 && box.top <= window.innerHeight) {
      eyes.push([eye.firstElementChild, box]);
    }
  }
  for (const [pupil, box] of eyes) {
    const angle = Math.atan2(
      pointer.clientY - (box.top + box.height / 2),
      pointer.clientX - (box.left + box.width / 2),
    );
    pupil.style.setProperty("--look-x", `${(Math.cos(angle) * GAZE).toFixed(1)}px`);
    pupil.style.setProperty("--look-y", `${(Math.sin(angle) * GAZE).toFixed(1)}px`);
  }
}

document.addEventListener("pointermove", (event) => {
  pointer = event;
  if (waiting || calm.matches) {
    return;
  }
  waiting = true;
  window.requestAnimationFrame(look);
});
