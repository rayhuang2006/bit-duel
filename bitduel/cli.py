"""Bit Duel entrypoint: python -m bitduel.cli <command>."""
import argparse
import base64
import hashlib
import json
import os
import secrets
from pathlib import Path
from .asm import assemble_file
from .model import evaluate, STEPS, TRIALS
from .referee import ROOT, read_json, write_json, ingest_event, reconcile, verify_final_reveal
from .sealed import referee_keys_from_seed, make_payload, seal, to_issue_comment
from .vm import decode


def _secrets():
    # Only one GitHub Actions secret; derives both the private key and seed.
    filename=ROOT/'.secrets'/'arena.env'
    if filename.exists():
        for line in filename.read_text().splitlines():
            if '=' in line and not line.startswith('#'):
                k,v=line.split('=',1)
                if k not in os.environ:os.environ[k]=v
    seed=os.environ.get('ARENA_MASTER_SEED_HEX','')
    if not seed:
        raise ValueError('Missing ARENA_MASTER_SEED_HEX GitHub Actions secret')
    raw=bytes.fromhex(seed)
    _, private=referee_keys_from_seed(raw)
    return private, seed


def main():
    parser=argparse.ArgumentParser(description='Bit Duel 1024-bit mathematical arena')
    sp=parser.add_subparsers(dest='cmd',required=True)
    init=sp.add_parser('init',help='create public config and private referee secrets')
    init.add_argument('--game',default='game-001');init.add_argument('--user',required=True)
    init.add_argument('--issue',type=int,required=True)
    asm=sp.add_parser('assemble',help='assemble local strategy')
    asm.add_argument('source');asm.add_argument('--out',required=True)
    demo=sp.add_parser('demo',help='play local example legs')
    demo.add_argument('--gpt',default='examples/local.asm'); demo.add_argument('--claude',default='examples/sweep.asm')
    sub=sp.add_parser('submit',help='encrypt program and notes as issue comment')
    sub.add_argument('--game',default=None);sub.add_argument('--round',type=int,required=True)
    sub.add_argument('--player',choices=('gpt','claude'),required=True)
    sub.add_argument('--program',required=True);sub.add_argument('--note',required=True)
    sub.add_argument('--out',required=True)
    intake=sp.add_parser('intake',help='accept GitHub issue_comment event and score if ready')
    intake.add_argument('--event',required=True)
    sp.add_parser('reconcile',help='run latest pending round if both submissions exist')
    sp.add_parser('verify',help='verify all scores and commitments after final public reveal')
    args=parser.parse_args()
    if args.cmd=='init':
        config_path=ROOT/'config'/'game.json'
        if config_path.exists() or (ROOT/'.secrets'/'arena.env').exists():
            raise ValueError('already initialized: refusing to overwrite secrets')
        secret=secrets.token_bytes(32)
        public, _=referee_keys_from_seed(secret)
        config={'schema':'bitduel.config.v2','game_id':args.game,'rules_version':'0.2',
                'rounds':12,'steps':STEPS,'trials':TRIALS,'submission_issue':args.issue,
                'allowed_submitters':{'gpt':[args.user],'claude':[args.user]},
                'public_key_b64':public,'seed_sha256':hashlib.sha256(secret).hexdigest()}
        write_json(config_path,config)
        sec=ROOT/'.secrets'/'arena.env';sec.parent.mkdir(exist_ok=True)
        sec.write_text(f'ARENA_MASTER_SEED_HEX={secret.hex()}\n')
        try:sec.chmod(0o600)
        except OSError:pass
        print('Created config/game.json and .secrets/arena.env (DO NOT COMMIT THE SECRET).')
        print('Set the single ARENA_MASTER_SEED_HEX value in GitHub Actions repository secrets.')
    elif args.cmd=='assemble':
        code=assemble_file(args.source)
        Path(args.out).parent.mkdir(parents=True,exist_ok=True)
        Path(args.out).write_bytes(code)
        print(f'Assembled {len(code)} bytes / 128 bytes ({len(code)*8} bits / 1024 bits)')
    elif args.cmd=='demo':
        def load(path):
            return assemble_file(path) if path.endswith('.asm') else Path(path).read_bytes()
        a=load(args.gpt);b=load(args.claude)
        print(f'gpt program {len(a)} bytes, claude program {len(b)} bytes')
        seed=bytes.fromhex('0123456789abcdef'*4)
        print(json.dumps(evaluate(a,b,'demo',seed,1),indent=2))
    elif args.cmd=='submit':
        config=read_json(ROOT/'config'/'game.json')
        game=args.game or config['game_id']
        program=Path(args.program).read_bytes();decode(program)
        note=Path(args.note).read_text(encoding='utf-8')
        envelope=seal(make_payload(game,args.round,args.player,program,note),config['public_key_b64'])
        Path(args.out).write_text(to_issue_comment(envelope)+'\n',encoding='utf-8')
        print(f'Encrypted issue comment written to {args.out}')
    elif args.cmd=='verify':
        config=read_json(ROOT/'config'/'game.json')
        print(json.dumps(verify_final_reveal(config),ensure_ascii=False,sort_keys=True))
    elif args.cmd in ('intake','reconcile'):
        config=read_json(ROOT/'config'/'game.json')
        priv,seed=_secrets()
        if args.cmd=='intake':
            event=read_json(Path(args.event))
            output=ingest_event(event,config,priv,seed)
        else:output=reconcile(config,priv,seed)
        print(json.dumps(output,ensure_ascii=False,sort_keys=True))

if __name__=='__main__': main()
