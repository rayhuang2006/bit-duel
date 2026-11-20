"""Fixed public mathematical model: F2^64 ring automaton."""
import hashlib
from .vm import MASK, execute, decode, VMError

STEPS = 64
TRIALS = 8
OBS_MASK = (1 << 32) - 1
ROLES = {'attacker':0, 'defender':1}


def rot(x: int, k: int) -> int:
    k %= 64
    return ((x << k) | (x >> (64-k))) & MASK if k else x & MASK


def evolve(x: int, a: int, d: int) -> int:
    return (x ^ rot(x, 1) ^ rot(x, 3) ^ a ^ d) & MASK


def objective(x: int) -> int:
    return (x ^ rot(x, 1)).bit_count()


def observe(x: int) -> int:
    return x & OBS_MASK


def initial_state(game_id: str, seed: bytes, round_number: int, trial: int) -> int:
    """Domain-separated round/trial initial state derived from one committed seed.

    Players see the SHA-256 commitment to the master seed, not the seed.
    The same (round, trial) is used in both attacking legs for fairness.
    """
    if not 1 <= round_number <= 12 or not 0 <= trial < TRIALS or len(seed) != 32:
        raise ValueError('invalid initial state parameters')
    name = game_id.encode('utf-8')
    material = (b'bitduel/v0.2/initial\x00' + len(name).to_bytes(2,'big') + name
                + round_number.to_bytes(2,'big') + trial.to_bytes(2,'big') + seed)
    return int.from_bytes(hashlib.sha256(material).digest()[:8], 'little')


def run_leg(attacker: bytes, defender: bytes, game_id: str, seed: bytes,
            round_number: int) -> dict:
    p_att = decode(attacker); p_def = decode(defender)
    total = 0
    checkpoints = [0] * 8
    errors = set()
    public_probe = []  # Fixed, sparse observation samples from trial 0 only.
    for trial in range(TRIALS):
        x = initial_state(game_id, seed, round_number, trial)
        mem_a = mem_d = 0
        for t in range(STEPS):
            y = observe(x)
            try:
                a, mem_a = execute(attacker, y, t, 0, mem_a, parsed=p_att)
            except VMError:
                a, mem_a = 0, 0
                errors.add('attacker')
            try:
                d, mem_d = execute(defender, y, t, 1, mem_d, parsed=p_def)
            except VMError:
                d, mem_d = 0, 0
                errors.add('defender')
            x = evolve(x, a, d)
            if trial == 0 and t + 1 in (8, 24, 40, 56):
                public_probe.append({"step":t+1,"observed_low32_hex":f"{observe(x):08x}"})
            val = objective(x)
            total += val
            if (t + 1) % 8 == 0:
                checkpoints[(t+1)//8 - 1] += val
    return {'total':total, 'mean_q':round(total/(TRIALS*STEPS),4),
            'checkpoints_mean_q': [round(v/TRIALS,4) for v in checkpoints],
            'public_probe_trial0': public_probe,
            'invalid_roles': sorted(errors)}


def evaluate(gpt_program: bytes, claude_program: bytes, game_id: str, seed: bytes,
             round_number: int) -> dict:
    # Both programs run one attacking leg and one defending leg.
    gc = run_leg(gpt_program, claude_program, game_id, seed, round_number)
    cg = run_leg(claude_program, gpt_program, game_id, seed, round_number)
    bad_gpt = 'attacker' in gc['invalid_roles'] or 'defender' in cg['invalid_roles']
    bad_claude = 'defender' in gc['invalid_roles'] or 'attacker' in cg['invalid_roles']
    if bad_gpt and bad_claude:
        score = 50.0; outcome = 'both_forfeit'
    elif bad_gpt:
        score = 0.0; outcome = 'gpt_forfeit'
    elif bad_claude:
        score = 100.0; outcome = 'claude_forfeit'
    else:
        score = round(50 + 50*(gc['total']-cg['total'])/(64*STEPS*TRIALS), 4)
        outcome = 'normal'
    return {'gpt_attacks':gc, 'claude_attacks':cg,
            'gpt_score_0_100':score, 'claude_score_0_100':round(100-score,4),
            'gpt_advantage_raw':gc['total']-cg['total'] if outcome == 'normal' else None,
            'outcome':outcome}
