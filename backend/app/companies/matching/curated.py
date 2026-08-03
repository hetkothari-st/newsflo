"""Trade names that no exchange registry carries.

Reviewed by hand, keyed by ticker. This file exists because registries hold
legal names ("Infosys Limited", "Life Insurance Corporation of India") while
news copy uses trade names ("Infosys", "LIC"). Keep it small and reviewed --
it is the one place in the matching package where a human asserts a fact
rather than deriving it from a source.
"""

CURATED_TRADE_NAMES: dict[str, tuple[str, ...]] = {
    "INFY.NS": ("Infosys",),
    "TCS.NS": ("TCS", "Tata Consultancy"),
    "LICI.NS": ("LIC", "Life Insurance Corporation"),
    "MARUTI.NS": ("Maruti", "Maruti Suzuki"),
    "HDFCBANK.NS": ("HDFC Bank",),
    "ICICIBANK.NS": ("ICICI Bank",),
    "SBIN.NS": ("SBI", "State Bank of India"),
    "RELIANCE.NS": ("Reliance", "RIL"),
    "BHARTIARTL.NS": ("Airtel", "Bharti Airtel"),
    "HINDUNILVR.NS": ("HUL", "Hindustan Unilever"),
    "LT.NS": ("L&T", "Larsen and Toubro"),
    "M&M.NS": ("Mahindra", "Mahindra and Mahindra"),
    "HINDPETRO.NS": ("HPCL", "Hindustan Petroleum"),
    "BPCL.NS": ("BPCL", "Bharat Petroleum"),
    "IOC.NS": ("IOC", "Indian Oil"),
    "OIL.NS": ("Oil India",),
    "SBICARD.NS": ("SBI Cards",),
    "APOLLOHOSP.NS": ("Apollo Hospitals",),
    "SBILIFE.NS": ("SBI Life",),
}
