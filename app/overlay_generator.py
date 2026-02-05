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

    # フォールバック: 日本語フォントを順に試す
    fallback_fonts = [
        # Windows
        "C:/Windows/Fonts/meiryo.ttc",      # メイリオ
        "C:/Windows/Fonts/msgothic.ttc",    # MSゴシック
        "C:/Windows/Fonts/YuGothM.ttc",     # 游ゴシック Medium
        "C:/Windows/Fonts/YuGothR.ttc",     # 游ゴシック Regular
        "C:/Windows/Fonts/msmincho.ttc",    # MS明朝
        # Linux (Docker / Cloud Run)
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJKjp-Regular.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf",
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
    title_text: str = "",
    bottom_text: str = "",
    *,
    width: int = 1080,
    height: int = 1920,
    keifont_path: Path | None = None,
    thumbnail_path: str | None = None,
    hook_text: str | None = None,
) -> str:
    """
    Generate a transparent overlay card PNG with glow effects.

    The layout:
    - Top area: Thumbnail image with rounded corners and shadow
    - Bottom area: Hook text (誘導ワード) with red border

    Args:
        output_path: 出力PNGファイルパス
        title_text: メインタイトル（現在未使用、将来用）
        bottom_text: 下部テキスト（現在未使用、hook_textを優先）
        thumbnail_path: サムネイル画像パス
        hook_text: 本動画誘導テキスト（下部に表示）
    """
    # スクリプトのディレクトリからの相対パスでkeifontを探す
    if keifont_path is None:
        script_dir = Path(__file__).parent.parent  # appディレクトリの親 = プロジェクトルート
        keifont_path = script_dir / "keifont.ttf"

    # 日本語対応フォント（メイリオ）のパス
    meiryo_path = Path("C:/Windows/Fonts/meiryo.ttc")

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))

    # フォント設定
    font_hook = _load_font(keifont_path, 64)

    # レイアウト計算
    center_x = width / 2

    # サムネイル配置（上部）
    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            thumb = Image.open(thumbnail_path).convert("RGBA")

            # サムネイルサイズ計算（幅900px、アスペクト比維持）
            thumb_width = 900
            aspect = thumb.height / thumb.width
            thumb_height = int(thumb_width * aspect)

            # リサイズ
            thumb = thumb.resize((thumb_width, thumb_height), Image.Resampling.LANCZOS)

            # 角丸マスクを作成
            mask = Image.new("L", (thumb_width, thumb_height), 0)
            mask_draw = ImageDraw.Draw(mask)
            corner_radius = 30
            mask_draw.rounded_rectangle(
                [(0, 0), (thumb_width, thumb_height)],
                radius=corner_radius,
                fill=255
            )

            # 影を作成
            shadow_offset = 10
            shadow = Image.new("RGBA", (thumb_width + shadow_offset * 2, thumb_height + shadow_offset * 2), (0, 0, 0, 0))
            shadow_mask = Image.new("L", shadow.size, 0)
            shadow_draw = ImageDraw.Draw(shadow_mask)
            shadow_draw.rounded_rectangle(
                [(shadow_offset, shadow_offset), (thumb_width + shadow_offset, thumb_height + shadow_offset)],
                radius=corner_radius,
                fill=180
            )
            shadow_mask = shadow_mask.filter(ImageFilter.GaussianBlur(15))
            shadow.putalpha(shadow_mask)

            # 配置位置（上部中央）
            thumb_x = (width - thumb_width) // 2
            thumb_y = 100

            # 影を配置
            img.paste(shadow, (thumb_x - shadow_offset, thumb_y - shadow_offset), shadow)

            # サムネイルを角丸で配置
            thumb.putalpha(mask)
            img.paste(thumb, (thumb_x, thumb_y), thumb)

        except Exception:
            pass  # サムネイル読み込み失敗時はスキップ

    # 下部に誘導テキスト（hook_text）を配置
    draw = ImageDraw.Draw(img)

    if hook_text:
        hook_y = height - 250  # 下部から250px上
        hook_wrapped = _wrap_text(hook_text, max_chars_per_line=12)

        # 白文字＋赤縁（目立つスタイル）
        draw.text(
            (center_x, hook_y),
            hook_wrapped,
            font=font_hook,
            fill=(255, 255, 255, 255),
            stroke_width=12,
            stroke_fill=(220, 0, 0, 255),
            anchor="mm",
        )

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")
    return str(out_path)
