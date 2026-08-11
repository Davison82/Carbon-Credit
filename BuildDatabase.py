import sqlite3
import pandas as pd
import os
from datetime import date

DB_PATH = "onchain_audit.db"
UNIVERSE_CSV = "tokenisation_universe.csv"
VERRA_CSV = "Verra Database 2026 04.csv"

KNOWN_POOLS = {
    "0xd838290e877e0188a4a44700463419ed96c16107": "NCT Pool",
    "0x2f800db0fdb5223b3c3f354886d907a671414a7f": "BCT Pool",
    "0xb139c4cc9d20a3618e9a2268d73eff18c496b991": "CHAR Pool",
}

# Finding type -> claim category
CLAIM_MAPPING = {
    "Mismatch Alert": "Claim 1",
    "Ghost Mint": "Claim 2",
    "Pool Contamination": "Claim 3",
    "Speculative Holding": "Claim 4",
}

# All four automated finding outputs
FINDING_CSVS = [
    "full_audit_results.csv",
    "double_count_results.csv",
    "pool_contamination_results.csv",
    "speculative_holding_results.csv",
]


# ============================================================
# DATABASE
# ============================================================

def create_database():
    conn = sqlite3.connect(DB_PATH)

    conn.executescript("""
    CREATE TABLE IF NOT EXISTS projects (
        project_id TEXT PRIMARY KEY,
        project_name TEXT,
        standard TEXT,
        country TEXT,
        project_type TEXT,
        crediting_start TEXT,
        crediting_end TEXT,
        verra_status TEXT,
        verra_total_issued REAL,
        verra_total_retired REAL,
        verra_total_remaining REAL,
        has_tokens INTEGER DEFAULT 0,
        token_count INTEGER DEFAULT 0,
        chains TEXT,
        last_updated TEXT,
        data_source TEXT
    );

    CREATE TABLE IF NOT EXISTS token_contracts (
        contract_address TEXT PRIMARY KEY,
        project_id TEXT,
        vintage TEXT,
        chain TEXT,
        standard TEXT,
        total_retired_t REAL,
        active_supply_t REAL,
        total_minted_t REAL,
        pool_assignment TEXT,
        last_updated TEXT
    );

    CREATE TABLE IF NOT EXISTS verra_vintage_issuance (
        issuance_id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id TEXT,
        vintage TEXT,
        verra_issued REAL,
        last_updated TEXT
    );

    CREATE TABLE IF NOT EXISTS reconciliation (
        reconciliation_id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id TEXT,
        vintage TEXT,
        chain TEXT,
        verra_issued REAL,
        blockchain_retired REAL,
        blockchain_active REAL,
        blockchain_minted REAL,
        retirement_gap REAL,
        minting_gap REAL,
        reconciliation_status TEXT,
        run_date TEXT
    );

    CREATE TABLE IF NOT EXISTS audit_findings (
        finding_id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id TEXT,
        vintage TEXT,
        chain TEXT,
        finding_type TEXT,
        claim_category TEXT,
        finding_detail TEXT,
        tonnes_affected REAL,
        confidence TEXT,
        certificate TEXT,
        date_found TEXT,
        verified_against TEXT,
        notes TEXT
    );

    CREATE TABLE IF NOT EXISTS pool_contamination (
        contamination_id INTEGER PRIMARY KEY AUTOINCREMENT,
        pool_name TEXT,
        pool_contract TEXT,
        project_id TEXT,
        vintage TEXT,
        chain TEXT,
        tonnes_in_pool REAL,
        project_certificate TEXT,
        date_detected TEXT
    );

    CREATE TABLE IF NOT EXISTS audit_log (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_date TEXT,
        projects_in_verra INTEGER,
        projects_tokenised INTEGER,
        token_contracts INTEGER,
        red_count INTEGER,
        green_count INTEGER,
        pool_contaminations INTEGER,
        reconciliation_gaps INTEGER,
        notes TEXT
    );
    """)

    # --------------------------------------------------------
    # MIGRATE EXISTING DATABASE
    # --------------------------------------------------------

    columns = [
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(audit_findings)"
        ).fetchall()
    ]

    if "claim_category" not in columns:
        conn.execute("""
            ALTER TABLE audit_findings
            ADD COLUMN claim_category TEXT
        """)
        conn.commit()
        print("✅ Added claim_category column")

    print("✅ Database schema ready")

    return conn


