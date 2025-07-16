import pyperclip

def split_include_comment(comment_block: str) -> str:
    lines = comment_block.strip().splitlines()
    result_lines = []

    for line in lines:
        # Remove leading '//' and strip whitespace
        stripped_line = line.lstrip('/').strip()
        # Split by commas, strip each item, and ignore empty entries
        parts = [part.strip() for part in stripped_line.split(',') if part.strip()]
        # Add each part as a separate comment line
        for part in parts:
            result_lines.append(f"// {part}")

    return '\n'.join(result_lines)


input_comment = """..."""

output = split_include_comment(input_comment)
pyperclip.copy(output)
print(output)
