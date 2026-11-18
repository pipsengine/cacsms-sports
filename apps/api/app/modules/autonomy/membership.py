"""Evidence-based season membership changes; never automatic official promotion."""
from sqlalchemy import select,or_
from app.db import models as m

GERMAN_TIERS={'Bundesliga':1,'2. Bundesliga':2,'3. Liga':3}


def observe(db,team,fixture,profile):
    competition=db.get(m.Competition,fixture.competition_id)
    raw_tier=profile.details.get('division') or GERMAN_TIERS.get(competition.name)
    try:tier=int(raw_tier);year=int(profile.season_label[:4])
    except (ValueError,TypeError):return
    if not competition.country or not 1<=tier<=20:return
    # A club's cup appearances are excluded by requiring a known league tier.
    provenance=select(m.Observation.fixture_id).join(m.Source,m.Source.id==m.Observation.source_id).where(m.Source.permission=='AUTHORIZED',m.Source.enabled.is_(True))
    rows=db.execute(select(m.Fixture,m.Competition,m.CompetitionSeason).join(m.Competition,m.Competition.id==m.Fixture.competition_id)
         .join(m.CompetitionSeason,m.CompetitionSeason.id==m.Fixture.season_id)
         .where(m.Competition.country==competition.country,m.Competition.sport_id==competition.sport_id,
          m.Competition.id!=competition.id,m.CompetitionSeason.label.like(str(year-1)+'%'),
          m.Fixture.id.in_(provenance),or_(m.Fixture.home_team_id==team.id,m.Fixture.away_team_id==team.id,
                                         m.Fixture.home_name==team.name,m.Fixture.away_name==team.name))
         .order_by(m.Fixture.kickoff_at.desc()).limit(20)).all()
    for previous,league,season in rows:
        old_profile=db.scalar(select(m.DiscoveryCompetition).where(m.DiscoveryCompetition.competition_id==league.id,m.DiscoveryCompetition.season_id==season.id).limit(1))
        old_tier=(old_profile.details.get('division') if old_profile else None) or GERMAN_TIERS.get(league.name)
        try:old_tier=int(old_tier)
        except (ValueError,TypeError):continue
        if not 1<=old_tier<=20 or old_tier==tier:continue
        transition_key=':'.join((team.id,league.id,competition.id,profile.season_label))
        exists=db.scalar(select(m.AuditEvent.id).where(m.AuditEvent.action=='competition.membership_transition_candidate',m.AuditEvent.payload['transition_key'].as_string()==transition_key))
        if not exists:
            db.add(m.AuditEvent(actor='fixture-discovery',action='competition.membership_transition_candidate',correlation_id=team.id,
                payload={'transition_key':transition_key,'team':team.name,'previous_competition':league.name,'competition':competition.name,
                 'previous_season':season.label,'season':profile.season_label,'previous_fixture_id':previous.id,'fixture_id':fixture.id,
                 'classification':'PROMOTION_CANDIDATE' if tier<old_tier else 'RELEGATION_CANDIDATE','review_required':True}))
        break
