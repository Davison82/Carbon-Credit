import requests
import pandas as pd
import time

# --- CONFIG ---
API_KEY = "d562d03c4b1c92f7e710eff9b01cc6d0"

CHAINS = {
    "Polygon": f"https://gateway-arbitrum.network.thegraph.com/api/{API_KEY}/subgraphs/id/FU5APMSSCqcRy9jy56aXJiGV3PQmFQHg2tzukvSJBgwW",
    "Base":    f"https://gateway-arbitrum.network.thegraph.com/api/{API_KEY}/subgraphs/id/AEJ5PEDye6Z198HRQBioG6mZ6ZacHenBg2HTopZPsUCi",
    "Celo":    f"https://gateway-arbitrum.network.thegraph.com/api/{API_KEY}/subgraphs/id/BWmN569zDopYXp3nzDukJsGDHqRstYAFULFPH8rxyVBk",
}

# Known pool contract addresses — confirmed from VCS-981 audit
KNOWN_POOLS = {
    "0xd838290e877e0188a4a44700463419ed96c16107": "NCT Pool",
    "0x2f800db0fdb5223b3c3f354886d907a671414a7f": "BCT Pool",
    "0xb139c4cc9d20a3618e9a2268d73eff18c496b991": "CHAR Pool",
}

# --- FETCH ALL TOKENS WITH PAGINATION ---
def fetch_all_tokens(endpoint, chain_name, batch_size=1000):
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
            projectVintage {
              totalVintageQuantity
            }
          }
        }
        """ % (batch_size, skip)

        try:
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
            print(f"  {chain_name}: fetched {len(all_tokens)} tokens...")

            if len(tokens) < batch_size:
                break

            skip += batch_size
            time.sleep(0.5)

        except Exception as e:
            print(f"  Error on {chain_name}: {e}")
            break

    return all_tokens

# --- FETCH ACTIVE SUPPLY & POOL ASSIGNMENT IN ONE QUERY ---
def get_token_balances_and_pool(endpoint, contract_address):
    """
    Query balances for a token contract to retrieve:
      1. Total active (unretired) supply across all wallets
      2. Primary pool assignment label (if held by a known pool)
      3. Detailed breakdown of pool holdings
    """
    query = """
    {
      tco2Balances(
        where: {token: "%s"}
        first: 1000
      ) {
        balance
        user {
          id
        }
      }
    }
    """ % contract_address.lower()

    try:
        response = requests.post(
            endpoint,
            json={"query": query},
            headers={"Content-Type": "application/json"},
            timeout=15
        )
        data = response.json()
        balances = data.get("data", {}).get("tco2Balances", [])

        total_active_raw = 0
        pool_assignment = "ERC20 Raw TCO2"
        pool_holdings = {}

        for b in balances:
            bal = int(b.get("balance", 0)) / 1e18
            total_active_raw += bal
            holder = b.get("user", {}).get("id", "").lower()

            for pool_addr, pool_name in KNOWN_POOLS.items():
                if holder == pool_addr.lower():
                    pool_holdings[pool_name] = round(bal, 4)
                    pool_assignment = pool_name

        return round(total_active_raw, 4), pool_assignment, pool_holdings

    except Exception:
        return 0.0, "Unknown", {}

# --- PARSE TOKEN ---
def parse_token(token, chain_name, pool_assignment, active_supply, pool_holdings):
    symbol = token.get("symbol", "")
    parts = symbol.split("-")

    if len(parts) >= 4:
        standard = parts[1]
        project_id = parts[2]
        vintage = parts[3][:4]
    else:
        standard = "unknown"
        project_id = "unknown"
        vintage = "unknown"

    retired_tonnes = round(int(token.get("totalRetired", 0)) / 1e18, 4)
    total_minted = round(retired_tonnes + active_supply, 4)

    vintage_quantity = 0
    if token.get("projectVintage") and token["projectVintage"].get("totalVintageQuantity"):
        try:
            vintage_quantity = int(token["projectVintage"]["totalVintageQuantity"])
        except (ValueError, TypeError):
            pass

    return {
        "chain": chain_name,
        "contract_address": token["id"],
        "symbol": symbol,
        "standard": standard,
        "project_id": project_id,
        "vintage": vintage,
        "total_retired_tonnes": retired_tonnes,
        "active_supply": active_supply,
        "total_minted_tonnes": total_minted,
        "verra_vintage_quantity": vintage_quantity,
        "pool_assignment": pool_assignment,
        "pool_holdings": str(pool_holdings),
        "created_at": token.get("createdAt", "")
    }

# --- BUILD UNIVERSE ---
def build_universe():
    print("\n" + "="*70)
    print("TOKENISATION UNIVERSE BUILDER v3 — SNAPSHOT GENERATOR")
    print("="*70 + "\n")

    all_records = []

    for chain_name, endpoint in CHAINS.items():
        print(f"Querying {chain_name}...")
        tokens = fetch_all_tokens(endpoint, chain_name)
        print(f"  {chain_name}: {len(tokens)} total tokens\n")

        for i, token in enumerate(tokens):
            # Fetch active supply and pool information in one query
            active_supply, pool, holdings = get_token_balances_and_pool(
                endpoint, token["id"]
            )
            time.sleep(0.2)

            record = parse_token(
                token, chain_name, pool, active_supply, holdings
            )
            all_records.append(record)

            if i % 50 == 0:
                print(f"  Processed {i}/{len(tokens)} tokens...")

        time.sleep(1)

    df = pd.DataFrame(all_records)

    # --- SUMMARY ---
    print("\n" + "="*70)
    print("UNIVERSE SUMMARY")
    print("="*70)
    print(f"Total token contracts: {len(df)}")
    print(f"\nBy chain:")
    print(df.groupby("chain")["symbol"].count().to_string())
    print(f"\nBy standard:")
    print(df.groupby("standard")["symbol"].count().to_string())
    print(f"\nUnique VCS projects: {df[df['standard']=='VCS']['project_id'].nunique()}")
    print(f"\nPool assignment breakdown:")
    print(df.groupby("pool_assignment")["symbol"].count().to_string())
    print(f"\nProjects with retirement activity: {df[df['total_retired_tonnes']>0]['project_id'].nunique()}")
    print(f"Projects with active supply: {df[df['active_supply']>0]['project_id'].nunique()}")

    # Export
    df.to_csv("tokenisation_universe.csv", index=False)
    print(f"\nExported complete snapshot to tokenisation_universe.csv")
    print("="*70 + "\n")

    return df

if __name__ == "__main__":
    build_universe()
