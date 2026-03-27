"""Instagram ストーリーズ用 Before/After 画像生成ツール（テンプレート方式）"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

BASE_DIR = Path(__file__).parent
TEMPLATE_PATH = BASE_DIR / "template.png"
LOGO_PATH = BASE_DIR / "logo.png"
OUTPUT_DIR = BASE_DIR / "output"

# Instagram ストーリーズ サイズ
CANVAS_W = 1080
CANVAS_H = 1920

# テンプレート上の写真配置エリア
BEFORE_AREA = (0, 0, 1080, 791)     # (x1, y1, x2, y2)
AFTER_AREA = (0, 1129, 1080, 1920)

# タイトルテキスト配置エリア（緑バー上段の右側）
TITLE_AREA = (530, 792, 1080, 900)

# フォント
FONT_PATH = "/System/Library/Fonts/ヒラギノ角ゴシック W4.ttc"


def load_font(size):
    try:
        return ImageFont.truetype(FONT_PATH, size, index=0)
    except (OSError, IOError):
        return ImageFont.load_default()


def crop_center_fill(img, target_w, target_h):
    """画像を中央クロップして指定サイズにフィットさせる"""
    img_ratio = img.width / img.height
    target_ratio = target_w / target_h

    if img_ratio > target_ratio:
        new_h = img.height
        new_w = int(new_h * target_ratio)
    else:
        new_w = img.width
        new_h = int(new_w / target_ratio)

    left = (img.width - new_w) // 2
    top = (img.height - new_h) // 2
    cropped = img.crop((left, top, left + new_w, top + new_h))
    return cropped.resize((target_w, target_h), Image.LANCZOS)


def crop_center_fill_with_zoom(img, target_w, target_h, zoom=1.0, offset_x=0, offset_y=0):
    """画像を中央クロップ+ズーム+オフセットして指定サイズにフィットさせる"""
    img_ratio = img.width / img.height
    target_ratio = target_w / target_h

    if img_ratio > target_ratio:
        sh = img.height / zoom
        sw = sh * target_ratio
    else:
        sw = img.width / zoom
        sh = sw / target_ratio

    # オフセット（ピクセル座標をソース画像座標に変換）
    ox = offset_x * img.width / target_w
    oy = offset_y * img.height / target_h

    cx = img.width / 2 - ox
    cy = img.height / 2 - oy

    left = max(0, min(img.width - sw, cx - sw / 2))
    top = max(0, min(img.height - sh, cy - sh / 2))

    cropped = img.crop((int(left), int(top), int(left + sw), int(top + sh)))
    return cropped.resize((target_w, target_h), Image.LANCZOS)


def apply_adjustments(img, adj):
    """画像に調整を適用する。adj は各値 -100〜100 の辞書。"""
    if not adj or all(v == 0 for v in adj.values()):
        return img

    arr = np.array(img, dtype=np.float64)

    exposure = adj.get("exposure", 0)
    brightness = adj.get("brightness", 0)
    contrast = adj.get("contrast", 0)
    blackpoint = adj.get("blackpoint", 0)
    highlights = adj.get("highlights", 0)
    shadows = adj.get("shadows", 0)
    saturation = adj.get("saturation", 0)
    vibrance = adj.get("vibrance", 0)
    warmth = adj.get("warmth", 0)
    tint = adj.get("tint", 0)

    # 露出
    if exposure != 0:
        arr *= 2 ** (exposure / 100)

    # 明るさ
    if brightness != 0:
        arr += brightness * 2.55

    # コントラスト
    if contrast != 0:
        f = 1 + contrast / 100
        arr = (arr - 128) * f + 128

    # ブラックポイント
    if blackpoint != 0:
        bp = blackpoint * 1.275
        if bp > 0:
            arr = bp + arr * (255 - bp) / 255
        else:
            arr *= np.maximum(0, 1 + bp / 255)

    # ハイライト
    if highlights != 0:
        luma = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
        mask = np.clip((luma - 128) / 127, 0, 1)
        shift = highlights * 1.275 * mask
        for c in range(3):
            arr[:, :, c] += shift

    # シャドウ
    if shadows != 0:
        luma = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
        mask = np.clip(1 - luma / 128, 0, 1)
        shift = shadows * 1.275 * mask
        for c in range(3):
            arr[:, :, c] += shift

    # 彩度
    if saturation != 0:
        gray = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
        f = 1 + saturation / 100
        for c in range(3):
            arr[:, :, c] = gray + (arr[:, :, c] - gray) * f

    # 自然な彩度
    if vibrance != 0:
        max_c = np.max(arr, axis=2)
        min_c = np.min(arr, axis=2)
        sat = np.where(max_c > 0, (max_c - min_c) / np.maximum(max_c, 1), 0)
        amount = (1 - sat) * (vibrance / 100)
        gray = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
        for c in range(3):
            arr[:, :, c] = gray + (arr[:, :, c] - gray) * (1 + amount)

    # 温かみ
    if warmth != 0:
        w = warmth / 100 * 30
        arr[:, :, 0] += w
        arr[:, :, 2] -= w

    # 色合い
    if tint != 0:
        t = tint / 100 * 30
        arr[:, :, 1] -= t
        arr[:, :, 0] += t * 0.5
        arr[:, :, 2] += t * 0.5

    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def rotate_and_fill(img, angle):
    """画像を回転させ、隙間ができないよう拡大してクロップする"""
    if angle == 0:
        return img
    w, h = img.size
    rad = abs(angle * np.pi / 180)
    cos, sin = np.cos(rad), np.sin(rad)
    scale = max((w * cos + h * sin) / w, (w * sin + h * cos) / h)
    # 拡大してから回転→元サイズにクロップ
    new_w, new_h = int(w * scale) + 2, int(h * scale) + 2
    img_scaled = img.resize((new_w, new_h), Image.LANCZOS)
    rotated = img_scaled.rotate(-angle, resample=Image.BICUBIC, expand=False)
    # 中央からクロップ
    cx, cy = rotated.width // 2, rotated.height // 2
    left = cx - w // 2
    top = cy - h // 2
    return rotated.crop((left, top, left + w, top + h))


def create_story_image(before_path, after_path, title, output_path=None,
                       before_zoom=1.0, after_zoom=1.0,
                       before_rotate=0, after_rotate=0,
                       before_offset_x=0, before_offset_y=0,
                       after_offset_x=0, after_offset_y=0,
                       before_adjustments=None, after_adjustments=None):
    """Before/After ストーリー画像を生成する"""
    # テンプレート読み込み
    template = Image.open(TEMPLATE_PATH).convert("RGBA")

    # 写真読み込み
    before_img = Image.open(before_path).convert("RGB")
    after_img = Image.open(after_path).convert("RGB")

    # Before写真をフィット
    bw = BEFORE_AREA[2] - BEFORE_AREA[0]
    bh = BEFORE_AREA[3] - BEFORE_AREA[1]
    before_fitted = crop_center_fill_with_zoom(before_img, bw, bh, before_zoom, before_offset_x, before_offset_y)

    # After写真をフィット
    aw = AFTER_AREA[2] - AFTER_AREA[0]
    ah = AFTER_AREA[3] - AFTER_AREA[1]
    after_fitted = crop_center_fill_with_zoom(after_img, aw, ah, after_zoom, after_offset_x, after_offset_y)

    # キャンバスに写真を配置
    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), (255, 255, 255))

    # 回転適用
    if before_rotate:
        before_fitted = rotate_and_fill(before_fitted, before_rotate)
    if after_rotate:
        after_fitted = rotate_and_fill(after_fitted, after_rotate)

    # 画像調整適用
    if before_adjustments:
        before_fitted = apply_adjustments(before_fitted, before_adjustments)
    if after_adjustments:
        after_fitted = apply_adjustments(after_fitted, after_adjustments)

    canvas.paste(before_fitted, (BEFORE_AREA[0], BEFORE_AREA[1]))
    canvas.paste(after_fitted, (AFTER_AREA[0], AFTER_AREA[1]))

    # テンプレートを上に重ねる
    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba = Image.alpha_composite(canvas_rgba, template)

    # タイトルテキストを描画
    draw = ImageDraw.Draw(canvas_rgba)
    font = load_font(70)
    tx1, ty1, tx2, ty2 = TITLE_AREA
    center_x = tx1 + (tx2 - tx1) // 2
    center_y = ty1 + (ty2 - ty1) // 2 + 30
    draw.text((center_x, center_y), title, fill=(255, 255, 255), font=font, anchor="mm")

    # ロゴを白縁付きでオーバーレイ
    if LOGO_PATH.exists():
        logo = Image.open(LOGO_PATH).convert("RGBA")
        # 白縁を追加
        outline_w = 16
        w = logo.width + outline_w * 2
        h = logo.height + outline_w * 2
        logo_outlined = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        alpha = logo.split()[3]
        # アルファを二値化（半透明をなくす）
        alpha = alpha.point(lambda p: 255 if p > 30 else 0)
        white_sil = Image.new("RGBA", logo.size, (255, 255, 255, 255))
        white_sil.putalpha(alpha)
        for dx in range(-outline_w, outline_w + 1):
            for dy in range(-outline_w, outline_w + 1):
                if dx * dx + dy * dy <= outline_w * outline_w:
                    logo_outlined.paste(
                        white_sil,
                        (outline_w + dx, outline_w + dy),
                        white_sil,
                    )
        logo_outlined.paste(logo, (outline_w, outline_w), logo)
        # リサイズして元テンプレートと同じ位置に配置
        # 元テンプレート: 幅530, 中心x=768, 下端から51px
        logo_w = 530
        logo_h = int(logo_outlined.height * (logo_w / logo_outlined.width))
        logo_outlined = logo_outlined.resize((logo_w, logo_h), Image.LANCZOS)
        logo_x = 768 - logo_w // 2
        logo_y = CANVAS_H - logo_h - 51
        canvas_rgba.paste(logo_outlined, (logo_x, logo_y), logo_outlined)

    # 保存
    if output_path is None:
        OUTPUT_DIR.mkdir(exist_ok=True)
        output_path = OUTPUT_DIR / f"story_{Path(before_path).stem}_BA.jpg"

    canvas_rgb = canvas_rgba.convert("RGB")
    canvas_rgb.save(str(output_path), "JPEG", quality=95)
    print(f"保存: {output_path}")
    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("使い方:")
        print("  python story_maker.py <before画像> <after画像> <タイトル> [出力パス]")
        print()
        print("例:")
        print('  python story_maker.py before.jpg after.jpg "洗濯機分解洗浄"')
        sys.exit(0)

    before = sys.argv[1]
    after = sys.argv[2]
    title = sys.argv[3]
    output = sys.argv[4] if len(sys.argv) > 4 else None

    create_story_image(before, after, title, output)