# ============================================================
# HELPERS
# ============================================================

def safe_float(value):
    try:
        if pd.isna(value):
            return 0.0

        return float(
            str(value)
            .replace(",", "")
            .strip()
        )

    except (ValueError, TypeError):
        return 0.0


# ============================================================
# LOAD VERRA DATA
# ============================================================

def load_verra_data(conn, csv_file):

    if not os.path.exists(csv_file):
        print(f"ERROR: Cannot find {csv_file}")
        return {}

    print("\nLoading Verra CSV...")

    df = pd.read_csv(
        csv_file,
        low_memory=False
    )

    today = date.today().isoformat()

    def find_col(test):
        return next(
            (c for c in df.columns if test(c)),
            None
        )

    id_col = find_col(
        lambda c: c.strip().lower() == "project id"
    )

    name_col = find_col(
        lambda c: "project name" in c.lower()
    )

    status_col = find_col(
        lambda c: "voluntary status" in c.lower()
    )

    country_col = find_col(
        lambda c: c.strip().lower() == "country"
    )

    type_col = find_col(
        lambda c: c.strip().lower() == "type"
    )

    issued_col = find_col(
        lambda c:
            "total credits" in c.lower()
            and "issued" in c.lower()
    )

    retired_col = find_col(
        lambda c:
            "total credits" in c.lower()
            and "retired" in c.lower()
    )

    remaining_col = find_col(
        lambda c:
            "total credits" in c.lower()
            and "remaining" in c.lower()
    )

    year_cols = {
        c.strip(): c
        for c in df.columns
        if (
            c.strip().isdigit()
            and 1990 <= int(c.strip()) <= 2030
        )
    }

    projects = []
    vintages = []
    baselines = {}

    for _, row in df.iterrows():

        raw_id = str(
            row.get(id_col, "")
        ).strip()

        if not raw_id.startswith("VCS"):
            continue

        if raw_id.startswith("VCS-"):
            project_id = raw_id
        else:
            project_id = (
                "VCS-" +
                raw_id.replace("VCS", "", 1)
            )

        projects.append((
            project_id,

            str(
                row.get(name_col, "")
            ).strip()
            if name_col else "",

            "VCS",

            str(
                row.get(country_col, "")
            ).strip()
            if country_col else "",

            str(
                row.get(type_col, "")
            ).strip()
            if type_col else "",

            "",
            "",

            str(
                row.get(status_col, "")
            ).strip()
            if status_col else "",

            safe_float(
                row.get(issued_col, 0)
            ),

            safe_float(
                row.get(retired_col, 0)
            ),

            safe_float(
                row.get(remaining_col, 0)
            ),

            0,
            0,
            "",
            today,
            "Berkeley CSV v2026-04"
        ))

        baseline = {}

        for vintage, col in year_cols.items():

            value = safe_float(
                row[col]
            )

            if value > 0:

                baseline[vintage] = value

                vintages.append((
                    project_id,
                    vintage,
                    value,
                    today
                ))

        baselines[project_id] = baseline

    # Insert projects
    conn.executemany("""
        INSERT OR REPLACE INTO projects (
            project_id,
            project_name,
            standard,
            country,
            project_type,
            crediting_start,
            crediting_end,
            verra_status,
            verra_total_issued,
            verra_total_retired,
            verra_total_remaining,
            has_tokens,
            token_count,
            chains,
            last_updated,
            data_source
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, projects)

    # Refresh vintage issuance
    conn.execute(
        "DELETE FROM verra_vintage_issuance"
    )

    conn.executemany("""
        INSERT INTO verra_vintage_issuance (
            project_id,
            vintage,
            verra_issued,
            last_updated
        )
        VALUES (?,?,?,?)
    """, vintages)

    conn.commit()

    print(
        f"✅ Loaded {len(projects)} Verra projects"
    )

    print(
        f"✅ Loaded {len(vintages)} vintage records"
    )

    return baselines


# ============================================================
# LOAD TOKEN CONTRACTS
# ============================================================

def load_token_contracts(conn, csv_file):

    if not os.path.exists(csv_file):
        print(f"ERROR: Cannot find {csv_file}")
        return

    print("\nLoading token contracts...")

    df = pd.read_csv(
        csv_file,
        low_memory=False
    )

    today = date.today().isoformat()

    records = []

    for _, row in df.iterrows():

        raw_id = str(
            row.get("project_id", "")
        ).split(".")[0].strip()

        if raw_id.startswith("VCS-"):
            project_id = raw_id
        else:
            project_id = (
                "VCS-" +
                raw_id.replace("VCS", "", 1)
            )

        records.append((
            str(
                row.get("contract_address", "")
            ).strip(),

            project_id,

            str(
                row.get("vintage", "")
            ).split(".")[0].strip(),

            str(
                row.get("chain", "")
            ).strip(),

            str(
                row.get("standard", "")
            ).strip(),

            safe_float(
                row.get(
                    "total_retired_tonnes",
                    0
                )
            ),

            safe_float(
                row.get(
                    "active_supply_tonnes",
                    0
                )
            ),

            safe_float(
                row.get(
                    "total_minted_tonnes",
                    0
                )
            ),

            str(
                row.get(
                    "pool_assignment",
                    "Unknown"
                )
            ).strip(),

            today
        ))

    conn.executemany("""
        INSERT OR REPLACE INTO token_contracts (
            contract_address,
            project_id,
            vintage,
            chain,
            standard,
            total_retired_t,
            active_supply_t,
            total_minted_t,
            pool_assignment,
            last_updated
        )
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, records)

    # Update project token information
    conn.execute("""
        UPDATE projects
        SET
            has_tokens = 1,
            token_count = (
                SELECT COUNT(*)
                FROM token_contracts t
                WHERE t.project_id = projects.project_id
            ),
            chains = (
                SELECT GROUP_CONCAT(
                    DISTINCT t.chain
                )
                FROM token_contracts t
                WHERE t.project_id = projects.project_id
            )
        WHERE project_id IN (
            SELECT DISTINCT project_id
            FROM token_contracts
        )
    """)

    conn.commit()

    print(
        f"✅ Loaded {len(records)} token contracts"
    )


