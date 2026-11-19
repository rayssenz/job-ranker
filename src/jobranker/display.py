"""What the collect command shows while it runs: finished lines, a bar and the running source."""

from collections.abc import Sequence
from types import TracebackType
from typing import Self

import typer
from rich.console import Console, Group
from rich.live import Live
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)

from jobranker.collect import SourceReport


def summary(reports: Sequence[SourceReport], seconds: float) -> str:
    """The last line of a run."""
    minutes, rest = divmod(int(seconds), 60)
    missed = sum(report.error is not None for report in reports)
    new = sum(report.new for report in reports)
    return (
        f"Done in {minutes}:{rest:02d}: {len(reports)} sources,"
        f" {missed} not collected, {new} new postings."
    )


class RunDisplay:
    """Prints the line of each source when it is finished.

    With `live`, a bar and the name of the running source stay under the lines. Without it
    the output is plain text, which is what a file, a pipe or a scheduled job needs.
    The display only ever gets the source and target of a report, never a token.
    """

    def __init__(self, console: Console, total: int, *, live: bool) -> None:
        self._console = console
        self._live: Live | None = None
        if live:
            self._bar = Progress(
                TextColumn("Collecting"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                console=console,
            )
            self._running = Progress(
                SpinnerColumn(),
                TextColumn("{task.description}", markup=False),
                TimeElapsedColumn(),
                console=console,
            )
            self._bar_task = self._bar.add_task("", total=total)
            self._running_task: TaskID | None = None
            # Transient, so the bar is gone when the run ends or is stopped with Ctrl+C.
            self._live = Live(Group(self._bar, self._running), console=console, transient=True)

    def __enter__(self) -> Self:
        if self._live is not None:
            self._live.start(refresh=True)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._live is not None:
            self._live.stop()

    def start(self, report: SourceReport) -> None:
        if self._live is None:
            return
        self._running_task = self._running.add_task(f"{report.source:<10} {report.target}")
        self._live.refresh()

    def finish(self, report: SourceReport) -> None:
        self.line(report.line())
        if self._live is None:
            return
        if self._running_task is not None:
            self._running.remove_task(self._running_task)
            self._running_task = None
        self._bar.advance(self._bar_task)
        self._live.refresh()

    def line(self, text: str) -> None:
        if self._live is None:
            typer.echo(text)
        else:
            # Printed as written: posting and company names are not markup.
            self._console.print(text, markup=False, highlight=False)
