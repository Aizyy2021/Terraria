"""Shows or changes progression flags stored in a Terraria world file.

    python3 scripts/world_flags.py                     show the flags
    python3 scripts/world_flags.py --unsave mechanic   mark the Mechanic as not freed

Only the single byte for the chosen flag is changed; the rest of the file is
left untouched. The header layout follows TEdit's World.FileV2 reader.
Run it with the server stopped (scripts/world-flags.sh does that for you).
"""
import argparse
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORLD = ROOT / "data" / "worlds" / "OurWorld.wld"

BOSS_FLAGS = [
    "Eye of Cthulhu", "Eater of Worlds / Brain of Cthulhu", "Skeletron", "Queen Bee",
    "The Destroyer", "The Twins", "Skeletron Prime", "Any mechanical boss",
    "Plantera", "Golem", "King Slime",
]
SAVED_FLAGS = ["goblin", "wizard", "mechanic"]


class Reader:
    def __init__(self, data, pos=0):
        self.d, self.p = data, pos

    def take(self, n):
        chunk = self.d[self.p:self.p + n]
        if len(chunk) != n:
            raise ValueError("unexpected end of file")
        self.p += n
        return chunk

    def u8(self): return self.take(1)[0]
    def i16(self): return struct.unpack("<h", self.take(2))[0]
    def i32(self): return struct.unpack("<i", self.take(4))[0]
    def u32(self): return struct.unpack("<I", self.take(4))[0]
    def i64(self): return struct.unpack("<q", self.take(8))[0]
    def f64(self): return struct.unpack("<d", self.take(8))[0]

    def boolean(self):
        b = self.u8()
        if b not in (0, 1):
            raise ValueError(f"expected a true/false byte at offset {self.p - 1}, found {b}")
        return b == 1

    def string(self):
        length, shift = 0, 0
        while True:
            b = self.u8()
            length |= (b & 0x7F) << shift
            shift += 7
            if b < 0x80:
                break
        return self.take(length).decode("utf-8", "replace")


def parse(data):
    r = Reader(data)
    version = r.u32()
    if version < 225:
        raise ValueError(f"world version {version} is older than this tool supports")
    if r.take(7) != b"relogic" or r.u8() != 2:
        raise ValueError("not a Terraria world file")
    r.u32(); r.take(8)                          # file revision, favourite flags
    pointers = [r.i32() for _ in range(r.i16())]

    r.p = pointers[0]                           # header section
    info = {"version": version, "title": r.string()}
    r.string(); r.take(8)                       # seed, worldgen version
    r.take(16); r.i32()                         # GUID, world id
    for _ in range(4): r.i32()                  # world bounds
    info["height"], info["width"] = r.i32(), r.i32()
    info["mode"] = r.i32()
    for v in (222, 227, 238, 239, 241, 249, 266, 267, 302):   # secret-seed flags
        if version >= v:
            r.boolean()
    r.i64()                                     # creation time
    if version >= 284:
        r.i64()                                 # last played
    r.u8()                                      # moon type
    for _ in range(3 + 4 + 3 + 4 + 3): r.i32()  # tree / cave / ice / jungle / hell backgrounds
    r.i32(); r.i32()                            # spawn
    r.f64(); r.f64(); r.f64()                   # ground level, rock level, time
    r.boolean(); r.i32()                        # day time, moon phase
    r.boolean(); r.boolean()                    # blood moon, eclipse
    r.i32(); r.i32()                            # dungeon position
    r.boolean()                                 # crimson
    info["bosses"] = {name: r.boolean() for name in BOSS_FLAGS}
    info["saved"] = {}
    info["offsets"] = {}
    for name in SAVED_FLAGS:
        info["offsets"][name] = r.p
        info["saved"][name] = r.boolean()

    # sanity checks so a layout mismatch can never write to the wrong byte
    if not (0 <= info["mode"] <= 3 and 1000 <= info["width"] <= 10000 and 500 <= info["height"] <= 5000):
        raise ValueError("world header doesn't look right; refusing to continue")
    return info


def show(info):
    modes = ["Classic", "Expert", "Master", "Journey"]
    print(f"World: {info['title']}  ({info['width']}x{info['height']}, {modes[info['mode']]}, file version {info['version']})")
    print("\nBosses defeated:")
    for name, done in info["bosses"].items():
        print(f"  {'✔' if done else '·'} {name}")
    print("\nNPCs freed:")
    for name, done in info["saved"].items():
        print(f"  {'✔' if done else '·'} {name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", type=Path, default=DEFAULT_WORLD)
    ap.add_argument("--unsave", choices=SAVED_FLAGS, help="mark this NPC as not freed")
    args = ap.parse_args()

    data = bytearray(args.world.read_bytes())
    try:
        info = parse(data)
    except ValueError as e:
        sys.exit(f"Can't read {args.world}: {e}")

    if args.unsave:
        off = info["offsets"][args.unsave]
        if data[off] == 0:
            print(f"{args.unsave.capitalize()} is already marked as not freed. Nothing to change.")
        else:
            data[off] = 0
            args.world.write_bytes(data)
            info = parse(data)
            print(f"Done: {args.unsave.capitalize()} is now marked as not freed.\n")
    show(info)


if __name__ == "__main__":
    main()
