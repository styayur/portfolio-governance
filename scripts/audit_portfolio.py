#!/usr/bin/env python3
import json, subprocess, sys, time
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "evidence" / "baseline"
OUT.mkdir(parents=True, exist_ok=True)
NOW = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def gh_json(args, paginate=False, allow=(200,)):
    cmd = ["gh", "api"] + args
    if paginate:
        cmd.append("--paginate")
    p = subprocess.run(cmd, text=True, capture_output=True)
    if p.returncode != 0:
        text = p.stderr.strip() or p.stdout.strip()
        return {"_error": text, "_status": p.returncode}
    try:
        return json.loads(p.stdout) if p.stdout.strip() else None
    except json.JSONDecodeError:
        return {"_raw": p.stdout}

def gh_graphql(query, variables=None):
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
    if variables:
        for k, v in variables.items():
            if isinstance(v, bool):
                cmd += ["-F", f"{k}={str(v).lower()}"]
            else:
                cmd += ["-f", f"{k}={v}"]
    p = subprocess.run(cmd, text=True, capture_output=True)
    if p.returncode != 0:
        return {"_error": p.stderr.strip() or p.stdout.strip(), "_status": p.returncode}
    return json.loads(p.stdout)

def endpoint(repo, suffix=""):
    return f"repos/{repo}{suffix}"

repos_resp = gh_json(["user/repos?affiliation=owner&per_page=100"], paginate=True)
if isinstance(repos_resp, dict) and repos_resp.get("_error"):
    raise SystemExit(f"repository enumeration failed: {repos_resp['_error']}")
