"""Exploratory only: out-of-sample Python baselines, NOT the 1024-bit tournament.

Used to check that this game's math structure is at least responsive to simple
state-dependent strategies. This is not a balance proof and has no hidden opponents.
"""
import hashlib
import random
from bitduel.model import evolve, objective, observe, rot
from bitduel.vm import MASK


def ror(x,k): return ((x>>k)|(x<<(64-k)))&MASK

def low4(v):
    ans=0
    for _ in range(4):
        bit=v&-v;ans|=bit;v^=bit
    return ans

def structured(y, role):
    pred=y^rot(y,1)^rot(y,3)
    s=pred^rot(pred,1)
    candidates=(~(s|ror(s,1)))&MASK if role==0 else s&ror(s,1)
    return low4(candidates)

def play(atk,dfn,trial):
    x=int.from_bytes(hashlib.sha256(f'holdout/v0.1/{trial}'.encode()).digest()[:8],'little')
    rand=random.Random(100000+trial)
    score=0
    for t in range(64):
        y=observe(x)
        def act(kind,role):
            if kind=='struct':return structured(y,role)
            return sum(1<<i for i in rand.sample(range(64),4))
        a=act(atk,0);d=act(dfn,1)
        x=evolve(x,a,d)
        score+=objective(x)
    return score

if __name__=='__main__':
    for a,d in [('random','random'),('struct','random'),('random','struct'),('struct','struct')]:
        values=[play(a,d,i) for i in range(100)]
        mean=sum(values)/len(values)
        print(f'{a:>7} attack / {d:>7} defense: {mean:.1f} avg total; min={min(values)}, max={max(values)}')
