"""Connect bounded discovery histories to research without upgrading their coverage.

Discovery's development feeds do not prove a complete recent-match window. Their
derived sections are deliberately SINGLE_SOURCE and never quorum eligible. Keeping
the original observation/job references makes the sample auditable and idempotent.
"""
import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from app.db import models as m
from app.modules.autonomy.fixture_providers import OL_ID, SPORTSDB_ID
from app.modules.research.sport_profiles import PROFILES, profile as research_profile, sample_metrics

PRODUCER = 'discovery-history-research-v1'
PROVIDERS = {OL_ID: ('OpenLigaDB', 'openligadb'), SPORTSDB_ID: ('TheSportsDB', 'thesportsdb')}
SECTIONS = ('recent_form', 'match_statistics')


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def key(value):
    from app.modules.autonomy.open_intelligence import canonical
    return ' '.join(canonical(value).split()).casefold()


def registry(db):
    return {sid: {'reviewed': True, 'independence_group': group,
                  'sections': list(SECTIONS), 'producer': PRODUCER}
            for sid, (_, group) in PROVIDERS.items()
            if (source := db.get(m.Source, sid)) and source.enabled and source.permission == 'AUTHORIZED'}


def normalized_results(data, fixture, captured_at):
    """Reject an invalid sample in full; never silently turn it into a complete one."""
    side = data.get('side')
    if side not in ('home', 'away') or key(data.get('team')) != key(getattr(fixture, side + '_name')):
        raise ValueError('Team identity does not match fixture')
    results = data.get('results')
    if not isinstance(results, list) or not results or len(results) > 500:
        raise ValueError('No bounded completed-match sample')
    seen, rows = set(), []
    for result in results:
        stamp = datetime.fromisoformat(result['kickoff_at'].replace('Z', '+00:00'))
        if stamp.tzinfo is None or utc(stamp) >= min(utc(captured_at), utc(fixture.kickoff_at)):
            raise ValueError('Result is not from before capture and kickoff')
        home, away = key(result['home']), key(result['away'])
        if not home or not away or home == away or key(data['team']) not in (home, away):
            raise ValueError('Result participants do not match team')
        scores = (result['home_score'], result['away_score'])
        if any(type(score) is not int or not 0 <= score <= 1000 for score in scores):
            raise ValueError('Invalid final score')
        identity = str(result['event_id'])
        match = (utc(stamp).isoformat(), home, away)
        if not identity or identity in seen or match in seen:
            raise ValueError('Duplicate result')
        seen.update((identity, match))
        rows.append({'kickoff_at': utc(stamp).isoformat(), 'home': home, 'away': away,
                     'home_score': scores[0], 'away_score': scores[1]})
    return sorted(rows, key=lambda row: row['kickoff_at'], reverse=True)[:10]


def merge_samples(samples):
    """Union fresh captures from one provider, rejecting conflicting score claims."""
    matches={}
    for raw,rows in samples:
        for row in rows:
            identity=(row['kickoff_at'],row['home'],row['away'])
            if identity in matches:
                prior=matches[identity][1]
                if (prior['home_score'],prior['away_score'])!=(row['home_score'],row['away_score']):
                    raise ValueError('Conflicting provider scores for the same match')
            else:matches[identity]=(raw,row)
    selected=sorted(matches.values(),key=lambda pair:pair[1]['kickoff_at'],reverse=True)[:10]
    parents={raw.id:raw for raw,_ in selected}
    return max(parents.values(),key=lambda raw:utc(raw.observed_at)),[row for _,row in selected],list(parents)


