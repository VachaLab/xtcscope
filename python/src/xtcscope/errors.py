"""Expected failures and the exit codes they map to."""

# exit codes
EXIT_OK = 0
EXIT_BUG = 1
EXIT_USAGE = 2
EXIT_NO_JOB = 3
EXIT_NO_WORK_DIR = 4
EXIT_NO_FILE = 5
EXIT_MISMATCH = 6
EXIT_SSH = 7
EXIT_AGENT = 8
EXIT_VIEWER = 9
EXIT_INTERRUPTED = 130


class XtcscopeError(Exception):
    """An expected failure: printed as one ERROR line, exits with `exit_code`."""

    def __init__(self, message: str, exit_code: int):
        """Create an error with its message and exit code."""
        super().__init__(message)
        self.exit_code = exit_code
