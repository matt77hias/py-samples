from contextlib import redirect_stdout
import os
import re
import sys

pattern_fmt   = "fmt::([A-Za-z0-9_:]+)"
pattern_std   = "std::([A-Za-z0-9_:]+)"
pattern_MAGE  = "MAGE_[A-Za-z0-9_:]+"
pattern_D3D12 = "I?D3D12_[A-Za-z0-9_:]+"
pattern_DXGI  = "I?DXGI_[A-Za-z0-9_:]+"

patterns = [pattern_fmt, pattern_std, pattern_MAGE, pattern_D3D12, pattern_DXGI]


def write_tokens(tokens):
    if len(tokens) == 0:
        return
    
    token = tokens[0]
    sys.stdout.write('\n')
    sys.stdout.write("// ")
    sys.stdout.write(token)
    c = 3 + len(token)
    if 1 < len(tokens):
       sys.stdout.write(",")
       c += 1

    for token in tokens[1:-1]:
        token = token
        if (c + 2 + len(token)) <= 80:
            sys.stdout.write(" ")
            sys.stdout.write(token)
            sys.stdout.write(",")
            c += 2 + len(token)
        else:
            sys.stdout.write('\n')
            sys.stdout.write("// ")
            sys.stdout.write(token)
            sys.stdout.write(",") 
            c = 4 + len(token)

    if 1 < len(tokens):
        token = tokens[-1]
        if (c + 1 + len(token)) <= 80:
            sys.stdout.write(" ")
            sys.stdout.write(token)
        else:
            sys.stdout.write('\n')
            sys.stdout.write("// ")
            sys.stdout.write(token)

    sys.stdout.write('\n')


def scan(path):
    print("//-----------------------------------------------------------------------------")
    print(path)
    print("//-----------------------------------------------------------------------------")
    tokens = [[] for i in range(len(patterns))]
    with open(path, "r", encoding="utf-8", errors='ignore') as file:
        for line in file:
            if line.startswith("//"):
                continue
            if line.find("namespace fmt") != -1:
                print("namespace fmt")
            if line.find("namespace std") != -1:
                print("namespace std")
            for i in range(len(patterns)):
                hits = re.findall(patterns[i], line)
                for hit in hits:
                    tokens[i].append(hit.replace('ranges::', ''))

    for i in range(len(patterns)):
        tokens[i] = sorted(list(dict.fromkeys(tokens[i])))
        write_tokens(tokens[i])
    print()
        
def scan_all(rootdir):
    for subdir, dirs, files in os.walk(rootdir):
        for file in files:
            path = subdir + os.sep + file
            if path.endswith(".cpp") or path.endswith(".hpp") or path.endswith(".ixx"):
                scan(path)