# ============================================================
# THREE-WAY RECONCILIATION
# ============================================================

def run_reconciliation(conn, baselines):

    print("\nRunning three-way reconciliation...")

    today = date.today().isoformat()

    conn.execute(
        "DELETE FROM reconciliation"
    )

    rows = conn.execute("""
        SELECT
            project_id,
            vintage,
            chain,
            SUM(total_retired_t),
            SUM(active_supply_t),
            SUM(total_minted_t)
        FROM token_contracts
        WHERE standard = 'VCS'
        GROUP BY
            project_id,
            vintage,
            chain
    """).fetchall()

    results = []
    gaps = 0

    for (
        project_id,
        vintage,
        chain,
        retired,
        active,
        minted
    ) in rows:

        issued = (
            baselines
            .get(project_id, {})
            .get(vintage, 0)
        )

        retirement_gap = (
            retired - issued
            if issued > 0
            else 0
        )

        minting_gap = (
            minted - issued
            if issued > 0
            else 0
        )

        if issued == 0 and minted > 0:

            status = (
                "GHOST — No Verra Record"
            )

            gaps += 1

        elif minted > issued and issued > 0:

            status = (
                f"OVER-MINTED "
                f"+{minting_gap:,.0f}t"
            )

            gaps += 1

        elif retired > issued and issued > 0:

            status = (
                f"OVER-RETIRED "
                f"+{retirement_gap:,.0f}t"
            )

            gaps += 1

        elif minted > 0 and issued > 0:

            percentage = (
                minted / issued
            ) * 100

            status = (
                f"Clean — "
                f"{percentage:.2f}% "
                f"of issued tokenised"
            )

        else:

            status = "No activity"

        results.append((
            project_id,
            vintage,
            chain,
            issued,
            retired,
            active,
            minted,
            retirement_gap,
            minting_gap,
            status,
            today
        ))

    # IMPORTANT:
    # reconciliation_id is AUTOINCREMENT, so we explicitly
    # insert the other 11 columns only.
    conn.executemany("""
        INSERT INTO reconciliation (
            project_id,
            vintage,
            chain,
            verra_issued,
            blockchain_retired,
            blockchain_active,
            blockchain_minted,
            retirement_gap,
            minting_gap,
            reconciliation_status,
            run_date
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, results)

    conn.commit()

    print(
        f"✅ Reconciled "
        f"{len(results)} combinations"
    )

    print(
        f"   Gaps found: {gaps}"
    )

    return gaps


# ============================================================
# FINDING TYPE DETECTION
# ============================================================

def detect_finding_type(row):

    # First use explicit finding_type
    value = str(
        row.get("finding_type", "")
    ).strip()

    for finding_type in CLAIM_MAPPING:

        if (
            value.lower()
            == finding_type.lower()
        ):
            return finding_type

    # Otherwise inspect signal
    signal = str(
        row.get("signal", "")
    ).upper()

    if "MISMATCH" in signal:
        return "Mismatch Alert"

    if (
        "GHOST" in signal
        and "MINT" in signal
    ):
        return "Ghost Mint"

    if (
        "POOL" in signal
        and "CONTAMINATION" in signal
    ):
        return "Pool Contamination"

    if "SPECULATIVE" in signal:
        return "Speculative Holding"

    return None


# ============================================================
# CERTIFICATE DETECTION
# ============================================================

def detect_certificate(row):

    value = str(
        row.get("certificate", "")
    ).strip().upper()

    if value in {
        "RED",
        "GREEN",
        "AMBER"
    }:
        return value

    signal = str(
        row.get("signal", "")
    ).upper()

    if any(
        word in signal
        for word in [
            "GHOST",
            "OVER",
            "MISMATCH",
            "CONTAMINATION",
            "SPECULATIVE"
        ]
    ):
        return "RED"

    return "GREEN"


# ============================================================
# TONNES DETECTION
# ============================================================

def detect_tonnes(row):

    columns = [
        "tonnes_affected",
        "total_minted_all_chains",
        "combined_retired_all_chains",
        "total_retired_tonnes",
        "tonnes_in_pool",
        "speculative_tonnes",
        "affected_tonnes"
    ]

    for column in columns:

        if column in row.index:

            value = safe_float(
                row.get(column, 0)
            )

            if value != 0:
                return value

    return 0.0


# ============================================================
# LOAD AUDIT FINDINGS
# ============================================================

def load_audit_findings(conn):

    print(
        "\nLoading automated audit findings..."
    )

    today = date.today().isoformat()

    # Remove previous automated findings
    # so each run reloads the latest CSV results.
    conn.execute("""
        DELETE FROM audit_findings
        WHERE verified_against = 'Automated'
    """)

    total_loaded = 0

    for csv_file in FINDING_CSVS:

        if not os.path.exists(csv_file):

            print(
                f"⚠️ Not found: {csv_file}"
            )

            continue

        try:

            df = pd.read_csv(
                csv_file,
                low_memory=False
            )

        except Exception as e:

            print(
                f"⚠️ Could not read "
                f"{csv_file}: {e}"
            )

            continue

        file_count = 0

        for _, row in df.iterrows():

            finding_type = (
                detect_finding_type(row)
            )

            # Ignore non-finding rows
            if not finding_type:
                continue

            # Automatically assign Claim 1–4
            claim_category = (
                CLAIM_MAPPING[finding_type]
            )

            project_id = str(
                row.get(
                    "project_id",
                    ""
                )
            ).strip()

            vintage = str(
                row.get(
                    "vintage",
                    ""
                )
            ).strip()

            chain = str(
                row.get(
                    "chain",
                    "All Chains"
                )
            ).strip()

            if (
                not chain
                or chain.lower() == "nan"
            ):
                chain = "All Chains"

            signal = str(
                row.get(
                    "signal",
                    ""
                )
            ).strip()

            detail = (
                signal
                or str(
                    row.get(
                        "finding_detail",
                        ""
                    )
                ).strip()
            )

            tonnes = detect_tonnes(row)

            certificate = (
                detect_certificate(row)
            )

            conn.execute("""
                INSERT INTO audit_findings (
                    project_id,
                    vintage,
                    chain,
                    finding_type,
                    claim_category,
                    finding_detail,
                    tonnes_affected,
                    confidence,
                    certificate,
                    date_found,
                    verified_against,
                    notes
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                project_id,
                vintage,
                chain,
                finding_type,
                claim_category,
                detail,
                tonnes,
                "Signal",
                certificate,
                today,
                "Automated",
                f"Loaded from {csv_file}"
            ))

            file_count += 1
            total_loaded += 1

        print(
            f"  {csv_file}: "
            f"{file_count} finding(s)"
        )

    conn.commit()

    print(
        f"\n✅ Loaded "
        f"{total_loaded} automated findings"
    )

    print("\nClaim mapping:")

    rows = conn.execute("""
        SELECT
            claim_category,
            finding_type,
            COUNT(*)
        FROM audit_findings
        WHERE verified_against = 'Automated'
        GROUP BY
            claim_category,
            finding_type
        ORDER BY
            claim_category
    """).fetchall()

    for claim, finding_type, count in rows:

        print(
            f"  {finding_type} -> "
            f"{claim}: {count}"
        )


