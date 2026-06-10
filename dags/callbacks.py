"""Airflow failure callbacks.

notify_slack_failure posts to SLACK_WEBHOOK_URL when a task fails. If no webhook
is configured (the env var is empty), it logs the alert instead of erroring, so
the pipeline still runs without Slack wired up.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)


def notify_slack_failure(context: dict[str, Any]) -> None:
    dag = context.get("dag")
    task_instance = context.get("task_instance")
    dag_id = getattr(dag, "dag_id", "unknown_dag")
    task_id = getattr(task_instance, "task_id", "unknown_task")
    run_id = context.get("run_id", "unknown_run")
    message = f":red_circle: Airflow failure: {dag_id}.{task_id} (run {run_id})"

    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not webhook:
        logger.warning("SLACK_WEBHOOK_URL not set; would have alerted: %s", message)
        return

    try:
        resp = requests.post(webhook, json={"text": message}, timeout=10)
        resp.raise_for_status()
        logger.info("sent Slack failure alert for %s.%s", dag_id, task_id)
    except requests.RequestException as exc:
        logger.error("failed to send Slack alert: %s", exc)
