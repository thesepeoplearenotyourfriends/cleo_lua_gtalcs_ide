
#!/usr/bin/env python

from dataclasses import dataclass
import json
import struct
import re
import sys
import subprocess
import shutil

MAX_SCRIPT_SIZE = 16384

TOKEN_RE = re.compile(
    r'''
    "[^"]*" |
    \$[0-9A-Fa-f]+ |
    \d+@ |  #LOCAL@
    @\w+ |  #@LABEL

    -?\d+\.\d+ |      # floats FIRST
    -?\d+ |           # ints after

    [A-Za-z_][A-Za-z0-9_]*
    ''',
    re.VERBOSE
)

HANDSHAKE_BYTES = (
    b'\xD5\x0D\x0C\xDB\x00\x01\x39\x00\x0c\x07\x01\x4d\x00\x01'
    b'\xd8\xff\xff\xff\x8b\x00\x00\xce\x19\x02\x00\x01\xd3\xff'
    b'\xff\xff\x8b\x00\x0c\xce\x18\xdb\x00\x01\x5b\x02\x0c\x4d'
    b'\x00\x01\xc3\xff\xff\xff'
)


# Lua frontend: this is a compile-time Lua layer, not an in-game Lua VM.
# A .lua file emits ordinary CLEO source lines, then the existing compiler backend
# performs the same label collection and bytecode emission it already knows how to do.
LUA_PRELUDE = r"""
local function is_operand_string(s)
    return s:match('^@[%w_]+$')
        or s:match('^%d+@$')
        or s:match('^%$[0-9A-Fa-f]+$')
        or s == 'PLAYER'
        or s:match('^%-?%d+$')
        or s:match('^%-?%d+%.%d+$')
end

local function arg_to_text(v)
    if type(v) == 'number' then
        return tostring(v)
    elseif type(v) == 'string' then
        if is_operand_string(v) then
            return v
        end
        return string.format('%q', v)
    elseif type(v) == 'boolean' then
        return v and '1' or '0'
    else
        error('unsupported CLEO operand type: '..type(v), 3)
    end
end

function OP(name, ...)
    local parts = { tostring(name) }
    for i = 1, select('#', ...) do
        parts[#parts + 1] = arg_to_text(select(i, ...))
    end
    io.write(table.concat(parts, ' '), '\n')
end

function thread(name)
    io.write("thread '" .. tostring(name):sub(1, 8) .. "'\n")
end

function label(name, data)
    if data == nil then
        io.write(':' .. tostring(name), '\n')
    else
        io.write(':' .. tostring(name) .. ' ' .. string.format('%q', tostring(data)), '\n')
    end
end

-- Operand constructors
function V(n) return tostring(n) .. '@' end
function G(n) return '$' .. tostring(n) end
function L(name) return '@' .. tostring(name) end
function sym(name) return tostring(name) end

-- Labels/control aliases. Lowercase names avoid Lua keywords like "goto"/"return".
function jmp(name) OP('GOTO_@LABEL', L(name)) end
function goto_false(name) OP('GOTO_IF_FALSE_@LABEL', L(name)) end
function gosub(name) OP('GOSUB_@LABEL', L(name)) end
function ret() OP('RETURN') end
function wait(ms) OP('WAIT_TIME_INT', ms) end

-- Aliases for opcodes whose dictionary names are not legal Lua identifiers.
function gt(a, b) OP('LOCAL_VAR_INT_>_LITERAL_INT', a, b) end
function dec(a, b) OP('LOCAL_VAR_INT_-=_LITERAL_INT', a, b) end
function seti(a, b) OP('LOCAL_VAR_INT_=_LITERAL_INT', a, b) end
function int_from_float(a, b) OP('LOCAL_VAR_INT_=#_LOCAL_VAR_FLOAT', a, b) end

-- Most dictionary opcode names are valid uppercase Lua identifiers, so let them
-- be called directly: WAIT_TIME_INT(0), PRINT_HELP('TEXT'), etc.
setmetatable(_G, {
    __index = function(_, name)
        return function(...)
            return OP(name, ...)
        end
    end
})
"""


