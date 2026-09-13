"""Read-only SSP capacity and scheduling audit; run with the clusterx Python env.

Unlike clusterx stats, follow pagination and retain unique node identities.
Output only capacity/status fields, never configuration credentials or annotations.
"""

import argparse
import collections
import json
from datetime import datetime, timezone
from pathlib import Path

from clusterx.launcher.ssp.ssp import SSPCluster


def node_summary(client, path):
    records, token, seen = [], None, set()
    while True:
        params = {"page_size": 100}
        if token:
            params["page_token"] = token
        page = client._make_management_request("GET", path, params=params)
        records.extend(page.get("nodes", []))
        token = page.get("next_page_token")
        if not token:
            break
        if token in seen:
            raise RuntimeError("Repeated pagination token")
        seen.add(token)
    nodes = {row.get("uid", row["id"]): row for row in records}
    capacity = collections.defaultdict(lambda: {"total": 0, "allocated": 0, "unallocated": 0})
    fit = []
    for row in nodes.values():
        free = {}
        for resource in row.get("summary_data", []):
            kind = resource["resource_type"]
            for key in capacity[kind]:
                capacity[kind][key] += int(resource.get(key, 0))
            free[kind] = int(resource.get("unallocated", 0))
        if free.get("DEVICE", 0) >= 2 and free.get("CPU", 0) >= 16 and free.get("MEMORY", 0) >= 192:
            fit.append({"node": row["name"], "free": free})
    return {
        "reported_nodes": page.get("total_size"),
        "rows_received": len(records),
        "unique_nodes": len(nodes),
        "capacity": dict(capacity),
        "nodes_fitting_two_gpu_request": fit,
        "count_consistent": page.get("total_size") == len(nodes),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cluster = SSPCluster()
    client, cfg = cluster.client, cluster.cfg
    base = (
        f"/subscriptions/{client.subscription}/resourceGroups/{client.resource_group}"
        f"/regions/{client.region}/clusters/{cfg['cluster']}"
    )
    queue = cfg.get("queue", cfg.get("partition"))
    record = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "cluster": cfg["cluster"],
        "queue": queue,
        "cluster_capacity": node_summary(client, base + "/nodes"),
        "queue_capacity": node_summary(client, base + f"/queues/{queue}/nodes"),
    }
    jobs = []
    for name in ("mmhe-q38-2gpu-0911-a", "mmhe-swe-image-probe-0911"):
        job = client.get_training_job(name)
        spec = job["spec"]
        jobs.append(
            {
                "name": name,
                "status": job["status"],
                "priority": spec["priority"],
                "tasks": [
                    {"replicas": t["replicas"], "resources": t["resource_spec"]}
                    for t in spec["vc_job"]["tasks"]
                ],
            }
        )
    record["own_jobs"] = jobs
    pending = client.list_training_jobs(filter_str='state="PENDING"', page_size=100)
    record["pending"] = {
        "reported_total": pending.get("total_size"),
        "listed": [
            {
                "priority": j["spec"].get("priority"),
                "created": j["status"].get("create_time"),
                "tasks": [
                    {"replicas": t["replicas"], "resources": t["resource_spec"]}
                    for t in j["spec"]["vc_job"]["tasks"]
                ],
            }
            for j in pending.get("training_jobs", [])
        ],
    }
    record["limitations"] = [
        "Node pages are not an atomic snapshot; report count discrepancies.",
        "Free capacity is not a guarantee of schedulability.",
        "Pending state does not identify a scheduler rejection reason.",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2) + "\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "cluster_nodes": record["cluster_capacity"]["unique_nodes"],
                "cluster_gpu": record["cluster_capacity"]["capacity"].get("DEVICE"),
                "queue_nodes": record["queue_capacity"]["unique_nodes"],
                "queue_gpu": record["queue_capacity"]["capacity"].get("DEVICE"),
            }
        )
    )


if __name__ == "__main__":
    main()
