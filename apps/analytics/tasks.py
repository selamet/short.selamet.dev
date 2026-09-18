"""Click recording.

This is a placeholder: it only logs at debug level. The real implementation (writing a
Click row and updating the link's counters) lands in a later task.
"""

import logging

from django.tasks import task

logger = logging.getLogger(__name__)


@task
def record_click(link_id, *, occurred_at, ip, user_agent, referrer, query_string, target_platform):
    logger.debug(
        "click recorded (stub) link_id=%s platform=%s occurred_at=%s",
        link_id,
        target_platform,
        occurred_at,
    )