def inspect(db, fixture, at, observations=None):
    """Read-only readiness for the pipeline and deep-research workspace."""
    from app.modules.autonomy.fixture_status import quarantined_fixtures
    quarantined = bool(db.scalar(select(m.Fixture.id).where(m.Fixture.id == fixture.id, m.Fixture.id.in_(quarantined_fixtures()))))
    mappings = {row.source_id: row for row in db.scalars(select(m.FixtureSourceMapping).where(m.FixtureSourceMapping.fixture_id == fixture.id))}
    observations = observations if observations is not None else db.scalars(select(m.Observation).where(
        m.Observation.fixture_id == fixture.id, m.Observation.observed_at <= at).order_by(m.Observation.observed_at.desc(), m.Observation.id)).all()
    reports, samples = [], {}
    for sid, (name, _) in PROVIDERS.items():
        source, mapping = db.get(m.Source, sid), mappings.get(sid)
        sides, issues, parents = {}, [], {}
        if not source or not source.enabled or source.permission != 'AUTHORIZED':
            issues.append('source is not enabled and authorized')
        elif mapping is None:
            issues.append('fixture is not covered by this provider')
        elif quarantined or mapping.state in ('CONFLICT', 'QUARANTINED'):
            issues.append('fixture identity is quarantined or conflicting')
        else:
            candidate = db.get(m.FixtureCandidate, mapping.candidate_id)
            normalized = (candidate.data or {}).get('normalized', {}) if candidate else {}
            for side in ('home', 'away'):
                raw_records = [o for o in observations if o.source_id == sid and isinstance(o.payload, dict)
                               and o.payload.get('section') == 'team_recent_results'
                               and isinstance(o.payload.get('data'), dict) and o.payload['data'].get('side') == side]
                if not raw_records:
                    issues.append(side + ': no completed-match history collected')
                    continue
                collected, errors = [], []
                for raw in raw_records:
                    try:
                        data = raw.payload['data']
                        if (not candidate or candidate.fixture_id != fixture.id or candidate.source_id != sid
                                or candidate.status in ('CONFLICT', 'QUARANTINED', 'REJECTED')):
                            raise ValueError('provider fixture mapping is invalid')
                        job = db.get(m.FixtureDiscoveryJob, raw.payload.get('job_id')) if raw.payload.get('job_id') else None
                        if (not raw.content_hash or raw.payload.get('verification') != 'SINGLE_SOURCE' or not job
                                or job.status != 'COMPLETED' or job.source_id != sid
                                or job.kind not in ('team_recent', 'season_history', 'fixtures')):
                            raise ValueError('history lacks a successful provider collection job')
                        request = job.request or {}
                        if job.kind == 'team_recent':
                            if (request.get('fixture_id') != fixture.id or request.get('side') != side
                                    or str(request.get('provider_team_id')) != str(data.get('provider_team_id'))):
                                raise ValueError('history collection scope does not match fixture and team')
                        else:
                            profile = db.get(m.DiscoveryCompetition, request.get('profile_id')) if request.get('profile_id') else None
                            if (not profile or not profile.active or profile.source_id != sid
                                    or profile.competition_id != fixture.competition_id or profile.season_id != fixture.season_id):
                                raise ValueError('history competition or season does not match fixture')
                        if not data.get('provider_team_id') or str(data['provider_team_id']) != str(normalized.get(side + '_provider_id')):
                            raise ValueError('provider team mapping changed')
                        if not timedelta(0) <= utc(at) - utc(raw.observed_at) <= timedelta(hours=24):
                            raise ValueError('history capture is older than 24 hours')
                        if utc(raw.observed_at) >= utc(fixture.kickoff_at):
                            raise ValueError('history was captured after fixture kickoff')
                        rows = normalized_results(data, fixture, raw.observed_at)
                        collected.append((raw, rows))
                    except (ValueError, TypeError, KeyError, AttributeError) as exc:
                        errors.append(str(exc))
                if collected:
                    try:
                        raw, rows, parent_ids = merge_samples(collected)
                        sides[side] = {'matches': len(rows), 'captured_at': utc(raw.observed_at).isoformat(),
                                       'latest_result_at': rows[0]['kickoff_at'], 'coverage': 'PARTIAL',
                                       'evidence_ids': parent_ids,
                                       'limitation': 'Collected provider samples may omit matches; complete recent window is not established'}
                        parents[side] = (raw, rows)
                        issues.append(f'{side}: {len(rows)}/10 sampled matches; complete recent window is not established')
                    except ValueError as exc:
                        issues.append(side + ': ' + str(exc))
                else:
                    issues.append(side + ': ' + '; '.join(dict.fromkeys(errors)))
        samples[sid] = parents
        reports.append({'source_id': sid, 'provider': name, 'mapped': mapping is not None,
                        'sides': sides, 'issues': issues, 'quorum_eligible': False})
    competition = db.get(m.Competition, fixture.competition_id)
    sport = db.get(m.Sport, competition.sport_id) if competition else None
    football = bool(sport and sport.name.casefold() == 'football')
    supported = bool(sport and sport.name.casefold() in PROFILES)
    message = ' '.join(report['provider'] + ': ' + '; '.join(report['issues']) + '.' for report in reports)
    if not supported:
        message += ' This sport has no implemented research score adapter.'
    from app.modules.autonomy.window_corroboration import readiness_note
    message += readiness_note(db, fixture)
    return {'required_matches_per_team': 10, 'providers': reports, 'reason': message,
            'usable_parent_observation_ids': sorted({ident for report in reports for side in report['sides'].values() for ident in side['evidence_ids']}),
            'next_action': 'Collect complete pre-match histories for both teams from two independent providers, or obtain an independent section review.',
            'football_adapter': football, 'research_adapter': supported,
            'sport_profile': research_profile(sport.name if sport else 'Unknown')}, samples


