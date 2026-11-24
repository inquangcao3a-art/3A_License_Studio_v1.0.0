"""Validate the files required to build and identify this Windows release."""
import ast
import base64
import io
import sys
import wave
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from PIL import Image

from license_public_key import PUBLIC_KEY

from p149_robot_images import ROBOT_IMAGES

root = Path(__file__).resolve().parent
version = '7.1.1'
installer_name = f'AI_Font_Finder_PRO_{version}_Setup'
sources = {file.stem: ast.parse(file.read_bytes()) for file in root.glob('*.py')}

for module, tree in sources.items():
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [item.name.split('.')[0] for item in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module.split('.')[0]]
        else:
            continue
        for name in names:
            if name.startswith('p') and name[1:2].isdigit() and name not in sources:
                raise SystemExit(f'{module}.py imports missing module {name}.py')

app_version = next(
    ast.literal_eval(node.value)
    for node in sources['AI_Font_Finder_PRO'].body
    if isinstance(node, ast.Assign)
    and any(isinstance(target, ast.Name) and target.id == 'APP_VERSION' for target in node.targets)
)
if app_version != version:
    raise SystemExit(f'Application version mismatch: {app_version}, expected {version}')

installer = (root / 'installer.iss').read_text(encoding='utf-8')
for setting in (f'#define AppVersion "{version}"', f'OutputBaseFilename={installer_name}',
                'SetupIconFile=ai_pro_logo.ico'):
    if setting not in installer.splitlines():
        raise SystemExit(f'Installer setting missing: {setting}')

with Image.open(root / 'ai_pro_logo.ico') as icon:
    if icon.format != 'ICO' or not {(16, 16), (32, 32), (256, 256)} <= icon.ico.sizes():
        raise SystemExit('Windows icon is missing required sizes')
    for size in icon.ico.sizes():
        icon.ico.getimage(size).load()

expected_images = {f'logo_{size}': size for size in (30, 64, 240)}
expected_images.update({f'frame_{index:02d}': 240 for index in range(12)})
if set(ROBOT_IMAGES) != set(expected_images):
    raise SystemExit('Embedded robot assets do not match the required logo sizes and 12 frames')
for name, size in expected_images.items():
    with Image.open(io.BytesIO(base64.b64decode(ROBOT_IMAGES[name], validate=True))) as image:
        if image.format != 'PNG' or image.size != (size, size):
            raise SystemExit(f'Invalid embedded robot image: {name}')
        image.load()

with wave.open(str(root / 'assets' / '3a_applause.wav')) as audio:
    if not audio.getnframes():
        raise SystemExit('Applause WAV is empty')

print(f'PASS: {version} application, installer, modules, icon, embedded images and audio')

if '--release' in sys.argv:
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(PUBLIC_KEY))
    except ValueError:
        raise SystemExit('Configure the seller public key before building a customer installer.') from None
