"""Draw the integration's original geometric network icon (requires Pillow)."""

from pathlib import Path

from PIL import Image, ImageDraw

target = Path(__file__).resolve().parents[1] / "custom_components/esk_net/brand/icon.png"
target.parent.mkdir(exist_ok=True)
image = Image.new("RGBA", (1024, 1024))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((32, 32, 992, 992), radius=200, fill="#123447")
for x, y in ((280, 320), (744, 320), (512, 744)):
    draw.line((512, 500, x, y), fill="#50D6CB", width=48)
    draw.ellipse((x - 72, y - 72, x + 72, y + 72), fill="#50D6CB")
draw.ellipse((392, 380, 632, 620), fill="#FFFFFF")
draw.ellipse((458, 446, 566, 554), fill="#123447")
image.resize((256, 256), Image.Resampling.LANCZOS).save(target)