def lua_to_cleo_source(lua_path):
    lua_exe = (
        shutil.which('lua')
        or shutil.which('lua5.4')
        or shutil.which('lua5.3')
        or shutil.which('lua5.2')
        or shutil.which('lua5.1')
    )

    if not lua_exe:
        raise RuntimeError(
            'Lua frontend requires a lua executable on PATH '
            '(try installing lua5.4).'
        )

    with open(lua_path, 'r', encoding='utf-8') as f:
        user_lua = f.read()

    proc = subprocess.run(
        [lua_exe, '-'],
        input=LUA_PRELUDE + '\n' + user_lua,
        text=True,
        capture_output=True,
    )

    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or 'Lua frontend failed.')

    return proc.stdout


@dataclass
class OpcodeEntry:
    name: str
    opcode: int
    param_count: int = -1
    params: list = None

@dataclass
class Instruction:
    opcode: OpcodeEntry
    operands: list
    line: int

class CLEOCompiler:

    SPECIAL_SYMBOLS = {"PLAYER": b"\xdb\x00"}

    def __init__(self):
        self.bytecode = bytearray()
        self.opcodes = {}
        self.instructions = []
        self.labels = {}
        self.error = ""

    def load_opcodes(self, path):

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for name, info in data.items():

            opcode = int(info["opcode"],16)
            count = info.get("var_count",-1)
            params = info.get("params",[])

            self.opcodes[name.upper()] = OpcodeEntry(
                name.upper(),
                opcode,
                count,
                params
            )

    def tokenize_operands(self,text):
        return TOKEN_RE.findall(text)

    def write(self,data):

        if len(self.bytecode)+len(data) > MAX_SCRIPT_SIZE:
            raise OverflowError(
                "Script exceeds maximum size"
            )

        self.bytecode.extend(data)

    def write_short(self,value):
        self.write(struct.pack("<H",value))

    def write_int(self,value):
        self.write(struct.pack("<i",value))

    def header_size(self):

        return (
            8 +                     # nulls
            2 +                     # A903
            8 +                     # thread name
            len(HANDSHAKE_BYTES)
        )

    def write_header(self,thread_name):

        thread_name = thread_name[:8]

        self.write(
            b"\x00"*8 +
            b"\xA9\x03" +
            thread_name.encode(
                "ascii"
            ).ljust(8,b"\x00") +

            # FIXME we understand this enough now to not use a hex chunk.
            # 1. THE HANDSHAKE:
            # this is what the equivalent in sannybuilder looks like:
            #
            # 0DD5: 0@ = get_platform
            # if
            #     0@ == 1
            # then
            #     008B: 0@ = $537 // player handle on Android
            # else
            #     008B: 0@ = $536 // player handle on PSP
            # end
            #
            # if
            #     025B: player 0@ defined
            # then
            #
            # summarized:
            #
            # platform check (android/psp)
            # followed by:
            # if player defined
            # then user's script begins
            #
            HANDSHAKE_BYTES
        )

    def encoded_size(
        self,
        kind,
        value,
        param_def=None
    ):

        if param_def:
            if param_def.get("type") == "raw_byte":
                return 1

        if kind == "INT":
            if 0 <= value <= 255:
                return 2
            elif 0 <= value <= 65535:
                return 3
            return 5

        elif kind == "LOCAL":
            return 1

        elif kind == "LABEL":
            return 5

        elif kind == "STRING":
            return 8

        elif kind == "SYMBOL":
            return 2

        elif kind == "GLOBAL":
            return 5

        return 0

    def parse_instructions(self,source):
        instructions=[]
        for line_num,raw_line in enumerate(source.splitlines(),1):
            line=raw_line.strip()

            if not line:
                continue

            if line.startswith(";"):
                continue

            if line.startswith(":"):
                continue

            if line.startswith("{"):
                continue

            if line.lower().startswith("thread"):
                continue

            tokens = line.split(None,1)
            opcode_token=tokens[0]
            remainder=""

            if len(tokens)>1:
                remainder=tokens[1]

            #
            # Raw opcode syntax
            #
            if opcode_token.endswith(":"):
                opcode_hex=opcode_token[:-1]

                try:
                    opcode=OpcodeEntry(opcode_hex, int(opcode_hex,16))

                except:
                    self.error=(f"Line {line_num}: Invalid opcode {opcode_token}")
                    return None

            #
            # Dictionary lookup syntax
            #
            else:
                opcode_name=opcode_token.upper()
                if opcode_name not in self.opcodes:
                    self.error=(f"Line {line_num}: Unknown opcode {opcode_name}")
                    return None

                opcode=self.opcodes[opcode_name]

            parsed=[]

            for token in self.tokenize_operands(remainder):
                operand=self.parse_operand(token)
                if operand is None:
                    self.error=(f"Line {line_num}: Invalid operand {token}")
                    return None

                parsed.append(operand)

            if opcode.param_count >= 0:
                if len(parsed) != opcode.param_count:
                    self.error=(
                        f"Line {line_num}: {opcode.name} expects {opcode.param_count} params, got {len(parsed)}")
                    return None

            instructions.append(Instruction(opcode,parsed,line_num))

        return instructions

    def collect_labels(self,source):
        self.labels={}
        offset=self.header_size()
        for raw_line in source.splitlines():
            line=raw_line.strip()
            if not line:
                continue

            if line.startswith(";"):
                continue

            #
            # label definition
            #
            if line.startswith(":"):

                parts=line.split('"')

                label_name=parts[0][1:].strip()

                print(f"pass 1: LABEL: {label_name} | offset: {hex(offset-8)}")

                self.labels[label_name]=offset

                if len(parts)==3:
                    raw_data=parts[1]
                    offset += len(raw_data)+1

                continue

            #
            # ignore thread directives for now FIXME
            #
            if line.lower().startswith(
                "thread"
            ):
                continue

            size=2
            instruction=self.instructions.pop(0)

            for i,(kind,value) in enumerate(
                instruction.operands
            ):
                param_def=None
                if (instruction.opcode.params 
                and i<len(instruction.opcode.params)):
                    param_def=(instruction.opcode.params[i])
                size += self.encoded_size(kind, value, param_def)
            offset += size
        offset +=3

    def parse_operand(self,token):
        token=token.strip()

        if token.startswith("@"):
            return ("LABEL",token[1:])

        if (token.startswith('"') and token.endswith('"')):
            return ("STRING",token[1:-1])

        if token.upper() in self.SPECIAL_SYMBOLS:
            return ("SYMBOL",token.upper())

        if token.startswith("$"):
            try:
                return ("GLOBAL",int(token[1:]))
            except:
                return None

        if re.match(r"^\d+@$",token):
            return ("LOCAL",int(token[:-1]))

        try:
            if "." in token:
                return ("FLOAT",float(token))
        except:
            pass

        try:
            return ("INT",int(token))
        except:
            return None

    ####################
    # "PASS 2"
    ####################

    def write_operand(self,kind,value,param_def=None):

        before = len(self.bytecode) #DEBUG

        if param_def:
            if param_def.get("type") == "raw_byte":
                if not (0 <= value <=255):
                    raise ValueError(
                        f"raw_byte out of range: {value}")

                self.write(bytes([value]))
                return

        if kind=="INT":

            if 0<=value<=255:

                self.write(b"\x07")
                self.write(bytes([value]))

            elif 0<=value<=65535:
                self.write(b"\x08")
                self.write_short(value)

            else:
                self.write(b"\x09")
                self.write_int(value)

        elif kind=="LABEL":
            if value not in self.labels:
                raise ValueError(f"Undefined label: {value}")

            target=self.labels[value]
            encoded=-(target-8)
            print(f"pass 2: LABEL: {value} | {hex(encoded)}")
            self.write(b"\x06" )
            self.write(struct.pack("<i",encoded))

        elif kind=="GLOBAL":
            raise NotImplementedError("Globals still broken.")
            #self.write(b"\x20")
            #self.write_short(value << 8 | 0xCE)

        elif kind=="LOCAL":
            self.write(bytes([value+0x0c]))

        elif kind=="STRING":
            encoded=value[:7].encode("ascii")
            self.write(encoded.ljust(8,b"\x00"))

        elif kind=="SYMBOL":
            self.write(self.SPECIAL_SYMBOLS[value])

        elif kind=="FLOAT":
            packed = struct.pack("<f", value)
            self.write(b"\x04")
            self.write(packed[2:4])
        
        after = len(self.bytecode) #DEBUG
        emitted = self.bytecode[before:after] #DEBUG

        print(f"{kind}:{value} ({len(emitted)} bytes) -> {emitted.hex(' ')}") #DEBUG

    def compile(self,source):
        self.bytecode.clear()
        self.error=""
        instructions=self.parse_instructions(source)

        if instructions is None:
            return False

        self.instructions=instructions.copy()
        self.collect_labels(source)
        thread_name="SCRIPT"
        m=re.search(r"thread\s+'([^']+)'",source,re.IGNORECASE)

        if m:
            thread_name=m.group(1)

        self.write_header(thread_name)

        for raw_line in source.splitlines(): #DATA_STREAM

            line=raw_line.strip()

            if line.startswith(":"):

                parts=line.split('"')

                if len(parts)==3:
                    raw_data=parts[1]
                    self.write(raw_data.encode("ascii")+b"\x00")


        for instruction in instructions:
            self.write_short(instruction.opcode.opcode)
            for i,(kind,value) in enumerate(instruction.operands):
                param_def=None
                if (instruction.opcode.params and i<len(instruction.opcode.params)):
                    param_def=(instruction.opcode.params[i])
                self.write_operand(kind,value,param_def)

        #'004e': signature closer.
        self.write(b"\x4E\x00")

        return True

    def get_bytecode(self):
        return bytes(self.bytecode)


