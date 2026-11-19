"""Country for competitions whose provider supplies none (mostly OpenLigaDB community feeds).

Only unambiguous name signals are used; anything else stays unspecified rather than guessed. Every backfilled value
is recorded as an audit event. Order matters: Austrian "Bundesliga" and international tournaments are matched
before the German keywords.
"""
import unicodedata
from sqlalchemy import select
from app.db import models as m

RULES = (
    ('Europe', ('champions league', 'europa league', 'conference league', 'uefa', 'nations league')),
    ('International', ('world cup', 'wm 2026', 'wm2026', 'wm26', 'wc2026', 'fifa')),
    ('Austria', ('osterreich', 'admiral bundesliga', 'blo', 'obl')),
    ('Spain', ('laliga', 'la liga')),
    ('England', ('premier league', 'permier league england')),
    ('Germany', ('regionalliga', 'oberliga', 'nofv', 'bundesliga', 'dfb', 'fussball', 'thuringenliga', 'beckenbauer',
                 'arminia bielefeld', 'eintracht frankfurt', 'hallenstadtmeisterschaft')),
)


def fold(text):
    text = str(text or '').replace('ß', 'ss')
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c)).casefold().split())


def infer_country(name, provider_key=None):
    words = fold(name)
    padded = f' {words} '
    for country, keys in RULES:
        for key in keys:
            # Short keys (blo, obl) must be whole words; longer ones may appear inside compound words.
            if (len(key) <= 3 and f' {key} ' in padded) or (len(key) > 3 and key in words):
                return country
    key = fold(provider_key)
    if key in ('blo', 'obl'): return 'Austria'
    return None


def backfill(db):
    changed = []
    for competition in db.scalars(select(m.Competition).where(m.Competition.country.is_(None))):
        keys = db.scalars(select(m.DiscoveryCompetition.provider_key).where(m.DiscoveryCompetition.competition_id == competition.id)).all()
        country = infer_country(competition.name) or next((c for c in (infer_country('', k) for k in keys) if c), None)
        if not country: continue
        competition.country = country
        db.add(m.AuditEvent(actor='competition-country', action='competition.country_inferred', correlation_id=competition.id,
                            payload={'name': competition.name, 'country': country, 'method': 'NAME_RULES', 'provider_keys': keys}))
        changed.append({'competition': competition.name, 'country': country})
    return changed
