import pandas as pd
import os
import sys

# --- CONFIG ---
UNIVERSE_CSV = "tokenisation_universe.csv"
VERRA_CSV = "Verra Database 2026 04.csv"

# --- LOAD VERRA BASELINE ---
def load_verra_baseline(verra_df, project_id):
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

# --- RUN DOUBLE COUNT SENTINEL FOR ONE PROJECT ---
def run_double_count_sentinel(project_id, universe_df, verra_df, verbose=True):

    project_name = get_project_name(verra_df, project_id)

    if verbose:
        print(f"\n{'='*75}")
        print(f"DOUBLE COUNT SENTINEL — VCS-{project_id}")
        print(f"Project: {project_name}")
        print("Method: Cross-chain retirement totals vs KNOWN Verra issuance")
        print("Signal if: Combined retired (all chains) > KNOWN Verra issued")
        print("Ghost Mint / missing issuance is handled by PreRetirement")
        print(f"{'='*75}")

    # Load Verra baseline
    baseline = load_verra_baseline(verra_df, project_id)
    if not baseline and verbose:
        print(f"  No Verra baseline found — continuing with blockchain data only")

    # Filter universe for this project
    proj_tokens = universe_df[
        (universe_df["standard"] == "VCS") &
        (universe_df["project_id"].astype(str).str.split('.').str[0].str.strip() == str(project_id).strip())
    ].copy()

    if proj_tokens.empty:
        if verbose:
            print(f"  No tokens found in universe for VCS-{project_id}")
        return None

    # Normalise vintage to clean 4-digit string
    proj_tokens["vintage"] = proj_tokens["vintage"].astype(str).str.split('.').str[0].str.strip()

    # Aggregate retired tonnes by vintage and chain
    chain_pivot = proj_tokens.groupby(["vintage", "chain"])["total_retired_tonnes"].sum().reset_index()

    # Get all vintages
    all_vintages = sorted(set(
        proj_tokens["vintage"].unique().tolist() +
        list(baseline.keys())
    ))

    chains = sorted(proj_tokens["chain"].unique().tolist())

    findings = []
    results = []

    if verbose:
        # Build header
        header = f"{'Vintage':<10}"
        for chain in chains:
            header += f"{chain:<16}"
        header += f"{'Combined':<16} {'Verra Issued':<16} {'Signal'}"
        print(f"\n{header}")
        print("-" * (10 + 16 * len(chains) + 32 + 20))

    for vintage in all_vintages:
        verra_issued = baseline.get(vintage, 0)
        combined = 0.0
        chain_amounts = {}

        for chain in chains:
            mask = (
                (chain_pivot["vintage"] == vintage) &
                (chain_pivot["chain"] == chain)
            )
            amount = chain_pivot[mask]["total_retired_tonnes"].sum() if mask.any() else 0.0
            chain_amounts[chain] = amount
            combined += amount

        # Signal logic
        signal = ""

        # Only flag over-retirement when there is a KNOWN
        # Verra issuance figure for this vintage.
        #
        # If Verra issuance is zero / unknown, do NOT flag it
        # as Ghost Retirement. That condition is already handled
        # by PreRetirement as Ghost Mint.

        if verra_issued > 0 and combined > verra_issued:
            overflow = combined - verra_issued
            signal = f"*** CROSS-CHAIN OVER-RETIREMENT +{overflow:,.0f} t ***"
            findings.append(
                (vintage, "Cross-Chain Over-Retirement", overflow)
            )

        elif combined > 0 and verra_issued > 0:
            signal = "Within known Verra issuance"

        elif combined > 0 and verra_issued == 0:
            signal = "No known Verra issuance — handled by PreRetirement"

        if verbose:
            row_str = f"{vintage:<10}"
            for chain in chains:
                row_str += f"{chain_amounts.get(chain, 0.0):<16,.2f}"
            row_str += f"{combined:<16,.2f} {verra_issued:<16,} {signal}"
            print(row_str)

        results.append({
            "project_id": f"VCS-{project_id}",
            "project_name": project_name,
            "vintage": vintage,
            "verra_issued": verra_issued,
            "combined_retired_all_chains": round(combined, 4),
            **{f"retired_{chain.lower()}": round(chain_amounts.get(chain, 0.0), 4) for chain in chains},
            "signal": signal if signal else "Clean"
        })

    cert = "RED" if findings else "GREEN"

    if verbose:
        print(f"\n{'='*75}")
        print(f"CERTIFICATE: {cert} — VCS-{project_id} {project_name}")
        if findings:
            for vintage, flag_type, amount in findings:
                print(f"  🔴 Vintage {vintage}: {flag_type} — {amount:,.2f} t")
        else:
            print(f"  🟢 No cross-chain over-retirement against known issuance detected")
        print(f"{'='*75}\n")

    return {
        "project_id": f"VCS-{project_id}",
        "project_name": project_name,
        "certificate": cert,
        "findings": findings,
        "results": results
    }

