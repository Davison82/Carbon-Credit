import pandas as pd
import ast
import os
import sys

# --- CONFIG ---
VERRA_CSV = "Verra Database 2026 04.csv"
UNIVERSE_CSV = "tokenisation_universe.csv"

# --- LOAD VERRA BASELINE ---
def load_verra_baseline(verra_df, project_id):
    """
    Extracts vintage issuance amounts for a given project ID from the Verra CSV.
    """
    id_col = next((c for c in verra_df.columns if "project id" in c.lower()), None)
    if not id_col:
        return {}

    mask = verra_df[id_col].astype(str).str.strip().str.fullmatch(
        f"VCS{project_id}", case=False, na=False
    )
    match = verra_df[mask]
    if match.empty:
        return {}

    row = match.iloc[0]

    year_cols = {
        col.strip(): col for col in verra_df.columns
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
def get_project_name(verra_df, project_id):
    id_col = next((c for c in verra_df.columns if "project id" in c.lower()), None)
    name_col = next((c for c in verra_df.columns if "project name" in c.lower()), None)
    if not id_col or not name_col:
        return "Unknown"
    mask = verra_df[id_col].astype(str).str.strip().str.fullmatch(
        f"VCS{project_id}", case=False, na=False
    )
    match = verra_df[mask]
    if match.empty:
        return "Unknown"
    return match.iloc[0][name_col]

# --- RUN SENTINEL FOR ONE PROJECT (OFFLINE) ---
def run_preretirement_sentinel_offline(project_id, universe_df, verra_df, verbose=True):
    project_name = get_project_name(verra_df, project_id)

    if verbose:
        print(f"\n{'='*75}")
        print(f"OFFLINE PRE-RETIREMENT SENTINEL — VCS-{project_id}")
        print(f"Project: {project_name}")
        print(f"Formula: Active Supply + Total Retired = Total Ever Minted")
        print(f"Signal if: Total Ever Minted > Verra Issued")
        print(f"{'='*75}")

    baseline = load_verra_baseline(verra_df, project_id)
    if not baseline:
        if verbose:
            print(f"  No Verra baseline found — skipping")
        return None

    # Filter snapshot data for this VCS project
    proj_tokens = universe_df[
        (universe_df["standard"] == "VCS") & 
        (universe_df["project_id"].astype(str).str.split('.').str[0].str.strip() == str(project_id).strip())
    ].copy()

    # Normalize vintage column to clean YYYY strings
    if not proj_tokens.empty:
        proj_tokens["vintage"] = proj_tokens["vintage"].astype(str).str.split('.').str[0].str.strip()

    # Calculate multi-chain active holdings
    multichain_findings = []
    if not proj_tokens.empty:
        active_tokens = proj_tokens[proj_tokens["active_supply"] > 0]
        vintages_multichain = active_tokens.groupby("vintage")["chain"].nunique()
        vintages_multichain = vintages_multichain[vintages_multichain > 1].index.tolist()

        for vm in vintages_multichain:
            sub = active_tokens[active_tokens["vintage"] == vm]
            active_chains = dict(zip(sub["chain"], sub["active_supply"]))
            multichain_findings.append({
                "vintage": vm,
                "active_chains": active_chains,
                "total_active": sum(active_chains.values())
            })

    # Extract pool contamination
    pool_contamination = {}
    for _, row in proj_tokens.iterrows():
        holdings_str = row.get("pool_holdings", "{}")
        try:
            holdings = ast.literal_eval(holdings_str) if isinstance(holdings_str, str) else holdings_str
        except Exception:
            holdings = {}

        if isinstance(holdings, dict) and holdings:
            key = f"Vintage {row['vintage']} ({row['chain']})"
            if key not in pool_contamination:
                pool_contamination[key] = {}
            for pool_name, amt in holdings.items():
                if amt > 0:
                    pool_contamination[key][pool_name] = amt

    # Aggregate token stats by vintage across all chains
    if not proj_tokens.empty:
        chain_agg = proj_tokens.groupby("vintage").agg(
            retired=('total_retired_tonnes', 'sum'),
            active=('active_supply', 'sum'),
            minted=('total_minted_tonnes', 'sum')
        ).to_dict(orient="index")
    else:
        chain_agg = {}

    clean_chain_keys = {str(k).split('.')[0].strip() for k in chain_agg.keys() if pd.notna(k)}
    clean_base_keys = {str(k).split('.')[0].strip() for k in baseline.keys() if pd.notna(k)}

    all_vintages = sorted(set(clean_chain_keys) | set(clean_base_keys))

    findings = []
    results = []

    if verbose:
        print(f"\n{'Vintage':<10} {'Verra Issued':<16} {'Total Minted':<16} {'Active':<14} {'Retired':<14} {'Signal'}")
        print("-" * 100)

    for vintage in all_vintages:
        verra_issued = baseline.get(vintage, 0)
        v_data = chain_agg.get(vintage, {"retired": 0.0, "active": 0.0, "minted": 0.0})

        total_minted_all = v_data["minted"]
        total_active_all = v_data["active"]
        total_retired_all = v_data["retired"]

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
            print(f"{str(vintage):<10} {verra_issued:<16,} {total_minted_all:<16,.2f} {total_active_all:<14,.2f} {total_retired_all:<14,.2f} {signal}")

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

    # Certificate
    cert = "RED" if (findings or multichain_findings) else "GREEN"

    if verbose:
        if pool_contamination:
            print(f"\n--- POOL CONTAMINATION ---")
            for vintage_chain, pools in sorted(pool_contamination.items()):
                for pool_name, tonnes in pools.items():
                    print(f"  {vintage_chain} → {pool_name}: {tonnes:,.2f} t")

        if multichain_findings:
            print(f"\n--- SIMULTANEOUS MULTI-CHAIN HOLDINGS CHECK ---")
            for f in multichain_findings:
                print(f"  ⚠️  Vintage {f['vintage']}: Active on {len(f['active_chains'])} chains — {f['total_active']:,.4f} t total")
                for chain, supply in f['active_chains'].items():
                    print(f"       {chain}: {supply:,.4f} t")

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
# --- RUN ACROSS ALL PROJECTS (FULL OFFLINE AUDIT) ---
def run_full_offline_audit():
    print("\n" + "="*75)
    print("ONCHAIN AUDIT — 100% OFFLINE PRE-RETIREMENT SENTINEL")
    print("="*75)

    if not os.path.exists(VERRA_CSV):
        print(f"ERROR: Cannot find {VERRA_CSV}")
        return

    if not os.path.exists(UNIVERSE_CSV):
        print(f"ERROR: Cannot find {UNIVERSE_CSV}")
        return

    print(f"Loading Verra database and Snapshot CSV...")
    verra_df = pd.read_csv(VERRA_CSV, low_memory=False)
    universe_df = pd.read_csv(UNIVERSE_CSV)

    vcs_projects = sorted(universe_df[
        universe_df["standard"] == "VCS"
    ]["project_id"].astype(str).unique())

    print(f"Auditing {len(vcs_projects)} tokenised VCS projects offline...\n")

    all_results = []
    red_certs = []
    green_certs = []
    pool_findings = []
    multichain_alerts = []

    for i, project_id in enumerate(vcs_projects):
        result = run_preretirement_sentinel_offline(
            project_id, universe_df, verra_df, verbose=False
        )

        if result is None:
            continue

        cert = result["certificate"]
        findings_count = len(result["findings"])
        pool_count = sum(
            1 for pools in result["pool_contamination"].values()
            for t in pools.values() if t > 0
        )
        multichain_count = len(result["multichain_findings"])

        status_parts = [f"[{i+1}/{len(vcs_projects)}] VCS-{project_id}", cert]
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

    # Export Results
    results_df = pd.DataFrame(all_results)
    results_df.to_csv("full_audit_results.csv", index=False)

    # Summary Output
    print(f"\n{'='*75}")
    print(f"FULL AUDIT COMPLETE (OFFLINE)")
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
                    f"{c}: {s:,.4f}t" for c, s in f['findings']
                )
                print(f"    Vintage {f['vintage']}: {chains}")

    print(f"\nFull results exported to full_audit_results.csv")
    print(f"{'='*75}\n")

# --- MAIN ENTRY POINT ---
if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Single project verbose mode: python PreRetirement_Sentinel.py 981
        verra_df = pd.read_csv(VERRA_CSV, low_memory=False)
        universe_df = pd.read_csv(UNIVERSE_CSV)
        run_preretirement_sentinel_offline(sys.argv[1], universe_df, verra_df, verbose=True)
    else:
        # Full universe offline audit
        run_full_offline_audit()
