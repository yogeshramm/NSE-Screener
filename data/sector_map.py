"""
Static NSE sector classification for the major Nifty 500 stocks.
Based on NSE Macro/Industry taxonomy.
"""

SECTORS = {
    # Banking & Financial Services
    "HDFCBANK": "Banking", "ICICIBANK": "Banking", "SBIN": "Banking", "KOTAKBANK": "Banking",
    "AXISBANK": "Banking", "INDUSINDBK": "Banking", "BANKBARODA": "Banking", "PNB": "Banking",
    "CANBK": "Banking", "UNIONBANK": "Banking", "IDFCFIRSTB": "Banking", "FEDERALBNK": "Banking",
    "RBLBANK": "Banking", "BANDHANBNK": "Banking", "AUBANK": "Banking", "IOB": "Banking",
    "YESBANK": "Banking", "BANKINDIA": "Banking", "UCOBANK": "Banking", "CENTRALBK": "Banking",
    "SHRIRAMFIN": "NBFC", "BAJFINANCE": "NBFC", "BAJAJFINSV": "NBFC", "CHOLAFIN": "NBFC",
    "SBICARD": "NBFC", "MUTHOOTFIN": "NBFC", "MANAPPURAM": "NBFC", "POONAWALLA": "NBFC",
    "LICHSGFIN": "NBFC", "PFC": "NBFC", "RECLTD": "NBFC", "IRFC": "NBFC", "HUDCO": "NBFC",
    "LTF": "NBFC", "M&MFIN": "NBFC", "ABCAPITAL": "NBFC", "IIFL": "NBFC", "AAVAS": "NBFC",
    "CREDITACC": "NBFC", "FIVESTAR": "NBFC", "AADHARHFC": "NBFC", "CANFINHOME": "NBFC",
    "HDFCLIFE": "Insurance", "SBILIFE": "Insurance", "ICICIGI": "Insurance", "ICICIPRULI": "Insurance",
    "LICI": "Insurance", "MAXHEALTH": "Insurance", "NIACL": "Insurance", "STARHEALTH": "Insurance",

    # IT / Technology
    "TCS": "IT Services", "INFY": "IT Services", "WIPRO": "IT Services", "HCLTECH": "IT Services",
    "TECHM": "IT Services", "LTIM": "IT Services", "MPHASIS": "IT Services", "PERSISTENT": "IT Services",
    "COFORGE": "IT Services", "SONATSOFTW": "IT Services", "KPITTECH": "IT Services", "BSOFT": "IT Services",
    "CYIENT": "IT Services", "TATAELXSI": "IT Services", "ZENSARTECH": "IT Services", "OFSS": "IT Services",
    "LTTS": "IT Services", "NEWGEN": "IT Services", "BIRLASOFT": "IT Services", "FSL": "IT Services",
    "AFFLE": "Internet", "NYKAA": "Internet", "ZOMATO": "Internet", "POLICYBZR": "Internet",
    "PAYTM": "Internet", "MAPMYINDIA": "Internet", "JUSTDIAL": "Internet", "INFIBEAM": "Internet",
    "NAZARA": "Internet", "INDIAMART": "Internet",

    # FMCG
    "HINDUNILVR": "FMCG", "ITC": "FMCG", "NESTLEIND": "FMCG", "BRITANNIA": "FMCG", "DABUR": "FMCG",
    "MARICO": "FMCG", "GODREJCP": "FMCG", "COLPAL": "FMCG", "TATACONSUM": "FMCG", "VBL": "FMCG",
    "UBL": "FMCG", "RADICO": "FMCG", "EMAMILTD": "FMCG", "PGHH": "FMCG", "JUBLFOOD": "FMCG",
    "HATSUN": "FMCG", "CCL": "FMCG", "BIKAJI": "FMCG", "DODLA": "FMCG", "ITCHOTELS": "FMCG",

    # Pharma & Healthcare
    "SUNPHARMA": "Pharma", "DRREDDY": "Pharma", "CIPLA": "Pharma", "DIVISLAB": "Pharma",
    "APOLLOHOSP": "Healthcare", "ZYDUSLIFE": "Pharma", "TORNTPHARM": "Pharma", "LUPIN": "Pharma",
    "ALKEM": "Pharma", "AUROPHARMA": "Pharma", "MANKIND": "Pharma", "GLENMARK": "Pharma",
    "BIOCON": "Pharma", "ABBOTINDIA": "Pharma", "SANOFI": "Pharma", "IPCALAB": "Pharma",
    "PFIZER": "Pharma", "NATCOPHARM": "Pharma", "GLAND": "Pharma", "LAURUSLABS": "Pharma",
    "AJANTPHARM": "Pharma", "JBCHEPHARM": "Pharma", "ERIS": "Pharma", "SUVENPHAR": "Pharma",
    "METROPOLIS": "Healthcare", "FORTIS": "Healthcare", "MAXHEALTH": "Healthcare", "NH": "Healthcare",
    "GLOBALHEALTH": "Healthcare", "KIMS": "Healthcare", "RAINBOW": "Healthcare", "KRSNAA": "Healthcare",

    # Auto & Auto Ancillary
    "MARUTI": "Auto", "TATAMOTORS": "Auto", "M&M": "Auto", "BAJAJ-AUTO": "Auto", "EICHERMOT": "Auto",
    "HEROMOTOCO": "Auto", "TVSMOTOR": "Auto", "ASHOKLEY": "Auto", "MOTHERSON": "Auto Ancillary",
    "BOSCHLTD": "Auto Ancillary", "BHARATFORG": "Auto Ancillary", "APOLLOTYRE": "Auto Ancillary",
    "MRF": "Auto Ancillary", "CEAT": "Auto Ancillary", "BALKRISIND": "Auto Ancillary",
    "EXIDEIND": "Auto Ancillary", "SONACOMS": "Auto Ancillary", "UNOMINDA": "Auto Ancillary",
    "ENDURANCE": "Auto Ancillary", "TVSHLTD": "Auto Ancillary", "SCHAEFFLER": "Auto Ancillary",
    "SUNDRMFAST": "Auto Ancillary",

    # Energy & Oil
    "RELIANCE": "Energy", "ONGC": "Energy", "BPCL": "Energy", "IOC": "Energy", "HPCL": "Energy",
    "GAIL": "Energy", "PETRONET": "Energy", "OIL": "Energy", "MGL": "Energy", "IGL": "Energy",
    "GUJGASLTD": "Energy", "CASTROLIND": "Energy", "MRPL": "Energy", "CHENNPETRO": "Energy",

    # Metals & Mining
    "TATASTEEL": "Metals", "JSWSTEEL": "Metals", "HINDALCO": "Metals", "VEDL": "Metals",
    "COALINDIA": "Metals", "NMDC": "Metals", "NALCO": "Metals", "SAIL": "Metals", "JINDALSTEL": "Metals",
    "APLAPOLLO": "Metals", "HINDZINC": "Metals", "RATNAMANI": "Metals", "JSL": "Metals",
    "WELCORP": "Metals", "GMDCLTD": "Metals", "GRAVITA": "Metals",

    # Cement
    "ULTRACEMCO": "Cement", "AMBUJACEM": "Cement", "SHREECEM": "Cement", "ACC": "Cement",
    "DALBHARAT": "Cement", "JKCEMENT": "Cement", "RAMCOCEM": "Cement", "HEIDELBERG": "Cement",
    "INDIACEM": "Cement", "NUVOCO": "Cement",

    # Power & Utilities
    "NTPC": "Power", "POWERGRID": "Power", "TATAPOWER": "Power", "ADANIPOWER": "Power",
    "JSWENERGY": "Power", "NHPC": "Power", "SJVN": "Power", "TORNTPOWER": "Power", "CESC": "Power",
    "PTCIL": "Power", "NLCINDIA": "Power", "INDIANB": "Power", "IEX": "Power", "RPOWER": "Power",

    # Infra & Construction
    "LT": "Infrastructure", "GMRINFRA": "Infrastructure", "IRB": "Infrastructure", "NBCC": "Infrastructure",
    "KEC": "Infrastructure", "NCC": "Infrastructure", "HGINFRA": "Infrastructure", "GRINFRA": "Infrastructure",
    "KALPATPOWR": "Infrastructure", "RVNL": "Infrastructure", "IRCON": "Infrastructure",
    "KNRCON": "Infrastructure", "PNCINFRA": "Infrastructure", "JWL": "Infrastructure",
    "ADANIPORTS": "Infrastructure", "CONCOR": "Infrastructure", "GRAPHITE": "Infrastructure",

    # Real Estate
    "DLF": "Real Estate", "GODREJPROP": "Real Estate", "OBEROIRLTY": "Real Estate", "BRIGADE": "Real Estate",
    "PRESTIGE": "Real Estate", "PHOENIXLTD": "Real Estate", "SOBHA": "Real Estate", "LODHA": "Real Estate",
    "SUNTECK": "Real Estate", "MAHLIFE": "Real Estate",

    # Telecom
    "BHARTIARTL": "Telecom", "IDEA": "Telecom", "INDUSTOWER": "Telecom", "TATACOMM": "Telecom",
    "HFCL": "Telecom",

    # Consumer Durables / Retail
    "TITAN": "Consumer Durables", "HAVELLS": "Consumer Durables", "VOLTAS": "Consumer Durables",
    "DIXON": "Consumer Durables", "CROMPTON": "Consumer Durables", "WHIRLPOOL": "Consumer Durables",
    "BLUESTARCO": "Consumer Durables", "KAYNES": "Consumer Durables", "BEL": "Defense",
    "HAL": "Defense", "BDL": "Defense", "DATAPATTNS": "Defense", "ASTRAMICRO": "Defense",
    "PAGEIND": "Retail", "TRENT": "Retail", "DMART": "Retail", "ABFRL": "Retail",
    "VMART": "Retail", "SHOPERSTOP": "Retail", "BATAINDIA": "Retail",

    # Chemicals
    "UPL": "Chemicals", "PIDILITIND": "Chemicals", "SRF": "Chemicals", "DEEPAKNTR": "Chemicals",
    "AARTIIND": "Chemicals", "COROMANDEL": "Chemicals", "CHAMBLFERT": "Chemicals", "NAVINFLUOR": "Chemicals",
    "PIIND": "Chemicals", "ATUL": "Chemicals", "BASF": "Chemicals", "CLEAN": "Chemicals",
    "ALKYLAMINE": "Chemicals", "FINEORG": "Chemicals", "SUMICHEM": "Chemicals", "GODREJIND": "Chemicals",
    "TATACHEM": "Chemicals", "BAYERCROP": "Chemicals", "ASTRAL": "Chemicals",

    # Paint
    "ASIANPAINT": "Paint", "BERGEPAINT": "Paint", "KANSAINER": "Paint", "AKZOINDIA": "Paint",
    "INDIGOPNTS": "Paint",

    # Capital Goods / Electricals
    "SIEMENS": "Capital Goods", "ABB": "Capital Goods", "CUMMINSIND": "Capital Goods",
    "SCHNEIDER": "Capital Goods", "THERMAX": "Capital Goods", "POLYCAB": "Capital Goods",
    "KEI": "Capital Goods", "SUZLON": "Capital Goods", "INOXWIND": "Capital Goods",
    "CGPOWER": "Capital Goods", "HONAUT": "Capital Goods", "ELGIEQUIP": "Capital Goods",
    "AIAENG": "Capital Goods", "GRINDWELL": "Capital Goods",

    # Aviation / Logistics
    "INDIGO": "Aviation", "SPICEJET": "Aviation", "DELHIVERY": "Logistics", "BLUEDART": "Logistics",
    "TCI": "Logistics", "MAHLOG": "Logistics", "ALLCARGO": "Logistics", "GATI": "Logistics",

    # Media & Entertainment
    "ZEEL": "Media", "SUNTV": "Media", "PVRINOX": "Media", "SAREGAMA": "Media", "NETWORK18": "Media",
    "NAVNETEDUL": "Media", "HATHWAY": "Media", "DBCORP": "Media",

    # Textiles
    "KPRMILL": "Textiles", "TRIDENT": "Textiles", "VARDHACRLC": "Textiles", "GARFIBRES": "Textiles",
    "RAYMOND": "Textiles", "WELSPUNIND": "Textiles",

    # Other
    "ADANIENT": "Conglomerate", "ADANIGREEN": "Renewable Energy", "ADANIENSOL": "Power",
    "ADANIGAS": "Energy", "GLAXO": "Pharma", "WHIRLPOOL": "Consumer Durables",
}


def get_sector(symbol: str) -> str:
    """Return sector for symbol, or 'Other' if unknown."""
    return SECTORS.get(symbol.upper(), "Other")
