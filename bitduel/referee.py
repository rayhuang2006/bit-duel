"""Immutable-round referee and public limited feedback publisher."""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from .sealed import open_sealed, load_program, from_issue_comment
from .model import evaluate, STEPS, TRIALS

ROOT = Path(__file__).resolve().parents[1]


def read_json(p:Path) -> dict:
    return json.loads(p.read_text(encoding='utf-8'))


def write_json(p:Path, obj:dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True)+'\n',encoding='utf-8')


def validate_config(config: dict) -> None:
    """Reject mismatched or stale configuration rather than silently mis-scoring."""
    if (config.get('schema') != 'bitduel.config.v2'
            or config.get('rules_version') != '0.2'
            or not isinstance(config.get('rounds'), int) or not 1 <= config['rounds'] <= 12
            or config.get('steps') != STEPS
            or config.get('trials') != TRIALS
            or not isinstance(config.get('submission_issue'), int)
            or config['submission_issue'] < 1):
        raise ValueError('wrong or uninitialized v0.2 referee config')
    digest = config.get('seed_sha256')
    if not isinstance(digest,str) or len(digest) != 64:
        raise ValueError('invalid seed commitment')
    try:
        bytes.fromhex(digest)
    except ValueError as exc:
        raise ValueError('invalid seed commitment') from exc


def current_round(game_id: str, rounds: int=12, root:Path=ROOT) -> int:
    r=1
    while r<=rounds and (root/'results'/game_id/f'round-{r:02}.json').exists():
        r+=1
    return r


def submission_file(game_id: str, rd: int, player: str, root:Path=ROOT) -> Path:
    return root/'submissions'/game_id/f'round-{rd:02}'/f'{player}.json'


def validate_envelope(envelope: dict, config: dict, private_key_b64: str, rd:int|None=None):
    if envelope.get('game_id')!=config['game_id'] or envelope.get('player') not in ('gpt','claude'):
        raise ValueError('wrong game/player')
    if rd is not None and envelope.get('round')!=rd:
        raise ValueError(f'expected round {rd}')
    payload=open_sealed(envelope,private_key_b64)
    program=load_program(payload)
    return payload,program


def reconcile(config:dict, private_key_b64:str, secret_seed_hex:str, root:Path=ROOT):
    validate_config(config)
    game=config['game_id']
    rd=current_round(game,config['rounds'],root)
    if rd>config['rounds']:
        return {'status':'finished'}
    paths={p: submission_file(game,rd,p,root) for p in ('gpt','claude')}
    if not all(p.exists() for p in paths.values()):
        return {'status':'waiting','round':rd,'received':[name for name,p in paths.items() if p.exists()]}
    decrypted={}
    programs={}
    for player,path in paths.items():
        entry=read_json(path)
        payload, program=validate_envelope(entry['sealed'],config,private_key_b64,rd)
        if payload['player']!=player:
            raise ValueError('player filename mismatch')
        decrypted[player]=payload
        programs[player]=program
    seed=bytes.fromhex(secret_seed_hex)
    if hashlib.sha256(seed).hexdigest()!=config['seed_sha256'] or len(seed)!=32:
        raise ValueError('referee secret seed does not match public commitment')
    from .sealed import referee_keys_from_seed
    if referee_keys_from_seed(seed)[0] != config['public_key_b64']:
        raise ValueError('referee public key does not match the committed master seed')
    metrics=evaluate(programs['gpt'],programs['claude'],game,seed,rd)
    result={'schema':'bitduel.result.v2','game_id':game,'round':rd,
            'rules_version':'0.2','commits':{p:read_json(paths[p])['sealed']['sha256'] for p in paths},
            'metrics':metrics}
    write_json(root/'results'/game/f'round-{rd:02}.json',result)
    # A human-readable, versioned progression is computed from adjudicated results.
    rows=[]
    cumulative=0.0
    for r in range(1,rd+1):
        prior=read_json(root/'results'/game/f'round-{r:02}.json')
        g=prior['metrics']['gpt_score_0_100']
        cumulative+=g
        rows.append({'round':r,'gpt_score':g,
                     'claude_score':prior['metrics']['claude_score_0_100'],
                     'running_gpt_mean':round(cumulative/r,4),
                     'running_claude_mean':round(100-cumulative/r,4),
                     'gpt_attacker_total':prior['metrics']['gpt_attacks']['total'],
                     'claude_attacker_total':prior['metrics']['claude_attacks']['total']})
    write_json(root/'results'/game/'leaderboard.json',
               {'schema':'bitduel.leaderboard.v2','game_id':game,'completed_rounds':rd,
                'scheduled_rounds':config['rounds'],'rounds':rows,
                'overall_gpt_score':round(cumulative/rd,4),
                'overall_claude_score':round(100-cumulative/rd,4)})
    if rd==config['rounds']:
        reveal={'schema':'bitduel.reveal.v2','game_id':game,'secret_seed_hex':secret_seed_hex,
                'seed_sha256':config['seed_sha256'],'rounds':[]}
        for r in range(1, rd+1):
            item={'round':r,'players':{}}
            for p in ('gpt','claude'):
                raw=read_json(submission_file(game,r,p,root))
                payload, _=validate_envelope(raw['sealed'],config,private_key_b64,r)
                item['players'][p]={'payload':payload,'receipt':raw['receipt'],
                                     'sha256':raw['sealed']['sha256']}
            reveal['rounds'].append(item)
        write_json(root/'reveal'/game/'all_rounds.json',reveal)
    return {'status':'scored','round':rd,'gpt_score':metrics['gpt_score_0_100'],
            'claude_score':metrics['claude_score_0_100']}