def assemble(db, fixture, at):
    readiness, samples = inspect(db, fixture, at)
    if not readiness['research_adapter']:
        return readiness
    for sid, sides in samples.items():
        if set(sides) != {'home', 'away'}:
            continue
        data = {'coverage': 'PARTIAL', 'sport': readiness['sport_profile']['sport'],
                'score_unit': readiness['sport_profile']['score_unit'],
                'samples': {side: rows for side, (_, rows) in sides.items()}}
        form, statistics = {}, {}
        for side, (_, rows) in sides.items():
            scores = [(row['home_score'], row['away_score']) if row['home'] == key(getattr(fixture, side + '_name'))
                      else (row['away_score'], row['home_score']) for row in rows]
            sample = sample_metrics(scores, data['sport'])
            form[side + '_results'] = sample['form']
            form[side + '_sample_size'] = sample['sample_size']
            if readiness['football_adapter']:
                form[side + '_form'] = round(sum(3 if a > b else 1 if a == b else 0 for a, b in scores[:5]) / len(scores[:5]), 6)
                statistics[side + '_scoring_rate'] = round(sum(a for a, _ in scores) / len(scores), 6)
                statistics[side + '_conceding_rate'] = round(sum(b for _, b in scores) / len(scores), 6)
            else:
                form[side + '_win_rate'] = sample['win_rate']
                statistics[side + '_average_score'] = sample['average_score']
                statistics[side + '_average_conceded'] = sample['average_conceded']
                statistics[side + '_sample_size'] = sample['sample_size']
        parents = sorted({ident for report in readiness['providers'] if report['source_id']==sid for side in report['sides'].values() for ident in side['evidence_ids']})
        for section, metrics in (('recent_form', form), ('match_statistics', statistics)):
            payload = {'section': section, 'data': {**data, **metrics}, 'producer': PRODUCER,
                       'verification': 'SINGLE_SOURCE', 'parent_observation_ids': parents,
                       'quorum_eligible': False, 'limitation': 'Sample metrics only; development collector does not establish a complete recent window.'}
            digest = hashlib.sha256(json.dumps([fixture.id, sid, payload], sort_keys=True).encode()).hexdigest()
            if not db.scalar(select(m.Observation.id).where(m.Observation.source_id == sid, m.Observation.content_hash == digest)):
                raw = sides['home'][0]
                db.add(m.Observation(source_id=sid, fixture_id=fixture.id, source_url=raw.source_url,
                                     observed_at=max(utc(raw.observed_at), utc(sides['away'][0].observed_at)),
                                     content_hash=digest, payload=payload))
    db.flush()
    return readiness
