# xtcscope

> [!NOTE]
> This tool works only with jobs submitted with [qq](https://github.com/VachaLab/qq).

View the last frames of a running GROMACS job in VMD 1.9, VMD 2, ViaMD or any viewer that opens `<command> <gro> <xtc>`, even when the trajectory sits on the compute node's local scratch.

A small Rust agent on the compute node copies the last complete frames of the XTC through SSH to a temporary file on your desktop, and your viewer opens it like any local trajectory. The simulation is not touched.

### Why not run VMD on the compute node?

Over X11, every redraw crosses the network as a picture, so rotating and zooming lag. xtcscope sends the coordinates once, and your desktop draws them as fast as a local file.

### Why not open the remote XTC in a local VMD, through sshfs or a tunnel?

An XTC has no index, so VMD has to read the whole file, which can be gigabytes over the network, to reach the last frames. The agent jumps to the end and sends only the frames you asked for, so a longer trajectory doesn't slow it down. It also skips a frame mdrun is still writing, which could otherwise cause an error.

### Why not run a VNC server on the compute node and connect to it with a VNC viewer?

Yeah. And do you know how to do that?

## Requirements

- [uv](https://docs.astral.sh/uv) needs to be installed on your desktop.
- Supports only jobs submitted with [qq](https://github.com/VachaLab/qq). Infinity and raw PBS are **not** supported.
- You need to have a viewer: VMD 1.9, VMD 2, ViaMD, or another program that opens `<command> <gro> <xtc>`.

## Installing on Robox

Install or update the latest release on your desktop and the compute nodes:

```bash
bash <(curl -fsSL https://github.com/VachaLab/xtcscope/releases/latest/download/xtcscope-robox-install.sh)
```

Pre-releases are never "latest"; install one with its own URL:

```bash
https://github.com/VachaLab/xtcscope/releases/download/<version>/xtcscope-robox-install.sh
```

It installs `xtcscope/` into `$HOME` and into `/storage/brno14-ceitec/home/$USER`. Running it again with the same version changes nothing.

> [!NOTE]
> The installer refuses to touch an existing `~/xtcscope` that is not an installation, so don't clone this repository to `~/xtcscope`.

## Usage

```bash
xtcscope [JOB_ID] [--viewer CMD] [--gro PATH] [--xtc PATH] [-n N] [--dry-run] [--debug]
```

Go to the directory you submitted the job from and run

```bash
xtcscope
```

xtcscope finds the newest qq job there, takes the GRO from that directory and the XTC from the job's working directory, copies the last 10 frames to your desktop and opens them in VMD. The copy is deleted when you close the viewer. You may need to load the VMD module before running the command.

More examples:

```bash
xtcscope 1234567                    # a job by its ID, from any directory
xtcscope -n 50                      # the last 50 frames
xtcscope --viewer viamd             # open in ViaMD
xtcscope --xtc md_whole.xtc         # pick the XTC without being asked
xtcscope --xtc run2/md.xtc          # an XTC in a subdirectory of the working directory
xtcscope --dry-run                  # show what would be fetched and opened
```

### Options

| Option               | Meaning                                                                      | Default                                        |
| -------------------- | ---------------------------------------------------------------------------- | ---------------------------------------------- |
| `JOB_ID`             | The job to view.                                                             | The newest qq job in the current directory.    |
| `--viewer CMD`       | Command that opens `<gro> <xtc>`; may include options, e.g. `"vmd -nt"`.     | `$XTCSCOPE_VIEWER`, or `vmd`.                  |
| `--gro PATH`         | GRO file, relative to the job's input directory, or absolute.                | The only one in the input directory, or ask.   |
| `--xtc PATH`         | XTC file on the node, relative to the job's working directory, or absolute.  | The only one in the working directory, or ask. |
| `-n N`, `--frames N` | Number of frames from the end of the XTC; all of them if there are fewer.    | 10                                             |
| `--dry-run`          | Choose and check the files, then print the commands instead of running them. |                                                |
| `--debug`            | Print every command and every message from the Rust agent.                   |                                                |
| `--version`          | Print the version.                                                           |                                                |

When there are several GRO or XTC files, xtcscope lists them, newest first, with their sizes and atom counts, and asks which one to use. Files it can't use (empty, not an XTC, not a valid GRO) are skipped with a warning. Without `--gro` or `--xtc`, only the top level of the directory is searched.

### Viewers

Any program that loads a structure and a trajectory given as `<command> <gro> <xtc>` works:

| Viewer  | `--viewer`          |
| ------- | ------------------- |
| VMD 1/2 | `vmd` (the default) |
| ViaMD   | `viamd`             |

To change the default for good, set `XTCSCOPE_VIEWER` in your `.bashrc`, e.g. `export XTCSCOPE_VIEWER=viamd`.

### Exit codes

| Code | Meaning                                                                                           |
| ---- | ------------------------------------------------------------------------------------------------- |
| 0    | Done: the viewer was closed.                                                                      |
| 1    | Unexpected error (a bug; please report it).                                                       |
| 2    | Invalid arguments.                                                                                |
| 3    | No job found: unknown ID, or no qq job in the current directory.                                  |
| 4    | The job has no working directory, or it is not accessible on the node.                            |
| 5    | The input directory is not accessible, no usable GRO or XTC file, or a named file does not exist. |
| 6    | The GRO and XTC have different atom counts, or a file is not readable.                            |
| 7    | The SSH connection to the node failed.                                                            |
| 8    | The agent failed: not installed, an error, or an incomplete copy.                                 |
| 9    | The viewer was not found or could not be started.                                                 |
| 130  | Interrupted (Ctrl-C).                                                                             |

## Limitations

- **Does not follow a running simulation.** xtcscope copies the last frames once and doesn't follow the job. To see newer frames, run it again.
- **The newest frame may be missing.** A frame mdrun is still writing is skipped, and mdrun writes its output in bursts, so the file on the node can lag the simulation by minutes.
- **The GRO comes from the input directory.** Its atoms must match the XTC's exactly. A job that writes only some atoms (`compressed-x-grps`) needs a matching GRO in its input directory; files created during the run, such as `confout.gro`, can't be used.

## Troubleshooting

| Message                                             | What to do                                                                   |
| --------------------------------------------------- | ---------------------------------------------------------------------------- |
| `xtcscope-agent is not installed on <node>`         | Run the installer; it installs the agent into Robox home too.                |
| `Several XTC files ...; choose one with --xtc PATH` | Without a terminal to ask on, name the file with `--xtc` (or `--gro`).       |
| `... has N atoms but ... has M`                     | The GRO and the XTC describe different atoms.                                |
| `Viewer '...' was not found`                        | Install the viewer, or point `--viewer` or `XTCSCOPE_VIEWER` at its command. |

`--debug` shows every SSH command and every message from the agent, which usually tells where things went wrong.
