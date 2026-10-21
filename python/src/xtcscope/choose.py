"""Choosing the GRO and XTC file: the requested one, the only one, or by asking."""

from collections.abc import Callable, Sequence

from xtcscope.errors import EXIT_NO_FILE, XtcscopeError
from xtcscope.files import Candidate, human_size
from xtcscope.log import info, warn

# picks a candidate interactively: (kind, candidates) -> index into candidates
Ask = Callable[[str, Sequence[Candidate]], int]


def ask_with_rich(kind: str, candidates: Sequence[Candidate]) -> int:
    """Show the candidates in a table and ask for one; returns its index."""
    # imported here: rich is only needed when there is something to ask
    from datetime import datetime

    from rich.console import Console
    from rich.prompt import Prompt
    from rich.table import Table

    console = Console(stderr=True)
    table = Table(title=f"{kind} files", title_justify="left")
    for column in ("#", "name", "size", "modified", "atoms"):
        table.add_column(column)

    for i, c in enumerate(candidates, start=1):
        modified = datetime.fromtimestamp(c.mtime).strftime("%Y-%m-%d %H:%M")
        table.add_row(str(i), c.name, human_size(c.size), modified, str(c.natoms))

    console.print(table)
    choices = [str(i) for i in range(1, len(candidates) + 1)]
    answer = Prompt.ask(f"Select the {kind} file", choices=choices, default="1", console=console)
    return int(answer) - 1


def choose(
    kind: str,
    where: str,
    candidates: Sequence[Candidate],
    requested: str | None,
    ask: Ask | None,
) -> Candidate:
    """
    Pick a file: the requested one, the only one, or one the user chooses.

    `ask` is None when the user can't be asked (stdin is not a terminal).
    """
    usable = [c for c in candidates if c.problem is None]
    for c in candidates:
        if c.problem is not None and c.name != requested:
            warn(f"Ignoring {c.name} in {where}: {c.problem}.")

    if requested is not None:
        for c in candidates:
            if c.name == requested:
                if c.problem is not None:
                    raise XtcscopeError(f"{requested} in {where}: {c.problem}.", EXIT_NO_FILE)
                return c
        raise XtcscopeError(f"There is no {requested} in {where}.", EXIT_NO_FILE)

    if not usable:
        raise XtcscopeError(f"No usable {kind} file in {where}.", EXIT_NO_FILE)

    if len(usable) == 1:
        info(f"Using {usable[0].name}")
        return usable[0]

    if ask is None:
        option = f"--{kind.lower()}"
        raise XtcscopeError(
            f"Several {kind} files in {where}; choose one with {option} PATH.", EXIT_NO_FILE
        )

    return usable[ask(kind, usable)]
