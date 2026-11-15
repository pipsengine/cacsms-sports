"""Uncalibrated research baseline from the supplied scaffold; no qualification."""
import math

def poisson(k, rate):
    if type(k) is not int or k<0 or not math.isfinite(rate) or rate<0: raise ValueError('Invalid Poisson inputs')
    return math.exp(-rate)*rate**k/math.factorial(k)

def total_over_probability(home_rate,away_rate,threshold=2.5):
    if threshold!=2.5: raise ValueError('Baseline supports over 2.5 only')
    if any(not math.isfinite(r) or r < 0 for r in (home_rate, away_rate)):
        raise ValueError('Rates must be finite and nonnegative')
    total=home_rate+away_rate
    return 1-sum(poisson(k,total) for k in range(3))

