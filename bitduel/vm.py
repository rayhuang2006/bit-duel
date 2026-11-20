"""A small, deterministic, total-instruction-budget 64-bit bytecode VM.

Fixed register ABI per invocation:
 r0 action (output, initialized 0); r1 persistent memory (in/out),
 r2 low 32 observed state bits, r3 step index (0..63),
 r4 role (0 attacker, 1 defender), r5-r7 scratch.
 All registers are unsigned 64-bit values. Memory resets for each trial.
"""
from dataclasses import dataclass

MASK = (1 << 64) - 1
MAX_BYTES = 128
MAX_OPS = 512

# opcode -> (mnemonic, byte_length, argument_kind)
OPS = {
    0x00: ("HALT", 1, "none"),
    0x01: ("MOV", 2, "pair"),
    0x02: ("XOR", 2, "pair"),
    0x03: ("AND", 2, "pair"),
    0x04: ("OR", 2, "pair"),
    0x05: ("ADD", 2, "pair"),
    0x06: ("SUB", 2, "pair"),
    0x07: ("MUL", 2, "pair"),
    0x08: ("EQ", 2, "pair"),
    0x09: ("LT", 2, "pair"),
    0x0A: ("POPCNT", 2, "pair"),
    0x0B: ("ROL", 3, "shift"),
    0x0C: ("ROR", 3, "shift"),
    0x0D: ("SHL", 3, "shift"),
    0x0E: ("SHR", 3, "shift"),
    0x0F: ("LI8", 3, "imm8"),
    0x10: ("LI64", 10, "imm64"),
    0x11: ("JNZ", 3, "cond"),
    0x12: ("JZ", 3, "cond"),
    0x13: ("JMP", 2, "jump"),
    0x14: ("NOT", 2, "single"),
    0x15: ("LOW4", 2, "single"),
}
NAMES = {v[0]: k for k,v in OPS.items()}

class VMError(ValueError):
    pass

@dataclass(frozen=True)
class Instruction:
    op: int
    pc: int
    length: int
    arg: int | None
    extra: int | None


def _signed8(b: int) -> int:
    return b - 256 if b >= 128 else b


def _rol(x: int, shift: int) -> int:
    shift %= 64
    return ((x << shift) | (x >> ((64 - shift) % 64))) & MASK if shift else x


def _ror(x: int, shift: int) -> int:
    shift %= 64
    return ((x >> shift) | (x << ((64 - shift) % 64))) & MASK if shift else x


def _low4(x: int) -> int:
    out = 0
    for _ in range(4):
        bit = x & -x
        out |= bit
        x ^= bit
    return out


def decode(program: bytes) -> dict[int, Instruction]:
    if not 1 <= len(program) <= MAX_BYTES:
        raise VMError(f"program must contain 1..{MAX_BYTES} bytes")
    pc = 0
    instructions: dict[int, Instruction] = {}
    jumps: list[tuple[int,int]] = []
    halted = False
    while pc < len(program):
        op = program[pc]
        if op not in OPS:
            raise VMError(f"unknown opcode 0x{op:02x} at {pc}")
        _, length, kind = OPS[op]
        if pc + length > len(program):
            raise VMError(f"truncated {OPS[op][0]} at {pc}")
        arg: int | None = None
        extra: int | None = None
        if kind == "pair":
            arg = program[pc+1] >> 4
            extra = program[pc+1] & 15
            if max(arg, extra) >= 8:
                raise VMError(f"invalid register at {pc}")
        elif kind in ("single", "shift", "imm8", "imm64", "cond"):
            arg = program[pc+1]
            if arg >= 8:
                raise VMError(f"invalid register at {pc}")
            if kind in ("shift", "imm8"):
                extra = program[pc+2]
                if kind == "shift" and extra >= 64:
                    raise VMError(f"shift must be 0..63 at {pc}")
            elif kind == "imm64":
                extra = int.from_bytes(program[pc+2:pc+10], "little")
            elif kind == "cond":
                extra = _signed8(program[pc+2])
                jumps.append((pc, pc+length+extra))
        elif kind == "jump":
            arg = _signed8(program[pc+1])
            jumps.append((pc, pc+length+arg))
        if op == 0x00:
            halted = True
        instructions[pc] = Instruction(op, pc, length, arg, extra)
        pc += length
    if not halted:
        raise VMError("program has no HALT instruction")
    for from_pc, target in jumps:
        if target not in instructions:
            raise VMError(f"jump at {from_pc} targets invalid byte {target}")
    return instructions


def execute(program: bytes, observation: int, step: int, role: int,
            memory: int = 0, *, parsed: dict[int,Instruction] | None = None) -> tuple[int,int]:
    if not (0 <= observation < 1 << 32 and 0 <= step < 64 and role in (0,1)):
        raise VMError("invalid input ABI")
    instructions = parsed if parsed is not None else decode(program)
    r = [0, memory & MASK, observation, step, role, 0, 0, 0]
    pc = 0
    for _ in range(MAX_OPS):
        ins = instructions.get(pc)
        if ins is None:
            raise VMError(f"program counter out of bounds: {pc}")
        op, a, b = ins.op, ins.arg, ins.extra
        next_pc = pc + ins.length
        if op == 0x00:
            action = r[0]
            if action.bit_count() > 4:
                raise VMError(f"action exceeds four-bit budget: {action.bit_count()}")
            return action, r[1]
        if op == 0x01: r[a] = r[b]
        elif op == 0x02: r[a] ^= r[b]
        elif op == 0x03: r[a] &= r[b]
        elif op == 0x04: r[a] |= r[b]
        elif op == 0x05: r[a] = (r[a] + r[b]) & MASK
        elif op == 0x06: r[a] = (r[a] - r[b]) & MASK
        elif op == 0x07: r[a] = (r[a] * r[b]) & MASK
        elif op == 0x08: r[a] = int(r[a] == r[b])
        elif op == 0x09: r[a] = int(r[a] < r[b])
        elif op == 0x0A: r[a] = r[b].bit_count()
        elif op == 0x0B: r[a] = _rol(r[a], b)
        elif op == 0x0C: r[a] = _ror(r[a], b)
        elif op == 0x0D: r[a] = (r[a] << b) & MASK
        elif op == 0x0E: r[a] >>= b
        elif op in (0x0F, 0x10): r[a] = b
        elif op == 0x11:
            if r[a] != 0: next_pc += b
        elif op == 0x12:
            if r[a] == 0: next_pc += b
        elif op == 0x13: next_pc += a
        elif op == 0x14: r[a] = (~r[a]) & MASK
        elif op == 0x15: r[a] = _low4(r[a])
        pc = next_pc
    raise VMError("instruction budget (512) exceeded")