repos = repos_resp if isinstance(repos_resp, list) else []
public = sorted([r for r in repos if not r.get("private")], key=lambda r: r["name"])
inventory = []
raw = {}
for r in public:
    name = r["full_name"]
    branch = r.get("default_branch", "main")
    item = {
        "id": r["id"],
        "node_id": r.get("node_id"),
        "name": r["name"],
        "full_name": name,
        "visibility": str(r.get("visibility") or "").upper(),
        "private": r.get("private"),
        "fork": r.get("fork"),
        "archived": r.get("archived"),
        "default_branch": branch,
        "description": r.get("description"),
        "homepage": r.get("homepage"),
        "language": (r.get("language") or None),
        "license": ((r.get("license") or {}).get("spdx_id")),
        "has_issues": r.get("has_issues"),
        "has_discussions": r.get("has_discussions"),
        "has_projects": r.get("has_projects"),
        "has_wiki": r.get("has_wiki"),
        "is_template": r.get("is_template"),
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
        "pushed_at": r.get("pushed_at"),
        "size_kb": r.get("size"),
        "permissions": r.get("permissions"),
        "security_and_analysis": r.get("security_and_analysis"),
        "open_issues_count": r.get("open_issues_count"),
        "default_branch_sha": None,
    }
    br = gh_json([endpoint(name, f"/branches/{branch}")])
    if isinstance(br, dict) and not br.get("_error"):
        item["default_branch_sha"] = (br.get("commit") or {}).get("sha")
    pulls = gh_json([endpoint(name, "/pulls?state=open&per_page=100")], paginate=True)
    issues = gh_json([endpoint(name, "/issues?state=open&per_page=100")], paginate=True)
    workflows = gh_json([endpoint(name, "/actions/workflows?per_page=100")], paginate=True)
    rulesets = gh_json([endpoint(name, "/rulesets?includes_parents=true&per_page=100")], paginate=True)
    labels = gh_json([endpoint(name, "/labels?per_page=100")], paginate=True)
    releases = gh_json([endpoint(name, "/releases?per_page=30")], paginate=True)
    tags = gh_json([endpoint(name, "/tags?per_page=30")], paginate=True)
    protection = gh_json([endpoint(name, f"/branches/{branch}/protection")])
    actions_perms = gh_json([endpoint(name, "/actions/permissions")])
    community = gh_json([endpoint(name, "/community/profile")])
    dependabot = gh_json([endpoint(name, "/dependabot/alerts?state=open&per_page=100")], paginate=True)
    secret_scanning = gh_json([endpoint(name, "/secret-scanning/alerts?state=open&per_page=100")], paginate=True)
    code_scanning = gh_json([endpoint(name, "/code-scanning/alerts?state=open&per_page=100")], paginate=True)
    files = {}
    for path in ["AGENTS.md","SECURITY.md","CONTRIBUTING.md","README.md",".github/PULL_REQUEST_TEMPLATE.md",".github/ISSUE_TEMPLATE/config.yml"]:
        files[path] = gh_json([endpoint(name, f"/contents/{path}?ref={branch}")])
    # normalize list responses while preserving exact API errors for audit
    def count_or_error(x):
        if isinstance(x, list): return {"status":"OK","count":len(x)}
        if isinstance(x, dict): return {"status":"ERROR","error":x.get("_error","unknown")}
        return {"status":"EMPTY","count":0}
    gql = gh_graphql("""
      query($owner:String!,$name:String!) {
        repository(owner:$owner,name:$name) {
          id nameWithOwner isArchived visibility
          discussionCategories(first:50) { totalCount nodes { id name slug description isAnswerable } }
          discussions(first:20, orderBy:{field:UPDATED_AT,direction:DESC}) { totalCount nodes { id number title url createdAt updatedAt category {name} author {login} answer {id} } }
        }
      }
    """, {"owner":"styayur","name":r["name"]})
    item["open_prs"] = len(pulls) if isinstance(pulls,list) else None
    item["open_issues"] = len([x for x in issues if "pull_request" not in x]) if isinstance(issues,list) else None
    item["workflows"] = [{"id":w.get("id"),"name":w.get("name"),"path":w.get("path"),"state":w.get("state")} for w in workflows.get("workflows",[])] if isinstance(workflows,dict) and "workflows" in workflows else []
    item["rulesets"] = [{"id":w.get("id"),"name":w.get("name"),"target":w.get("target"),"enforcement":w.get("enforcement"),"source_type":w.get("source_type")} for w in rulesets] if isinstance(rulesets,list) else []
    item["labels"] = sorted([x.get("name") for x in labels]) if isinstance(labels,list) else []
    item["releases"] = [{"id":x.get("id"),"tag_name":x.get("tag_name"),"name":x.get("name"),"draft":x.get("draft"),"prerelease":x.get("prerelease"),"published_at":x.get("published_at"),"assets":len(x.get("assets",[]))} for x in releases] if isinstance(releases,list) else []
    item["tags"] = [x.get("name") for x in tags] if isinstance(tags,list) else []
    item["branch_protection"] = "present" if isinstance(protection,dict) and not protection.get("_error") else ("absent" if isinstance(protection,dict) and "Branch not protected" in protection.get("_error","") else "unknown")
    item["actions_permissions"] = actions_perms if isinstance(actions_perms,dict) and not actions_perms.get("_error") else {"status":"unknown"}
    item["dependabot_alerts"] = count_or_error(dependabot)
    item["secret_scanning_alerts"] = count_or_error(secret_scanning)
    item["code_scanning_alerts"] = count_or_error(code_scanning)
    item["files"] = {}
    for path, data in files.items():
        if isinstance(data,dict) and data.get("sha"):
            item["files"][path] = {"sha":data.get("sha"),"size":data.get("size"),"type":data.get("type")}
        else:
            item["files"][path] = {"status":"absent"}
    if isinstance(community,dict) and not community.get("_error"):
        item["community_health"] = {"health_percentage":community.get("health_percentage"),"files":community.get("files")}
    else:
        item["community_health"] = {"status":"unknown"}
    item["discussion_state"] = (gql.get("data",{}).get("repository",{}) if isinstance(gql,dict) else {})
    inventory.append(item)
    raw[name] = {"pulls":pulls,"issues":issues,"workflows":workflows,"rulesets":rulesets,"labels":labels,"releases":releases,"tags":tags,"protection":protection,"actions_permissions":actions_perms,"community":community,"dependabot":dependabot,"secret_scanning":secret_scanning,"code_scanning":code_scanning,"files":files,"discussion_graphql":gql}
    print(f"audited {name}", flush=True)

meta = {"generated_at":NOW,"source":"GitHub API from GitHub Codespace","repo_count":len(inventory),"private_repo_excluded":"styayur/site","auth":{"account":"styayur"}}
(OUT / "portfolio-inventory.json").write_text(json.dumps({"meta":meta,"repositories":inventory},indent=2,ensure_ascii=False)+"\n")
(OUT / "raw-github.json").write_text(json.dumps(raw,indent=2,ensure_ascii=False)+"\n")
print(f"wrote {len(inventory)} repos to {OUT}")
