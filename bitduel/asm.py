"""Two-pass assembler for Bit Duel VM; exact byte lengths are public."""
import re
from pathlib import Path
from .vm import OPS, NAMES, VMError, decode


def _register(token: str) -> int:
    if not re.fullmatch(r"r[0-7]", token.lower()):
        raise VMError(f"register expected: {token}")
    return int(token[1:])


def assemble(source: str) -> bytes:
    labels = {}
    records = []
    pc = 0
    for lineno, original in enumerate(source.splitlines(), 1):
        line = original.split(';', 1)[0].split('#', 1)[0].strip()
        if not line: continue
        if ':' in line:
            label, rest = line.split(':', 1)
            label = label.strip()
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', label) or label in labels:
                raise VMError(f"line {lineno}: invalid/duplicate label {label}")
            labels[label] = pc
            line = rest.strip()
            if not line: continue
        parts = [s for s in re.split(r'[\s,]+', line) if s]
        name = parts[0].upper()
        if name not in NAMES:
            raise VMError(f"line {lineno}: unknown mnemonic {name}")
        op = NAMES[name]
        length = OPS[op][1]
        records.append((lineno, pc, name, parts[1:]))
        pc += length
    if pc > 128: raise VMError(f"assembled program is {pc} bytes > 128")
    buf = bytearray()
    for lineno, pc, name, args in records:
        op = NAMES[name]
        _, length, kind = OPS[op]
        need = {"none":0,"pair":2,"single":1,"shift":2,"imm8":2,"imm64":2,"cond":2,"jump":1}[kind]
        if len(args) != need:
            raise VMError(f"line {lineno}: {name} expects {need} operands")
        chunk = bytearray([op])
        try:
            if kind == 'pair':
                chunk.append((_register(args[0]) << 4) | _register(args[1]))
            elif kind == 'single':
                chunk.append(_register(args[0]))
            elif kind == 'shift':
                value = int(args[1], 0)
                if not 0 <= value < 64: raise ValueError()
                chunk.extend([_register(args[0]), value])
            elif kind == 'imm8':
                value = int(args[1], 0)
                if not 0 <= value < 256: raise ValueError()
                chunk.extend([_register(args[0]), value])
            elif kind == 'imm64':
                value = int(args[1], 0)
                if not 0 <= value < (1 << 64): raise ValueError()
                chunk.append(_register(args[0]));chunk.extend(value.to_bytes(8, 'little'))
            elif kind == 'cond':
                target = labels.get(args[1], None)
                if target is None: raise VMError(f"undefined label: {args[1]}")
                delta = target - (pc+length)
                if not -128 <= delta <= 127: raise ValueError('jump out of 8-bit range')
                chunk.extend([_register(args[0]), delta & 255])
            elif kind == 'jump':
                target = labels.get(args[0], None)
                if target is None: raise VMError(f"undefined label: {args[0]}")
                delta = target - (pc+length)
                if not -128 <= delta <= 127: raise ValueError('jump out of 8-bit range')
                chunk.append(delta & 255)
        except ValueError as exc:
            raise VMError(f"line {lineno}: invalid immediate or jump: {exc}") from exc
        buf.extend(chunk)
    if not buf: raise VMError('empty assembly')
    decode(bytes(buf))
    return bytes(buf)


def assemble_file(path: str | Path) -> bytes:
    return assemble(Path(path).read_text(encoding='utf-8'))
