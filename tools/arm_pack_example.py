"""Pack a completed arm loop (blinkflow.arm.run) as examples/<name>, including every successful SAM reply and
calibration cost. It made examples/arm, examples/arm-bug2 and examples/arm-voice; it reads the arm's state
from BLINKFLOW_ARM_STATE (default ~/blinkflow-runs/arm), so run it with the state the loop ran with.

    python3 tools/arm_pack_example.py ~/blinkflow-runs/arm/loop-1 examples/arm-2 [--caption TEXT] [--lost-calibration-reply]
"""
import argparse
import gzip
import hashlib
import importlib.metadata
import json
import os
import pathlib
import shutil
import subprocess
import sys

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from blinkflow.arm import HERE, REPO, ROBOT, STATE, WORLD  # noqa: E402
TEXT={'.json','.jsonl','.txt','.md','.diff','.py','.toml','.xml'}


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


CAPTION='One planted clearance bug. SAM masks, Wonder diagnosis, Code fix, deterministic proof.'


def pack(source,dest,lost=False,caption=CAPTION):
    src,out=pathlib.Path(source).resolve(),pathlib.Path(dest).resolve()
    result=json.loads((src/'result.json').read_text())
    assert result['passed']
    if out.exists(): raise RuntimeError(f'{out} already exists')
    shutil.copytree(src,out)
    shutil.copytree(HERE,out/'snapshot/arm',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy(WORLD/'scene.xml',out/'snapshot/scene.xml')
    (out/'brain-after').mkdir()
    for name in ('brain.py','brain.toml'):shutil.copy(ROBOT/name,out/'brain-after'/name)
    (out/'calibration/sam-cache').mkdir(parents=True)
    calls=json.loads((src/'models.json').read_text())['calls']
    main_keys={c.get('cache_key') for c in calls if c['model']=='sam-3.1' and c['cost_usd']}
    for f in sorted((STATE/'.cache/sam').glob('*.json')):
        d=json.loads(f.read_text())
        shutil.copy(f,out/'calibration/sam-cache'/f.name)
        if f.stem not in main_keys:
            calls.append({'model':'sam-3.1','where':'Meta Model API','purpose':'calibration: '+d['concept'],
                          'seconds':d['seconds'],'frames':d['frames'],'cost_usd':d['cost_usd'],
                          'usage':d['usage'],'cache_key':f.stem,'stage':'calibration',
                          'raw_reply':'./calibration/sam-cache/'+f.name})
    local=STATE/'runs/perception-probe/identification-models.json'
    if local.exists():
        calls += [{**c,'stage':'calibration'} for c in json.loads(local.read_text())['calls'] if c['model']=='muse-glimmer']
        shutil.copy(STATE/'runs/perception-probe/glimmer.json',out/'calibration/glimmer.json')
    # The Nov 1 run: a response lost on a local decoder exception remains conservatively charged.
    if lost: calls.append({'model':'sam-3.1','where':'Meta Model API','purpose':'calibration red block; decoder failed',
                  'frames':6,'cost_usd':.0012,'stage':'calibration','status':'response received; local decoder failed',
                  'raw_reply':None,'cost_note':'full frame charge retained; no fabricated reply'})
    from blinkflow.arm import budget
    total=sum(c['cost_usd'] for c in calls)
    # a ledger started here opens with the earlier public spend: this pack accounts for what came after it
    rows=[json.loads(s) for s in (STATE/'.budget/spend.jsonl').read_text().splitlines()]
    prior=rows[0]['usd'] if rows and rows[0]['what']=='prior public repo spend' else 0.
    assert abs(total-(budget.total()-prior))<.0001,(total,budget.total(),prior)
    accounting={'calls':calls,'total_cost_usd':round(total,8),'repo_spend_usd':round(budget.total(),8),
                'budget_cap_usd':3.,'includes':'finished loop plus all paid calibration and failed calls',
                'prices':json.loads((src/'models.json').read_text())['prices']}
    (out/'models.json').write_text(json.dumps(accounting,indent=1))
    shutil.copy(STATE/'.budget/spend.jsonl',out/'calibration/reservations.jsonl')
    version=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
    dep_root=REPO
    hashes={f'blinkflow/{n}.py':digest(dep_root/'blinkflow'/f'{n}.py')
            for n in ('sam','see','diagnose','fix','prove','twin','models')}
    (out/'dependencies.json').write_text(json.dumps({'blinkflow_commit':version,'mujoco':'3.10.0',
            'python':'3.12.3','meta_sam_parser':importlib.metadata.version('meta-sam-parser'),
            'source_repositories':'this repository (blinkflow.arm)',
            'verification_module_sha256':hashes},indent=1))
    # Every internal path is portable, from the folder of the document containing it.
    pairs=[(str(p),out/p.relative_to(src)) for p in [src,*src.rglob('*')]]
    pairs.sort(key=lambda item:len(item[0]),reverse=True)
    home=str(pathlib.Path.home())
    def scrub(text,dest):
        for old,new in pairs:
            rel=os.path.relpath(new,dest.parent)
            if not rel.startswith('.'):rel='./'+rel
            text=text.replace(old,rel)
        return text.replace(home,'~')
    for f in out.rglob('*'):
        if not f.is_file():continue
        if f.suffix in TEXT:f.write_text(scrub(f.read_text(),f))
        elif f.name.endswith('.jsonl.gz'):
            f.write_bytes(gzip.compress(scrub(gzip.decompress(f.read_bytes()).decode(),f).encode(),mtime=0))
    for tag,path in [('before',out/'before/twin/shot.mp4'),('after',out/f"attempt-{result['attempt']}/twin/shot.mp4")]:
        subprocess.run(['ffmpeg','-v','error','-y','-i',str(path),'-vf','fps=10,scale=480:-1','-loop','0',str(out/f'{tag}.gif')],check=True)
    (out/'preview.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>BlinkFlow arm</title>'
        '<style>body{background:#15171b;color:white;font:18px sans-serif;margin:2rem}main{display:flex;gap:1rem}img{width:100%}figure{margin:0;max-width:48%}</style>'
        '<h1>BlinkFlow: second robot</h1><p>'+caption+'</p>'
        '<main><figure><figcaption>Before: contact</figcaption><img src="before.gif"></figure>'
        '<figure><figcaption>After: target reached, no contact</figcaption><img src="after.gif"></figure></main>'
        '<p>SAM arm tracking is initialized from a box marked in the first image. It is not text-only arm detection.</p></html>')
    hashes={str(f.relative_to(out)):digest(f) for f in sorted(out.rglob('*')) if f.is_file() and f.name!='sha256.json'}
    (out/'sha256.json').write_text(json.dumps(hashes,indent=1))
    print(json.dumps({'files':len(hashes),'bytes':sum(f.stat().st_size for f in out.rglob('*') if f.is_file()),'total_cost_usd':total}))


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('source');ap.add_argument('dest');ap.add_argument('--lost-calibration-reply',action='store_true');ap.add_argument('--caption',default=CAPTION)
    a=ap.parse_args();pack(a.source,a.dest,a.lost_calibration_reply,a.caption)
