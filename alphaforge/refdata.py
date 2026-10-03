"""Static reference data: display names and GICS-style sectors for search, sector risk and sorting.

Approximate as of 2025. Unknown symbols fall back to the ticker and "Other".
"""

EQUITY = {
    "AAPL": ("Apple", "Technology"), "ABBV": ("AbbVie", "Health Care"), "ABT": ("Abbott Laboratories", "Health Care"),
    "ACN": ("Accenture", "Technology"), "ADBE": ("Adobe", "Technology"), "AIG": ("American International Group", "Financials"),
    "AMD": ("Advanced Micro Devices", "Technology"), "AMGN": ("Amgen", "Health Care"), "AMT": ("American Tower", "Real Estate"),
    "AMZN": ("Amazon", "Consumer Discretionary"), "AVGO": ("Broadcom", "Technology"), "AXP": ("American Express", "Financials"),
    "BA": ("Boeing", "Industrials"), "BAC": ("Bank of America", "Financials"), "BK": ("BNY Mellon", "Financials"),
    "BKNG": ("Booking Holdings", "Consumer Discretionary"), "BLK": ("BlackRock", "Financials"), "BMY": ("Bristol-Myers Squibb", "Health Care"),
    "BRK-B": ("Berkshire Hathaway", "Financials"), "C": ("Citigroup", "Financials"), "CAT": ("Caterpillar", "Industrials"),
    "CHTR": ("Charter Communications", "Communication Services"), "CL": ("Colgate-Palmolive", "Consumer Staples"),
    "CMCSA": ("Comcast", "Communication Services"), "COF": ("Capital One", "Financials"), "COP": ("ConocoPhillips", "Energy"),
    "COST": ("Costco", "Consumer Staples"), "CRM": ("Salesforce", "Technology"), "CSCO": ("Cisco", "Technology"),
    "CVS": ("CVS Health", "Health Care"), "CVX": ("Chevron", "Energy"), "DE": ("Deere", "Industrials"),
    "DHR": ("Danaher", "Health Care"), "DIS": ("Walt Disney", "Communication Services"), "DUK": ("Duke Energy", "Utilities"),
    "EMR": ("Emerson Electric", "Industrials"), "F": ("Ford", "Consumer Discretionary"), "FDX": ("FedEx", "Industrials"),
    "GD": ("General Dynamics", "Industrials"), "GE": ("GE Aerospace", "Industrials"), "GILD": ("Gilead Sciences", "Health Care"),
    "GM": ("General Motors", "Consumer Discretionary"), "GOOGL": ("Alphabet", "Communication Services"),
    "GS": ("Goldman Sachs", "Financials"), "HD": ("Home Depot", "Consumer Discretionary"), "HON": ("Honeywell", "Industrials"),
    "IBM": ("IBM", "Technology"), "INTC": ("Intel", "Technology"), "INTU": ("Intuit", "Technology"),
    "ISRG": ("Intuitive Surgical", "Health Care"), "JNJ": ("Johnson & Johnson", "Health Care"), "JPM": ("JPMorgan Chase", "Financials"),
    "KO": ("Coca-Cola", "Consumer Staples"), "LIN": ("Linde", "Materials"), "LLY": ("Eli Lilly", "Health Care"),
    "LMT": ("Lockheed Martin", "Industrials"), "LOW": ("Lowe's", "Consumer Discretionary"), "MA": ("Mastercard", "Financials"),
    "MCD": ("McDonald's", "Consumer Discretionary"), "MDLZ": ("Mondelez", "Consumer Staples"), "MDT": ("Medtronic", "Health Care"),
    "MET": ("MetLife", "Financials"), "META": ("Meta Platforms", "Communication Services"), "MMM": ("3M", "Industrials"),
    "MO": ("Altria", "Consumer Staples"), "MRK": ("Merck", "Health Care"), "MS": ("Morgan Stanley", "Financials"),
    "MSFT": ("Microsoft", "Technology"), "NEE": ("NextEra Energy", "Utilities"), "NFLX": ("Netflix", "Communication Services"),
    "NKE": ("Nike", "Consumer Discretionary"), "NOW": ("ServiceNow", "Technology"), "NVDA": ("Nvidia", "Technology"),
    "ORCL": ("Oracle", "Technology"), "PEP": ("PepsiCo", "Consumer Staples"), "PFE": ("Pfizer", "Health Care"),
    "PG": ("Procter & Gamble", "Consumer Staples"), "PLTR": ("Palantir", "Technology"), "PM": ("Philip Morris", "Consumer Staples"),
    "PYPL": ("PayPal", "Financials"), "QCOM": ("Qualcomm", "Technology"), "RTX": ("RTX", "Industrials"),
    "SBUX": ("Starbucks", "Consumer Discretionary"), "SCHW": ("Charles Schwab", "Financials"), "SO": ("Southern Company", "Utilities"),
    "SPG": ("Simon Property Group", "Real Estate"), "T": ("AT&T", "Communication Services"), "TGT": ("Target", "Consumer Staples"),
    "TMO": ("Thermo Fisher Scientific", "Health Care"), "TMUS": ("T-Mobile US", "Communication Services"),
    "TSLA": ("Tesla", "Consumer Discretionary"), "TXN": ("Texas Instruments", "Technology"), "UBER": ("Uber", "Industrials"),
    "UNH": ("UnitedHealth", "Health Care"), "UNP": ("Union Pacific", "Industrials"), "UPS": ("UPS", "Industrials"),
    "USB": ("U.S. Bancorp", "Financials"), "V": ("Visa", "Financials"), "VZ": ("Verizon", "Communication Services"),
    "WFC": ("Wells Fargo", "Financials"), "WMT": ("Walmart", "Consumer Staples"), "XOM": ("Exxon Mobil", "Energy"),
    "SPY": ("SPDR S&P 500 ETF", "ETF"),
}

CRYPTO = {
    "BTC/USD": "Bitcoin", "ETH/USD": "Ethereum", "SOL/USD": "Solana", "LTC/USD": "Litecoin",
    "LINK/USD": "Chainlink", "AVAX/USD": "Avalanche", "DOGE/USD": "Dogecoin", "BCH/USD": "Bitcoin Cash",
    "XRP/USD": "XRP", "DOT/USD": "Polkadot", "UNI/USD": "Uniswap", "AAVE/USD": "Aave",
}


def name(sym):
    return EQUITY.get(sym, (CRYPTO.get(sym, sym), ""))[0]


def sector(sym):
    return EQUITY.get(sym, (None, "Crypto" if sym in CRYPTO else "Other"))[1]


def yahoo(sym):
    """Alpaca crypto pair -> Yahoo symbol (BTC/USD -> BTC-USD); equities unchanged."""
    return sym.replace("/", "-")
