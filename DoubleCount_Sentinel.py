import requests
import time

API_KEY = "d562d03c4b1c92f7e710eff9b01cc6d0"

# Chain endpoints
CHAINS = {
    "Polygon": f"https://gateway-arbitrum.network.thegraph.com/api/{API_KEY}/subgraphs/id/FU5APMSSCqcRy9jy56aXJiGV3PQmFQHg2tzukvSJBgwW",
    "Base": f"https://gateway-arbitrum.network.thegraph.com/api/{API_KEY}/subgraphs/id/AEJ5PEDye6Z198HRQBioG6mZ6ZacHenBg2HTopZPsUCi",
    "Celo": f"https://gateway-arbitrum.network.thegraph.com/api/{API_KEY}/subgraphs/id/BWmN569zDopYXp3nzDukJsGDHqRstYAFULFPH8rxyVBk",
}

# Verra issued figures for VCS-981 — from your audit database
VERRA_ISSUED = {
    "2012": 2063076,
    "2013": 1585465,
    "2014": 1586184,
    "2016": 1586184,
    "2017": 1653262,
}

# Project to audit
PROJECT_ID = "981"

def query_retirements(endpoint, project_id):
    """Pull all TCO2 tokens and their totalRetired for a project"""
    query = """
    {
      tco2Tokens(where: {symbol_contains: "VCS-%s"}) {
        id
        name
        symbol
        totalRetired
      }
    }
    """ % project_id

    response = requests.post(
        endpoint,
        json={"query": query},
        headers={"Content-Type": "application/json"},
        timeout=15
    )
    data = response.json()
    return data.get("data", {}).get("tco2Tokens", [])

def extract_vintage(symbol):
    """Extract vintage year from symbol like TCO2-VCS-981-2014"""
    parts = symbol.split("-")
    raw = parts[-1]
    return raw[:4]  # first 4 chars = year

def run_double_count_sentinel(project_id):
    print(f"\n{'='*70}")
    print(f"DOUBLE COUNT SENTINEL — VCS-{project_id}")
    print(f"{'='*70}\n")

    # Collect retirements per vintage per chain
    chain_results = {}

    for chain_name, endpoint in CHAINS.items():
        print(f"Querying {chain_name}...")
        tokens = query_retirements(endpoint, project_id)
        chain_results[chain_name] = {}

        for token in tokens:
            vintage = extract_vintage(token["symbol"])
            retired_tonnes = int(token.get("totalRetired", 0)) / 1e18
            if vintage not in chain_results[chain_name]:
                chain_results[chain_name][vintage] = 0
            chain_results[chain_name][vintage] += retired_tonnes

        time.sleep(1)

    # Build cross-chain comparison table
    all_vintages = sorted(set(
        v for chain in chain_results.values() for v in chain.keys()
    ))

    print(f"\n{'Vintage':<10}", end="")
    for chain in CHAINS.keys():
        print(f"{chain:<15}", end="")
    print(f"{'Combined':<15} {'Verra Issued':<15} {'Signal'}")
    print("-" * 85)

    findings = []

    for vintage in all_vintages:
        verra_issued = VERRA_ISSUED.get(vintage, 0)
        combined = 0

        print(f"{vintage:<10}", end="")
        for chain in CHAINS.keys():
            amount = chain_results[chain].get(vintage, 0)
            combined += amount
            print(f"{amount:<15,.2f}", end="")

        # Flag if combined retirements across chains exceed Verra issued
        signal = ""
        if combined > verra_issued:
            signal = "*** DOUBLE COUNT SIGNAL ***"
            findings.append(vintage)
        elif combined > 0:
            signal = "Activity detected"

        print(f"{combined:<15,.2f} {verra_issued:<15,} {signal}")

    # Summary
    print(f"\n{'='*70}")
    if findings:
        print(f"FINDINGS: {len(findings)} vintage(s) show cross-chain retirement exceeding Verra issuance")
        for v in findings:
            print(f"  Vintage {v} — investigate further")
    else:
        print("No cross-chain double count signals detected for this project")
    print(f"{'='*70}\n")

if __name__ == "__main__":
    run_double_count_sentinel(PROJECT_ID)
