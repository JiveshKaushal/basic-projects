"""Market defaults. Exchanges revise lot sizes periodically — always verify
current values on nseindia.com / bseindia.com and override with --lot-size."""

LOT_SIZES = {
    "NIFTY": 65,
    "BANKNIFTY": 30,
    "FINNIFTY": 60,
    "MIDCPNIFTY": 120,
    "SENSEX": 20,
}

STRIKE_STEPS = {
    "NIFTY": 50,
    "BANKNIFTY": 100,
    "FINNIFTY": 50,
    "MIDCPNIFTY": 25,
    "SENSEX": 100,
}

# Approximate Indian risk-free rate (91-day T-bill). Override with --rate.
DEFAULT_RISK_FREE_RATE = 0.055

DAYS_IN_YEAR = 365.0


def lot_size(symbol: str, default: int = 1) -> int:
    return LOT_SIZES.get(symbol.upper(), default)
