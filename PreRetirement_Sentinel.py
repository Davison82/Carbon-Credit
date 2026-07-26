import requests
import pandas as pd
import time
import os

# --- CONFIG ---
API_KEY = "d562d03c4b1c92f7e710eff9b01cc6d0"

CHAINS = {
    "Polygon": f"https://gateway-arbitrum.network.thegraph.com/api/{API_KEY}/subgraphs/id/FU5APMSSCqcRy9jy56aXJiGV3PQmFQHg2tzukvSJBgwW",
    "Base":    f"https://gateway-arbitrum.network.thegraph.com/api/{API_KEY}/subgraphs/id/AEJ5PEDye6Z198HRQBioG6mZ6ZacHenBg2HTopZPsUCi",
    "Celo":    f"https://gateway-arbitrum.network.thegraph.com/api/{API_KEY}/subgraphs/id/BWmN569zDopYXp3nzDukJsGDHqRstYAFULFPH8rxyVBk",
}

VERRA_CSV = "Verra Database 2026 04.csv"

# --- LOAD VERRA BASELINE FROM CSV ---
def load_verra_baseline(csv_path, project_id):
    if not os.path.exists(csv_path):
        print(f"ERROR: Cannot find {csv_path}")
        return {}

    df = pd.read_csv(csv_path, low_memory=False)

    id_col = next((c for c in df.columns if "project id" in c.lower()), None)
    if not id_col:
        print("ERROR: Cannot find Project ID column")
        return {}

    # Match VCS981 format (no hyphen)
    mask = df[id_col].astype(str).str.strip().str.fullmatch(
        f"VCS{project_id}", case=False, na=False
    )
    match = df[mask]

    if match.empty:
        print(f"Project VCS{project_id} not found in Verra CSV")
        return {}

    row = match.iloc[0]
    print(f"Found: {row.get('Project Name', 'Unknown')}")

    # Only plain year columns — no .1 .2 .3 suffixes
    year_cols = {
        col.strip(): col for col in df.columns
        if col.strip().isdigit() and 1990 <= int(col.strip()) <= 2030
    }

    if not year_cols:
        print("ERROR: No vintage year columns found")
        return {}

    baseline = {}
    for year_str, col in year_cols.items():
        val = row[col]
        if pd.notna(val) and str(val).strip() not in ["", "-", "0", "nan"]:
            try:
                issued = int(float(str(val).replace(",", "").replace(" ", "")))
                if issued > 0:
                    baseline[year_str] = issued
            except ValueError:
                continue

    return baseline

