; A legitimate <=128-byte deterministic math strategy for BOTH roles.
; Infer x from observed low 32 bits; predict L(x), then s=H(L(x)).
; An action on bit i toggles neighboring s_i and s_{i+1}.
; Attacker: prefer 0/0 pairs, defender: prefer 1/1 pairs.
MOV r5, r2
MOV r6, r2
ROL r6, 1
XOR r5, r6
MOV r6, r2
ROL r6, 3
XOR r5, r6
MOV r6, r5
ROL r6, 1
XOR r5, r6
JNZ r4, defender
MOV r6, r5
ROR r6, 1
OR r5, r6
NOT r5
LOW4 r5
MOV r0, r5
HALT
defender:
MOV r6, r5
ROR r6, 1
AND r5, r6
LOW4 r5
MOV r0, r5
HALT
