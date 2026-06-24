import sys, yaml

def contiguous_block(chs: set[int]) -> bool:
    return max(chs) - min(chs) + 1 == len(chs)

def main(path: str):
    cfg = yaml.safe_load(open(path, "r", encoding="utf-8"))
    used = set()
    ok = True
    for f in cfg.get("fixtures", []):
        if f["type"] == "rgb":
            chs = {int(f["channels"]["r"]), int(f["channels"]["g"]), int(f["channels"]["b"])}
            for k,v in (f.get("steady") or {}).items():
                chs.add(int(k))
        else:
            chs = {int(k) for k in f["channels"].keys()}
        if not contiguous_block(chs):
            print(f"[ERR] {f['name']}: Kanäle nicht zusammenhängend: {sorted(chs)}"); ok = False
        if used.intersection(chs):
            print(f"[ERR] {f['name']}: Kanalüberlappung mit {sorted(used.intersection(chs))}"); ok = False
        used |= chs
    print("[OK]" if ok else "[FAILED]")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv)>1 else "fixtures.yml")
