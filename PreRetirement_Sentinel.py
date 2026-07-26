import requests
import pandas as pd
import time
import os
import sys

# --- CONFIG ---
API_KEY = "d562d03c4b1c92f7e710eff9b01cc6d0"

CHAINS = {
    "Polygon": f"https://gateway-arbitrum.network.thegraph.com/api/{API_KEY}/subgraphs/id/FU5APMSSCqcRy9jy56aXJiGV3PQmFQHg2tzukvSJBgwW",
    "Base":    f"https://gateway-arbitrum.network.thegraph.com/api/{API_KEY}/subgraphs/id/AEJ5PEDye6Z198HRQBioG6mZ6ZacHenBg2HTopZPsUCi",
    "Celo":    f"https://gateway-arbitrum.network.thegraph.com/api/{API_KEY}/subgraphs/id/BWmN569zDopYXp3nzDukJsGDHqRstYAFULFPH8rxyVBk",
}

VERRA_CSV = "Verra Database 2026 04.csv"
UNIVERSE_CSV = "tokenisation_universe.csv"

# Known pool contract addresses
KNOWN_POOLS = {
    "0xd838290e877e0188a4a44700463419ed96c16107": "NCT Pool",
    "0x2f800db0fdb5223b3c3f354886d907a671414a7f": "BCT Pool",
    "0xb139c4cc9d20a3618e9a2268d73eff18c496b991": "CHAR Pool",
}

# --- LOAD VERRA BASELINE ---
def load_verra_baseline(df, project_id):
    id_col = next((c for c in df.columns if "project id" in c.lower()), None)
    if not id_col:
        return {}

    mask = df[id_col].astype(str).str.strip().str.fullmatch(
        f"VCS{project_id}", case=False, na=False
    )
    match = df[mask]
    if match.empty:
        return {}

    row = match.iloc[0]

    year_cols = {
        col.strip(): col for col in df.columns
        if col.strip().isdigit() and 1990 <= int(col.strip()) <= 2030
    }

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

# --- GET PROJECT NAME ---
def get_project_name(df, project_id):
    id_col = next((c for c in df.columns if "project id" in c.lower()), None)
    name_col = next((c for c in df.columns if "project name" in c.lower()), None)
    if not id_col or not name_col:
        return "Unknown"
    mask = df[id_col].astype(str).str.strip().str.fullmatch(
        f"VCS{project_id}", case=False, na=False
    )
    match = df[mask]
    if match.empty:
        return "Unknown"
    return match.iloc[0][name_col]

# --- GET ACTIVE SUPPLY WITH POOL DETECTION ---
def get_active_supply(endpoint, contract_address):
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

        total = 0
        pool_holdings = {}

        for b in balances:
            bal = int(b.get("balance", 0))
            total += bal
            holder = b.get("user", {}).get("id", "").lower()
            for pool_addr, pool_name in KNOWN_POOLS.items():
                if holder == pool_addr.lower():
                    pool_holdings[pool_name] = bal / 1e18

        return total / 1e18, pool_holdings

    except Exception as e:
        return 0.0, {}

# --- GET PROJECT TOKENS ---
def get_project_tokens(endpoint, project_id):
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
        return []

def extract_vintage(symbol):
    parts = symbol.split("-")
    return parts[-1][:4] if len(parts) >= 4 else "unknown"

