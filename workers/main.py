"""Start every worker:  python -m workers.main

Reads CONDUCTOR_SERVER_URL, CONDUCTOR_AUTH_KEY and CONDUCTOR_AUTH_SECRET
from the environment (or .env). Without the auth variables it talks to a
local Conductor with no login.
"""
import logging
import os

from scripts.env import load_env

load_env()
# Workers are I/O bound, so threads are enough and start much faster than
# one process per worker.
os.environ.setdefault("CONDUCTOR_WORKER_ISOLATION", "thread")

from conductor.client.automator.task_handler import TaskHandler  # noqa: E402
from conductor.client.configuration.configuration import Configuration  # noqa: E402

MODULES = ["workers.poc1", "workers.poc2", "workers.poc5", "workers.poc6", "workers.migrate", "workers.governance"]


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = Configuration()
    logging.info("Polling %s for tasks", config.host)
    handler = TaskHandler(configuration=config, scan_for_annotated_workers=True, import_modules=MODULES)
    handler.start_processes()
    try:
        handler.join_processes()
    except KeyboardInterrupt:
        handler.stop_processes()


if __name__ == "__main__":
    main()
