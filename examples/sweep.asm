; Sweep four contiguous bits around the circle with time t; role independent.
LI8 r0, 15
MOV r5, r3
LI8 r6, 1
loop:
JZ r5, end
ROL r0, 1
SUB r5, r6
JMP loop
end:
HALT