# --- RUN FULL AUDIT ---
def run_full_audit():
    print("\n" + "="*75)
    print("DOUBLE COUNT SENTINEL — FULL UNIVERSE AUDIT (OFFLINE)")
    print("="*75)

    if not os.path.exists(UNIVERSE_CSV):
        print(f"ERROR: Cannot find {UNIVERSE_CSV} — run MasterTokenisation.py first")
        return

    if not os.path.exists(VERRA_CSV):
        print(f"ERROR: Cannot find {VERRA_CSV}")
        return

    print("Loading data...")
    universe_df = pd.read_csv(UNIVERSE_CSV)
    verra_df = pd.read_csv(VERRA_CSV, low_memory=False)

    vcs_projects = sorted(
        universe_df[universe_df["standard"] == "VCS"]["project_id"]
        .astype(str).str.split('.').str[0].str.strip()
        .unique().tolist()
    )

    print(f"Running double count check across {len(vcs_projects)} projects...\n")

    all_results = []
    red_certs = []
    green_certs = []

    for i, project_id in enumerate(vcs_projects):
        result = run_double_count_sentinel(
            project_id, universe_df, verra_df, verbose=False
        )

        if result is None:
            print(f"[{i+1}/{len(vcs_projects)}] VCS-{project_id} — No tokens found")
            continue

        cert = result["certificate"]
        findings_count = len(result["findings"])

        status = f"[{i+1}/{len(vcs_projects)}] VCS-{project_id} — {cert}"
        if findings_count:
            status += f" | {findings_count} finding(s)"
        print(status)

        all_results.extend(result["results"])

        if cert == "RED":
            red_certs.append({
                "id": project_id,
                "name": result["project_name"],
                "findings": result["findings"]
            })
        else:
            green_certs.append(project_id)

    # Export
    if all_results:
        results_df = pd.DataFrame(all_results)
        results_df.to_csv("double_count_results.csv", index=False)

    # Summary
    print(f"\n{'='*75}")
    print(f"DOUBLE COUNT SENTINEL — COMPLETE")
    print(f"{'='*75}")
    print(f"Projects audited: {len(red_certs) + len(green_certs)}")
    print(f"🔴 RED CERTIFICATES: {len(red_certs)}")
    print(f"🟢 GREEN CERTIFICATES: {len(green_certs)}")

    if red_certs:
        print(f"\n🔴 RED CERTIFICATE DETAILS:")
        for r in red_certs:
            print(f"\n  VCS-{r['id']} — {r['name']}")
            for vintage, flag_type, amount in r['findings']:
                print(f"    Vintage {vintage}: {flag_type} — {amount:,.2f} t")

    print(f"\nResults exported to double_count_results.csv")
    print(f"{'='*75}\n")

# --- MAIN ---
if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Single project verbose: python DoubleCount_Sentinel.py 981
        universe_df = pd.read_csv(UNIVERSE_CSV)
        verra_df = pd.read_csv(VERRA_CSV, low_memory=False)
        run_double_count_sentinel(sys.argv[1], universe_df, verra_df, verbose=True)
    else:
        # Full audit
        run_full_audit()
