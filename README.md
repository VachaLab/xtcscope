# xtcscope

> [!NOTE]
> This tool was written for the specific needs of the [RoVa research group](https://vacha.ceitec.cz/) and works only with jobs submitted with [qq](https://github.com/VachaLab/qq).

xtcscope shows the last frames of a running GROMACS job straight from the compute node's local scratch. It is much smoother than running VMD on the node and much faster than copying the whole trajectory. It can also be used to view your jobs on Karolina/LUMI from your Robox desktop or to display jobs directly on your home computer.

## How it works

xtcscope gets the job's main node, working directory and input directory from [qq_lib](https://qq.readthedocs.io/en/stable/qq_lib.html). It takes the GRO from the input directory and lists the XTC files in the working directory, checking that their atom counts match. If the working directory is readable on this machine, everything runs locally; otherwise xtcscope opens one SSH master connection to the main node.

On the node, `xtcscope-agent` (a static Rust binary) scans the XTC backwards from its end for frame headers. It accepts the last N frames only if they chain exactly to the end of the file, so a frame mdrun is still writing is skipped. It streams those frames' bytes, unchanged, into a temporary file, which together with the GRO is opened in your viewer and deleted when the viewer exits.

With `--remote HOST`, xtcscope runs itself on `HOST` over a single SSH connection. `HOST` performs all of the above, reaching the node with its own credentials, and only the GRO and the extracted frames come back to your machine.

## Installing

Install or update the latest release with the installer for a specific cluster, e.g. for Robox:

```bash
bash <(curl -fsSL https://github.com/VachaLab/xtcscope/releases/latest/download/xtcscope-robox-install.sh)
```

| Where                                            | Installer                         | Installs into                                   |
| ------------------------------------------------ | --------------------------------- | ----------------------------------------------- |
| Robox                                            | `xtcscope-robox-install.sh`       | `$HOME` and `/storage/brno14-ceitec/home/$USER` |
| Metacentrum Grid                                 | `xtcscope-metacentrum-install.sh` | `$HOME` and every Metacentrum storage home      |
| Sokar                                            | `xtcscope-sokar-install.sh`       | `$HOME`                                         |
| Karolina                                         | `xtcscope-karolina-install.sh`    | `$HOME`                                         |
| LUMI                                             | `xtcscope-lumi-install.sh`        | `$HOME`                                         |
| A machine without a batch system, for `--remote` | `xtcscope-desktop-install.sh`     | `$HOME`                                         |

Each installer puts `xtcscope/` into every home listed and adds it to `PATH` through a block in that home's `.bashrc`; open a new terminal afterwards. Homes that don't exist are skipped with a warning. Running an installer again with the same version changes nothing.

If you are using a shell other than bash (zsh, fish), you need to modify the corresponding RC file yourself.

To install a specific version of the tool, use a URL like this:

```bash
https://github.com/VachaLab/xtcscope/releases/download/<version>/xtcscope-robox-install.sh
```

## Usage

```bash
xtcscope [JOB_ID] [--remote HOST] [--access MODE] [--viewer CMD] [--gro PATH] [--xtc PATH] [-n N] [--dry-run] [--debug]
```

Go to the directory you submitted the job from and run

```bash
xtcscope
```

xtcscope finds the newest qq job there, takes the GRO from that directory and the XTC from the job's working directory, copies the last 10 frames to your desktop, and opens them in VMD. **Note that on Robox, you will need to load a VMD module first.** Also note that you will see 11 frames, where the first frame in VMD corresponds to the structure from the GRO file.

The copied part of the trajectory is deleted when you close the viewer.

More examples:

```bash
xtcscope 1234567                                     # a job by its ID, from any directory
xtcscope -n 50                                       # the last 50 frames
xtcscope --viewer viamd                              # open in ViaMD
xtcscope --xtc md_whole.xtc                          # pick the XTC without being asked
xtcscope --xtc run2/md.xtc                           # an XTC in a subdirectory of the working directory
xtcscope --dry-run                                   # show what would be fetched and opened
xtcscope --remote example.ceitec.muni.cz 1234567     # from home, through a machine that reaches the cluster
```

### Options

| Option               | Meaning                                                                      | Default                                        |
| -------------------- | ---------------------------------------------------------------------------- | ---------------------------------------------- |
| `JOB_ID`             | The job to view. Required with `--remote`.                                   | The newest qq job in the current directory.    |
| `--remote HOST`      | Look up the job and extract its frames on `HOST`; see below.                 | This machine.                                  |
| `--access MODE`      | How the working directory is read: `auto`, `direct` or `node`; see below.    | `auto`                                         |
| `--viewer CMD`       | Command that opens `<gro> <xtc>`; may include options, e.g. `"vmd -nt"`.     | `$XTCSCOPE_VIEWER`, or `vmd`.                  |
| `--gro PATH`         | GRO file, relative to the job's input directory, or absolute.                | The only one in the input directory, or ask.   |
| `--xtc PATH`         | XTC file, relative to the job's working directory, or absolute.              | The only one in the working directory, or ask. |
| `-n N`, `--frames N` | Number of frames from the end of the XTC; all of them if there are fewer.    | 10                                             |
| `--dry-run`          | Choose and check the files, then print the commands instead of running them. |                                                |
| `--debug`            | Print every command and every message from the Rust agent.                   |                                                |
| `--version`          | Print the version.                                                           |                                                |

When there are several GRO or XTC files, xtcscope lists them, newest first, with their sizes and atom counts, and asks which one to use. Files it can't use (empty, not an XTC, not a valid GRO) are skipped with a warning. Without `--gro` or `--xtc`, only the top level of the directory is searched.

### From another machine: `--remote`

`--remote HOST` runs everything except the viewer on `HOST`: it finds the job, lists and reads the files, and extracts the frames there, then copies the GRO and the frames to your machine. Use it from home with your work desktop as `HOST`, or from your desktop with a supercomputer's frontend as `HOST`.

1. Install xtcscope on `HOST` (or on the cluster `HOST` belongs to) with the cluster's installer.
2. Install the **same version** on your own machine, with `xtcscope-desktop-install.sh` if it has no batch system.
3. Run `xtcscope --remote HOST JOB_ID`.

`HOST` is anything `ssh` accepts, so an alias from `~/.ssh/config` works. You may be asked to type your password when using `--remote`, but at most once.

> [!WARNING]
> If you want to view a job on a cluster, you first need to install `xtcscope` on that cluster, as shown above. It's not enough to install it only on your desktop.

### How the working directory is read: `--access`

With the default `--access auto`, xtcscope reads the job's working directory directly, with no SSH to the compute node, when the directory exists on the machine that looks up the job (`HOST` with `--remote`) and either is on shared storage or belongs to a job running on that machine. Otherwise, it connects to the job's main node. This covers jobs running on your own desktop, jobs with `--work-dir input_dir`, and supercomputers whose working directories are shared, such as Karolina and LUMI. You can force a specific way of accessing the working directory with `--access direct` or `--access node`.

### Viewers

Any program that loads a structure and a trajectory given as `<command> <gro> <xtc>` works:

| Viewer  | `--viewer`          |
| ------- | ------------------- |
| VMD 1/2 | `vmd` (the default) |
| ViaMD   | `viamd`             |

To change the default for good, set `XTCSCOPE_VIEWER` in your `.bashrc`, e.g. `export XTCSCOPE_VIEWER=viamd`.

### Exit codes

| Code | Meaning                                                                                                |
| ---- | ------------------------------------------------------------------------------------------------------ |
| 0    | Done: the viewer was closed.                                                                           |
| 1    | Unexpected error (a bug; please [report it](https://github.com/VachaLab/xtcscope/issues)).             |
| 2    | Invalid arguments.                                                                                     |
| 3    | No job found: unknown ID, or no qq job in the current directory.                                       |
| 4    | The job has no working directory, or it is not accessible (with `--access direct`: not readable here). |
| 5    | The input directory is not accessible, no usable GRO or XTC file, or a named file does not exist.      |
| 6    | The GRO and XTC have different atom counts, or a file is not readable.                                 |
| 7    | An SSH connection failed: to the node, or to the `--remote` host.                                      |
| 8    | The agent failed: not installed, an error, or an incomplete copy.                                      |
| 9    | The viewer was not found or could not be started.                                                      |
| 10   | xtcscope on the `--remote` host failed: not installed there, a different release, or an error.         |
| 130  | Interrupted (Ctrl-C).                                                                                  |

## Limitations

- **Only qq jobs on supported clusters.** xtcscope can only be used with qq jobs, which also means that it only works on qq-supported clusters (Robox, Sokar, Metacentrum Grid, Karolina, LUMI).
- **Does not follow a running simulation.** xtcscope copies the last frames once and doesn't follow the job. To see newer frames, run it again.
- **The newest frame may be missing.** A frame that mdrun is still writing is skipped, and mdrun writes its output in bursts, so the file on the node can lag behind the simulation by minutes.
- **The same release everywhere.** With `--remote`, your machine and `HOST` should run the same xtcscope release.
- **The GRO comes from the input directory.** Its atoms must match the XTC's exactly. A job that writes only some atoms (`compressed-x-grps`) needs a matching GRO in its input directory; files created during the run, such as `confout.gro`, can't be used.

## FAQ

### Won't this slow down my job, or other people's jobs on the compute node?

Hardly. The agent runs on the compute node only for a moment: it reads the end of the XTC and sends just the frames you asked for. It also runs at the lowest priority a user can set (`nice -n 19 ionice -c3`), so the simulation gets the CPU and the disk first. The only longer run is the rare fallback that reads a damaged XTC from the start, and that runs at the lowest priority too.

### Why not run VMD on the compute node instead?

Over X11, every redraw crosses the network as a picture, so rotating and zooming lag. xtcscope sends the coordinates once, and your desktop draws them as fast as a local file. VMD on the node also takes CPU and memory from the jobs running there, for as long as you keep it open. That's usually harmless for a quick look, but `xtcscope-agent` needs only a moment at the lowest priority.

### Why not open the remote XTC in a local VMD through sshfs or a tunnel instead?

An XTC has no index, so VMD has to read the whole file, which can be gigabytes over the network, to reach the last frames. The xtcscope agent jumps to the end and sends only the frames you asked for, so a longer trajectory doesn't slow it down. It also skips a frame that mdrun is still writing, which could otherwise cause an error.

### Why not run a VNC server on the compute node and connect to it with a VNC viewer instead?

You would have to start a VNC server and tunnel a port for every job, just for a quick check. VMD on the node would also still read the whole XTC from the start to reach the last frames. xtcscope is one command, and it reads only the end of the file.

## Troubleshooting

### xtcscope-agent is not installed on node

Run the installer for the given cluster; it installs the agent into the cluster home too.

### xtcscope is not installed on HOST

Install xtcscope on `HOST` with its cluster's installer, then run it again.

### `... speaks backend protocol N, this one speaks M`

Install the same release on both machines.

### Could not connect to HOST

Check that `ssh HOST` works on its own. If it does, [report this issue](https://github.com/VachaLab/xtcscope/issues).

### Several XTC files ...; choose one with --xtc PATH

Without a terminal to ask on, name the file with `--xtc` (or `--gro`).

### ... has N atoms but ... has M

The GRO and XTC files correspond to different systems.

### Viewer '...' was not found

Load the viewer's module, install the viewer yourself, or point `--viewer` or `XTCSCOPE_VIEWER` at its command.

## Disclaimer

This tool was designed by a human ([@Ladme](https://github.com/Ladme)). Most of the code was written by Claude Opus 5.5, based on a specification drafted by the human author and expanded by the model. The documentation was also largely written by Claude. All code and documentation were reviewed by a human. Because the code is largely AI-generated, it is released into the public domain under [The Unlicense](https://unlicense.org/). This means that the human author waives all rights to the software. If you have ethical reservations about AI-assisted software development, nobody forces you to use this ¯\\\_(ツ)\_/¯.