# --- QUERY ACTIVE SUPPLY PER TOKEN ---
def get_active_supply(endpoint, contract_address):
    """
    Sums all tco2Balance entries for a contract to get
    current active (unretired) supply.
    """
    query = """
    {
      tco2Balances(
        where: {token: "%s"}
        first: 1000
      ) {
        balance
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
        total = sum(int(b["balance"]) for b in balances if b.get("balance"))
        return total / 1e18
    except Exception as e:
        print(f"  Balance query error: {e}")
        return 0.0

# --- QUERY TOKENS AND RETIRED FOR A PROJECT ---
def get_project_tokens(endpoint, project_id):
    """
    Returns all TCO2 tokens for a project with totalRetired.
    """
    query = """
    {
      tco2Tokens(where: {symbol_contains: "VCS-%s"}) {
        id
        symbol
        totalRetired
      }
    }
    """ % project_id

    try:
        response = requests.post(
            endpoint,
            json={"query": query},
            headers={"Content-Type": "application/json"},
            timeout=15
        )
        data = response.json()
        return data.get("data", {}).get("tco2Tokens", [])
    except Exception as e:
        print(f"  Token query error: {e}")
        return []

def extract_vintage(symbol):
    parts = symbol.split("-")
    return parts[-1][:4] if len(parts) >= 4 else "unknown"

# --- MAIN SENTINEL ---
def run_preretirement_sentinel(project_id, verra_csv):
    print(f"\n{'='*75}")
    print(f"PRE-RETIREMENT DOUBLE COUNT SENTINEL — VCS-{project_id}")
    print(f"Formula: Active Supply + Total Retired = Total Ever Minted")
    print(f"Signal if: Total Ever Minted (any chain) > Verra Issued")
    print(f"{'='*75}\n")

    # Load Verra baseline
    print("Loading Verra baseline from CSV...")
    baseline = load_verra_baseline(verra_csv, project_id)
    if not baseline:
        print("ERROR: No baseline data found. Cannot run sentinel.")
        return

    print(f"Verra baseline loaded: {len(baseline)} vintages found")
    for vintage, issued in sorted(baseline.items()):
        print(f"  {vintage}: {issued:,} issued")

    # Collect data across all chains
    print(f"\nQuerying chains...\n")

    chain_data = {}

    for chain_name, endpoint in CHAINS.items():
        print(f"  {chain_name}:")
        tokens = get_project_tokens(endpoint, project_id)

        if not tokens:
            print(f"    No tokens found")
            chain_data[chain_name] = {}
            time.sleep(0.5)
            continue

        chain_data[chain_name] = {}

        for token in tokens:
            vintage = extract_vintage(token["symbol"])
            contract = token["id"]
            retired = int(token.get("totalRetired", 0)) / 1e18

            # Get active supply from balances
            active = get_active_supply(endpoint, contract)
            total_minted = retired + active

            print(f"    {token['symbol']}")
            print(f"      Retired:      {retired:>12,.2f} t")
            print(f"      Active:       {active:>12,.2f} t")
            print(f"      Total Minted: {total_minted:>12,.2f} t")

            if vintage not in chain_data[chain_name]:
                chain_data[chain_name][vintage] = {
                    "retired": 0.0,
                    "active": 0.0,
                    "total_minted": 0.0
                }

            chain_data[chain_name][vintage]["retired"] += retired
            chain_data[chain_name][vintage]["active"] += active
            chain_data[chain_name][vintage]["total_minted"] += total_minted

            time.sleep(0.5)

        time.sleep(1)

    # Build results table
    all_vintages = sorted(set(
        v for chain in chain_data.values() for v in chain.keys()
    ) | set(baseline.keys()))

    print(f"\n{'='*75}")
    print(f"RESULTS TABLE")
    print(f"{'='*75}\n")
    print(f"{'Vintage':<10} {'Verra Issued':<16} {'Total Minted':<16} {'Active':<14} {'Retired':<14} {'Signal'}")
    print("-" * 95)

    findings = []
    results = []

    for vintage in all_vintages:
        verra_issued = baseline.get(vintage, 0)

        # Sum across all chains
        total_minted_all = sum(
            chain_data[c].get(vintage, {}).get("total_minted", 0)
            for c in CHAINS
        )
        total_active_all = sum(
            chain_data[c].get(vintage, {}).get("active", 0)
            for c in CHAINS
        )
        total_retired_all = sum(
            chain_data[c].get(vintage, {}).get("retired", 0)
            for c in CHAINS
        )

        # Signal logic
        signal = ""
        if verra_issued == 0 and total_minted_all > 0:
            signal = "*** NO VERRA RECORD — GHOST MINT ***"
            findings.append((vintage, "Ghost Mint", total_minted_all))
        elif total_minted_all > verra_issued and verra_issued > 0:
            overflow = total_minted_all - verra_issued
            signal = f"*** OVER-MINTED by {overflow:,.0f} t ***"
            findings.append((vintage, "Over-Minted", overflow))
        elif total_active_all > 0 or total_retired_all > 0:
            signal = "Activity — within limits"

        print(f"{vintage:<10} {verra_issued:<16,} {total_minted_all:<16,.2f} {total_active_all:<14,.2f} {total_retired_all:<14,.2f} {signal}")

        results.append({
            "vintage": vintage,
            "verra_issued": verra_issued,
            "total_minted_all_chains": total_minted_all,
            "total_active_all_chains": total_active_all,
            "total_retired_all_chains": total_retired_all,
            "signal": signal
        })

    # Export
    results_df = pd.DataFrame(results)
    output_file = f"preretirement_sentinel_VCS{project_id}.csv"
    results_df.to_csv(output_file, index=False)

    # Summary
    print(f"\n{'='*75}")
    print(f"SUMMARY — VCS-{project_id}")
    print(f"{'='*75}")
    if findings:
        print(f"\n🔴 {len(findings)} RED FINDING(S):\n")
        for vintage, flag_type, amount in findings:
            print(f"  Vintage {vintage}: {flag_type} — {amount:,.2f} tonnes")
    else:
        print(f"\n🟢 GREEN — No over-minting detected across {len(all_vintages)} vintages")

    print(f"\nResults exported to {output_file}")
    print(f"{'='*75}\n")

# --- RUN ---
if __name__ == "__main__":
    run_preretirement_sentinel("981", VERRA_CSV)
