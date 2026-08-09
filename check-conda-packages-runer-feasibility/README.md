# Python Minimal Template

This is the smallest RCC robot baseline in this template set: one Python task,
one `robot.yaml` entry, and one runtime dependency on `robocorp.tasks`.

Use it when you want a clean starting point for a plain Python automation. It
does not include browser automation, work items, AI services, Action Server, or
extra package-management patterns.

## Run It

Run these from the `01-python` directory.

```bash
ROBOCORP_HOME=/tmp/robot-templates-01-python-rcc rcc ht vars -r robot.yaml
```

That command proves RCC can resolve the robot environment without running the
task.

The smoke command is:

```bash
ROBOCORP_HOME=/tmp/robot-templates-01-python-rcc rcc run -r robot.yaml -t RunTask --silent
```

Expected console output includes:

```text
Hello from the minimal Python robot.
```

Expected artifacts are written under `output/`:

- `output/greeting.txt` contains the same greeting.
- `output/log.html` contains the Robocorp task run log.

`output/` is ignored by git and can be deleted between runs.

## First Files To Edit

- `tasks.py`: replace `minimal_task()` with your automation logic.
- `robot.yaml`: add or rename RCC tasks when you add more task entry points.
- `conda.yaml`: add only the runtime packages your automation actually needs.

If you add another Python task function in `tasks.py`, add a matching task in
`robot.yaml` and document the new `rcc run -t ...` command here.

## Development Notes

- Keep commands repo-local and RCC-backed. On Bluefin or another Linux
  workstation, there is no host package install step for this template.
- Keep this template plain Python. Use the sibling templates for browser,
  work-item, AI, uv-native, or Action Server examples.
