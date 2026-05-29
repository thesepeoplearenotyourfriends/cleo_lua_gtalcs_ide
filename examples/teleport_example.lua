-- Compile-time Lua frontend example for the existing CLEO compiler backend.
-- Usage: python compiler_with_lua.py teleport_example.lua opcodes.dict.txt

thread('SCRIPT')

label('loop')
wait(0)

-- if gate active, count down
IF(1)
gt(V(2), 0)
goto_false('check_keys')

dec(V(2), 1)
jmp('loop')

label('check_keys')

-- if L+Left: save position
IF(1)
IS_BUTTON_PRESSED(0, 4)
goto_false('s8')

IF(1)
IS_BUTTON_PRESSED(0, 10)
goto_false('s8')

PRINT_HELP('TSAVE')
seti(V(2), 300)
gosub('get_position')

label('s8')

-- if L+Right: goto position
IF(1)
IS_BUTTON_PRESSED(0, 4)
goto_false('s9')

IF(1)
IS_BUTTON_PRESSED(0, 11)
goto_false('s9')

PRINT_HELP('TLOAD')
seti(V(2), 300)
gosub('teleport_to')

label('s9')
jmp('loop')

label('get_position')
GET_PLAYER_CHAR(V(0), V(1))
GET_OFFSET_FROM_CHAR_IN_WORLD_COORDS(V(1), 0.0, 0.0, 0.0, V(3), V(4), V(5))
int_from_float(V(6), V(3))
int_from_float(V(7), V(4))
int_from_float(V(8), V(5))
PRINT_WITH_NUMBER('ONEX', V(6), 1000, 0)
PRINT_WITH_NUMBER('ONEY', V(7), 1000, 0)
PRINT_WITH_NUMBER('ONEZ', V(8), 1000, 0)
ret()

label('teleport_to')
SET_PLAYER_CONTROL(V(0), 0)
GET_CLOSEST_CAR_NODE(V(3), V(4), V(5), V(3), V(4), V(5))
TELEPORT_PLAYER_TO_COORDS(V(0), V(3), V(4), V(5))
SET_PLAYER_CONTROL(V(0), 1)
ret()
