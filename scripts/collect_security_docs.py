import base64, json, subprocess, time
from pathlib import Path
root=Path(__file__).resolve().parents[1]
out=root/'evidence'/'baseline'/'security-docs'
out.mkdir(parents=True,exist_ok=True)
inv=json.load(open(root/'evidence'/'baseline'/'portfolio-inventory.json'))
results=[]
for r in inv['repositories']:
    full=r['full_name']; name=r['name']; branch=r['default_branch']
    row={'repository':full,'default_branch':branch,'files':{}}
    for path in ['SECURITY.md','.github/SECURITY.md','docs/SECURITY.md']:
        p=subprocess.run(['gh','api',f'repos/{full}/contents/{path}?ref={branch}'],text=True,capture_output=True)
        if p.returncode==0:
            d=json.loads(p.stdout)
            raw=base64.b64decode(d['content']).decode('utf-8')
            safe=name+'__'+path.replace('/','_')
            (out/safe).write_text(raw)
            row['files'][path]={'sha':d.get('sha'),'size':d.get('size'),'path':str(out/safe)}
        else:
            row['files'][path]={'status':'absent'}
    p=subprocess.run(['gh','api',f'repos/{full}/private-vulnerability-reporting'],text=True,capture_output=True)
    row['private_vulnerability_reporting']=json.loads(p.stdout) if p.returncode==0 else {'error':(p.stderr or p.stdout).strip()}
    results.append(row)
    print(full, list(row['files']), row['private_vulnerability_reporting'], flush=True)
(root/'evidence'/'baseline'/'security-docs-index.json').write_text(json.dumps(results,indent=2)+'\n')
