import fileinput
import os
import re
import sys

def correct(path):
    with fileinput.input(files=(path), inplace=True) as file:
        for i, line in enumerate(file):
            if 0 < len(re.findall("//[-]+", line)):
                length = len(line.replace('\t', "    ").rstrip('\n'))
                if length < 80:
                    line = line.replace("//", "//" + "-" * (80 - length))
                elif length > 80:
                    line = line.replace("//" + "-" * (length - 80), "//")
            sys.stdout.write(line)

def correct_all(rootdir):
    for subdir, dirs, files in os.walk(rootdir):
        for file in files:
            if file.endswith(".cpp") or file.endswith(".hpp") or file.endswith(".ixx") or file.endswith(".hlsl") or file.endswith(".hlsli"):
                path = subdir + os.sep + file
                try:
                    correct(path)
                except UnicodeDecodeError:
                    print(path)
