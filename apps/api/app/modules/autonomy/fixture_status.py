"""Read-only discovery health and time-bound multi-source fixture corroboration."""
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func
from app.db import models as m


def verified_query(at):
    return (select(m.FixtureSourceMapping.fixture_id).join(m.Source, m.Source.id == m.FixtureSourceMapping.source_id)
            .where(m.Source.enabled.is_(True), m.Source.permission == 'AUTHORIZED',
                   m.FixtureSourceMapping.last_seen_at >= at - timedelta(hours=24),m.FixtureSourceMapping.last_seen_at <= at)
            .group_by(m.FixtureSourceMapping.fixture_id)
            .having(func.count(func.distinct(m.FixtureSourceMapping.source_id)) >= 2,
                    func.count(func.distinct(m.FixtureSourceMapping.signature)) == 1))


def summary(db, at=None):
    at = at or datetime.now(timezone.utc)
    from app.modules.acquisition.source_policy import PROHIBITED, source_id_for
    from app.modules.autonomy import fixture_discovery, fixture_providers
    import os
    counts = dict(db.execute(select(m.FixtureDiscoveryJob.status, func.count()).group_by(m.FixtureDiscoveryJob.status)).all())
    candidates = dict(db.execute(select(m.FixtureCandidate.status, func.count()).group_by(m.FixtureCandidate.status)).all())
    latest = db.scalar(select(func.max(m.FixtureDiscoveryJob.finished_at)).where(m.FixtureDiscoveryJob.status == 'COMPLETED',m.FixtureDiscoveryJob.kind.in_(('fixtures','day'))))
    engines = []
    for name, kinds in [('Competition discovery', ('catalogue', 'league')), ('Fixture acquisition', ('fixtures', 'day'))]:
        states = dict(db.execute(select(m.FixtureDiscoveryJob.status, func.count()).where(m.FixtureDiscoveryJob.kind.in_(kinds)).group_by(m.FixtureDiscoveryJob.status)).all())
        status = 'RUNNING' if states.get('RUNNING') else 'QUEUED' if states.get('QUEUED') else 'WAITING' if states.get('RETRY_SCHEDULED') else 'FAILED' if states.get('DEAD') else 'BLOCKED' if states.get('BLOCKED') else 'COMPLETED' if states.get('COMPLETED') else 'NOT_STARTED'
        engines.append({'name': name, 'state': status, 'counts': states})
    sources = []
    for source in db.scalars(select(m.Source).order_by(m.Source.name)):
        jobs = db.scalars(select(m.FixtureDiscoveryJob).where(m.FixtureDiscoveryJob.source_id == source.id).order_by(m.FixtureDiscoveryJob.created_at.desc()).limit(50)).all()
        successes = [job.finished_at for job in jobs if job.kind in ('fixtures','day') and job.status == 'COMPLETED' and job.finished_at]
        errors = [{'job_id': job.id, 'state': job.status, 'reason': job.error, 'next_run_at': job.next_run_at} for job in jobs if job.error]
        candidate_counts = dict(db.execute(select(m.FixtureCandidate.status, func.count()).where(m.FixtureCandidate.source_id == source.id).group_by(m.FixtureCandidate.status)).all())
        restriction = next((entry['reason'] for domain, entry in PROHIBITED.items()
                            if source.permission == 'PROHIBITED' and (source.id == source_id_for(domain) or source.name == entry['name'])), None)
        sources.append({'id': source.id, 'name': source.name, 'permission': source.permission, 'enabled': source.enabled,
                        'state': 'BLOCKED' if source.permission != 'AUTHORIZED' or not source.enabled else 'FAILED' if jobs and jobs[0].error else 'AVAILABLE' if successes else 'NOT_OBSERVED',
                        'last_successful_acquisition': max(successes) if successes else None, 'errors': errors[:5],
                        'restriction': restriction, 'candidate_counts': candidate_counts,
                        'coverage_complete': False, 'licence_scope': 'Development API limits apply' if 'TheSportsDB' in source.name else 'See source permission record'})
    changes=[{'id':row.id,'payload':row.payload,'at':row.created_at} for row in db.scalars(select(m.AuditEvent).where(m.AuditEvent.action=='competition.membership_transition_candidate').order_by(m.AuditEvent.created_at.desc()).limit(20))]
    return {'jobs': counts, 'candidates': candidates, 'engines': engines, 'sources': sources,'membership_changes':changes,
            'target_sports': list(fixture_providers.SPORTSDB_SPORTS.values())
                if fixture_discovery.enabled() and os.getenv('SPORTS_THESPORTSDB_ENABLED', '0') == '1'
                and fixture_discovery.authorized(db, fixture_providers.SPORTSDB_ID) else [],
            'verified_fixtures': db.scalar(select(func.count()).select_from(verified_query(at).subquery())) or 0,
            'mapped_fixtures': db.scalar(select(func.count(func.distinct(m.FixtureSourceMapping.fixture_id)))) or 0,
            'last_successful_acquisition': latest,
            'latest_fixture_at': db.scalar(select(func.max(m.Fixture.kickoff_at))),
            'verification_policy': 'Two currently authorized providers, identical identity/kickoff/status, both observed within 24 hours; not research or prediction approval',
            'coverage_notice': 'Provider catalogues and free API responses are incomplete. Unknown countries/divisions remain unavailable. No live-status guarantee is inferred from kickoff time.'}
