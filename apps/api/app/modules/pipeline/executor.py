"""Compatibility facade; all execution uses the canonical pipeline runner."""


def execute_run(db,run):
 from app.modules.pipeline.runner import drive_run
 drive_run(db,run)
 return run
