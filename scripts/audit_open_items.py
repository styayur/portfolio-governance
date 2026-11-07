#!/usr/bin/env python3
import json, subprocess, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/"evidence"/"baseline"
OUT.mkdir(parents=True, exist_ok=True)
now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def run(args):
    p=subprocess.run(args,text=True,capture_output=True)
    return {"ok":p.returncode==0,"stdout":p.stdout,"stderr":p.stderr,"returncode":p.returncode}

def api(path, paginate=False):
    a=["gh","api",path]
    if paginate: a.append("--paginate")
    r=run(a)
    if not r["ok"]: return {"_error":(r["stderr"] or r["stdout"]).strip(),"_returncode":r["returncode"]}
    try:return json.loads(r["stdout"])
    except Exception:return {"_raw":r["stdout"]}

inventory=json.load(open(OUT/"portfolio-inventory.json"))
records=[]
for repo in inventory["repositories"]:
    full=repo["full_name"]
    pulls=api(f"repos/{full}/pulls?state=open&per_page=100",True)
    if not isinstance(pulls,list):
        continue
    for pr in pulls:
        n=pr["number"]; head=pr["head"]["sha"]; base=pr["base"]["sha"]
        rec={
          "repo":full,"repository_id":repo["id"],"number":n,"title":pr["title"],"url":pr["html_url"],
          "draft":pr["draft"],"state":pr["state"],"created_at":pr["created_at"],"updated_at":pr["updated_at"],
          "author":pr["user"]["login"],"base_ref":pr["base"]["ref"],"base_sha":base,"head_ref":pr["head"]["ref"],"head_sha":head,
          "mergeable":pr.get("mergeable"),"rebaseable":pr.get("rebaseable"),"mergeable_state":pr.get("mergeable_state"),
          "additions":pr.get("additions"),"deletions":pr.get("deletions"),"changed_files":pr.get("changed_files"),
          "labels":[x["name"] for x in pr.get("labels",[])]
        }
        rec["files"]=api(f"repos/{full}/pulls/{n}/files?per_page=100",True)
        rec["commits"]=api(f"repos/{full}/pulls/{n}/commits?per_page=100",True)
        rec["reviews"]=api(f"repos/{full}/pulls/{n}/reviews?per_page=100",True)
        rec["review_comments"]=api(f"repos/{full}/pulls/{n}/comments?per_page=100",True)
        rec["issue_comments"]=api(f"repos/{full}/issues/{n}/comments?per_page=100",True)
        rec["check_runs"]=api(f"repos/{full}/commits/{head}/check-runs?per_page=100",True)
        rec["combined_status"]=api(f"repos/{full}/commits/{head}/status")
        diff=run(["gh","pr","diff",str(n),"-R",full])
        rec["diff"]={"ok":diff["ok"],"text":diff["stdout"],"error":(diff["stderr"] or "").strip()}
        records.append(rec)
        print(f"collected {full}#{n}",flush=True)
(OUT/"pr-review-evidence.json").write_text(json.dumps({"generated_at":now,"items":records},indent=2,ensure_ascii=False)+"\n")
print(f"wrote {len(records)} open PRs")