def ingest_event(event:dict, config:dict, private_key_b64:str, seed_hex:str, root:Path=ROOT) -> dict:
    validate_config(config)
    if event.get('action')!='created' or event.get('issue',{}).get('number') != config['submission_issue']:
        return {'status':'ignored','reason':'not the designated issue or not a new comment'}
    comment=event.get('comment',{})
    sealed=from_issue_comment(comment.get('body',''))
    if sealed is None:
        return {'status':'ignored','reason':'comment is not a BITDUEL_V1 submission'}
    player=sealed.get('player')
    if player not in ('gpt','claude'): raise ValueError('unknown player')
    login=comment.get('user',{}).get('login','')
    if login not in config['allowed_submitters'].get(player,[]):
        raise ValueError(f'GitHub commenter {login} is not authorized for {player}')
    rd=current_round(config['game_id'], config['rounds'],root)
    if rd>config['rounds']:raise ValueError('game already ended')
    payload, _ = validate_envelope(sealed,config,private_key_b64,rd)
    path=submission_file(config['game_id'],rd,player,root)
    if path.exists():
        if read_json(path)['sealed']['sha256']==sealed['sha256']:
            return {'status':'duplicate','round':rd,'player':player}
        raise ValueError(f'{player} has already submitted round {rd}; submissions are immutable')
    date=comment.get('created_at')
    if not isinstance(date,str) or not date.endswith('Z'):
        raise ValueError('missing trusted GitHub comment creation timestamp')
    write_json(path, {'sealed':sealed,'receipt':{'github_login':login,
        'github_comment_id':comment.get('id'), 'github_created_at_utc':date,
        'github_comment_url':comment.get('html_url','')}})
    outcome=reconcile(config,private_key_b64,seed_hex,root)
    return {'status':'accepted','round':rd,'player':player,'next':outcome}


def verify_final_reveal(config:dict, root:Path=ROOT) -> dict:
    """Public, keyless post-match verifier of scheduled rounds and commitments."""
    from .sealed import canonical, load_program
    validate_config(config)
    game=config['game_id']
    reveal=read_json(root/'reveal'/game/'all_rounds.json')
    seed=bytes.fromhex(reveal['secret_seed_hex'])
    if len(seed)!=32 or hashlib.sha256(seed).hexdigest()!=config['seed_sha256']:
        raise ValueError('revealed seed fails public SHA-256 commitment')
    from .sealed import referee_keys_from_seed
    if referee_keys_from_seed(seed)[0] != config['public_key_b64']:
        raise ValueError('revealed seed does not reproduce referee public key')
    if len(reveal['rounds'])!=config['rounds']:
        raise ValueError('incorrect revealed round count')
    for rd,item in enumerate(reveal['rounds'],1):
        if item['round']!=rd:raise ValueError('revealed rounds are out of order')
        programs={}
        for player in ('gpt','claude'):
            r=item['players'][player]
            payload=r['payload']
            if payload.get('game_id')!=game or payload.get('round')!=rd or payload.get('player')!=player:
                raise ValueError('wrong player/round in reveal')
            digest=hashlib.sha256(canonical(payload)).hexdigest()
            sealed=read_json(submission_file(game,rd,player,root))['sealed']
            if digest != r['sha256'] or digest != sealed['sha256']:
                raise ValueError(f'commitment mismatch in round {rd} for {player}')
            programs[player]=load_program(payload)
        computed=evaluate(programs['gpt'],programs['claude'],game,seed,rd)
        recorded=read_json(root/'results'/game/f'round-{rd:02}.json')['metrics']
        if computed!=recorded:
            raise ValueError(f'scoring mismatch in round {rd}')
    return {'status':'verified','rounds':config['rounds'], 'game_id':game}
