from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "korea_customs_trade_scenic_source.png"
ASSET = ROOT / "assets" / "korea_customs_trade_kaggle_banner.jpg"
RELEASE = ROOT / "release" / "kaggle" / "dataset-cover-image.jpg"
CARD_PREVIEW = ROOT / "kaggle_card_preview.jpg"
COVER_PREVIEW = ROOT / "kaggle_cover_preview.jpg"

source = Image.open(SOURCE).convert("RGB")

# Kaggle preserves an old crop rectangle for this Dataset. It first renders a
# 2:1 cover, then derives the card by center-cropping that cover to 1:1.
# Therefore all essential copy must live in the centered 275x275 safe square.
scene = source.crop((350, 360, 930, 650)).resize((550, 275), Image.Resampling.LANCZOS)
scene = ImageEnhance.Contrast(scene).enhance(0.96)
scene = ImageEnhance.Brightness(scene).enhance(0.94)
cover = scene.copy()

panel_left = (550 - 275) // 2
panel_right = panel_left + 275
panel = Image.new("RGBA", cover.size, (0, 0, 0, 0))
panel_draw = ImageDraw.Draw(panel)
panel_draw.rectangle((panel_left, 0, panel_right, 275), fill=(4, 30, 56, 228))
cover = Image.alpha_composite(cover.convert("RGBA"), panel).convert("RGB")

draw = ImageDraw.Draw(cover)
bold = r"C:\Windows\Fonts\segoeuib.ttf"
regular = r"C:\Windows\Fonts\segoeui.ttf"

font_kicker = ImageFont.truetype(bold, 10)
font_title = ImageFont.truetype(bold, 31)
font_meta = ImageFont.truetype(bold, 17)
font_sub = ImageFont.truetype(regular, 12)
font_fact = ImageFont.truetype(regular, 11)

left = panel_left + 16
draw.text((left, 18), "OFFICIAL KCS DATA", font=font_kicker, fill=(170, 221, 255))
draw.text((left, 46), "South Korea", font=font_title, fill="white")
draw.text((left, 81), "Customs Trade", font=font_title, fill="white")
draw.text((left, 124), "2012-2026 | HSK10", font=font_meta, fill=(88, 190, 255))
draw.text((left, 151), "Monthly | Partner | Product", font=font_sub, fill=(235, 245, 252))
draw.text((left, 181), "22.35M rows", font=font_fact, fill=(205, 226, 240))
draw.text((left, 199), "269 partner codes", font=font_fact, fill=(205, 226, 240))
draw.rounded_rectangle((left, 230, left + 188, 235), radius=2, fill=(54, 177, 255))
draw.rounded_rectangle((left + 188, 230, left + 230, 235), radius=2, fill=(238, 69, 92))

master = Image.new("RGB", (1200, 1200), (8, 31, 52))
background = scene.resize((1200, 1200), Image.Resampling.LANCZOS)
background = background.filter(ImageFilter.GaussianBlur(30))
background = ImageEnhance.Brightness(background).enhance(0.26)
master.paste(background, (0, 0))
master.paste(cover, (0, 0))

for path in (ASSET, RELEASE):
    path.parent.mkdir(parents=True, exist_ok=True)
    master.save(path, "JPEG", quality=92, optimize=True, progressive=True)

master.crop((panel_left, 0, panel_right, 275)).resize(
    (1200, 1200), Image.Resampling.LANCZOS
).save(CARD_PREVIEW, "JPEG", quality=92)
master.crop((0, 0, 550, 275)).resize(
    (800, 400), Image.Resampling.LANCZOS
).save(COVER_PREVIEW, "JPEG", quality=92)

print("asset", Image.open(ASSET).size, ASSET.stat().st_size)
print("card_preview", CARD_PREVIEW)
print("cover_preview", COVER_PREVIEW)