# --- SIMULTANEOUS MULTI-CHAIN HOLDINGS CHECK ---
def check_simultaneous_multichain_holdings(project_id, verbose=True):
    """
    Checks if the same vintage has non-zero active supply
    on multiple chains simultaneously — potential double minting.
    """
    if verbose:
        print(f"\n--- SIMULTANEOUS MULTI-CHAIN HOLDINGS CHECK ---")

    vintage_chain_supply = {}

    for chain_name, endpoint in CHAINS.items():
        tokens = get_project_tokens(endpoint, project_id)

        for token in tokens:
            vintage = extract_vintage(token["symbol"])
            contract = token["id"]
            active, _ = get_active_supply(endpoint, contract)

            if vintage not in vintage_chain_supply:
                vintage_chain_supply[vintage] = {}
            vintage_chain_supply[vintage][chain_name] = active
            time.sleep(0.3)

    findings = []

    for vintage, chain_supplies in sorted(vintage_chain_supply.items()):
        active_chains = {
            chain: supply
            for chain, supply in chain_supplies.items()
            if supply > 0
        }

        if len(active_chains) > 1:
            total_active = sum(active_chains.values())
            if verbose:
                print(f"  ⚠️  Vintage {vintage}: Active on {len(active_chains)} chains — {total_active:,.4f} t total")
                for chain, supply in active_chains.items():
                    print(f"       {chain}: {supply:,.4f} t")
            findings.append({
                "vintage": vintage,
                "active_chains": active_chains,
                "total_active": total_active
            })
        else:
            if active_chains and verbose:
                chain = list(active_chains.keys())[0]
                supply = list(active_chains.values())[0]
                print(f"  ✅  Vintage {vintage}: Single chain ({chain}: {supply:,.4f} t)")
            elif verbose:
                print(f"  ✅  Vintage {vintage}: Zero active supply")

    if not findings and verbose:
        print(f"  No simultaneous multi-chain holdings detected")

    return findings

