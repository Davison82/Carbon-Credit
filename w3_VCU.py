import requests
import pandas as pd
import time

API_KEY = "TKG4JAC829ZXXJ5E2NSFA2WH4YGF9KCMR5"

# (Project, Vintage, Contract Address, Verra Issued)
contracts = [
    # VCS-191 Dayingjiang Hydropower China
    ("VCS-191", "2008", "0xb139c4cc9d20a3618e9a2268d73eff18c496b991", 609708, "Hydropower", "China", "ACM0002", "Registered"),
    ("VCS-191", "2009", "0xccacc6099debd9654c6814fcb800431ef7549b10", 745096, "Hydropower", "China", "ACM0002", "Registered"),
    ("VCS-191", "2010", "0xc645b80fd8a23a1459d59626ba3f872e8a59d4cb", 817655, "Hydropower", "China", "ACM0002", "Registered"),
    ("VCS-191", "2011", "0xB0D34B2eC3b47ba1f27C9D4e8520F8fA38EF538D", 868628, "Hydropower", "China", "ACM0002", "Registered"),

    # VCS-1577 Forestry China
    ("VCS-1577", "2012", "0x68e65cc375f10baf74ac41773658dd00b5de1eaa", 52222, "Forestry", "China", "VM0010", "Registered"),
    ("VCS-1577", "2013", "0x38C518400a3f9e2110Dc52e6c92E37fB7378Aaaf", 52519, "Forestry", "China", "VM0010", "Registered"),
    ("VCS-1577", "2014", "0x80ea96D75A308144708570A8E84F50dF5477ee8A", 52814, "Forestry", "China", "VM0010", "Registered"),
    ("VCS-1577", "2015", "0x04943C19896c776c78770429eC02C5384ee78292", 53111, "Forestry", "China", "VM0010", "Registered"),
    ("VCS-1577", "2016", "0x8d6E4e58CC7D18a7c9552d679722ACDDffC7387B", 55041, "Forestry", "China", "VM0010", "Registered"),

    # VCS-1525 Wind India
    ("VCS-1525", "2011", "0xCFCAd380A9F21aD3E73Cb0c8898A25FcB87679fe", 46318, "Wind Energy", "India", "ACM0002", "Registered"),
    ("VCS-1525", "2012", "0x7526b59e5A7dAa4Ef2667274647c9D49f427F1fb", 64029, "Wind Energy", "India", "ACM0002", "Registered"),

    # VCS-981 Pacajai REDD+ Brazil
    ("VCS-981", "2012", "0x65d96F0D45606016E30c97ee039775dE9722A7D2", 2063076, "REDD+", "Brazil", "VM0015", "On Hold"),
    ("VCS-981", "2013", "0x88DA4C6bFfdaEDf6b64bDB6060973F86a77830eC", 1585465, "REDD+", "Brazil", "VM0015", "On Hold"),
    ("VCS-981", "2014", "0xaBFd6760151C7f9361cc5b03bbEebE2d7c0251Da", 1586184, "REDD+", "Brazil", "VM0015", "On Hold"),
    ("VCS-981", "2016", "0x1bDF022E0CF838EB3c777e3e502db9e4029962C8", 1586184, "REDD+", "Brazil", "VM0015", "On Hold"),
    ("VCS-981", "2017", "0xeaa9938076748d7eDD4DF0721B3e3fe4077349D3", 1653262, "REDD+", "Brazil", "VM0015", "On Hold"),
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
        if data["status"] == "1":
            raw = int(data["result"])
            tonnes = raw / 10**18
            return round(tonnes, 2)
        else:
            print(f"API error for {contract_address}: {data.get('message', 'Unknown error')}")
            return None
    except Exception as e:
        print(f"Error: {e}")
        return None

results = []
for project, vintage, address, verra_issued, project_type, country, methodology, verra_status in contracts:
    print(f"Querying {project} {vintage}...")
    supply = get_total_supply(address)
    if supply is not None:
        retired = round(verra_issued - supply, 2)
        retirement_rate = round((retired / verra_issued) * 100, 1)
    else:
        retired = None
        retirement_rate = None
    results.append({
        "Project": project,
        "Vintage": vintage,
        "Project Type": project type,
        "Methodology": methodology,
        "Verra Status": verra_status,
        "Verra Issued": verra_issued,
        "Active Supply (tonnes)": supply,
        "Retired (tonnes)": retired,
        "Retirement Rate %": retirement_rate
    })
    time.sleep(0.5)

df = pd.DataFrame(results)
print("\n--- RECONCILIATION RESULTS ---")
print(df.to_string(index=False))
df.to_csv("TCO2_active_supply_20250509_v2.csv", index=False)
print("\nSaved to TCO2_active_supply_20250509_v2.csv")