# ============================================================
# POOL CONTAMINATION
# ============================================================

def load_pool_contamination(conn):

    print(
        "\nBuilding pool contamination records..."
    )

    today = date.today().isoformat()

    conn.execute(
        "DELETE FROM pool_contamination"
    )

    rows = conn.execute("""
        SELECT
            project_id,
            vintage,
            chain,
            pool_assignment,
            total_retired_t
        FROM token_contracts
        WHERE pool_assignment NOT IN (
            'ERC20 Raw TCO2',
            'Unknown',
            ''
        )
        AND standard = 'VCS'
    """).fetchall()

    records = []

    for (
        project_id,
        vintage,
        chain,
        pool,
        retired
    ) in rows:

        red = conn.execute("""
            SELECT 1
            FROM audit_findings
            WHERE project_id = ?
            AND certificate = 'RED'
            LIMIT 1
        """, (
            project_id,
        )).fetchone()

        certificate = (
            "RED"
            if red
            else "GREEN"
        )

        pool_contract = next(
            (
                address
                for address, name
                in KNOWN_POOLS.items()
                if name == pool
            ),
            ""
        )

        records.append((
            pool,
            pool_contract,
            project_id,
            vintage,
            chain,
            retired,
            certificate,
            today
        ))

    conn.executemany("""
        INSERT INTO pool_contamination (
            pool_name,
            pool_contract,
            project_id,
            vintage,
            chain,
            tonnes_in_pool,
            project_certificate,
            date_detected
        )
        VALUES (?,?,?,?,?,?,?,?)
    """, records)

    conn.commit()

    print(
        f"✅ Loaded "
        f"{len(records)} pool records"
    )


