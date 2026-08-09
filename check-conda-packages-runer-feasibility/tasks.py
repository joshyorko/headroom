from pathlib import Path

from robocorp.tasks import task
from robocorp.tasks import get_output_dir


@task
def minimal_task():
    message = "Hello from the minimal Python robot."
    print(message)

    output_file = Path(get_output_dir()) / "greeting.txt"
    output_file.write_text(f"{message}\n", encoding="utf-8")
