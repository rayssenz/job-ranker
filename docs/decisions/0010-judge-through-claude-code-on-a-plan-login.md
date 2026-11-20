# The judge runs through Claude Code on a plan login

Status: accepted
Date: 2026-11-20

## Context

A model has to read each posting that passed the rules and say whether it fits the profile. A model can be reached with an API key, which is billed per token, or through Claude Code's non-interactive mode, which uses the login of Claude Code. The vendor's help pages state that this mode, signed in with a plan, draws from the usage limits of the plan. A call is still billed on top of the plan when a model API key is set in the environment, or when the account has usage credits turned on and a plan limit is reached.

## Decision

* The judge runs `claude -p` as a subprocess, once per posting, with a JSON schema for the answer, no tools, no saved session, no user or project settings, no MCP server, no skill, a fixed system prompt and a pinned model. It runs in an empty temporary folder and gets the prompt on standard input.
* The program holds no model API key and reads none.
* Before the first call the command checks that `claude` is installed, that no variable is set that would lead to a billed call, and that `claude auth status` reports a plan login. It refuses to start otherwise.
* A reached plan limit stops the run at once. The verdicts stored so far are kept and the next run continues.
* A failed call stores no verdict and is counted for its posting, which then waits behind the others. Three failed calls in a row stop the run.
* Usage credits are a setting of the account and outside the program. The README says that they have to be off.
* The cost figure in each answer is stored as a notional figure. On a plan login it is not a charge.
* The posting text is passed between fixed markers, and the system prompt says that nothing between them is an instruction.
* The tests and CI use a fake judge or a stand-in program. They call no model and need no login.

## Consequences

* Judging adds no cost to a plan as long as usage credits are off.
* Judging shares the plan limits with every other use of the account, so a large run can block that use until the limit resets. The run limit of 40 postings keeps one run small.
* The start check names a variable that is set and never prints its value.
* A posting that tries to give orders can at worst get a wrong yes or no for itself, because the model has no tools.
* The limit messages of Claude Code are recognised by their first words. When the wording changes, the rule of three failures in a row still stops the run.
* The vendor can change how this mode is billed. The judge sits behind an interface, so another backend can be added.
* CI cannot show that the real program still accepts the command line. One real call is made by hand when the flags or the schema change.
