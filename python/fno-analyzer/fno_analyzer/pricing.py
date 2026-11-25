"""Black-Scholes pricing, Greeks and implied volatility (European options).

Indian index options (NIFTY, BANKNIFTY, ...) are European-style and cash-settled,
so Black-Scholes is a reasonable baseline model. Stock options on NSE are also
European since 2011 but are physically settled.
"""
import math

_SQRT2 = math.sqrt(2.0)
_SQRT2PI = math.sqrt(2.0 * math.pi)


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / _SQRT2))


def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / _SQRT2PI


def _check_kind(kind: str) -> str:
    k = kind.lower()
    if k in ("c", "call", "ce"):
        return "call"
    if k in ("p", "put", "pe"):
        return "put"
    raise ValueError(f"Unknown option type: {kind!r}")


def intrinsic(S: float, K: float, kind: str) -> float:
    return max(S - K, 0.0) if _check_kind(kind) == "call" else max(K - S, 0.0)


def d1_d2(S, K, T, r, sigma, q=0.0):
    vol_t = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / vol_t
    return d1, d1 - vol_t


def bs_price(S, K, T, r, sigma, kind, q=0.0) -> float:
    """Black-Scholes price. T in years, r/q/sigma as decimals (0.15 = 15%)."""
    kind = _check_kind(kind)
    if T <= 0 or sigma <= 0:
        return intrinsic(S, K, kind)
    d1, d2 = d1_d2(S, K, T, r, sigma, q)
    if kind == "call":
        return S * math.exp(-q * T) * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)
    return K * math.exp(-r * T) * norm_cdf(-d2) - S * math.exp(-q * T) * norm_cdf(-d1)


def greeks(S, K, T, r, sigma, kind, q=0.0) -> dict:
    """Greeks per one unit of underlying.

    theta is per calendar day, vega per 1 vol point (1%), rho per 1% rate change.
    """
    kind = _check_kind(kind)
    if T <= 0 or sigma <= 0:
        itm = intrinsic(S, K, kind) > 0
        delta = (1.0 if itm else 0.0) if kind == "call" else (-1.0 if itm else 0.0)
        return {"delta": delta, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}
    d1, d2 = d1_d2(S, K, T, r, sigma, q)
    sqrt_t = math.sqrt(T)
    disc_q, disc_r = math.exp(-q * T), math.exp(-r * T)
    gamma = disc_q * norm_pdf(d1) / (S * sigma * sqrt_t)
    vega = S * disc_q * norm_pdf(d1) * sqrt_t / 100.0
    common = -S * disc_q * norm_pdf(d1) * sigma / (2 * sqrt_t)
    if kind == "call":
        delta = disc_q * norm_cdf(d1)
        theta = common - r * K * disc_r * norm_cdf(d2) + q * S * disc_q * norm_cdf(d1)
        rho = K * T * disc_r * norm_cdf(d2) / 100.0
    else:
        delta = -disc_q * norm_cdf(-d1)
        theta = common + r * K * disc_r * norm_cdf(-d2) - q * S * disc_q * norm_cdf(-d1)
        rho = -K * T * disc_r * norm_cdf(-d2) / 100.0
    return {"delta": delta, "gamma": gamma, "theta": theta / 365.0, "vega": vega, "rho": rho}


def prob_itm(S, K, T, r, sigma, kind, q=0.0) -> float:
    """Risk-neutral probability that the option expires in the money."""
    kind = _check_kind(kind)
    if T <= 0 or sigma <= 0:
        return 1.0 if intrinsic(S, K, kind) > 0 else 0.0
    _, d2 = d1_d2(S, K, T, r, sigma, q)
    return norm_cdf(d2) if kind == "call" else norm_cdf(-d2)


def implied_vol(price, S, K, T, r, kind, q=0.0, lo=1e-4, hi=5.0, tol=1e-6, max_iter=200):
    """Implied volatility by bisection. Returns None if no solution exists."""
    if T <= 0 or price <= 0:
        return None
    if price < bs_price(S, K, T, r, lo, kind, q) - tol or price > bs_price(S, K, T, r, hi, kind, q) + tol:
        return None
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        if bs_price(S, K, T, r, mid, kind, q) > price:
            hi = mid
        else:
            lo = mid
        if hi - lo < tol:
            break
    return 0.5 * (lo + hi)
