"""The selection rule: requested name, single match, or ask."""

import pytest


@pytest.fixture
def files(xtcscope):
    """Two usable XTC files and one that can't be used."""
    C = xtcscope.Candidate
    return [
        C("new.xtc", 10, 300.0, 100),
        C("old.xtc", 10, 100.0, 100),
        C("empty.xtc", 0, 200.0, None, "empty"),
    ]


def test_requested_name_wins(xtcscope, files):
    """A name from the command line is used without asking."""
    chosen = xtcscope.choose("XTC", "node:/w", files, "old.xtc", ask=None)
    assert chosen.name == "old.xtc"


def test_requested_name_missing(xtcscope, files):
    """A requested name that doesn't exist is exit 5."""
    with pytest.raises(xtcscope.XtcscopeError) as exc:
        xtcscope.choose("XTC", "node:/w", files, "nope.xtc", ask=None)
    assert exc.value.exit_code == xtcscope.EXIT_NO_FILE
    assert "There is no nope.xtc in node:/w" in str(exc.value)


def test_requested_name_unusable(xtcscope, files):
    """A requested file that can't be used says why."""
    with pytest.raises(xtcscope.XtcscopeError) as exc:
        xtcscope.choose("XTC", "node:/w", files, "empty.xtc", ask=None)
    assert "empty" in str(exc.value)


def test_single_usable_file_is_taken(xtcscope, files, capsys):
    """One usable file is chosen automatically; unusable ones are mentioned."""
    chosen = xtcscope.choose("XTC", "node:/w", files[1:], None, ask=None)
    assert chosen.name == "old.xtc"
    err = capsys.readouterr().err
    assert "Using old.xtc" in err
    assert "Ignoring empty.xtc" in err


def test_several_files_ask(xtcscope, files):
    """Several usable files: the user picks from the usable ones, newest first."""
    seen = []

    def ask(kind, candidates):
        """Record the offer and pick the second entry."""
        seen.append((kind, [c.name for c in candidates]))
        return 1

    chosen = xtcscope.choose("XTC", "node:/w", files, None, ask=ask)
    assert chosen.name == "old.xtc"
    assert seen == [("XTC", ["new.xtc", "old.xtc"])]


def test_several_files_without_a_terminal(xtcscope, files):
    """Without a terminal to ask on, several files are an error naming the option."""
    with pytest.raises(xtcscope.XtcscopeError) as exc:
        xtcscope.choose("XTC", "node:/w", files, None, ask=None)
    assert exc.value.exit_code == xtcscope.EXIT_NO_FILE
    assert "--xtc PATH" in str(exc.value)


def test_no_usable_files(xtcscope, files):
    """Nothing usable is exit 5, naming the place searched."""
    with pytest.raises(xtcscope.XtcscopeError) as exc:
        xtcscope.choose("GRO", "/input", files[2:], None, ask=None)
    assert exc.value.exit_code == xtcscope.EXIT_NO_FILE
    assert "No usable GRO file in /input" in str(exc.value)
