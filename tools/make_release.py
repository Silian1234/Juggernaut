# Builds the release archive dist/Juggernaut-<version>-SPT-4.1.6.zip from the current build outputs.
# Run from anywhere: python tools/make_release.py [version]
import os, sys, zipfile

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION = sys.argv[1] if len(sys.argv) > 1 else "1.1.1"
OUT = os.path.join(R, "dist", f"Juggernaut-{VERSION}-SPT-4.1.6.zip")
S = "SPT_Runtime/user/mods/Juggernaut/"
C = "BepInEx/plugins/JuggernautClient/"


def p(*parts):
    return os.path.join(R, *parts)


files = {
    S + "Juggernaut.dll": p("server", "bin", "Release", "net10.0", "Juggernaut.dll"),
    S + "bundles.json": p("server", "bundles.json"),
    S + "config.json": p("server", "config.json"),
    S + "locales.json": p("server", "locales.json"),
    S + "LICENSE": p("LICENSE"),
    S + "README.md": p("FORGE_DESCRIPTION.md"),
    C + "JuggernautClient.dll": p("client", "bin", "Release", "JuggernautClient.dll"),
    C + "juggernaut_thermal.bundle": p("client", "assets", "juggernaut_thermal.bundle"),
}
bundles = p("server", "bundles")
for root, _, names in os.walk(bundles):
    for name in names:
        src = os.path.join(root, name)
        files[S + "bundles/" + os.path.relpath(src, bundles).replace(os.sep, "/")] = src
for name in os.listdir(p("client", "sfx")):
    if name.endswith(".wav") or name == "CREDITS.txt":
        files[C + "sfx/" + name] = p("client", "sfx", name)

missing = [src for src in files.values() if not os.path.isfile(src)]
if missing:
    sys.exit("missing: " + ", ".join(missing))
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for arc, src in sorted(files.items()):
        z.write(src, arc)
print(f"{len(files)} files, {os.path.getsize(OUT) / 1e6:.1f} MB -> {OUT}")
