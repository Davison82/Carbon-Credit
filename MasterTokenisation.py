import requests
import pandas as pd
import time

API_KEY = "d562d03c4b1c92f7e710eff9b01cc6d0"

CHAINS = {
    "Polygon": f"https://gateway-arbitrum.network.thegraph.com/api/{API_KEY}/subgraphs/id/FU5APMSSCqcRy9jy56aXJiGV3PQmFQHg2tzukvSJBgwW",
    "Base": f"https://gateway-arbitrum.network.thegraph.com/api/{API_KEY}/subgraphs/id/AEJ5PEDye6Z198HRQBioG6mZ6ZacHenBg2HTopZPsUCi",
    "Celo": f"https://gateway-arbitrum.network.thegraph.com/api/{API_KEY}/subgraphs/id/BWmN569zDopYXp3nzDukJsGDHqRstYAFULFPH8rxyVBk",
}

def fetch_all_tokens(endpoint, chain_name, batch_size=1000):
    """Pull every TCO2 token from a chain using pagination"""
    all_tokens = []
    skip = 0

    while True:
        query = """
        {
          tco2Tokens(
            first: %d
            skip: %d
            orderBy: id
            orderDirection: asc
          ) {
            id
            name
            symbol
            totalRetired
            createdAt
          }
        }
        """ % (batch_size, skip)

        response = requests.post(
            endpoint,
            json={"query": query},
            headers={"Content-Type": "application/json"},
            timeout=30
        )

        data = response.json()
        tokens = data.get("data", {}).get("tco2Tokens", [])

        if not tokens:
            break

        all_tokens.extend(tokens)
        print(f"  {chain_name}: fetched {len(all_tokens)} tokens so far...")

        if len(tokens) < batch_size:
            break

        skip += batch_size
        time.sleep(0.5)

    return all_tokens

def parse_token(token, chain_name):
    """Extract project ID and vintage from token symbol"""
    symbol = token["symbol"]
    parts = symbol.split("-")

    # Handle both VCS and PUR standards
    if len(parts) >= 3:
        standard = parts[1]  # VCS or PUR
        project_id = parts[2]
        vintage = parts[3][:4] if len(parts) > 3 else "unknown"
    else:
        standard = "unknown"
        project_id = "unknown"
        vintage = "unknown"

    retired_tonnes = int(token.get("totalRetired", 0)) / 1e18

    return {
        "chain": chain_name,
        "contract_address": token["id"],
        "symbol": symbol,
        "standard": standard,
        "project_id": project_id,
        "vintage": vintage,
        "total_retired_tonnes": round(retired_tonnes, 4),
        "created_at": token.get("createdAt", "")
    }

def build_universe():
    print("\n" + "="*70)
    print("TOKENISATION UNIVERSE BUILDER")
    print("="*70 + "\n")

    all_records = []

    for chain_name, endpoint in CHAINS.items():
        print(f"Querying {chain_name}...")
        tokens = fetch_all_tokens(endpoint, chain_name)
        print(f"  {chain_name}: {len(tokens)} total tokens found\n")

        for token in tokens:
            record = parse_token(token, chain_name)
            all_records.append(record)

        time.sleep(1)

    # Build dataframe
    df = pd.DataFrame(all_records)

    # Summary stats
    print("\n" + "="*70)
    print("UNIVERSE SUMMARY")
    print("="*70)
    print(f"Total token contracts found: {len(df)}")
    print(f"\nBy chain:")
    print(df.groupby("chain")["symbol"].count().to_string())
    print(f"\nBy standard (VCS vs PUR vs other):")
    print(df.groupby("standard")["symbol"].count().to_string())
    print(f"\nUnique projects tokenised:")
    vcs_projects = df[df["standard"] == "VCS"]["project_id"].nunique()
    print(f"  VCS projects: {vcs_projects}")
    print(f"\nProjects with any retirement activity:")
    active = df[df["total_retired_tonnes"] > 0]["project_id"].nunique()
    print(f"  {active} unique projects")

    # Export
    df.to_csv("tokenisation_universe.csv", index=False)
    print(f"\nFull universe exported to tokenisation_universe.csv")
    print(f"Total records: {len(df)}")
    print("="*70 + "\n")

    return df

if __name__ == "__main__":
    df = build_universe()
