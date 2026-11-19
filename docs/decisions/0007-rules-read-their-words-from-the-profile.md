# Rules read their words from the profile and drop only on a certain mismatch

Status: accepted
Date: 2026-11-19

## Context

A company feed returns every open job of a company, so most stored postings cannot fit one person. Judging each of them with a model is slow and uses the subscription for postings that a plain check can rule out. A plain check works on words: place names, level words in a title, words a title should hold. Such word lists describe one person's search, and the repository is public.

A rule that drops too much is hard to notice, because a dropped posting is never shown. A rule that drops too little is noticed, because the posting reaches the judge.

## Decision

* The rules are pure functions of one posting and the profile. No model is involved.
* Every word list is a field of the profile, which is not committed. The code holds no place, level or role word. The names of languages are the one fixed list.
* Words are compared in normalised form and as whole words. A phrase matches when its words follow each other.
* A rule drops a posting only when the mismatch is certain. An empty location, a title without a level word and a language asked for only in the description all pass.
* Every rule is evaluated for every posting, and every reason code that applies is stored.
* A result is stored with the content hash of the posting, a hash of the rule fields of the profile, and the version of the rules. It is computed again when one of the three differs.
* A group of linked postings passes when any posting in it passes.

## Consequences

* The same posting and the same profile always give the same result, so the rules can be unit-tested with a fictional profile.
* The rules are only as good as the word lists in the profile. A level or role word that is missing there lets postings through or drops them.
* Postings that a person would rule out at a glance can still pass. They are left to the judge.
* A reason code can reveal profile details together with the posting, so the stored results stay on the machine.
* A change to what a rule drops needs a new rules version, or stored results stay as they were.
