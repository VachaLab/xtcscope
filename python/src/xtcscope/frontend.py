"""The flow of one run: from the parsed arguments to the closed viewer."""

import argparse
import shlex
import shutil
import sys
import tempfile
from pathlib import Path

from xtcscope.agent import extracted_name, fetch_frames
from xtcscope.backend import Backend, LocalBackend
from xtcscope.choose import ask_with_rich, choose
from xtcscope.errors import EXIT_MISMATCH, EXIT_OK, XtcscopeError
from xtcscope.job import ACCESS_DIRECT
from xtcscope.log import info
from xtcscope.transport import new_run_id
from xtcscope.viewer import launch_viewer, viewer_argv, viewer_words


def run(args: argparse.Namespace) -> int:
    """Run xtcscope with parsed arguments; returns the exit code."""
    words = viewer_words(args.viewer)
    backend: Backend = LocalBackend(new_run_id())

    tmp_dir = Path(tempfile.mkdtemp(prefix="xtcscope-"))
    try:
        # the job, how its working directory is read, and its GRO and XTC files
        inspection = backend.inspect(args.job_id, args.gro, args.xtc, args.access)
        job, access = inspection.job, inspection.access

        ask = ask_with_rich if sys.stdin.isatty() else None
        gro = choose("GRO", str(job.input_dir), inspection.gro, args.gro, ask)
        where = str(job.work_dir) if access.mode == ACCESS_DIRECT else f"{job.node}:{job.work_dir}"
        xtc = choose("XTC", where, inspection.xtc, args.xtc, ask)

        # both files must describe the same atoms
        if gro.natoms != xtc.natoms:
            raise XtcscopeError(
                f"{gro.name} has {gro.natoms} atoms but {xtc.name} has {xtc.natoms}; "
                "if the job writes only some atoms (compressed-x-grps), "
                "its input directory needs a GRO with the same atoms.",
                EXIT_MISMATCH,
            )

        xtc_path = job.work_dir / xtc.name
        local_xtc = tmp_dir / extracted_name(xtc.name, args.frames)
        plan = backend.fetch_plan(inspection, xtc_path, args.frames)
        if args.dry_run:
            gro_path = job.input_dir / gro.name
            print(f"job      {job.job_id} ({job.name})")
            print(f"node     {job.node}")
            print(f"backend  {backend.label}")
            print(f"access   {access.summary(job.node)}")
            print(f"gro      {gro_path} ({gro.natoms} atoms)")
            print(f"xtc      {xtc_path} ({xtc.natoms} atoms)")
            print(f"extract  {shlex.join(plan.argv)} > {local_xtc}")
            print(f"view     {shlex.join(viewer_argv(words, gro_path, local_xtc))}")
            return EXIT_OK

        # the GRO where the viewer can read it, then the last frames
        gro_path = backend.gro_file(inspection, gro.name, tmp_dir)
        fetch_frames(plan, xtc.name, local_xtc)

        # nothing else needs the node or the backend
        backend.close()

        # open the files and wait for the viewer to exit
        info(f"Opening {gro.name} and {local_xtc.name} in {words[0]}")
        launch_viewer(viewer_argv(words, gro_path, local_xtc))
        return EXIT_OK
    finally:
        backend.close()
        # remove the fetched frames
        shutil.rmtree(tmp_dir, ignore_errors=True)
