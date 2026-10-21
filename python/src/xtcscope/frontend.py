"""The flow of one run: from the parsed arguments to the closed viewer."""

import argparse
import shlex
import shutil
import sys
import tempfile
from pathlib import Path

from xtcscope.agent import extract_command, extracted_name, fetch_frames
from xtcscope.choose import ask_with_rich, choose
from xtcscope.errors import EXIT_MISMATCH, EXIT_NO_FILE, EXIT_OK, XtcscopeError
from xtcscope.files import list_gro_files, list_xtc_files
from xtcscope.job import find_job, ssh_timeout
from xtcscope.log import info
from xtcscope.transport import Remote
from xtcscope.viewer import launch_viewer, viewer_argv, viewer_words


def run(args: argparse.Namespace) -> int:
    """Run xtcscope with parsed arguments; returns the exit code."""
    words = viewer_words(args.viewer)

    # the job and its working directory
    job = find_job(args.job_id)
    info(f"Job {job.job_id} ({job.name}) runs on {job.node} in {job.work_dir}")

    # the GRO, read locally from the input directory
    if not job.input_dir.is_dir():
        raise XtcscopeError(
            f"Input directory {job.input_dir} is not accessible from this machine.",
            EXIT_NO_FILE,
        )

    ask = ask_with_rich if sys.stdin.isatty() else None
    gro = choose("GRO", str(job.input_dir), list_gro_files(job.input_dir, args.gro), args.gro, ask)
    gro_path = job.input_dir / gro.name

    tmp_dir = Path(tempfile.mkdtemp(prefix="xtcscope-"))
    try:
        # one SSH connection for everything on the node
        with Remote(job.node, tmp_dir, ssh_timeout()) as remote:
            # the XTC, listed on the node
            xtc_files = list_xtc_files(remote, job.work_dir, args.xtc)
            xtc = choose("XTC", f"{job.node}:{job.work_dir}", xtc_files, args.xtc, ask)
            xtc_path = job.work_dir / xtc.name

            # both files must describe the same atoms
            if gro.natoms != xtc.natoms:
                raise XtcscopeError(
                    f"{gro.name} has {gro.natoms} atoms but {xtc.name} has {xtc.natoms}; "
                    "if the job writes only some atoms (compressed-x-grps), "
                    "its input directory needs a GRO with the same atoms.",
                    EXIT_MISMATCH,
                )

            local_xtc = tmp_dir / extracted_name(xtc.name, args.frames)
            fetch = shlex.join(remote.command(extract_command(xtc_path, args.frames)))
            view = shlex.join(viewer_argv(words, gro_path, local_xtc))
            if args.dry_run:
                print(f"job      {job.job_id} ({job.name})")
                print(f"node     {job.node}")
                print(f"gro      {gro_path} ({gro.natoms} atoms)")
                print(f"xtc      {xtc_path} ({xtc.natoms} atoms)")
                print(f"extract  {fetch} > {local_xtc}")
                print(f"view     {view}")
                return EXIT_OK

            # copy the last frames into the temporary directory
            fetch_frames(remote, xtc_path, args.frames, local_xtc)
        # the connection is closed here; nothing else needs the node

        # open the files and wait for the viewer to exit
        info(f"Opening {gro.name} and {local_xtc.name} in {words[0]}")
        launch_viewer(viewer_argv(words, gro_path, local_xtc))
        return EXIT_OK
    finally:
        # remove the control socket and the fetched frames
        shutil.rmtree(tmp_dir, ignore_errors=True)
