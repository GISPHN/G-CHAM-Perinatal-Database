#!/usr/bin/env python3
from __future__ import annotations
import argparse, math
from pathlib import Path

def read_ids(path: Path) -> list[str]:
    ids=[x.strip() for x in path.read_text(encoding="utf-8-sig").splitlines() if x.strip().isdigit()]
    if not ids: raise SystemExit("No facility IDs found")
    if len(ids)!=len(set(ids)): raise SystemExit("Duplicate facility IDs found")
    return ids

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--ids-file", required=True)
    ap.add_argument("--shard-index", type=int, required=True)
    ap.add_argument("--shard-count", type=int, required=True)
    ap.add_argument("--out", required=True)
    a=ap.parse_args()
    ids=read_ids(Path(a.ids_file))
    if a.shard_count < 1 or not 0 <= a.shard_index < a.shard_count:
        raise SystemExit("Invalid shard settings")
    n=math.ceil(len(ids)/a.shard_count)
    part=ids[a.shard_index*n:min((a.shard_index+1)*n,len(ids))]
    if not part: raise SystemExit("Empty shard")
    out=Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(part)+"\n", encoding="utf-8")
    print(f"Shard {a.shard_index+1}/{a.shard_count}: {len(part)} IDs ({part[0]}..{part[-1]})")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
