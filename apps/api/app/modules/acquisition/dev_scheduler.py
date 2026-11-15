"""Local development scheduler: runs the Celery beat schedule in-process without Redis.

Production/Docker uses the real Celery worker + beat (see docker-compose.yml). Locally there is
often no Redis broker, so this runner executes the same tasks on the same intervals with Celery's
eager mode (``.delay()`` runs inline). PAPER mode only; no task here places wagers.

Usage (from apps/api, with PYTHONPATH set to the repo root):
    python -m app.modules.acquisition.dev_scheduler
"""
import logging
import time

from app.modules.acquisition import tasks

log = logging.getLogger('dev_scheduler')


def main() -> None:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', datefmt='%H:%M:%S')
    logging.getLogger('celery.app.trace').setLevel(logging.WARNING)  # avoid duplicate success lines
    tasks.celery_app.conf.task_always_eager = True
    tasks.celery_app.conf.task_eager_propagates = True

    schedule = []
    for name, entry in tasks.celery_app.conf.beat_schedule.items():
        task = tasks.celery_app.tasks[entry['task']]
        schedule.append({'name': name, 'task': task, 'every': float(entry['schedule']), 'next': 0.0})
    log.info('Running %d scheduled tasks in-process (no broker): %s',
             len(schedule), ', '.join(f"{s['name']}/{int(s['every'])}s" for s in schedule))

    while True:
        now = time.monotonic()
        for s in schedule:
            if now < s['next']:
                continue
            s['next'] = now + s['every']
            try:
                result = s['task'].apply().get()
                if not isinstance(result,dict) or result.get('status')!='NOT_DUE_OR_ALREADY_RUNNING':
                    log.info('%s -> %s', s['name'], result)
            except Exception as exc:  # keep the loop alive; surface the failure
                log.error('%s failed: %s: %s', s['name'], type(exc).__name__, exc)
        time.sleep(1.0)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
