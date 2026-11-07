import json, subprocess, sys
from pathlib import Path
PROJECT_ID="PVT_kwHOE1hmpc4BoN2B"
ROOT=Path(__file__).resolve().parents[1]

def gql(query, variables=None):
    body={"query":query}
    if variables is not None: body["variables"]=variables
    p=subprocess.run(["gh","api","graphql","--input","-"],input=json.dumps(body),text=True,capture_output=True)
    if p.returncode!=0: raise RuntimeError((p.stderr or p.stdout).strip())
    data=json.loads(p.stdout)
    if data.get("errors"): raise RuntimeError(json.dumps(data["errors"],ensure_ascii=False))
    return data["data"]

def snapshot():
    q="""query($id:ID!){ node(id:$id){ ... on ProjectV2 { id title readme fields(first:60){nodes{ ... on ProjectV2FieldCommon{id name dataType} ... on ProjectV2SingleSelectField{id name dataType options{id name}} }} views(first:30){nodes{id name number layout}} items(first:100){nodes{id type content{ ... on Issue{repository{nameWithOwner}} ... on PullRequest{repository{nameWithOwner}} }}} } } }"""
    return gql(q,{"id":PROJECT_ID})["node"]

def create_field(name,data_type,options=None):
    p=snapshot(); fields={f["name"]:f for f in p["fields"]["nodes"]}
    if name in fields:
        print("exists",name); return
    inp={"projectId":PROJECT_ID,"dataType":data_type,"name":name}
    if options: inp["singleSelectOptions"]=options
    gql("mutation($input:CreateProjectV2FieldInput!){createProjectV2Field(input:$input){projectV2Field{... on ProjectV2FieldCommon{id name dataType}}}}",{"input":inp})
    print("created",name)

create_field("Work Type","SINGLE_SELECT",[
 {"name":"Bug","color":"RED","description":"Defect in existing behavior."},
 {"name":"Feature","color":"BLUE","description":"New capability or product change."},
 {"name":"Maintenance","color":"GRAY","description":"Dependencies, refactors, docs, CI, or cleanup."},
 {"name":"Security","color":"ORANGE","description":"Security, privacy, permissions, or supply-chain work."},
])
create_field("Risk","SINGLE_SELECT",[
 {"name":"R0","color":"GREEN","description":"Documentation or non-executable asset change."},
 {"name":"R1","color":"BLUE","description":"Low-risk tests, comments, or small scoped changes."},
 {"name":"R2","color":"YELLOW","description":"Normal code or compatible dependency change with automated coverage."},
 {"name":"R3","color":"ORANGE","description":"Public API, migration, release, credential, or major dependency change; human decision required."},
 {"name":"R4","color":"RED","description":"Security-critical, destructive, signing, or high-blast-radius change."},
])
create_field("Last Verified","DATE")

p=snapshot(); views={v["name"]:v for v in p["views"]["nodes"]}
if "View 1" in views:
    gql("mutation($input:UpdateProjectV2ViewInput!){updateProjectV2View(input:$input){projectV2View{id name layout}}}",{"input":{"viewId":views["View 1"]["id"],"name":"Table","layout":"TABLE_LAYOUT"}})
    print("renamed Table view")
for name,layout in [("Board","BOARD_LAYOUT"),("Roadmap","ROADMAP_LAYOUT")]:
    p=snapshot(); current={v["name"] for v in p["views"]["nodes"]}
    if name not in current:
        gql("mutation($input:CreateProjectV2ViewInput!){createProjectV2View(input:$input){projectV2View{id name layout}}}",{"input":{"projectId":PROJECT_ID,"name":name,"layout":layout}})
        print("created",name)

p=snapshot()
for item in p["items"]["nodes"]:
    repo=(item.get("content") or {}).get("repository",{}).get("nameWithOwner")
    if repo=="styayur/site":
        gql("mutation($input:ArchiveProjectV2ItemInput!){archiveProjectV2Item(input:$input){item{id}}}",{"input":{"projectId":PROJECT_ID,"itemId":item["id"]}})
        print("archived private site item",item["id"])

inv=json.load(open(ROOT/"evidence"/"baseline"/"portfolio-inventory.json"))
linked=[]; ignored=[]; errors=[]
for r in inv["repositories"]:
    try:
        gql("mutation($input:LinkProjectV2ToRepositoryInput!){linkProjectV2ToRepository(input:$input){repository{nameWithOwner}}}",{"input":{"projectId":PROJECT_ID,"repositoryId":r["node_id"]}})
        linked.append(r["full_name"])
    except Exception as e:
        msg=str(e)
        if "already" in msg.lower(): ignored.append(r["full_name"])
        else: errors.append({"repository":r["full_name"],"error":msg})
print("linked",len(linked),"already",len(ignored),"errors",json.dumps(errors,ensure_ascii=False))
if errors: sys.exit(2)
