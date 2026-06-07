import csv
import os
import re
from pathlib import Path

script_dir = Path(__file__).parent
repo_root = script_dir.parent.parent

input_path = repo_root / 'data' / 'raw' / 'SIC.txt'
output_path = repo_root / 'data' / 'processed' / 'SIC.csv'

os.makedirs(output_path.parent, exist_ok=True)

with open(input_path, 'r', encoding='utf-8') as infile:
    lines = infile.readlines()

code_pattern = re.compile(r'^(\d{5})\t')
section_header_pattern = re.compile(r'^Section ([A-Z])')

rows = []
current_section = None  # will store sections

i = 0
while i < len(lines):
    line = lines[i].rstrip('\n')
    
    # Detect a section header line (ex. "Section A")
    header_match = section_header_pattern.match(line)
    if header_match:
        section_letter = header_match.group(1)
        # The next non‑empty line is the section name (ex. "Agriculture, Forestry and Fishing")
        i += 1
        # Skip blank lines
        while i < len(lines) and lines[i].strip() == '':
            i += 1
        if i < len(lines):
            section_name = lines[i].rstrip('\n').strip()
            current_section = f"Section {section_letter} - {section_name}"
        else:
            current_section = f"Section {section_letter}"
        i += 1
        continue
    
    # If we have a code line, add it with the current section
    code_match = code_pattern.match(line)
    if code_match and current_section is not None:
        code = code_match.group(1)
        description = line.split('\t', 1)[1]
        rows.append([code, description, current_section])
    
    i += 1

# Write CSV
with open(output_path, 'w', encoding='utf-8', newline='') as outfile:
    writer = csv.writer(outfile, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(['Code', 'Description', 'Section'])
    writer.writerows(rows)

print(f"CSV created with {len(rows)} entries")