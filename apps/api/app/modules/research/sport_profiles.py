"""Descriptive research contracts, separate from trained prediction models.

Racket-sport event scores are kept in provider score units: an event-level score
does not establish individual sets, games, rallies or serve statistics.
"""
PROFILES = {
    'football': {'sport': 'Football', 'score_unit': 'goals', 'score_label': 'Avg. Goals', 'clean_sheets': True},
    'basketball': {'sport': 'Basketball', 'score_unit': 'points', 'score_label': 'Avg. Points', 'clean_sheets': False},
    'ice hockey': {'sport': 'Ice Hockey', 'score_unit': 'goals', 'score_label': 'Avg. Goals', 'clean_sheets': True},
    'tennis': {'sport': 'Tennis', 'score_unit': 'provider score units', 'score_label': 'Avg. Match Score', 'clean_sheets': False},
    'table tennis': {'sport': 'Table Tennis', 'score_unit': 'provider score units', 'score_label': 'Avg. Match Score', 'clean_sheets': False},
}


def profile(name):
    return PROFILES.get(str(name).casefold(), {'sport': str(name), 'score_unit': 'provider score units',
                                             'score_label': 'Avg. Match Score', 'clean_sheets': False})


def sample_metrics(scores, sport):
    """Arithmetic over actual score pairs; no standings points or probabilities."""
    if not scores:
        return {'form': [], 'average_score': None, 'average_conceded': None,
                'clean_sheet_pct': None, 'win_rate': None, 'sample_size': 0}
    return {'form': ['W' if a > b else 'L' if a < b else 'D' for a, b in scores[:5]][::-1],
            'average_score': round(sum(a for a, _ in scores) / len(scores), 2),
            'average_conceded': round(sum(b for _, b in scores) / len(scores), 2),
            'clean_sheet_pct': round(sum(b == 0 for _, b in scores) * 100 / len(scores), 1) if profile(sport)['clean_sheets'] else None,
            'win_rate': round(sum(a > b for a, b in scores) * 100 / len(scores), 1), 'sample_size': len(scores)}
