import json, subprocess, sys
from pathlib import Path
PROJECT_ID="PVT_kwHOE1hmpc4BoN2B"
ROOT=Path(__file__).resolve().parents[1]

def gql(query, variables=None):
    body={"query":query}
    if variables is not None: body["variables"]=variables
    p=subprocess.run(["gh","api","graphql","--input","-"],input=json.dumps(body),text=True,capture_output=True)
    if p.returncode!=0:
        raise RuntimeError((p.stderr or p.stdout).strip())
    data=json.loads(p.stdout)
    if data.get("errors"):
        raise RuntimeError(json.dumps(data["errors"],ensure_ascii=False))
    return data["data"]

q="""query($id:ID!){ node(id:$id){ ... on ProjectV2 { id title readme fields(first:60){nodes{ ... on ProjectV2FieldCommon{id name dataType} ... on ProjectV2SingleSelectField{id name dataType options{id name}} }} views(first:30){nodes{id name number layout}} items(first:100){nodes{id type content{ ... on Issue{repository{nameWithOwner}} ... on PullRequest{repository{nameWithOwner}} }}} } } }"""
p=gql(q,{"id":PROJECT_ID})["node"]
fields={f["name"]:f for f in p["fields"]["nodes"]}
print("project",p["title"],"fields",sorted(fields),"views",[(v["name"],v["layout"]) for v in p["views"]["nodes"]])

readme="""# Styayur Portfolio

Single cross-repository view for public work under https://github.com/styayur. Issues and pull requests remain the source of truth; this project mirrors their live state and records only evidence links, risk, and verification metadata.

Scope: all public owned repositories. The private `styayur/site` repository is excluded. Archived items and historical releases are retained for audit history.

Flow: Backlog → Ready → In Progress → Verification → Done. Use Blocked when evidence, authorization, a native runner, or a product decision is missing. No due-date field and no invented SLA.

Automated review records bind repository ID, PR number, base SHA, head SHA, workflow run, tool version, test/security status, evidence, and decision. A green score never overrides a security blocker or missing real-world evidence.
"""
gql("mutation($input:UpdateProjectV2Input!){updateProjectV2(input:$input){projectV2{id title}}}",{"input":{"projectId":PROJECT_ID,"title":"Styayur Portfolio","readme":readme}})
print("renamed project")

status=fields.get("Status")
if not status:
    raise SystemExit("Status field missing")
opts={o["name"]:o for o in status["options"]}
status_input=[
 {"id":opts["Inbox"]["id"],"name":"Backlog","color":"GRAY","description":"Not yet ready for implementation."},
 {"id":opts["Audit"]["id"],"name":"Verification","color":"PURPLE","description":"Implementation complete; independent evidence is being verified."},
 {"id":opts["Ready"]["id"],"name":"Ready","color":"BLUE","description":"Scoped and ready for implementation."},
 {"id":opts["In progress"]["id"],"name":"In Progress","color":"YELLOW","description":"Implementation is actively underway."},
 {"id":opts["Deferred"]["id"],"name":"Blocked","color":"RED","description":"Blocked by evidence, authorization, environment, or an explicit decision."},
 {"id":opts["Done"]["id"],"name":"Done","color":"GREEN","description":"Completed and evidenced, or intentionally disposed."},
]
gql("mutation($input:UpdateProjectV2FieldInput!){updateProjectV2Field(input:$input){projectV2Field{... on ProjectV2SingleSelectField{id name options{id name}}}}}",{"input":{"fieldId":status["id"],"singleSelectOptions":status_input}})
print("updated status options")

if "Target" in fields:
    gql("mutation($input:UpdateProjectV2FieldInput!){updateProjectV2Field(input:$input){projectV2Field{... on ProjectV2FieldCommon{id name}}}}",{"input":{"fieldId":fields["Target"]["id"],"name":"Target Release"}})
    print("renamed Target Release")

def create_select(name, options):
    if name in fields:
        print("exists",name); return
    gql("mutation($input:CreateProjectV2FieldInput!){createProjectV2Field(input:$input){projectV2Field{... on ProjectV2SingleSelectField{id name options{id name}}}}}",{"input":{"projectId":PROJECT_ID,"dataType":"SINGLE_SELECT","name":name,"singleSelectOptions":options}})
    print("created",name)

create_select("Type",[
 {"name":"Bug","color":"RED","description":"Defect in existing behavior."},
 {"name":"Feature","color":"BLUE","description":"New capability or product change."},
 {"name":"Maintenance","color":"GRAY","description":"Dependencies, refactors, docs, CI, or cleanup."},
 {"name":"Security","color":"ORANGE","description":"Security, privacy, permissions, or supply-chain work."},
])
create_select("Risk",[
 {"name":"R0","color":"GREEN","description":"Documentation or non-executable asset change."},
 {"name":"R1","color":"BLUE","description":"Low-risk tests, comments, or small scoped changes."},
 {"name":"R2","color":"YELLOW","description":"Normal code or compatible dependency change with automated coverage."},
 {"name":"R3","color":"ORANGE","description":"Public API, migration, release, credential, or major dependency change; human decision required."},
 {"name":"R4","color":"RED","description":"Security-critical, destructive, signing, or high-blast-radius change."},
])
if "Last Verified" not in fields:
    gql("mutation($input:CreateProjectV2FieldInput!){createProjectV2Field(input:$input){projectV2Field{... on ProjectV2FieldCommon{id name dataType}}}}",{"input":{"projectId":PROJECT_ID,"dataType":"DATE","name":"Last Verified"}})
    print("created Last Verified")

views={v["name"]:v for v in p["views"]["nodes"]}
if "View 1" in views:
    gql("mutation($input:UpdateProjectV2ViewInput!){updateProjectV2View(input:$input){projectV2View{id name layout}}}",{"input":{"viewId":views["View 1"]["id"],"name":"Table","layout":"TABLE_LAYOUT"}})
    print("renamed Table view")
for name,layout in [("Board","BOARD_LAYOUT"),("Roadmap","ROADMAP_LAYOUT")]:
    current={v["name"] for v in p["views"]["nodes"]}
    if name not in current:
        gql("mutation($input:CreateProjectV2ViewInput!){createProjectV2View(input:$input){projectV2View{id name layout}}}",{"input":{"projectId":PROJECT_ID,"name":name,"layout":layout}})
        print("created",name)

# Archive existing private-site items without deleting their history.
for item in p["items"]["nodes"]:
    repo=(item.get("content") or {}).get("repository",{}).get("nameWithOwner")
    if repo=="styayur/site":
        gql("mutation($input:ArchiveProjectV2ItemInput!){archiveProjectV2Item(input:$input){item{id}}}",{"input":{"projectId":PROJECT_ID,"itemId":item["id"]}})
        print("archived private site item",item["id"])

inv=json.load(open(ROOT/"evidence"/"baseline"/"portfolio-inventory.json"))
linked=0; link_errors=[]
for r in inv["repositories"]:
    try:
        gql("mutation($input:LinkProjectV2ToRepositoryInput!){linkProjectV2ToRepository(input:$input){repository{nameWithOwner}}}",{"input":{"projectId":PROJECT_ID,"repositoryId":r["node_id"]}})
        linked+=1
    except Exception as e:
        msg=str(e)
        if "already" in msg.lower(): pass
        else: link_errors.append({"repository":r["full_name"],"error":msg})
print("linked",linked,"errors",json.dumps(link_errors,ensure_ascii=False))
if link_errors: sys.exit(2)
