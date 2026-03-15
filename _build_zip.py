import zipfile
import os

EXCLUDE_DIRS = {'tests', '__pycache__', '.git', '.github', 'docs',
                '.pytest_cache', '.ruff_cache', '.claude'}
EXCLUDE_FILES = {'.gitignore', 'pytest.ini', 'ruff.toml', 'CLAUDE.md',
                 '.python-version', '_build_zip.py'}
EXCLUDE_EXT = {'.png', '.pyc', '.zip'}

with zipfile.ZipFile('blender_tools.zip', 'w', zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk('.'):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in files:
            if f in EXCLUDE_FILES:
                continue
            if os.path.splitext(f)[1] in EXCLUDE_EXT:
                continue
            filepath = os.path.join(root, f)
            arcname = os.path.join('blender_tools', filepath[2:])
            zf.write(filepath, arcname)
    count = len(zf.namelist())

print(f'Created blender_tools.zip with {count} files')
