import requests
import pandas as pd
import time
import os

API_KEY = "TKG4JAC829ZXXJ5E2NSFA2WH4YGF9KCMR5"

contracts = [
    ("VCS-191", "2008", "0xb139c4cc9d20a3618e9a2268d73eff18c496b991"),
    ("VCS-191", "2009", "0xccacc6099debd9654c6814fcb800431ef7549b10"),
    ("VCS-191", "2010", "0xc645b80fd8a23a1459d59626ba3f872e8a59d4cb"),
    ("VCS-1577", "2012", "0x68e65cc375f10baf74ac41773658dd00b5de1eaa"),
    ("VCS-1525", "2011", "0xCFCAd380a9f21ad3e73cb0c8898a25fcb87679fe"),
]

def get_total_supply(contract_address):
    url = "https://api.etherscan.io/v2/api"
    params = {
        "chainid": "137",
        "module": "stats",
        "action": "tokensupply",
        "contractaddress": contract_address,
        "apikey": API_KEY
    }
    try:
        response = requests.get(url, params=params)
        data = response.json()
        print(f"Raw response: {data}")
        if data["status"] == "1":
            raw = int(data["result"])
            tonnes = raw / 10**18
            return round(tonnes, 2)
        else:
            return None
    except Exception as e:
        print(f"Error: {e}")
        return None

results = []
for project, vintage, address in contracts:
    print(f"Querying {project} {vintage}...")
    supply = get_total_supply(address)
    results.append({
        "Project": project,
        "Vintage": vintage,
        "Active Supply (tonnes)": supply
    })
    time.sleep(0.2)

df = pd.DataFrame(results)
print("\n--- RESULTS ---")
print(df.to_string(index=False))

df.to_csv("carbon_audit_results.csv", index=False)
print("Saved to carbon_audit_results.csv")
