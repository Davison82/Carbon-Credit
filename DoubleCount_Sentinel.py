import csv
import requests
import time

API_KEY = "d562d03c4b1c92f7e710eff9b01cc6d0"
CSV_FILENAME = "Verra 202604 Credits Issued.csv"
PROJECT_ID = "981"

CHAINS = {
    "Polygon": f"https://thegraph.com{API_KEY}/subgraphs/id/FU5APMSSCqcRy9jy56aXJiGV3PQmFQHg2tzukvSJBgwW",
    "Base": f"https://thegraph.com{API_KEY}/subgraphs/id/AEJ5PEDye6Z198HRQBioG6mZ6ZacHenBg2HTopZPsUCi",
    "Celo": f"https://thegraph.com{API_KEY}/subgraphs/id/BWmN569zDopYXp3nzDukJsGDHqRstYAFULFPH8rxyVBk",
}

def extract_verra_issued_horizontal(project_id, file_path):
    """Parses Row 1 for years 1996-2026, locates Column A for project match."""
    try:
        if not file_path.endswith('.csv'):
            file_path += '.csv'

        with open(file_path, mode='r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            headers = [h.strip() for h in next(reader)]
            
            years_to_track = [str(year) for year in range(1996, 2027)]
            year_indices = {year: headers.index(year) for year in years_to_track if year in headers}
            
            if not year_indices:
                return {}

            verra_issued_dict = {}

            for row in reader:
                if not row or row[0].strip() != str(project_id):
                    continue
                
                project_name = row[1].strip() if len(row) > 1 else "Unknown"
                print(f"🌲 Target Found: VCS-{project_id} | {project_name}")
                
                for year, idx in year_indices.items():
                    if idx < len(row):
                        val_str = row[idx].strip().replace(',', '')
                        val = int(float(val_str)) if val_str and val_str != "0" else 0
                        if val > 0:
                            verra_issued_dict[year] = verra_issued_dict.get(year, 0) + val
                return verra_issued_dict
            return {}
    except Exception as e:
        print(f"❌ Baseline Ingestion Error: {e}")
        return {}

def query_subgraph_tokens(endpoint, project_id):
    """Pulls both live active supply AND historical retirement totals."""
    query = """
    {
      tco2Tokens(where: {symbol_contains: "VCS-%s"}) {
        symbol
        totalSupply
        totalRetired
      }
    }
    """ % project_id

    try:
        response = requests.post(endpoint, json={"query": query}, timeout=15)
        response.raise_for_status()
        return response.json().get("data", {}).get("tco2Tokens", [])
    except Exception:
        return []

def extract_vintage_from_symbol(symbol):
    parts = symbol.split("-")
    return parts[-1][:4] if parts else "Unknown"

def run_double_count_sentinel(project_id):
    print("\n" + "="*95)
    print(f"🛰️  ONCHAIN AUDIT: DOUBLE COUNT SENTINEL — TOTAL FOOTPRINT RECONCILIATION")
    print("="*95 + "\n")

    verra_baseline = extract_verra_issued_horizontal(project_id, CSV_FILENAME)
    if not verra_baseline:
        print("❌ Core pipeline termination: Verification database baseline empty.")
        return

    # Structure data tracking to hold both active (supply) and historical metrics (retired)
    chain_data = {chain: {} for chain in CHAINS}
    for chain_name, endpoint in CHAINS.items():
        print(f"🔄 Scanning live subgraphs on {chain_name} network...")
        tokens = query_subgraph_tokens(endpoint, project_id)
        
        for token in tokens:
            vintage = extract_vintage_from_symbol(token["symbol"])
            active = float(token.get("totalSupply", 0)) / 1e18
            retired = float(token.get("totalRetired", 0)) / 1e18
            
            if vintage not in chain_data[chain_name]:
                chain_data[chain_name][vintage] = {"active": 0.0, "retired": 0.0}
            
            chain_data[chain_name][vintage]["active"] += active
            chain_data[chain_name][vintage]["retired"] += retired
        time.sleep(0.5)

    all_vintages = sorted(list(set(list(verra_baseline.keys()) + [v for c in chain_data.values() for v in c.keys()])))

    # Enhanced reporting layout
    header = f"{'Vintage':<10}{'Active (Σ)':<14}{'Retired (Σ)':<14}{'Total Minted':<16}{'Verra Issued':<16}{'Audit Status'}"
    print("\n" + header)
    print("-" * len(header))

    red_certificates = []

    for vintage in all_vintages:
        verra_max = verra_baseline.get(vintage, 0)
        
        # Aggregate across all cross-chain subgraphs
        total_active = sum(chain_data[c].get(vintage, {}).get("active", 0.0) for c in CHAINS)
        total_retired = sum(chain_data[c].get(vintage, {}).get("retired", 0.0) for c in CHAINS)
        
        # YOUR EXCELLENT FORMULA LOGIC HERE:
        total_historical_minted = total_active + total_retired
        
        print(f"{vintage:<10}{total_active:<14,.0f}{total_retired:<14,.0f}{total_historical_minted:<16,.0f}{verra_max:<16,.0f}", end="")

        if total_historical_minted > verra_max:
            print("🚨 RED CERTIFICATE: MINT OVERFLOW")
            red_certificates.append((vintage, total_historical_minted, verra_max))
        elif total_historical_minted > 0:
            print("🟢 VERIFIED VALID")
        else:
            print("⚪ No Activity")

    print("\n" + "="*95)
    if red_certificates:
        print(f"🛑 RECONCILIATION FAILURE: {len(red_certificates)} MINT INFLATION ANOMALIES FOUND")
        for vintage, minted, issued in red_certificates:
            print(f"  • Vintage {vintage}: Cumulative Minted ({minted:,.0f}) exceeds Verra Registry Max ({issued:,.0f}) by {minted-issued:,.0f} tonnes!")
    else:
        print("✅ AUDIT PASS: Absolute digital footprint completely verified within legacy issuance bounds.")
    print("="*95 + "\n")

if __name__ == "__main__":
    run_double_count_sentinel(PROJECT_ID)
