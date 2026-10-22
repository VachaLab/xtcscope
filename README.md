# xtcscope

> [!NOTE]
> This tool works only with jobs submitted with [qq](https://github.com/VachaLab/qq).

xtcscope shows the last frames of a running GROMACS job straight from the compute node's local scratch. Much smoother than VMD on the node, and much faster than copying the whole trajectory.

A small Rust program ("agent") on the node reads the XTC _from the end_ and copies the last complete frames through SSH to a temporary file on your desktop, where your viewer opens them like any local trajectory. Even very long trajectories take only a moment to prepare. The simulation is not affected.

xtcscope works with both VMD 1 and 2, as well as with ViaMD and any other molecular viewer that opens `<command> <gro> <xtc>`.

With `--remote`, you can do the same from a machine outside the cluster, such as your laptop at home: the job is looked up and its frames extracted on a machine that can reach the cluster, and only the frames travel to you.

## Requirements

- Linux on x86_64, on every machine involved. Nothing else needs to be installed: xtcscope ships with its own Python.
- Supports only jobs submitted with [qq](https://github.com/VachaLab/qq). Infinity and raw PBS are **not** supported.
- You need to have a viewer: VMD 1.9, VMD 2, ViaMD, or another program that opens `<command> <gro> <xtc>`.

## Installing

Install or update the latest release with the installer for your cluster, e.g. for Robox:

```bash
bash <(curl -fsSL https://github.com/VachaLab/xtcscope/releases/latest/download/xtcscope-robox-install.sh)
```

| Where                                            | Installer                         | Installs into                                   |
| ------------------------------------------------ | --------------------------------- | ----------------------------------------------- |
| Robox                                            | `xtcscope-robox-install.sh`       | `$HOME` and `/storage/brno14-ceitec/home/$USER` |
| Metacentrum                                      | `xtcscope-metacentrum-install.sh` | `$HOME` and every Metacentrum storage home      |
| Sokar                                            | `xtcscope-sokar-install.sh`       | `$HOME`                                         |
| Karolina                                         | `xtcscope-karolina-install.sh`    | `$HOME`                                         |
| LUMI                                             | `xtcscope-lumi-install.sh`        | `$HOME`                                         |
| A machine without a batch system, for `--remote` | `xtcscope-desktop-install.sh`     | `$HOME`                                         |

Each installer puts `xtcscope/` into every home listed and adds it to `PATH` through a block in that home's `.bashrc`; open a new terminal afterwards. Homes that don't exist are skipped with a warning. Running an installer again with the same version changes nothing.

Pre-releases are never "latest"; install one with its own URL:

```bash
https://github.com/VachaLab/xtcscope/releases/download/<version>/xtcscope-robox-install.sh
```

> [!NOTE]
> The installer refuses to touch an existing `~/xtcscope` that is not an installation, so don't clone this repository to `~/xtcscope`.

## Usage

```bash
xtcscope [JOB_ID] [--remote HOST] [--access MODE] [--viewer CMD] [--gro PATH] [--xtc PATH] [-n N] [--dry-run] [--debug]
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
xtcscope --remote robox 1234567     # from home, through a machine that reaches the cluster
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
2. Install the same release on your own machine, with `xtcscope-desktop-install.sh` if it has no batch system.
3. Run `xtcscope --remote HOST JOB_ID`.

`HOST` is anything `ssh` accepts, so an alias from `~/.ssh/config` works, including one that hops through a gateway:

```ssh-config
Host robox
    HostName mydesktop.ceitec.muni.cz
    User myname
    ProxyJump gateway.example.cz
```

One SSH connection carries the whole run, so you type your password or passphrase at most once. Messages from `HOST` are shown tagged with its name, e.g. `INFO    [robox] Job 1234567 ...`. Install the same release on both machines: xtcscope warns about a different version, and stops if the two can no longer talk to each other.

### How the working directory is read: `--access`

With the default `--access auto`, xtcscope reads the job's working directory directly, with no SSH to the compute node, when the directory exists on the machine that looks up the job (`HOST` with `--remote`) and either is on shared storage or belongs to a job running on that machine. Otherwise it connects to the job's main node. This covers jobs running on your own desktop, jobs with `--work-dir input_dir`, and supercomputers whose working directories are shared, such as Karolina and LUMI. `--access direct` and `--access node` force either way.

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
| 1    | Unexpected error (a bug; please report it).                                                            |
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

- **Does not follow a running simulation.** xtcscope copies the last frames once and doesn't follow the job. To see newer frames, run it again.
- **The newest frame may be missing.** A frame mdrun is still writing is skipped, and mdrun writes its output in bursts, so the file on the node can lag the simulation by minutes.
- **The same release everywhere.** With `--remote`, your machine and `HOST` should run the same xtcscope release.
- **The GRO comes from the input directory.** Its atoms must match the XTC's exactly. A job that writes only some atoms (`compressed-x-grps`) needs a matching GRO in its input directory; files created during the run, such as `confout.gro`, can't be used.

## FAQ

### Won't this slow down my job, or other people's jobs on the compute node?

Hardly. The agent runs on the compute node only for a moment: it reads the end of the XTC and sends just the frames you asked for. It also runs at the lowest priority a user can set (`nice -n 19 ionice -c3`), so the simulation gets the CPU and the disk first. The only longer run is the rare fallback that reads a damaged XTC from the start, and that runs at the lowest priority too.

### Why not run VMD on the compute node instead?

Over X11, every redraw crosses the network as a picture, so rotating and zooming lag. xtcscope sends the coordinates once, and your desktop draws them as fast as a local file.

### Why not open the remote XTC in a local VMD, through sshfs or a tunnel instead?

An XTC has no index, so VMD has to read the whole file, which can be gigabytes over the network, to reach the last frames. The xtcscope agent jumps to the end and sends only the frames you asked for, so a longer trajectory doesn't slow it down. It also skips a frame mdrun is still writing, which could otherwise cause an error.

### Why not run a VNC server on the compute node and connect to it with a VNC viewer instead?

You would have to start a VNC server and tunnel a port for every job, just for a quick check. VMD on the node also still reads the whole XTC from the start to reach the last frames. xtcscope is one command, and it reads only the end of the file.

## Troubleshooting

| Message                                             | What to do                                                                                        |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `xtcscope-agent is not installed on <node>`         | Run the installer for your cluster; it installs the agent into the cluster home too.              |
| `xtcscope is not installed on HOST`                 | Install xtcscope on `HOST` with its cluster's installer, then run again.                          |
| `... speaks backend protocol N, this one speaks M`  | Install the same release on both machines.                                                        |
| `Could not connect to HOST`                         | Check that `ssh HOST` works on its own.                                                           |
| `Several XTC files ...; choose one with --xtc PATH` | Without a terminal to ask on, name the file with `--xtc` (or `--gro`).                            |
| `... has N atoms but ... has M`                     | The GRO and the XTC describe different atoms.                                                     |
| `Viewer '...' was not found`                        | Install the viewer, activate its module, or point `--viewer` or `XTCSCOPE_VIEWER` at its command. |

`--debug` shows every SSH command and every message from the agent (with `--remote`, from `HOST` too), which usually tells where things went wrong. If xtcscope reads the working directory the wrong way, `--access` overrides its choice.