# ============================================================
# DATABASE SUMMARY
# ============================================================

def print_summary(conn, gaps):

    today = date.today().isoformat()

    total = conn.execute("""
        SELECT COUNT(*)
        FROM projects
    """).fetchone()[0]

    tokenised = conn.execute("""
        SELECT COUNT(*)
        FROM projects
        WHERE has_tokens = 1
    """).fetchone()[0]

    contracts = conn.execute("""
        SELECT COUNT(*)
        FROM token_contracts
    """).fetchone()[0]

    findings = conn.execute("""
        SELECT COUNT(*)
        FROM audit_findings
    """).fetchone()[0]

    red = conn.execute("""
        SELECT COUNT(DISTINCT project_id)
        FROM audit_findings
        WHERE certificate = 'RED'
    """).fetchone()[0]

    pool_count = conn.execute("""
        SELECT COUNT(*)
        FROM pool_contamination
    """).fetchone()[0]

    print("\n" + "=" * 65)
    print("ONCHAIN AUDIT — DATABASE SUMMARY")
    print("=" * 65)

    print(
        f"Run date: {today}"
    )

    print(
        f"\nVerra projects:       {total:,}"
    )

    print(
        f"Tokenised projects:   {tokenised:,}"
    )

    print(
        f"Token contracts:      {contracts:,}"
    )

    print(
        f"Reconciliation gaps:  {gaps:,}"
    )

    print(
        f"Audit findings:       {findings:,}"
    )

    print(
        f"RED projects:         {red:,}"
    )

    print(
        f"Pool records:         {pool_count:,}"
    )

    print("\nClaim totals:")

    rows = conn.execute("""
        SELECT
            claim_category,
            COUNT(*),
            SUM(tonnes_affected)
        FROM audit_findings
        GROUP BY claim_category
        ORDER BY claim_category
    """).fetchall()

    for claim, count, tonnes in rows:

        print(
            f"  {claim}: "
            f"{count} findings | "
            f"{tonnes or 0:,.2f}t"
        )

    conn.execute("""
        INSERT INTO audit_log (
            run_date,
            projects_in_verra,
            projects_tokenised,
            token_contracts,
            red_count,
            green_count,
            pool_contaminations,
            reconciliation_gaps,
            notes
        )
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        today,
        total,
        tokenised,
        contracts,
        red,
        max(
            tokenised - red,
            0
        ),
        pool_count,
        gaps,
        "Weekly automated run"
    ))

    conn.commit()

    print("=" * 65)


# ============================================================
# QUERY SINGLE PROJECT
# ============================================================

def query_project(conn, project_id):

    print("\n" + "=" * 65)
    print(
        f"PROJECT AUDIT STATUS — "
        f"{project_id}"
    )
    print("=" * 65)

    project = conn.execute("""
        SELECT *
        FROM projects
        WHERE project_id = ?
    """, (
        project_id,
    )).fetchone()

    if not project:

        print(
            "Project not found"
        )

        return

    print(
        f"\nName:      {project[1]}"
    )

    print(
        f"Country:   {project[3]}"
    )

    print(
        f"Type:      {project[4]}"
    )

    print(
        f"Status:    {project[7]}"
    )

    print(
        f"Issued:    {project[8]:,.0f}t"
    )

    print(
        f"Retired:   {project[9]:,.0f}t"
    )

    print(
        f"Remaining: {project[10]:,.0f}t"
    )

    findings = conn.execute("""
        SELECT
            vintage,
            finding_type,
            claim_category,
            tonnes_affected,
            confidence,
            certificate
        FROM audit_findings
        WHERE project_id = ?
        ORDER BY
            certificate,
            claim_category
    """, (
        project_id,
    )).fetchall()

    if findings:

        print("\nAUDIT FINDINGS:")

        for (
            vintage,
            finding,
            claim,
            tonnes,
            confidence,
            cert
        ) in findings:

            emoji = (
                "🔴"
                if cert == "RED"
                else "🟢"
            )

            print(
                f"  {emoji} "
                f"{finding} "
                f"({claim}) | "
                f"Vintage {vintage} | "
                f"{tonnes:,.2f}t | "
                f"{confidence}"
            )

    else:

        print(
            "\n🟢 No findings"
        )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    print(
        "\n" + "=" * 65
    )

    print(
        "ONCHAIN AUDIT — "
        "BUILDING DATABASE"
    )

    print(
        "=" * 65
    )

    conn = create_database()

    try:

        # Step 1 — Verra registry
        baselines = load_verra_data(
            conn,
            VERRA_CSV
        )

        # Step 2 — Blockchain universe
        load_token_contracts(
            conn,
            UNIVERSE_CSV
        )

        # Step 3 — Three-way reconciliation
        gaps = run_reconciliation(
            conn,
            baselines
        )

        # Step 4 — Load all four audit outputs
        load_audit_findings(
            conn
        )

        # Step 5 — Pool contamination
        load_pool_contamination(
            conn
        )

        # Step 6 — Summary
        print_summary(
            conn,
            gaps
        )

        # Optional example project queries
        query_project(
            conn,
            "VCS-981"
        )

        query_project(
            conn,
            "VCS-476"
        )

    finally:

        conn.close()

    print(
        f"\n✅ Database saved to "
        f"{DB_PATH}"
    )

    print(
        f"Query anytime: "
        f"sqlite3 {DB_PATH}"
    )
