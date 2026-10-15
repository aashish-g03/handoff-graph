"""Backfill issue bodies (truncated to 4000 chars) for the issues in the raw dump. Uses `gh` auth."""
import json, subprocess, sys, concurrent.futures as cf
raw = sys.argv[1]; out = sys.argv[2]
nums = [i["number"] for i in json.load(open(raw))]
def batch(ns):
    q = "query{repository(owner:\"microsoft\",name:\"vscode\"){" + " ".join(f"i{n}:issue(number:{n}){{number body}}" for n in ns) + "}}"
    for _ in range(3):
        r = subprocess.run(["gh", "api", "graphql", "-f", f"query={q}"], capture_output=True, text=True)
        try:
            d = json.loads(r.stdout)["data"]["repository"]
            return {v["number"]: (v["body"] or "")[:4000] for v in d.values() if v}
        except Exception:
            continue
    return {}
chunks = [nums[i:i + 50] for i in range(0, len(nums), 50)]
bodies = {}
with cf.ThreadPoolExecutor(4) as ex:
    for res in ex.map(batch, chunks):
        bodies.update(res)
json.dump(bodies, open(out, "w"))
print(f"bodies fetched: {len(bodies)}/{len(nums)}")
