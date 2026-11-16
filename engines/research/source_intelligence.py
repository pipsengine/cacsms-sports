"""Source Intelligence engine boundary.

Operational overview, registry health and acquisition analytics are served by
``apps.api.app.modules.acquisition.source_intelligence`` against PostgreSQL
provider, sync-state and acquisition-job records. This module remains the
engine-level contract surface for workers that need a typed execute boundary.
"""
from typing import Protocol,Any
class Engine(Protocol):
 def execute(self, payload:dict[str,Any])->dict[str,Any]: ...