# --- RUN SENTINEL FOR ONE PROJECT ---
def run_preretirement_sentinel(project_id, verra_df, verbose=True):

    project_name = get_project_name(verra_df, project_id)

    if verbose:
        print(f"\n{'='*75}")
        print(f"PRE-RETIREMENT SENTINEL — VCS-{project_id}")
        print(f"Project: {project_name}")
        print(f"Formula: Active Supply + Total Retired = Total Ever Minted")
        print(f"Signal if: Total Ever Minted > Verra Issued")
        print(f"{'='*75}")

    baseline = load_verra_baseline(verra_df, project_id)
    if not baseline:
        if verbose:
            print(f"  No Verra baseline found — skipping")
        return None

    if verbose:
        print(f"\nVerra baseline: {len(baseline)} vintages")
        for vintage, issued in sorted(baseline.items()):
            print(f"  {vintage}: {issued:,} issued")

    chain_data = {}
    pool_contamination = {}

    for chain_name, endpoint in CHAINS.items():
        tokens = get_project_tokens(endpoint, project_id)
        chain_data[chain_name] = {}

        for token in tokens:
            vintage = extract_vintage(token["symbol"])
            contract = token["id"]
            retired = int(token.get("totalRetired", 0)) / 1e18
            active, pool_holdings = get_active_supply(endpoint, contract)
            total_minted = retired + active

            if vintage not in chain_data[chain_name]:
                chain_data[chain_name][vintage] = {
                    "retired": 0.0,
                    "active": 0.0,
                    "total_minted": 0.0
                }

            chain_data[chain_name][vintage]["retired"] += retired
            chain_data[chain_name][vintage]["active"] += active
            chain_data[chain_name][vintage]["total_minted"] += total_minted

            # Record pool contamination with pool name and vintage
            for pool_name, pool_tonnes in pool_holdings.items():
                key = f"Vintage {vintage} ({chain_name})"
                if key not in pool_contamination:
                    pool_contamination[key] = {}
                pool_contamination[key][pool_name] = pool_tonnes

            time.sleep(0.3)

        time.sleep(0.5)

    # Build results table
    all_vintages = sorted(set(
        v for chain in chain_data.values() for v in chain.keys()
    ) | set(baseline.keys()))

    findings = []
    results = []

    if verbose:
        print(f"\n{'Vintage':<10} {'Verra Issued':<16} {'Total Minted':<16} {'Active':<14} {'Retired':<14} {'Signal'}")
        print("-" * 100)

    for vintage in all_vintages:
        verra_issued = baseline.get(vintage, 0)

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

        signal = ""
        if verra_issued == 0 and total_minted_all > 0:
            signal = "*** GHOST MINT — NO VERRA RECORD ***"
            findings.append((vintage, "Ghost Mint", total_minted_all))
        elif total_minted_all > verra_issued and verra_issued > 0:
            overflow = total_minted_all - verra_issued
            signal = f"*** OVER-MINTED +{overflow:,.0f} t ***"
            findings.append((vintage, "Over-Minted", overflow))
        elif total_active_all > 0 or total_retired_all > 0:
            signal = "Within limits"

        if verbose:
            print(f"{vintage:<10} {verra_issued:<16,} {total_minted_all:<16,.2f} {total_active_all:<14,.2f} {total_retired_all:<14,.2f} {signal}")

        results.append({
            "project_id": f"VCS-{project_id}",
            "project_name": project_name,
            "vintage": vintage,
            "verra_issued": verra_issued,
            "total_minted_all_chains": round(total_minted_all, 4),
            "total_active_all_chains": round(total_active_all, 4),
            "total_retired_all_chains": round(total_retired_all, 4),
            "signal": signal if signal else "Clean"
        })

    # Pool contamination report
    if verbose and pool_contamination:
        print(f"\n--- POOL CONTAMINATION ---")
        for vintage_chain, pools in sorted(pool_contamination.items()):
            for pool_name, tonnes in pools.items():
                if tonnes > 0:
                    print(f"  {vintage_chain} → {pool_name}: {tonnes:,.2f} t")

    # Simultaneous multi-chain holdings check
    multichain_findings = check_simultaneous_multichain_holdings(
        project_id, verbose=verbose
    )

    # Certificate
    cert = "RED" if (findings or multichain_findings) else "GREEN"

    if verbose:
        print(f"\n{'='*75}")
        print(f"CERTIFICATE: {cert} — VCS-{project_id} {project_name}")
        if findings:
            print(f"\nMINTING FINDINGS:")
            for vintage, flag_type, amount in findings:
                print(f"  🔴 Vintage {vintage}: {flag_type} — {amount:,.2f} t")
        if multichain_findings:
            print(f"\nMULTI-CHAIN HOLDINGS:")
            for f in multichain_findings:
                print(f"  ⚠️  Vintage {f['vintage']}: {f['total_active']:,.4f} t active across {len(f['active_chains'])} chains")
        if not findings and not multichain_findings:
            print(f"  🟢 No anomalies detected")
        print(f"{'='*75}\n")

    return {
        "project_id": f"VCS-{project_id}",
        "project_name": project_name,
        "certificate": cert,
        "findings": findings,
        "multichain_findings": multichain_findings,
        "pool_contamination": pool_contamination,
        "results": results
    }

