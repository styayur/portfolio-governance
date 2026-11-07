import json, subprocess, time
from pathlib import Path
root=Path(__file__).resolve().parents[1]
path=root/'evidence'/'baseline'/'private-vulnerability-reporting-audit.json'
inv=json.load(open(root/'evidence'/'baseline'/'portfolio-inventory.json'))
records=[]
for r in inv['repositories']:
    full=r['full_name']
    def get():
        p=subprocess.run(['gh','api',f'repos/{full}/private-vulnerability-reporting'],text=True,capture_output=True)
        return json.loads(p.stdout) if p.returncode==0 else {'error':(p.stderr or p.stdout).strip()}
    before=get()
    after=before
    changed=False
    if before.get('enabled') is False:
        p=subprocess.run(['gh','api','-X','PUT',f'repos/{full}/private-vulnerability-reporting'],text=True,capture_output=True)
        changed=p.returncode==0
        after=get()
        if p.returncode!=0:
            after['update_error']=(p.stderr or p.stdout).strip()
    status='PASS' if after.get('enabled') is True else ('BLOCKED' if 'error' in after or 'update_error' in after else 'FAIL')
    records.append({'subject':full,'before':before,'after':after,'changed':changed,'status':status,'verified_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())})
    print(full,status,after,flush=True)
path.write_text(json.dumps({'records':records},indent=2)+'\n')
