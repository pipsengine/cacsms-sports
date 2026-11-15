"""Compatibility entry point for the canonical twelve-stage runner."""
from app.modules.pipeline.runner import drive_run

def connect_engines(db,run):
 return drive_run(db,run)
