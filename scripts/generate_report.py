import os
from datetime import datetime

import pandas as pd

from src.utils.database import db

REPORT_DIR = "reports"


def generate_report():
    """
    Aggregates historical cycle data and generates an industrial reliability report.
    """
    if not os.path.exists(REPORT_DIR):
        os.makedirs(REPORT_DIR)

    all_cycles = db.get_recent_cycles_with_details(limit=1000)

    if not all_cycles:
        print("No historical cycles found in Evidence Store to report.")
        return

    df = pd.DataFrame(all_cycles)

    # Analysis Summary
    total_cycles = len(df)
    # Check for event column and count non-NORMAL values
    if "event" in df.columns:
        fault_count = len(df[df["event"].notna() & (df["event"] != "NORMAL")])
    else:
        fault_count = 0

    critical_count = len(df[df["severity"] == "CRITICAL"]) if "severity" in df.columns else 0

    report_name = f"Velqron_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    report_path = os.path.join(REPORT_DIR, report_name)

    with open(report_path, "w") as f:
        f.write("# Velqron Industrial Reliability Report\n")
        f.write(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        f.write("## Executive Summary\n")
        f.write(f"- **Total Cycles Monitored:** {total_cycles}\n")
        f.write(f"- **Total Anomalies Detected:** {fault_count}\n")
        f.write(f"- **Critical Interventions:** {critical_count}\n")
        f.write(
            f"- **System Availability:** {((total_cycles - critical_count) / total_cycles) * 100:.1f}%\n\n"
        )

        f.write("## Recent Incident Log\n")
        f.write("| Timestamp | Event | Severity | Action |\n")
        f.write("|---|---|---|---|\n")

        # Sort by timestamp (if available) or index
        recent = df.tail(10).iloc[::-1]
        for _, row in recent.iterrows():
            event = row.get("event", "NORMAL")
            severity = row.get("severity", "NONE")
            action = row.get("recommendation", "None")
            timestamp = row.get("timestamp", "N/A")
            f.write(f"| {timestamp} | {event} | {severity} | {action} |\n")

    print(f"Report generated successfully: {report_path}")


if __name__ == "__main__":
    generate_report()