# --- RUN ACROSS ALL PROJECTS ---
def run_full_audit():
    print("\n" + "="*75)
    print("ONCHAIN AUDIT — FULL UNIVERSE PRE-RETIREMENT SENTINEL")
    print("="*75)

    if not os.path.exists(VERRA_CSV):
        print(f"ERROR: Cannot find {VERRA_CSV}")
        return

    print(f"Loading Verra database...")
    verra_df = pd.read_csv(VERRA_CSV, low_memory=False)
    print(f"Loaded {len(verra_df)} projects\n")

    if not os.path.exists(UNIVERSE_CSV):
        print(f"ERROR: Cannot find {UNIVERSE_CSV}")
        return

    universe = pd.read_csv(UNIVERSE_CSV)
    vcs_projects = sorted(universe[
        universe["standard"] == "VCS"
    ]["project_id"].unique())

    print(f"Auditing {len(vcs_projects)} tokenised VCS projects...\n")

    all_results = []
    red_certs = []
    green_certs = []
    pool_findings = []
    multichain_alerts = []

    for i, project_id in enumerate(vcs_projects):
        print(f"[{i+1}/{len(vcs_projects)}] VCS-{project_id}...", end=" ", flush=True)

        result = run_preretirement_sentinel(
            project_id, verra_df, verbose=False
        )

        if result is None:
            print("No baseline — skipped")
            continue

        cert = result["certificate"]
        findings_count = len(result["findings"])
        pool_count = sum(
            1 for pools in result["pool_contamination"].values()
            for t in pools.values() if t > 0
        )
        multichain_count = len(result["multichain_findings"])

        status_parts = [cert]
        if findings_count:
            status_parts.append(f"{findings_count} mint findings")
        if pool_count:
            status_parts.append(f"{pool_count} pool contaminations")
        if multichain_count:
            status_parts.append(f"{multichain_count} multi-chain alerts")

        print(" | ".join(status_parts))

        all_results.extend(result["results"])

        if cert == "RED":
            red_certs.append({
                "id": project_id,
                "name": result["project_name"],
                "findings": result["findings"],
                "multichain": result["multichain_findings"]
            })
        else:
            green_certs.append(project_id)

        if result["pool_contamination"]:
            pool_findings.append({
                "project_id": f"VCS-{project_id}",
                "name": result["project_name"],
                "contaminations": result["pool_contamination"]
            })

        if result["multichain_findings"]:
            multichain_alerts.append({
                "project_id": f"VCS-{project_id}",
                "name": result["project_name"],
                "findings": result["multichain_findings"]
            })

        time.sleep(1)

    # Export
    results_df = pd.DataFrame(all_results)
    results_df.to_csv("full_audit_results.csv", index=False)

    # Summary
    print(f"\n{'='*75}")
    print(f"FULL AUDIT COMPLETE")
    print(f"{'='*75}")
    print(f"Total projects audited: {len(red_certs) + len(green_certs)}")
    print(f"🔴 RED CERTIFICATES: {len(red_certs)}")
    print(f"🟢 GREEN CERTIFICATES: {len(green_certs)}")
    print(f"Pool contaminations found: {len(pool_findings)}")
    print(f"Multi-chain active holdings: {len(multichain_alerts)}")

    if red_certs:
        print(f"\n🔴 RED CERTIFICATE DETAILS:")
        for r in red_certs:
            print(f"\n  VCS-{r['id']} — {r['name']}")
            for vintage, flag_type, amount in r['findings']:
                print(f"    Vintage {vintage}: {flag_type} — {amount:,.2f} t")
            for mf in r['multichain']:
                chains = ", ".join(
                    f"{c}: {s:,.2f}t" for c, s in mf['active_chains'].items()
                )
                print(f"    Multi-chain: Vintage {mf['vintage']} — {chains}")

    if pool_findings:
        print(f"\n🏊 POOL CONTAMINATION DETAILS:")
        for pf in pool_findings:
            print(f"\n  {pf['project_id']} — {pf['name']}")
            for vintage_chain, pools in sorted(pf["contaminations"].items()):
                for pool_name, tonnes in pools.items():
                    if tonnes > 0:
                        print(f"    {vintage_chain} → {pool_name}: {tonnes:,.2f} t")

    if multichain_alerts:
        print(f"\n⚠️  MULTI-CHAIN ACTIVE HOLDINGS:")
        for ma in multichain_alerts:
            print(f"\n  {ma['project_id']} — {ma['name']}")
            for f in ma['findings']:
                chains = ", ".join(
                    f"{c}: {s:,.4f}t" for c, s in f['active_chains'].items()
                )
                print(f"    Vintage {f['vintage']}: {chains}")

    print(f"\nFull results exported to full_audit_results.csv")
    print(f"{'='*75}\n")

# --- MAIN ---
if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Single project verbose mode
        verra_df = pd.read_csv(VERRA_CSV, low_memory=False)
        run_preretirement_sentinel(sys.argv[1], verra_df, verbose=True)
    else:
        # Full universe audit
        run_full_audit()
