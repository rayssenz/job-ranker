# Dashboard: the toy box look

Status: proposed on 2026-11-20

## Problem

The dashboard of milestone 3 works, and its "card file" look is calm and office-like. It is opened every day, and the owner wants it to feel alive: bold colour, movement, cards that react, and a satisfying moment when an application is marked.

## What changes

Only the look and the motion. The tabs, the cards, the two decisions, the search, the paging, the stored data and every safety rule stay as they are.

## Look

Thick outlines, hard offset shadows, rounded corners and flat colour. The shapes and the motion are playful, the colours are not those of a toy.

Three brand colours in a 60 / 30 / 10 split, and two helpers:

| Role | Colour | Share | Used for |
|---|---|---|---|
| Base | cream `#f7f0e3`, cards `#fffdf8` | 60% | the page and the cards |
| Brand | electric cobalt `#2433d6` | 30% | headings, the open tab, the run line, the shadow of a card |
| Accent | tangerine `#ff6a13` | 10% | "Applied", the count badge, the applied sticker, nothing else |
| Helper | sunflower `#ffd84d` | small | marks a posting first seen in the last 24 hours |
| Helper | red `#d92d20` | small | a source that was not collected |
| Ink | `#101347` | | text and outlines |

Cobalt, tangerine and sunflower are a split-complementary trio. The accent is kept to one job, so the eye lands on the main button.

The two typefaces stay: Bricolage Grotesque for headings and Instrument Sans for text.

## Motion

| Moment | What happens |
|---|---|
| A page opens | the first cards pop in one after the other; cards further down are simply there |
| The pointer is over a card | the card lifts, tilts a little, and its shadow grows |
| A button is pressed | it sinks into its shadow |
| A card is new today | it has two eyes on its top edge that blink and follow the pointer |
| "Applied" | a tangerine sticker slaps onto the card with a burst of stars, then the card leaves to the side |
| "Not for me" | the card drops away quietly, without a sticker |
| "Undo" | the card leaves the decided tab the same quiet way |
| The count badge | wobbles gently, and jumps when the number changes |

The decision is sent at once. The animation plays while the answer arrives, so nothing waits for it.

A person who asked their system for reduced motion gets no animation at all. Without JavaScript the page still works: the cards appear, the buttons decide with a reload, and the eyes do not follow.

## Constraints

- No file from another machine: no animation library, no icon set, no font service. Motion is CSS, and the small script of the package.
- The content security policy stays `default-src 'self'`. No inline `<style>`, `<script>` or `style=` in a template. The script may set positions through style properties, which the policy allows.
- Every text of a posting is still escaped. The eyes, the sticker and the stars are fixed markup and hold no posting text.
- Text keeps a contrast of at least 4.5 to 1 against its background. Keyboard focus stays visible.
- The layout works on a narrow window.
- A page with fifty cards stays smooth: only the first cards animate in, and the eyes move only for cards on screen.

## Non-goals

- A dark colour scheme.
- A different layout, such as tiles side by side.
- Sound.
- Any change to what the dashboard does or stores.

## Approaches

1. **Restyle in place (chosen).** New colour tokens and motion in the existing stylesheet, a few fixed elements in the card template, and a few more lines in the existing script. The pages stay built on the server and stay tested as text.
2. **Add an animation library.** Smoother effects for less code, but it is a third-party file to pack, review and keep current, and the motion here is simple enough for CSS.
3. **Rebuild the page as a JavaScript application.** More freedom for effects, with a second toolchain and the escaping and safety rules to prove again.

## Acceptance criteria

1. The page uses the colours of the table above, and tangerine appears only on "Applied", the count badge and the applied sticker.
2. Only cards first seen in the last 24 hours have eyes. The eyes blink, and follow the pointer when the script runs.
3. "Applied" shows the sticker and the stars before the card leaves. "Not for me" and "Undo" remove the card without a sticker.
4. The counts and the heading are right after every decision, as before.
5. With reduced motion requested, nothing animates and every action still works.
6. Without JavaScript, every button still works.
7. The pages and the stylesheet still name no other machine and hold no inline style or script. Every answer still carries the safety headers.
8. A posting whose text holds markup is still shown as text.
9. The browser console shows no error and no policy violation on any tab.
10. All tests of milestone 3 that describe behaviour still pass.

## Changes to other documents

- The "Look" part of the milestone 3 spec points to this document.
- The README gets one sentence on the look.
