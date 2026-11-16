"""Classic OS algorithms as small, testable functions (used by the OS Lab tab).

  simulate_cpu    : FCFS, SJF, SRTF, Priority, Round Robin  -> Gantt chart + waiting / turnaround / response times
  simulate_paging : FIFO, LRU, Optimal page replacement      -> frame table + page-fault count
In this project "processes" are payment jobs and "pages" are cached wallet balances.
"""
POLICIES = {
    "FCFS": "First-Come First-Served",
    "SJF": "Shortest Job First (non-preemptive)",
    "SRTF": "Shortest Remaining Time First (preemptive)",
    "PRIORITY": "Priority (non-preemptive, 1 = highest)",
    "RR": "Round Robin",
}


def simulate_cpu(jobs: list, policy: str = "FCFS", quantum: int = 2) -> dict:
    policy = str(policy).upper()
    if policy not in POLICIES:
        raise ValueError("Unknown scheduling policy.")
    if not 1 <= len(jobs) <= 12:
        raise ValueError("Use between 1 and 12 jobs.")
    procs, seen = [], set()
    for i, j in enumerate(jobs):
        pid = str(j.get("pid") or f"P{i + 1}")[:8]
        if pid in seen or pid == "idle":
            raise ValueError("Process names must be unique.")
        seen.add(pid)
        try:
            arrival, burst, prio = int(j.get("arrival", 0)), int(j.get("burst", 1)), int(j.get("priority", 1))
        except (TypeError, ValueError):
            raise ValueError("Arrival, burst and priority must be whole numbers.")
        if not (0 <= arrival <= 100 and 1 <= burst <= 50 and 1 <= prio <= 9):
            raise ValueError("Use arrival 0-100, burst 1-50 and priority 1-9.")
        procs.append({"pid": pid, "arrival": arrival, "burst": burst, "priority": prio, "idx": i})
    quantum = max(1, min(int(quantum or 2), 20))
    by = {p["pid"]: p for p in procs}
    remaining = {p["pid"]: p["burst"] for p in procs}
    waiting, admitted = [], set()          # `waiting` never contains the running process
    done, first, gantt = {}, {}, []
    t, current, used = 0, None, 0
    keys = {
        "FCFS": lambda pid: (by[pid]["arrival"], by[pid]["idx"]),
        "SJF": lambda pid: (by[pid]["burst"], by[pid]["arrival"], by[pid]["idx"]),
        "PRIORITY": lambda pid: (by[pid]["priority"], by[pid]["arrival"], by[pid]["idx"]),
        "SRTF": lambda pid: (remaining[pid], by[pid]["arrival"], by[pid]["idx"]),
    }
    for _ in range(20000):
        if len(done) == len(procs):
            break
        for p in sorted(procs, key=lambda p: (p["arrival"], p["idx"])):          # admit new arrivals
            if p["arrival"] <= t and p["pid"] not in admitted:
                admitted.add(p["pid"])
                waiting.append(p["pid"])
        if policy == "RR":
            if current is not None and used >= quantum:
                waiting.append(current)                                           # time slice over -> back of queue
                current = None
            if current is None and waiting:
                current, used = waiting.pop(0), 0
        elif policy == "SRTF":
            cands = waiting + ([current] if current else [])
            if cands:
                nxt = min(cands, key=keys["SRTF"])
                if nxt != current:
                    if current is not None:
                        waiting.append(current)
                    waiting.remove(nxt)
                    current = nxt
        elif current is None and waiting:
            current = min(waiting, key=keys[policy])
            waiting.remove(current)
        pid = current or "idle"
        if gantt and gantt[-1]["pid"] == pid and gantt[-1]["end"] == t:
            gantt[-1]["end"] = t + 1
        else:
            gantt.append({"pid": pid, "start": t, "end": t + 1})
        if current is not None:
            first.setdefault(current, t)
            remaining[current] -= 1
            used += 1
            if remaining[current] == 0:
                done[current] = t + 1
                current, used = None, 0
        t += 1
    else:
        raise ValueError("Simulation did not finish - check the inputs.")
    rows = []
    for p in procs:
        c = done[p["pid"]]
        rows.append({"pid": p["pid"], "arrival": p["arrival"], "burst": p["burst"], "priority": p["priority"],
                     "completion": c, "turnaround": c - p["arrival"], "waiting": c - p["arrival"] - p["burst"],
                     "response": first[p["pid"]] - p["arrival"]})
    n = len(rows)
    busy = sum(g["end"] - g["start"] for g in gantt if g["pid"] != "idle")
    runs = [g for g in gantt if g["pid"] != "idle"]
    return {"policy": policy, "policy_name": POLICIES[policy], "quantum": quantum if policy == "RR" else None,
            "gantt": gantt, "processes": rows, "total_time": t,
            "avg_waiting": round(sum(r["waiting"] for r in rows) / n, 2),
            "avg_turnaround": round(sum(r["turnaround"] for r in rows) / n, 2),
            "avg_response": round(sum(r["response"] for r in rows) / n, 2),
            "cpu_utilization": round(100 * busy / t, 1), "context_switches": max(0, len(runs) - 1)}


def simulate_paging(refs: list, frames: int, algo: str = "LRU") -> dict:
    algo = str(algo).upper()
    if algo not in ("FIFO", "LRU", "OPT"):
        raise ValueError("Choose FIFO, LRU or OPT.")
    try:
        refs = [int(r) for r in refs]
        frames = int(frames)
    except (TypeError, ValueError):
        raise ValueError("The reference string and frame count must be whole numbers.")
    if not 1 <= len(refs) <= 40 or not all(0 <= r <= 99 for r in refs):
        raise ValueError("Use 1 to 40 page numbers between 0 and 99.")
    if not 1 <= frames <= 8:
        raise ValueError("Use between 1 and 8 frames.")
    mem, order, last_used, steps, faults = [], [], {}, [], 0
    for i, r in enumerate(refs):
        fault, evicted = r not in mem, None
        if fault:
            faults += 1
            if len(mem) < frames:
                mem.append(r)
            else:
                if algo == "FIFO":
                    victim = order.pop(0)
                elif algo == "LRU":
                    victim = min(mem, key=lambda pg: last_used[pg])
                else:                                                             # OPT: page used farthest in the future
                    def next_use(pg):
                        try:
                            return refs.index(pg, i + 1)
                        except ValueError:
                            return float("inf")
                    victim = max(mem, key=next_use)
                mem[mem.index(victim)] = r
                evicted = victim
            order.append(r)
        last_used[r] = i
        steps.append({"ref": r, "frames": mem + [None] * (frames - len(mem)), "fault": fault, "evicted": evicted})
    n = len(refs)
    return {"algo": algo, "frames": frames, "faults": faults, "hits": n - faults,
            "fault_rate": round(faults / n, 3), "steps": steps}


def compare_paging(refs: list, frames: int) -> dict:
    out = {a: simulate_paging(refs, frames, a) for a in ("FIFO", "LRU", "OPT")}
    return {a: {"faults": r["faults"], "hits": r["hits"]} for a, r in out.items()}
