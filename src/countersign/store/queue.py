"""A durable work queue in the database.

Guarantees, and how each is obtained:

- a job is processed by one worker at a time: claiming is a single UPDATE of the row
  chosen by a sub-select, so two workers cannot both take it (on PostgreSQL the
  sub-select also skips rows another transaction has locked);
- a job survives the death of its worker: a claim is a lease with an expiry, and an
  expired lease makes the job claimable again. Nothing renews a lease, so it has to
  outlast the longest time one document can take (`Settings.lease_seconds`);
- a failing job is retried with exponential backoff, then parked as "failed" after
  `max_attempts`, where it stays visible instead of looping forever.

Delivery is therefore at-least-once: a job can run twice if a worker dies after doing
the work and before recording it. Processing a document is idempotent, which is what
makes that acceptable.
"""

from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from countersign.store.models import Job

QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"


def enqueue(session: Session, document_id: int, *, now: datetime, max_attempts: int = 3) -> Job:
    job = Job(document_id=document_id, run_after=now, created_at=now, max_attempts=max_attempts)
    session.add(job)
    session.flush()
    return job


def claim(session: Session, worker_id: str, *, now: datetime, lease_seconds: int) -> Job | None:
    """Take the oldest job that is ready, or whose lease ran out with its worker."""
    claimable = and_(
        Job.attempts < Job.max_attempts,
        or_(
            and_(Job.status == QUEUED, Job.run_after <= now),
            and_(Job.status == RUNNING, Job.locked_until < now),
        ),
    )
    oldest = (
        select(Job.id)
        .where(claimable)
        .order_by(Job.run_after, Job.id)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    claimed = session.execute(
        update(Job)
        # The condition is repeated on the outer statement: if another worker took the
        # row between the sub-select and the update, this one changes nothing.
        .where(Job.id == oldest, claimable)
        .values(
            status=RUNNING,
            locked_by=worker_id,
            locked_until=now + timedelta(seconds=lease_seconds),
            attempts=Job.attempts + 1,
        )
        .returning(Job.id)
    ).scalar_one_or_none()
    if claimed is None:
        return None
    session.expire_all()
    return session.get(Job, claimed)


def complete(session: Session, job: Job, *, now: datetime) -> None:
    job.status, job.finished_at = DONE, now
    job.locked_by = job.locked_until = None
    job.last_error = None


def fail(
    session: Session,
    job: Job,
    error: str,
    *,
    now: datetime,
    backoff_seconds: float,
    retry: bool = True,
) -> bool:
    """Record a failed attempt. Returns True if the job will be tried again.

    `retry=False` parks the job at once: for a failure that another attempt would
    only repeat.
    """
    job.last_error = error[:2000]
    job.locked_by = job.locked_until = None
    if retry and job.attempts < job.max_attempts:
        job.status = QUEUED
        job.run_after = now + timedelta(seconds=backoff_seconds * 2 ** (job.attempts - 1))
        return True
    job.status, job.finished_at = FAILED, now
    return False


def bury_exhausted(session: Session, *, now: datetime) -> list[Job]:
    """Park jobs whose last allowed attempt died with its worker; return them.

    A job whose worker is writing its result at this moment holds its row and is
    skipped: that worker did not die.
    """
    exhausted = list(
        session.scalars(
            select(Job)
            .where(
                Job.status == RUNNING,
                Job.locked_until < now,
                Job.attempts >= Job.max_attempts,
            )
            .with_for_update(skip_locked=True)
        )
    )
    for job in exhausted:
        job.status, job.finished_at = FAILED, now
        job.last_error = job.last_error or "worker lost during the last attempt"
        job.locked_by = job.locked_until = None
    return exhausted


def depth(session: Session) -> dict[str, int]:
    counts = dict.fromkeys((QUEUED, RUNNING, DONE, FAILED), 0)
    for status, count in session.execute(select(Job.status, func.count()).group_by(Job.status)):
        counts[status] = count
    return counts