def main():
    if len(sys.argv)<3:
        print("Usage:")
        print("python compiler.py script.txt opcodes.dict.txt")
        return

    script_path=sys.argv[1]
    opcode_path=sys.argv[2]

    if script_path.lower().endswith(".lua"):
        try:
            source = lua_to_cleo_source(script_path)
        except RuntimeError as e:
            print("--------XXXXXXXXXXX--------> Lua frontend FAILED: <--------XXXXXXXXXXXXXXX---------")
            print(e)
            return

        generated_path = re.sub(r"\.lua$", ".generated.txt", script_path, flags=re.IGNORECASE)
        with open(generated_path, "w", encoding="utf-8") as f:
            f.write(source)
        print("Lua frontend generated:", generated_path)
    else:
        with open(script_path,"r",encoding="utf-8") as f:
            source=f.read()

    compiler=CLEOCompiler()
    compiler.load_opcodes(opcode_path)
    success=compiler.compile(source)

    if not success:
        print("--------XXXXXXXXXXX--------> Compilation FAILED: <--------XXXXXXXXXXXXXXX---------")
        print(compiler.error)
        return

    script_base = re.sub(r"\.(txt|cleo|lua)$", "", script_path, flags=re.IGNORECASE)
    output_path=(script_base + ".csi")
    with open(output_path,"wb") as f:
        f.write(compiler.get_bytecode())

    print("SUCCESS: Compiled:-------------------------> ",output_path, "<-------------------------SUCCESS")


if __name__=="__main__":
    main()
