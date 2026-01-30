"""Overlay image generator for title cards."""
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


def _load_font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    """Try loading the requested font, fall back to Japanese-compatible fonts if missing."""
    # まず指定されたフォントを試す
    if path.exists():
        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            pass

    # フォールバック: Windows日本語フォントを順に試す
    fallback_fonts = [
        "C:/Windows/Fonts/meiryo.ttc",      # メイリオ
        "C:/Windows/Fonts/msgothic.ttc",    # MSゴシック
        "C:/Windows/Fonts/YuGothM.ttc",     # 游ゴシック Medium
        "C:/Windows/Fonts/YuGothR.ttc",     # 游ゴシック Regular
        "C:/Windows/Fonts/msmincho.ttc",    # MS明朝
    ]

    for fallback in fallback_fonts:
        if os.path.exists(fallback):
            try:
                return ImageFont.truetype(fallback, size)
            except Exception:
                continue

    # 最後の手段: PILのデフォルトフォント（日本語は表示できないが、エラーは回避）
    return ImageFont.load_default()


def _draw_dilated_glow(
    base_img: Image.Image,
    pos: tuple[float, float],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int, int],
    stroke_fill: tuple[int, int, int, int],
    glow_color: tuple[int, int, int, int],
    dilation_size: int = 25,
    blur_radius: int = 24,
    stroke_width: int = 14,
    anchor: str = "mm",
) -> None:
    """Draw text with a dilated mask-based glow and a stroked body."""
    mask = Image.new("L", base_img.size, 0)
    mdraw = ImageDraw.Draw(mask)
    mdraw.text(pos, text, font=font, fill=255, anchor=anchor)

    dilated = mask.filter(ImageFilter.MaxFilter(size=dilation_size))

    glow = Image.new("RGBA", base_img.size, glow_color)
    glow.putalpha(dilated)
    if blur_radius > 0:
        glow = glow.filter(ImageFilter.GaussianBlur(blur_radius))
    base_img.paste(glow, (0, 0), glow)

    temp = Image.new("RGBA", base_img.size, (0, 0, 0, 0))
    tdraw = ImageDraw.Draw(temp)
    tdraw.text(
        pos,
        text,
        font=font,
        fill=fill,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
        anchor=anchor,
    )
    base_img.paste(temp, (0, 0), temp)


def _wrap_text(text: str, max_chars_per_line: int = 10) -> str:
    """テキストを指定文字数で改行する"""
    if len(text) <= max_chars_per_line:
        return text

    # 句読点や区切りで分割を試みる
    for i in range(max_chars_per_line, 0, -1):
        if i < len(text) and text[i] in ['、', '。', '！', '？', '!', '?', ' ']:
            return text[:i+1] + '\n' + text[i+1:]

    # 区切りがない場合は単純に分割
    return text[:max_chars_per_line] + '\n' + text[max_chars_per_line:]


def generate_overlay_card(
    output_path: str,
    top_text: str,
    title_text: str,
    bottom_text: str,
    *,
    width: int = 1080,
    height: int = 1920,
    keifont_path: Path | None = None,
) -> str:
    """
    Generate a transparent overlay card PNG with glow effects.

    The layout matches the manual mock: top small white, main title with yellow
    stroke & yellow glow, bottom red with yellow glow.
    """
    # スクリプトのディレクトリからの相対パスでkeifontを探す
    if keifont_path is None:
        script_dir = Path(__file__).parent.parent  # appディレクトリの親 = プロジェクトルート
        keifont_path = script_dir / "keifont.ttf"

    # 日本語対応フォント（メイリオ）のパス
    meiryo_path = Path("C:/Windows/Fonts/meiryo.ttc")

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))

    # 小さいテキスト用は日本語フォント、タイトルと下部テキストはkeifont（日本語対応フォントにフォールバック）
    # 参考画像のように大きなフォントサイズに
    font_small = _load_font(meiryo_path, 54)
    font_title = _load_font(keifont_path, 86)
    font_bottom = _load_font(keifont_path, 70)

    rect_h = 720
    rect_top = (height - rect_h) // 2
    rect_bottom = rect_top + rect_h
    center_x = width / 2
    gap_small = 320  # 260から320に増やして上に配置
    gap_big = 90
    bottom_gap = 100

    # テキストを2行に改行
    title_wrapped = _wrap_text(title_text, max_chars_per_line=10)
    bottom_wrapped = _wrap_text(bottom_text, max_chars_per_line=10)

    draw = ImageDraw.Draw(img)
    draw.text(
        (center_x, rect_top - gap_small),
        top_text,
        font=font_small,
        fill=(255, 255, 255, 255),
        anchor="mm",
    )

    _draw_dilated_glow(
        base_img=img,
        pos=(center_x, rect_top - gap_big),
        text=title_wrapped,
        font=font_title,
        fill=(0, 0, 0, 255),
        stroke_fill=(255, 215, 0, 255),
        glow_color=(255, 230, 0, 255),
    )

    # 下部テキストはグローなしで描画（赤縁のみ）
    tdraw_bottom = ImageDraw.Draw(img)
    tdraw_bottom.text(
        (center_x, rect_bottom + bottom_gap),
        bottom_wrapped,
        font=font_bottom,
        fill=(255, 255, 255, 255),
        stroke_width=14,
        stroke_fill=(220, 0, 0, 255),
        anchor="mm",
    )

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")
    return str(out_path)
