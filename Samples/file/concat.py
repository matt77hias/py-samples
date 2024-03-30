import os
import shutil

def concat(append_path, read_path):
    if os.path.exists(append_path) and os.path.exists(read_path):
        with open(append_path, "ab") as append_file:
            with open(read_path, "rb") as read_file:
                shutil.copyfileobj(read_file, append_file)
