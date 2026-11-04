import sys, collections, email.utils

anni = collections.Counter()
messaggi = 0
prima_vuota = True
in_intestazioni = False
ha_data = False

with open(sys.argv[1], "rb", buffering=1024 * 1024) as f:
    for riga in f:
        vuota = riga in (b"\n", b"\r\n")
        if prima_vuota and riga.startswith(b"From "):
            if messaggi and not ha_data:
                anni["senza data"] += 1
            messaggi += 1
            in_intestazioni = True
            ha_data = False
        elif in_intestazioni:
            if vuota:
                in_intestazioni = False
            elif not ha_data and riga[:5].lower() == b"date:":
                t = email.utils.parsedate_tz(riga[5:].decode("latin-1").strip())
                anni[t[0] if t else "data illeggibile"] += 1
                ha_data = True
        prima_vuota = vuota

if messaggi and not ha_data:
    anni["senza data"] += 1

print("messaggi:", messaggi)
for a, n in sorted(anni.items(), key=lambda x: str(x[0])):
    print(a, n)
