"""Public-key sealed submissions: X25519 + HKDF-SHA256 + AES-256-GCM."""
import base64
import hashlib
import json
import os
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

SCHEMA = 'bitduel.sealed.v1'

def b64(b: bytes) -> str:
    return base64.b64encode(b).decode('ascii')

def unb64(s: str) -> bytes:
    return base64.b64decode(s, validate=True)

def canonical(v: dict) -> bytes:
    return json.dumps(v, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')

def pub_raw(key: X25519PublicKey) -> bytes:
    return key.public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)

def priv_raw(key: X25519PrivateKey) -> bytes:
    return key.private_bytes(encoding=serialization.Encoding.Raw, format=serialization.PrivateFormat.Raw, encryption_algorithm=serialization.NoEncryption())

def create_keys() -> tuple[str,str]:
    key = X25519PrivateKey.generate()
    return b64(pub_raw(key.public_key())), b64(priv_raw(key))

def derive(shared: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b'bitduel/v0.1/sealed').derive(shared)

def seal(payload: dict, public_key_b64: str) -> dict:
    if payload.get('schema') != 'bitduel.payload.v1':
        raise ValueError('invalid payload schema')
    public_key = X25519PublicKey.from_public_bytes(unb64(public_key_b64))
    ephemeral = X25519PrivateKey.generate()
    raw = canonical(payload)
    commitment = hashlib.sha256(raw).hexdigest()
    aad = canonical({'schema':SCHEMA,'game_id':payload['game_id'],
                     'round':payload['round'],'player':payload['player'],'sha256':commitment})
    nonce = os.urandom(12)
    ciphertext = AESGCM(derive(ephemeral.exchange(public_key))).encrypt(nonce, raw, aad)
    return {'schema':SCHEMA, 'game_id':payload['game_id'], 'round':payload['round'],
            'player':payload['player'], 'sha256':commitment,
            'ephemeral_key':b64(pub_raw(ephemeral.public_key())),
            'aes_nonce':b64(nonce), 'ciphertext':b64(ciphertext)}

def open_sealed(envelope: dict, private_key_b64: str) -> dict:
    if envelope.get('schema') != SCHEMA:
        raise ValueError('invalid sealed submission schema')
    hdr = {key:envelope[key] for key in ('schema','game_id','round','player','sha256')}
    priv = X25519PrivateKey.from_private_bytes(unb64(private_key_b64))
    pub = X25519PublicKey.from_public_bytes(unb64(envelope['ephemeral_key']))
    raw = AESGCM(derive(priv.exchange(pub))).decrypt(unb64(envelope['aes_nonce']),unb64(envelope['ciphertext']),canonical(hdr))
    if hashlib.sha256(raw).hexdigest() != envelope['sha256']:
        raise ValueError('commitment mismatch')
    payload = json.loads(raw)
    if canonical(payload) != raw:
        raise ValueError('noncanonical plaintext')
    if payload.get('schema')!='bitduel.payload.v1':
        raise ValueError('invalid payload schema')
    for k in ('game_id','round','player'):
        if payload.get(k) != envelope[k]:
            raise ValueError(f'{k} does not match sealed header')
    return payload


def load_program(payload: dict) -> bytes:
    from .vm import decode
    codehex = payload.get('program_hex','')
    if not isinstance(codehex,str):raise ValueError('program_hex must be string')
    program = bytes.fromhex(codehex)
    decode(program)
    if payload.get('player') not in ('gpt','claude'):raise ValueError('invalid player')
    if not isinstance(payload.get('note'),str) or len(payload['note'].encode('utf-8'))>16384:
        raise ValueError('notes must be UTF-8 text up to 16KiB')
    if not isinstance(payload.get('salt'),str) or len(unb64(payload['salt']))<16:
        raise ValueError('missing random 16-byte salt')
    if not isinstance(payload.get('round'),int) or not 1<=payload['round']<=12:
        raise ValueError('invalid round')
    return program


def make_payload(game_id: str, rd: int, player: str, program: bytes, note: str) -> dict:
    from .vm import decode
    decode(program)
    if player not in ('gpt','claude') or not 1<=rd<=12:
        raise ValueError('invalid role or round')
    if len(note.encode('utf-8'))>16384:
        raise ValueError('notes too long')
    return {'schema':'bitduel.payload.v1','game_id':game_id,'round':rd,'player':player,
            'program_hex':program.hex(),'note':note,'salt':b64(os.urandom(16))}


def to_issue_comment(envelope:dict) -> str:
    return 'BITDUEL_V1\n' + b64(canonical(envelope))


def from_issue_comment(body: str) -> dict|None:
    pieces = body.strip().splitlines()
    if len(pieces)!=2 or pieces[0].strip()!='BITDUEL_V1':
        return None
    if len(pieces[1])>32000:
        raise ValueError('sealed comment too long')
    obj=json.loads(unb64(pieces[1]))
    if not isinstance(obj, dict):raise ValueError('envelope must be object')
    return obj
